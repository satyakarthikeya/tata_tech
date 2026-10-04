"""Small text helpers: content tokens, sentence slicing, quote resolution, token checks."""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    ["a", "an", "the", "of", "to", "in", "on", "at", "for", "from", "by", "with", "and", "or", "not", "is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "can", "could", "should", "would", "will", "shall", "may", "might", "must", "what", "which", "who", "whom", "whose", "when", "where", "why", "how", "this", "that", "these", "those", "it", "its", "as", "if", "then", "than", "so", "there", "their", "they", "them", "i", "we", "you", "your", "our", "me", "my", "any", "all", "each", "every", "some", "no", "yes", "about", "into", "over", "under", "per", "via", "use", "used", "uses", "using", "need", "needs", "needed", "return", "returned", "returns", "give", "gives", "get", "gets", "have", "has", "had", "mean", "means", "meant", "tell", "explain", "one", "two", "ecu", "bcm", "did", "uds", "diagnostic", "diagnostics", "value", "values", "reading", "read", "tester"]
)
# Note: 'read' is generic for questions about DIDs; the spec/NRC lookups handle those. 'did' also
# appears twice on purpose (the data-identifier abbreviation and the verb); both are low-signal.

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9*]*")
_SENT_SEP = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9*`<(\[])|\n\s*\n|\n(?=\s*(?:[-*] |\d+\. ))")


def stem(word: str) -> str:
    """Very light stemmer: lower-case, strip a plural / -ed / -ing ending, unify state/status."""
    w = word.lower().strip("*")
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    if w in ("status", "statu"):
        w = "state"
    return w


def tokens(text: str) -> list[str]:
    """All stemmed word tokens of ``text`` (stopwords kept)."""
    return [stem(m) for m in _WORD_RE.findall(text.lower())]


def content_tokens(text: str) -> list[str]:
    """Distinct stemmed non-stopword tokens of ``text``, in order of first appearance."""
    seen: list[str] = []
    for m in _WORD_RE.findall(text.lower()):
        if m in STOPWORDS:
            continue
        t = stem(m)
        if t not in seen:
            seen.append(t)
    return seen


def sentence_spans(text: str, min_len: int = 20) -> list[tuple[int, int]]:
    """``(start, end)`` of each sentence / list item of ``text``; ``text[s:e]`` is an exact slice."""
    bounds = [0]
    spans: list[tuple[int, int]] = []
    for m in _SENT_SEP.finditer(text):
        spans.append((bounds[-1], m.start()))
        bounds.append(m.end())
    spans.append((bounds[-1], len(text)))
    out: list[tuple[int, int]] = []
    for s, e in spans:
        chunk = text[s:e]
        s2 = s + (len(chunk) - len(chunk.lstrip()))
        e2 = e - (len(chunk) - len(chunk.rstrip()))
        if e2 - s2 >= min_len:
            out.append((s2, e2))
    return out


def collapse(text: str) -> str:
    """Collapse all whitespace runs to single spaces."""
    return " ".join(text.split())


def resolve_quote(quote: str, chunk_text: str) -> str | None:
    """The exact slice of ``chunk_text`` that ``quote`` denotes, or None if it is not in it.

    An exact substring is returned as is. A quote that differs only in whitespace (the LLM
    re-wrapped a line) resolves to the original slice; anything else is rejected.
    """
    q = quote.strip()
    if len(q) < 8:
        return None
    if q in chunk_text:
        return q
    words = q.split()
    if not words:
        return None
    m = re.search(r"\s+".join(re.escape(w) for w in words), chunk_text)
    return m.group(0) if m else None


_NUM_RE = re.compile(r"0x[0-9a-f]+|\d+")


def number_tokens(text: str) -> set[str]:
    """Hex (``0x..``) and decimal tokens in ``text``, lower-cased."""
    return set(_NUM_RE.findall(text.lower()))


def contains_token(answer: str, token: str) -> bool:
    """True if ``token`` occurs in ``answer`` as a whole token (case-insensitive, whitespace-flexible)."""
    pat = r"\s*".join(re.escape(p) for p in token.lower().split())
    return re.search(rf"(?<![0-9a-z]){pat}(?![0-9a-z])", collapse(answer).lower()) is not None
