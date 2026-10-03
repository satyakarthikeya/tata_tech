"""Identifier grounding: keep a parsed DID / routine / DTC only if the evidence supports it.

A small local model tends to copy identifiers from the prompt's examples or from the spec
index into unrelated requirements. An identifier survives only if it is

(a) *written in the requirement text* (hex form, any case, with or without ``0x``; a DTC
    code as written), or
(b) *linked to a retrieved ecu_spec chunk* (a BM25/Chroma search with the requirement
    text, run here because ``parse`` runs before ``retrieve``) whose name matches words of
    the requirement text. The spec has no alias field, so the name is the only label; its
    underscore-separated words are compared with the requirement's words (light stemming,
    generic words ignored).

Services, sessions and security levels are not checked: they are small closed sets that
the prompt rules derive from the main action, and dropping them would remove the tests'
anchor service (kept as-is by design).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from uds_assistant.rag.model import Retriever

GROUNDED_FIELDS: tuple[tuple[str, str], ...] = (
    ("dids", "did:"),
    ("routines", "routine:"),
    ("dtcs", "dtc:"),
)
"""(ParsedRequirement field, ecu_spec chunk-ref prefix) for each checked identifier kind."""

EVIDENCE_K = 6
"""Chunks fetched from ``ecu_spec`` for the requirement text."""

_WEAK_WORDS = frozenset(
    {"id", "pct", "kph", "enable", "state", "level", "flag", "number", "index", "mode", "test",
     "self", "variant", "the", "and", "for", "with", "value"}
)
_TOKEN_RE = re.compile(r"[0-9A-Za-z]+")


@dataclass(frozen=True)
class Drop:
    """One identifier removed by the grounding check."""

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
