"""Grounding of parse output: identifiers, services, sessions and security levels.

A small local model copies identifiers from the prompt's examples or the spec index into
unrelated requirements and adds services the text never asked for. Everything here runs
only for backends that hallucinate (``applies_grounding``, i.e. not the mock) and every
removal is recorded as a :class:`Drop` (the parse node writes it to the notes and trace).

Identifiers (DIDs, routines, DTCs) survive only if they are

(a) *written in the requirement text* (hex form, any case, with or without ``0x``; a DTC
    code as written), or
(b) *linked to a retrieved ecu_spec chunk* (a BM25/Chroma search with the requirement
    text, run here because ``parse`` runs before ``retrieve``) whose name matches words of
    the requirement text. The spec has no alias field, so the name is the only label; its
    underscore-separated words are compared with the requirement's words (light stemming,
    generic words ignored).

Services need *evidence*; the first matching rule wins and its reason is kept:

====  ==================================================================================
Rule  Evidence for service S
====  ==================================================================================
(a)   Lexical: a strong pattern of S from :mod:`.service_lexicon` matches the text
      (read/report -> 0x22; write/set/change/configure/store -> 0x2E; session/mode
      names -> 0x10; reset/restart/reboot/power-cycle -> 0x11; clear/erase + fault
      memory -> 0x14; read/report + fault/DTC/status mask -> 0x19; unlock/security/
      seed/key -> 0x27; routine/self-test/calibration/start+test -> 0x31; keep-alive/
      tester present/heartbeat/S3 -> 0x3E).
(b)   Implied by a *kept* identifier plus intent: a DID with a read/verify/report intent
      -> 0x22, with a write intent (or the ``write``/``range``/``length`` intents) ->
      0x2E; a routine -> 0x31; a DTC with a clearing verb -> 0x14, otherwise -> 0x19.
(c)   Retrieval support: the BM25 search over the ``standard`` collection returns S's
      section (``svc-0x..``) among the top :data:`SERVICE_RETRIEVAL_K` AND at least one
      *weak* word of S (``SERVICE_WEAK``) is in the text. Never retrieval alone.
====  ==================================================================================

A service needed only to *reach a state* (0x10 for a session, 0x27 for security) is evidence
only when the text itself mentions the session or the unlock, i.e. rule (a). A service with
no evidence is dropped. Sessions are kept when the text names them (their own words, the
spec name, the hex id, or an any/every-session phrase); security levels only when an
unlock/security word is present.

Optional evidence quotes (``ParsedRequirement.evidence``, key ``service:0x2E`` /
``did:0xF190`` ...): a quote that is *not* a substring of the requirement (case-insensitive,
whitespace-normalised) makes that one item ungrounded. A valid quote is a gate only, never
sufficient evidence; items without a quote fall back to the rules above.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from uds_assistant.agent.service_lexicon import (
    ALL_SESSIONS_RE,
    CLEAR_INTENT_RE,
    CLEAR_INTENTS,
    READ_INTENT_RE,
    READ_INTENTS,
    SESSION_RE,
    STRONG_RE,
    WEAK_RE,
    WRITE_INTENT_RE,
    WRITE_INTENTS,
    first_hit,
)
from uds_assistant.llm.base import _norm_hex_id
from uds_assistant.rag.model import Retriever

GROUNDED_FIELDS: tuple[tuple[str, str], ...] = (
    ("dids", "did:"),
    ("routines", "routine:"),
    ("dtcs", "dtc:"),
)
"""(ParsedRequirement field, ecu_spec chunk-ref prefix) for each checked identifier kind."""

EVIDENCE_K = 6
"""Chunks fetched from ``ecu_spec`` for the requirement text."""

SERVICE_RETRIEVAL_K = 3
"""Top-k of the ``standard`` search a service section must appear in for rule (c)."""

_WEAK_WORDS = frozenset(
    {"id", "pct", "kph", "enable", "state", "level", "flag", "number", "index", "mode", "test",
     "self", "variant", "the", "and", "for", "with", "value"}
)
_TOKEN_RE = re.compile(r"[0-9A-Za-z]+")


@dataclass(frozen=True)
class Drop:
    """One item removed by the grounding check."""

    field: str
    identifier: str
    reason: str


def written_identifiers(text: str) -> set[str]:
    """Upper-cased alphanumeric tokens of ``text`` (``0xf190`` -> ``0XF190``, ``f190`` -> ``F190``)."""
    return {tok.upper() for tok in _TOKEN_RE.findall(text)}


def _stem(word: str) -> str:
    return word[:5]


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 3}


def name_matches_text(name: str, text: str) -> bool:
    """True if a distinctive word of the spec ``name`` also appears in ``text``."""
    wanted = {
        _stem(w) for w in re.findall(r"[a-z]+", name.lower()) if len(w) >= 3 and w not in _WEAK_WORDS
    }
    return bool(wanted & _words(text))


def _is_written(field: str, ident: str, tokens: set[str]) -> bool:
    """Is ``ident`` written in the text as ``0x0100``/``0x100``/``0100`` (any case)? A bare
    short number such as ``100`` does not count."""
    digits = ident.upper() if field == "dtcs" else ident.upper().removeprefix("0X")
    forms = {digits}
    if field != "dtcs":
        forms |= {"0X" + digits, "0X" + (digits.lstrip("0") or "0")}
    return bool(forms & tokens)


def ground_identifiers(
    parsed: dict[str, list[str]],
    text: str,
    index: dict[str, dict[str, str]],
    retriever: Retriever,
) -> tuple[dict[str, list[str]], list[Drop]]:
    """Filter DIDs/routines/DTCs in ``parsed``; return the kept lists and the drops."""
    kept = {k: list(v) for k, v in parsed.items()}
    drops: list[Drop] = []
    tokens = written_identifiers(text)
    chunks = None  # retrieved lazily: only when an identifier is not written in the text
    for field, prefix in GROUNDED_FIELDS:
        keep: list[str] = []
        for ident in parsed.get(field, []):
            if _is_written(field, ident, tokens):
                keep.append(ident)
                continue
            if chunks is None:
                chunks = [
                    h.chunk
                    for h in retriever.search(text, k=EVIDENCE_K, collections=["ecu_spec"])
                    if h.score > 0
                ]
            name = index[field].get(ident, "")
            ref = f"{prefix}{ident if field == 'dtcs' else name}"
            linked = any(c.ref == ref and ident in c.identifiers for c in chunks)
            if linked and name_matches_text(name, text):
                keep.append(ident)
            elif not linked:
                drops.append(Drop(field, ident, "not written in the requirement and its spec "
                                  "chunk was not retrieved for the requirement text"))
            else:
                drops.append(Drop(field, ident, "not written in the requirement and its name "
                                  f"({name}) shares no word with the requirement text"))
        kept[field] = keep
    return kept, drops


# ------------------------------------------------------------------ evidence quotes

_QUOTE_KINDS = {
    "service": "services", "did": "dids", "routine": "routines", "session": "sessions",
    "level": "security_levels", "security_level": "security_levels", "dtc": "dtcs",
}
_SINGULAR = {
    "services": "service", "dids": "did", "routines": "routine", "sessions": "session",
    "security_levels": "security_level", "dtcs": "dtc",
}


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def quote_in_text(quote: str, text: str) -> bool:
    """True if ``quote`` is a non-empty substring of ``text`` (case-insensitive, whitespace-normalised)."""
    q = _squash(quote)
    return bool(q) and q in _squash(text)


def parse_evidence_key(key: str) -> tuple[str, str] | None:
    """``"service:0x2e"`` -> ``("services", "0x2E")``; None for an unrecognised key."""
    kind, _, ident = key.partition(":")
    field = _QUOTE_KINDS.get(kind.strip().lower())
    ident = ident.strip()
    if field is None or not ident:
        return None
    return field, ident.upper() if field == "dtcs" else _norm_hex_id(ident)


def apply_quote_check(
    kept: dict[str, list[str]], evidence: dict[str, str], text: str
) -> tuple[dict[str, list[str]], list[Drop], dict[str, str]]:
    """Drop items whose quote is not in ``text``; return (kept, drops, valid quotes by key).

    Items without a quote are untouched (they fall back to the other rules).
    """
    bad: dict[tuple[str, str], str] = {}
    valid: dict[str, str] = {}
    for key, quote in evidence.items():
        parsed_key = parse_evidence_key(str(key))
        if parsed_key is None or not str(quote).strip():
            continue
        if quote_in_text(str(quote), text):
            valid[f"{_SINGULAR[parsed_key[0]]}:{parsed_key[1]}"] = str(quote).strip()
        else:
            bad[parsed_key] = str(quote)
    out = {k: list(v) for k, v in kept.items()}
    drops: list[Drop] = []
    for (field, ident), quote in bad.items():
        if ident in out.get(field, []):
            out[field].remove(ident)
            drops.append(Drop(field, ident, f"its evidence quote {quote[:60]!r} is not in the "
                              "requirement text"))
    return out, drops, valid


# ------------------------------------------------------------------ services / sessions / levels


def _service_evidence(
    sid: str,
    text: str,
    kept: dict[str, list[str]],
    intents: list[str],
    retrieved_refs: set[str] | None,
) -> str | None:
    """Reason why ``sid`` has evidence under rules (a), (b), (c); None if it has none.

    ``retrieved_refs`` is the set of ``standard`` chunk refs of the search (None = not run).
    """
    hit = first_hit(STRONG_RE.get(sid, ()), text)
    if hit:
        return f"lexical evidence {hit.strip()!r}"
    ints = set(intents)
    reads = bool(ints & READ_INTENTS) or bool(READ_INTENT_RE.search(text))
    writes = bool(ints & WRITE_INTENTS) or first_hit(WRITE_INTENT_RE, text) is not None
    clears = first_hit(CLEAR_INTENT_RE, text) is not None
    if sid == "0x22" and kept.get("dids") and reads:
        return "implied by kept DID with a read intent"
    if sid == "0x2E" and kept.get("dids") and writes:
        return "implied by kept DID with a write intent"
    if sid == "0x31" and kept.get("routines"):
        return "implied by kept routine"
    if sid == "0x14" and kept.get("dtcs") and clears:
        return "implied by kept DTC with a clearing intent"
    if sid == "0x19" and kept.get("dtcs") and not clears and (reads or ints & CLEAR_INTENTS):
        return "implied by kept DTC with a read intent"
    if retrieved_refs is not None and f"svc-{sid.lower()}" in retrieved_refs:
        weak = first_hit(WEAK_RE.get(sid, ()), text)
        if weak:
            return f"retrieval support plus word {weak.strip()!r}"
    return None


def ground_services(
    services: list[str],
    text: str,
    kept: dict[str, list[str]],
    intents: list[str],
    retriever: Retriever,
) -> tuple[list[str], list[Drop], dict[str, str]]:
    """Keep the services that have evidence; return (kept, drops, reason per kept service).

    ``kept`` holds the already-grounded identifier lists (rule (b) uses them).
    """
    refs: set[str] | None = None
    out: list[str] = []
    drops: list[Drop] = []
    reasons: dict[str, str] = {}
    for sid in services:
        reason = _service_evidence(sid, text, kept, intents, refs)
        if reason is None and refs is None:
            refs = {
                h.chunk.ref
                for h in retriever.search(text, k=SERVICE_RETRIEVAL_K, collections=["standard"])
                if h.score > 0
            }
            reason = _service_evidence(sid, text, kept, intents, refs)
        if reason is None:
            drops.append(Drop("services", sid, "no evidence: no matching word in the requirement, "
                              "not implied by a kept identifier, and no retrieval-plus-word support"))
        else:
            out.append(sid)
            reasons[sid] = reason
    return out, drops, reasons


def ground_sessions(
    sessions: list[str], text: str, index: dict[str, dict[str, str]]
) -> tuple[list[str], list[Drop]]:
    """Keep sessions the text names (own words, spec name, hex id, or any/every session)."""
    tokens = written_identifiers(text)
    everywhere = first_hit(ALL_SESSIONS_RE, text) is not None
    out: list[str] = []
    drops: list[Drop] = []
    for sid in sessions:
        name = index["sessions"].get(sid, "")
        if (
            first_hit(SESSION_RE.get(sid, ()), text)
            or (name and name_matches_text(name, text))
            or _is_written("sessions", sid, tokens)
            or everywhere
        ):
            out.append(sid)
        else:
            drops.append(Drop("sessions", sid, "the requirement does not name or imply this session"))
    return out, drops


def ground_security_levels(levels: list[str], text: str) -> tuple[list[str], list[Drop]]:
    """Keep security levels only if the text has an unlock/security word."""
    if not levels or first_hit(STRONG_RE["0x27"], text):
        return list(levels), []
    return [], [
        Drop("security_levels", lvl, "no unlock/security/seed/key word in the requirement")
        for lvl in levels
    ]
