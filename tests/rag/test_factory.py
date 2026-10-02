"""Tests for get_retriever: bm25 default, chroma fallback when unavailable."""

from __future__ import annotations

import warnings

from uds_assistant.config import Config
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.model import Chunk

_CHUNKS = [
    Chunk(id="a", collection="standard", source_path="s", ref="r", text="hello world VIN 0xF190")
]


def test_default_config_gives_bm25(monkeypatch):
    monkeypatch.delenv("RETRIEVER", raising=False)
    retriever = get_retriever(chunks=_CHUNKS)
    assert isinstance(retriever, Bm25Retriever)


def test_explicit_bm25_config_gives_bm25():
    retriever = get_retriever(Config(retriever="bm25"), chunks=_CHUNKS)
    assert isinstance(retriever, Bm25Retriever)


def test_chroma_requested_but_unavailable_falls_back_to_bm25(monkeypatch):
    import uds_assistant.rag.factory as factory_module

    monkeypatch.setattr(factory_module, "Bm25Retriever", Bm25Retriever)
    import uds_assistant.rag.chroma as chroma_module

    monkeypatch.setattr(chroma_module, "chroma_available", lambda: False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        retriever = get_retriever(Config(retriever="chroma"), chunks=_CHUNKS)

    assert isinstance(retriever, Bm25Retriever)
    assert any("falling back to the bm25 retriever" in str(w.message) for w in caught)


def test_chroma_requested_and_available_uses_chroma(monkeypatch):
    import uds_assistant.rag.chroma as chroma_module

    class FakeChromaRetriever:
        def __init__(self, chunks, **kwargs):
            self.chunks = chunks

        def search(self, query, k=5, collections=None):
            return []

    monkeypatch.setattr(chroma_module, "chroma_available", lambda: True)
    monkeypatch.setattr(chroma_module, "ChromaRetriever", FakeChromaRetriever)

    retriever = get_retriever(Config(retriever="chroma"), chunks=_CHUNKS)
    assert isinstance(retriever, FakeChromaRetriever)


def test_get_retriever_builds_corpus_from_repo_root(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sources").mkdir()
    (tmp_path / "data" / "sources" / "uds_reference_notes.md").write_text(
        "## Intro {#intro}\nSome text about 0x22 ReadDataByIdentifier.\n", encoding="utf-8"
    )
    retriever = get_retriever(Config(retriever="bm25"), repo_root=tmp_path)
    hits = retriever.search("ReadDataByIdentifier")
    assert hits
