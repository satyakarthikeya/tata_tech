"""Tests for the BM25 backend: tokenizer, filtering, relevance, and the
HandBM25 fallback's agreement with rank_bm25."""

from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.rag.bm25 import Bm25Retriever, HandBM25, tokenize
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.rag.model import Chunk

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def corpus():
    return build_corpus(REPO_ROOT)


@pytest.fixture(scope="module")
def retriever(corpus):
    return Bm25Retriever(corpus)


# ---------------------------------------------------------------------------
# Tokenizer / hex normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("form", ["0xF190", "F190", "f190", "0xf190"])
def test_hex_forms_tokenize_identically(form):
    assert tokenize(form) == tokenize("0xF190")


def test_plain_words_lowercased_not_mangled():
    assert tokenize("Read VIN") == ["read", "vin"]


def test_sid_byte_pair_tokenizes():
    # Bare decimal-looking bytes without a letter or 0x prefix are ambiguous
    # with plain numbers, so only the byte with a hex letter is normalized.
    tokens = tokenize("22 F1 90")
    assert tokens == ["22", "hex:f1", "90"]


def test_nrc_name_tokenizes_as_words():
    tokens = tokenize("requestOutOfRange")
    assert tokens == ["requestoutofrange"]


# ---------------------------------------------------------------------------
# rank_bm25 is actually in use (per DECISIONS: installed and importable)
# ---------------------------------------------------------------------------


def test_retriever_uses_rank_bm25_when_available(retriever):
    assert retriever.uses_rank_bm25 is True


# ---------------------------------------------------------------------------
# Relevance table
# ---------------------------------------------------------------------------


def test_read_vin_surfaces_ecu_spec_did(retriever):
    hits = retriever.search("read VIN", k=3)
    assert any(h.chunk.collection == "ecu_spec" and h.chunk.ref == "did:VIN" for h in hits)


def test_security_access_invalid_key_surfaces_standard_0x27(retriever):
    hits = retriever.search("security access invalid key", k=3)
    assert any(h.chunk.collection == "standard" and "0x27" in h.chunk.text for h in hits)


def test_nrc_0x7f_surfaces_relevant_chunk(retriever):
    hits = retriever.search("NRC 0x7F service not supported in active session", k=3)
    assert any("0x7F" in h.chunk.text or "0x7f" in h.chunk.text.lower() for h in hits)


def test_wiper_sensitivity_surfaces_did_0x0130(retriever):
    hits = retriever.search("wiper sensitivity", k=3)
    assert any("0x0130" in h.chunk.identifiers for h in hits)


# ---------------------------------------------------------------------------
# Collection filtering
# ---------------------------------------------------------------------------


def test_collection_filter_restricts_results(retriever):
    hits = retriever.search("wiper sensitivity security session DID", k=10, collections=["ecu_spec"])
    assert hits
    assert all(h.chunk.collection == "ecu_spec" for h in hits)


def test_no_filter_can_return_multiple_collections(retriever):
    hits = retriever.search("security access session DID routine", k=10)
    collections = {h.chunk.collection for h in hits}
    assert len(collections) >= 2


def test_empty_corpus_search_returns_empty():
    assert Bm25Retriever([]).search("anything") == []


# ---------------------------------------------------------------------------
# HandBM25 vs rank_bm25 consistency on a fixed corpus
# ---------------------------------------------------------------------------


_FIXED_CORPUS_TEXTS = [
    "DID 0xF190 VIN vehicle identification number read only",
    "DID 0x0130 wiper sensitivity level writable extended session security",
    "SecurityAccess 0x27 seed key invalid key NRC 0x35 lockout",
    "DiagnosticSessionControl 0x10 session timing P2 P2star S3",
    "RoutineControl 0x31 start stop results sequence error",
    "ReadDataByIdentifier 0x22 multiple identifiers request out of range",
    "TesterPresent 0x3E keep alive suppress positive response",
    "ClearDiagnosticInformation 0x14 group DTC programming failure",
]


@pytest.fixture(scope="module")
def fixed_tokenized():
    return [tokenize(t) for t in _FIXED_CORPUS_TEXTS]


@pytest.mark.parametrize(
    "query",
    ["security access invalid key", "wiper sensitivity", "read VIN identifier", "routine sequence"],
)
def test_handbm25_matches_rank_bm25_ranking(fixed_tokenized, query):
    rank_bm25 = pytest.importorskip("rank_bm25")
    real = rank_bm25.BM25Okapi(fixed_tokenized)
    fake = HandBM25(fixed_tokenized)

    q_tokens = tokenize(query)
    real_scores = real.get_scores(q_tokens)
    fake_scores = fake.get_scores(q_tokens)

    real_order = sorted(range(len(real_scores)), key=lambda i: -real_scores[i])
    fake_order = sorted(range(len(fake_scores)), key=lambda i: -fake_scores[i])
    assert real_order == fake_order


def test_handbm25_used_when_rank_bm25_chunk_list_empty():
    # A Bm25Retriever built with no chunks must not crash either backend path.
    retriever = Bm25Retriever([])
    assert retriever.search("query") == []


def test_handbm25_backend_selected_without_rank_bm25(monkeypatch):
    import uds_assistant.rag.bm25 as bm25_module

    monkeypatch.setattr(bm25_module, "_HAVE_RANK_BM25", False)
    chunk = Chunk(
        id="x:1", collection="standard", source_path="s", ref="r", text="read VIN DID 0xF190"
    )
    retriever = bm25_module.Bm25Retriever([chunk])
    assert retriever.uses_rank_bm25 is False
    hits = retriever.search("read VIN")
    assert hits and hits[0].chunk.id == "x:1"
