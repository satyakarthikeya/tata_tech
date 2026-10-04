"""BM25 retrieval backend: the default, fully offline retriever.

Uses ``rank_bm25.BM25Okapi`` when importable; otherwise falls back to a
hand-written pure-Python BM25 implementation (:class:`HandBM25`) with the
same ranking formula, so the package works even without ``rank-bm25``
installed (see AGENT.md's "fall back to an in-house implementation" rule).
"""

from __future__ import annotations

import math
import re
from collections import Counter

from uds_assistant.rag.ingest import normalize_identifier
from uds_assistant.rag.model import CORE_LAYERS, Chunk, Hit, normalize_layer

try:
    from rank_bm25 import BM25Okapi as _RankBm25Okapi

    _HAVE_RANK_BM25 = True
except ImportError:  # pragma: no cover - exercised only when rank-bm25 is absent
    _RankBm25Okapi = None
    _HAVE_RANK_BM25 = False

_WORD_RE = re.compile(r"[0-9a-zA-Z]+")
_HEX_TOKEN_RE = re.compile(r"^(0x)?[0-9a-fA-F]{2,8}$")
_HAS_LETTER_RE = re.compile(r"[a-fA-F]")
_HAS_DIGIT_RE = re.compile(r"[0-9]")


def tokenize(text: str) -> list[str]:
    """Tokenize text, normalizing hex identifiers so case/prefix don't matter.

    ``"0xF190"``, ``"F190"`` and ``"f190"`` all normalize to the same token
    (``"hex:f190"``); plain English words are lowercased as usual. A token is
    only treated as hex if it looks hex-ish (short, alphanumeric, at least one
    a-f letter or came with a ``0x`` prefix) so ordinary words like "data" or
    "read" are not mangled.
    """
    tokens: list[str] = []
    for match in _WORD_RE.finditer(text):
        raw = match.group(0)
        lower = raw.lower()
        had_prefix = lower.startswith("0x")
        body = raw[2:] if had_prefix else raw
        is_hexish = len(body) <= 8 and (had_prefix or _HAS_LETTER_RE.search(body))
        if is_hexish and body and _HEX_TOKEN_RE.match(body) and _HAS_DIGIT_RE.search(body):
            norm = normalize_identifier("0x" + body)
            tokens.append("hex:" + norm[2:].lower())
        else:
            tokens.append(lower)
    return tokens


def _bm25_scores_handwritten(
    query_tokens: list[str],
    doc_tokens: list[list[str]],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """Compute Okapi BM25 scores for a query against a tokenized corpus."""
    n_docs = len(doc_tokens)
    if n_docs == 0:
        return []
    doc_lens = [len(d) for d in doc_tokens]
    avgdl = sum(doc_lens) / n_docs if n_docs else 0.0
    df: Counter[str] = Counter()
    for doc in doc_tokens:
        df.update(set(doc))

    idf: dict[str, float] = {}
    for term in set(query_tokens):
        n_qi = df.get(term, 0)
        idf[term] = math.log((n_docs - n_qi + 0.5) / (n_qi + 0.5) + 1.0)

    scores = [0.0] * n_docs
    for i, doc in enumerate(doc_tokens):
        if not doc:
            continue
        counts = Counter(doc)
        dl = doc_lens[i]
        for term in query_tokens:
            if term not in counts:
                continue
            freq = counts[term]
            denom = freq + k1 * (1 - b + b * dl / avgdl) if avgdl else freq
            scores[i] += idf[term] * (freq * (k1 + 1)) / denom
    return scores


class HandBM25:
    """Pure-Python Okapi BM25 ranker, used automatically if ``rank_bm25`` is absent."""

    def __init__(self, tokenized_corpus: list[list[str]]) -> None:
        self._docs = tokenized_corpus

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        """Return a BM25 score per document in corpus order."""
        return _bm25_scores_handwritten(query_tokens, self._docs)


def _index_group(collection: str) -> str:
    """Which BM25 index a chunk lives in: the shared core index, or its own."""
    return "core" if collection in CORE_LAYERS else collection


class Bm25Retriever:
    """Layered BM25 retriever over a list of :class:`Chunk`, filterable by collection.

    Each non-core layer (``oem``) has its own BM25 index, so its text does not
    change the IDF statistics of the other layers. The original three layers
    (``standard``, ``ecu``, ``project``) share one index exactly as before, so
    their scores and rankings are unchanged by the OEM layer.
    """

    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = list(chunks)
        self._group_idx: dict[str, list[int]] = {}
        for idx, chunk in enumerate(self._chunks):
            self._group_idx.setdefault(_index_group(chunk.collection), []).append(idx)
        self._tokenized = [tokenize(c.text) for c in self._chunks]
        self._backends = {
            g: self._build_backend([self._tokenized[i] for i in ids])
            for g, ids in self._group_idx.items()
        }

    @staticmethod
    def _build_backend(tokenized: list[list[str]]) -> object:
        if _HAVE_RANK_BM25 and tokenized:
            return _RankBm25Okapi(tokenized)
        return HandBM25(tokenized)

    @property
    def uses_rank_bm25(self) -> bool:
        """True if the real ``rank_bm25`` package backs this instance."""
        return _HAVE_RANK_BM25 and bool(self._tokenized)

    @property
    def index_groups(self) -> dict[str, int]:
        """Number of chunks in each separate BM25 index (``core``, ``oem``, ...)."""
        return {g: len(ids) for g, ids in self._group_idx.items()}

    def search(
        self, query: str, k: int = 5, collections: list[str] | None = None
    ) -> list[Hit]:
        """Return the top ``k`` chunks for ``query``, optionally filtered by collection."""
        if not self._chunks:
            return []
        wanted = None if collections is None else {normalize_layer(c) for c in collections}
        query_tokens = tokenize(query)
        scores: dict[int, float] = {}
        for group, ids in self._group_idx.items():
            if wanted is not None and not any(self._chunks[i].collection in wanted for i in ids):
                continue
            group_scores = self._backends[group].get_scores(query_tokens)
            scores.update(zip(ids, group_scores, strict=True))
        candidates = [
            (score, idx)
            for idx, score in sorted(scores.items())
            if wanted is None or self._chunks[idx].collection in wanted
        ]
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return [
            Hit(chunk=self._chunks[idx], score=float(score))
            for score, idx in candidates[:k]
        ]
