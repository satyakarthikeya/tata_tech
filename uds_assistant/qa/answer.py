"""Cited diagnostic Q&A: spec lookups + layered retrieval, answered only from approved sources.

Flow of :func:`answer_question`:

1. **Deterministic lookup** (:mod:`uds_assistant.qa.lookup`): DID / routine / NRC / service /
   security / timing facts come from the parsed spec (and the standard layer's NRC table).
   An entity that does not exist (unknown DID, routine, level, NRC, service) -> ``not_found``.
2. **Retrieval** (no lookup applies): ``search_layers`` over standard / oem / ecu / project, the
   retrieved chunks are split into sentences, and a sentence is *supported* when it matches the
   question's content words well enough (:data:`MIN_MATCHED`, :data:`MIN_COVERAGE`). No supported
   sentence -> ``not_found`` (refusing is preferred over guessing).
3. **Phrasing**: the template answer is the lookup facts / verbatim supported sentences; the
   Ollama model only rephrases them, and its output is verified (every looked-up value must still
   appear, no number or hex value that is not in the facts / quotes / question, every claim's quote
   must be a substring of the chunk) and otherwise the template answer is used and a fallback
   event is recorded.
4. Every returned citation quote is checked to be a substring of its chunk's text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from uds_assistant.llm.base import LLMClient, LLMError
from uds_assistant.qa.confidence import qa_confidence
from uds_assistant.qa.lookup import FactLookup
from uds_assistant.qa.models import AskResponse, Fact, QACitation
from uds_assistant.qa.text import (
    collapse,
    contains_token,
    content_tokens,
    number_tokens,
    resolve_quote,
    sentence_spans,
    tokens,
)
from uds_assistant.rag.layers import search_layers
from uds_assistant.rag.model import LAYERS, Chunk, Retriever, citation_location
from uds_assistant.spec.schema import EcuSpec

NOT_FOUND_ANSWER = "Not found in the approved sources."

MIN_MATCHED = 2
"""A retrieved sentence is supported only if it contains at least this many of the question's
content words (or all of them when the question has fewer)."""
MIN_COVERAGE = 0.6
"""... and at least this share of the question's content words (stemmed, stopwords removed)."""
CLAIM_SUPPORT = 0.6
"""An LLM claim is kept only if at least this share of its content words occur in its own quote."""
K_PER_LAYER = 3
MAX_SENTENCES = 2
_LAYER_PRIORITY = {"standard": 0, "ecu": 1, "oem": 2, "project": 3}
_NRC_IN_TEXT = re.compile(r"NRC\s*0x([0-9A-Fa-f]{2})")

_SYSTEM_FACTS = (
    "You rewrite diagnostic facts as a short, clear answer to the question. Use ONLY the facts "
    "given. Keep every value (numbers, hex ids, session names) exactly as written. Do not add "
    "any information that is not in the facts."
)
_SYSTEM_CLAIMS = (
    "You answer a diagnostic question using ONLY the numbered evidence sentences. Return 1 or 2 "
    "claims; each claim has a short 'text', the 'chunk_id' of its evidence and a 'quote' copied "
    "word for word from that evidence sentence. Never state anything the evidence does not say."
)


class _Phrase(BaseModel):
    answer: str


class _Claim(BaseModel):
    text: str
    chunk_id: str
    quote: str


class _Claims(BaseModel):
    claims: list[_Claim] = Field(default_factory=list)


@dataclass
class _Sentence:
    chunk: Chunk
    text: str
    """Exact slice of ``chunk.text``."""
    matched: int
    coverage: float
    score: float


def _citation(chunk: Chunk, quote: str) -> QACitation:
    return QACitation(chunk_id=chunk.id, layer=chunk.layer, source=chunk.source_path, quote=quote,
                      ref=chunk.ref, **citation_location(chunk))


def _not_found(reason: str, llm_name: str) -> AskResponse:
    conf, why = qa_confidence(status="not_found", deterministic=False)
    return AskResponse(
        answer=NOT_FOUND_ANSWER, citations=[], confidence=conf,
        confidence_reason=f"{why} ({reason})", status="not_found", llm=llm_name,
    )


