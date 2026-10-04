"""Tests for citation_is_valid and Hit.to_citation."""

from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.rag.citations import citation_is_valid
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.rag.model import Chunk, Hit
from uds_assistant.testgen.model import Citation

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def corpus():
    return build_corpus(REPO_ROOT)


def test_hit_to_citation_round_trips_and_is_valid(corpus):
    chunk = next(c for c in corpus if c.ref == "did:VIN")
    hit = Hit(chunk=chunk, score=1.0)
    citation = hit.to_citation()
    assert isinstance(citation, Citation)
    assert citation.source == chunk.source_path
    assert citation.ref == chunk.ref
    assert citation_is_valid(citation, corpus) is True


def test_citation_with_custom_quote_matching_chunk_text_is_valid(corpus):
    chunk = next(c for c in corpus if c.ref == "did:VIN")
    citation = Hit(chunk=chunk, score=1.0).to_citation(quote="DID 0xF190 VIN")
    assert citation.quote.startswith("DID 0xF190")
    assert citation_is_valid(citation, corpus) is True


def test_citation_with_fabricated_quote_is_invalid(corpus):
    chunk = next(c for c in corpus if c.ref == "did:VIN")
    citation = Citation(
        source=chunk.source_path, ref=chunk.ref, quote="this text never appears anywhere"
    )
    assert citation_is_valid(citation, corpus) is False


def test_citation_with_unknown_source_is_invalid(corpus):
    citation = Citation(source="nonexistent.md", ref="nope")
    assert citation_is_valid(citation, corpus) is False


def test_citation_with_unknown_ref_in_known_source_is_invalid(corpus):
    chunk = corpus[0]
    citation = Citation(source=chunk.source_path, ref="totally-not-a-real-ref")
    assert citation_is_valid(citation, corpus) is False


def test_citation_quote_identifier_mismatch_is_invalid():
    chunk = Chunk(
        id="x", collection="ecu", source_path="s", ref="r", text="DID 0xF190", identifiers=["0xF190"]
    )
    # Quote references an identifier the chunk does not carry.
    citation = Citation(source="s", ref="r", quote="DID 0xF190")
    assert citation_is_valid(citation, [chunk]) is True
    bad_citation = Citation(source="s", ref="r", quote="0x9999")
    assert citation_is_valid(bad_citation, [chunk]) is False