def supported_sentences(
    question: str, retriever: Retriever, k_per_layer: int = K_PER_LAYER
) -> tuple[list[_Sentence], list[str]]:
    """Retrieve per layer and return the supported sentences (best first) plus the question terms.

    A sentence is supported if it matches at least ``min(MIN_MATCHED, n_terms)`` of the question's
    ``n_terms`` content words and at least ``MIN_COVERAGE`` of them.
    """
    q_terms = content_tokens(question)
    if not q_terms:
        return [], q_terms
    need = min(MIN_MATCHED, len(q_terms))
    by_layer = search_layers(retriever, question, k_per_layer=k_per_layer, layers=LAYERS)
    out: list[_Sentence] = []
    seen: set[tuple[str, int]] = set()
    for hits in by_layer.values():
        for hit in hits:
            for s, e in sentence_spans(hit.chunk.text):
                if (hit.chunk.id, s) in seen:
                    continue
                seen.add((hit.chunk.id, s))
                stoks = set(tokens(hit.chunk.text[s:e]))
                matched = sum(1 for t in q_terms if t in stoks)
                cov = matched / len(q_terms)
                if matched >= need and cov >= MIN_COVERAGE:
                    out.append(_Sentence(hit.chunk, hit.chunk.text[s:e], matched, cov, hit.score))
    out.sort(key=lambda x: (-x.coverage, -x.matched, _LAYER_PRIORITY.get(x.chunk.layer, 9), -x.score))
    return out, q_terms


def qa_facts_ok(answer: str, facts: list[Fact], question: str) -> list[str]:
    """Why a phrased answer must be rejected (empty list = fine).

    Every looked-up value (``Fact.must_include``) must still occur in the answer, and the answer
    may not contain a number or hex value that is in none of the facts, their quotes or the question.
    """
    problems = [f"missing fact value {t!r}" for f in facts for t in f.must_include
                if not contains_token(answer, t)]
    allowed = number_tokens(question)
    for f in facts:
        allowed |= number_tokens(f.text) | number_tokens(f.quote)
    extra = sorted(number_tokens(answer) - allowed)
    problems += [f"introduced value {t!r}" for t in extra]
    return problems


def _template_from_facts(facts: list[Fact]) -> str:
    return " ".join(f.text for f in facts if f.text)


def _nrc_enrichment(lookup: FactLookup, sentences: list[str]) -> list[Fact]:
    out: list[Fact] = []
    seen: set[str] = set()
    for s in sentences:
        for m in _NRC_IN_TEXT.finditer(s):
            f = lookup.nrc_fact(int(m.group(1), 16))
            if f is not None and f.key not in seen:
                seen.add(f.key)
                out.append(f)
    return out[:3]


def _finish(
    answer: str, cites: list[tuple[Chunk, str]], *, deterministic: bool, coverage: float,
    fallback_events: list[str], llm_name: str,
) -> AskResponse:
    """Enforce the quote-substring rule on every citation and build the response."""
    citations: list[QACitation] = []
    seen: set[tuple[str, str]] = set()
    for chunk, quote in cites:
        if quote in chunk.text and (chunk.id, quote) not in seen:
            seen.add((chunk.id, quote))
            citations.append(_citation(chunk, quote))
    if not citations:
        return _not_found("no citation survived quote verification", llm_name)
    conf, why = qa_confidence(
        status="answered", deterministic=deterministic, coverage=coverage,
        fallback_used=bool(fallback_events),
    )
    return AskResponse(
        answer=answer, citations=citations, confidence=conf, confidence_reason=why,
        status="answered", fallback_events=fallback_events, llm=llm_name,
    )


def _phrase_facts(
    llm: LLMClient, question: str, facts: list[Fact], events: list[str]
) -> str | None:
    """LLM phrasing of looked-up facts, or None (with a fallback event) if it fails verification."""
    prompt = (
        f"Question: {question}\nFacts:\n" + "\n".join(f"- {f.text}" for f in facts if f.text)
        + "\nWrite the answer in 1-3 sentences."
    )
    try:
        phrase = llm.complete_json(_SYSTEM_FACTS, prompt, _Phrase)
    except LLMError as exc:
        events.append(f"LLM error during phrasing; template answer used ({exc})")
        return None
    answer = collapse(phrase.answer)
    problems = qa_facts_ok(answer, facts, question)
    if problems or not answer:
        events.append("LLM phrasing rejected, template answer used: " + "; ".join(problems or ["empty"]))
        return None
    return answer


def _phrase_claims(
    llm: LLMClient, question: str, sents: list[_Sentence], extra: list[Fact], events: list[str]
) -> tuple[str, list[tuple[Chunk, str]]] | None:
    """LLM claims with verified quotes, or None (with a fallback event) if none survive."""
    by_id = {s.chunk.id: s.chunk for s in sents}
    schema = {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array", "maxItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "chunk_id": {"type": "string", "enum": sorted(by_id)},
                        "quote": {"type": "string"},
                    },
                    "required": ["text", "chunk_id", "quote"],
                },
            }
        },
        "required": ["claims"],
    }
    ev = "\n".join(f"[{s.chunk.id}] {collapse(s.text)}" for s in sents)
    prompt = f"Question: {question}\nEvidence:\n{ev}"
    try:
        reply = llm.complete_json(_SYSTEM_CLAIMS, prompt, _Claims, json_schema=schema)
    except LLMError as exc:
        events.append(f"LLM error during phrasing; template answer used ({exc})")
        return None
    texts: list[str] = []
    cites: list[tuple[Chunk, str]] = []
    allowed = number_tokens(question)
    for f in extra:
        allowed |= number_tokens(f.text)
    for c in reply.claims:
        chunk = by_id.get(c.chunk_id)
        quote = resolve_quote(c.quote, chunk.text) if chunk else None
        if chunk is None or quote is None:
            events.append(f"claim dropped: quote not found in chunk {c.chunk_id!r}")
            continue
        introduced = number_tokens(c.text) - number_tokens(quote) - allowed
        if introduced:
            events.append(f"claim dropped: introduced value(s) {sorted(introduced)}")
            continue
        claim_terms = content_tokens(c.text)
        qtoks = set(tokens(quote))
        support = sum(1 for t in claim_terms if t in qtoks) / len(claim_terms) if claim_terms else 0.0
        if support < CLAIM_SUPPORT:
            events.append(f"claim dropped: only {support:.0%} of its terms occur in its quote")
            continue
        texts.append(collapse(c.text))
        cites.append((chunk, quote))
    if not texts:
        events.append("LLM phrasing produced no verified claim, template answer used")
        return None
    return " ".join(texts), cites


def answer_question(
    question: str,
    *,
    spec: EcuSpec,
    chunks: list[Chunk],
    retriever: Retriever,
    llm: LLMClient,
    lookup: FactLookup | None = None,
) -> AskResponse:
    """Answer ``question`` from the approved sources, with citations, or refuse (``not_found``).

    The LLM only phrases (verified) facts and quotes it is handed; if its phrasing fails
    verification the template answer is used and a fallback event is recorded.
    """
    question = question.strip()
    lk = lookup or FactLookup(spec, chunks)
    llm_name = llm.name
    by_id = {c.id: c for c in chunks}
    events: list[str] = []

    res = lk.lookup(question)
    if res.unknown:
        return _not_found("; ".join(res.unknown), llm_name)

    if res.facts:
        answer = _template_from_facts(res.facts)
        answer = _phrase_facts(llm, question, res.facts, events) or answer
        cites = [(by_id[f.chunk_id], f.quote) for f in res.facts if f.chunk_id in by_id]
        return _finish(answer, cites, deterministic=True, coverage=1.0,
                       fallback_events=events, llm_name=llm_name)

    sents, _q_terms = supported_sentences(question, retriever)
    if not sents:
        reason = ("no approved sentence matches enough of the question terms "
                  f"(need >= {MIN_COVERAGE:.0%} coverage and >= {MIN_MATCHED} terms)")
        return _not_found(reason, llm_name)

    chosen = sents[:MAX_SENTENCES]
    chosen = [s for s in chosen if s.coverage >= MIN_COVERAGE]
    best_cov = chosen[0].coverage
    nrc_facts = _nrc_enrichment(lk, [s.text for s in chosen])
    answer = " ".join(collapse(s.text) for s in chosen)
    if nrc_facts:
        answer += " " + " ".join(f.text for f in nrc_facts)
    cites = [(s.chunk, s.text) for s in chosen] + [
        (by_id[f.chunk_id], f.quote) for f in nrc_facts if f.chunk_id in by_id
    ]
    got = _phrase_claims(llm, question, sents[:4], nrc_facts, events)
    if got is not None:
        text, claim_cites = got
        answer = text + (" " + " ".join(f.text for f in nrc_facts) if nrc_facts else "")
        cites = claim_cites + [(by_id[f.chunk_id], f.quote) for f in nrc_facts if f.chunk_id in by_id]
    return _finish(answer, cites, deterministic=False, coverage=best_cov,
                   fallback_events=events, llm_name=llm_name)
