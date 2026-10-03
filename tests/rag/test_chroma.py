"""Chroma backend: import-cleanliness without the package, plus needs_model tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from uds_assistant.rag.chroma import chroma_available
from uds_assistant.rag.model import Chunk


def test_chroma_module_imports_without_chromadb_installed():
    """The module itself must import fine even if chromadb/sentence-transformers
    are absent, because all heavy imports are lazy (inside functions/methods)."""
    result = subprocess.run(
        [sys.executable, "-c", "import uds_assistant.rag.chroma; print('ok')"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_chroma_available_reflects_actual_installation():
    # Whatever the environment, this must not raise.
    assert isinstance(chroma_available(), bool)


def test_chroma_module_has_no_top_level_heavy_imports():
    import ast
    import inspect

    import uds_assistant.rag.chroma as chroma_module

    source = inspect.getsource(chroma_module)
    tree = ast.parse(source)
    top_level_imports = [
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert "chromadb" not in top_level_imports
    assert "sentence_transformers" not in top_level_imports
    assert "fastembed" not in top_level_imports


def test_embedders_module_has_no_top_level_heavy_imports():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, uds_assistant.rag.embedders, uds_assistant.rag.chroma;"
                "bad=[m for m in ('fastembed','chromadb','sentence_transformers','torch')"
                " if m in sys.modules]; print('BAD', bad) if bad else print('ok')"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.stdout.strip() == "ok", result.stdout + result.stderr


def test_chroma_available_considers_chosen_embedder(monkeypatch):
    import uds_assistant.rag.chroma as chroma_module

    monkeypatch.setattr(chroma_module, "embedder_available", lambda name: name == "fastembed")
    if chroma_module.chroma_available("fastembed"):
        assert not chroma_module.chroma_available("sentence-transformers")


def test_fastembed_cache_dir_env_and_default(monkeypatch, tmp_path):
    from uds_assistant.rag.embedders import default_fastembed_cache_dir

    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path))
    assert default_fastembed_cache_dir() == tmp_path
    monkeypatch.delenv("FASTEMBED_CACHE_PATH")
    default = default_fastembed_cache_dir()
    assert default.parts[-2:] == ("uds_assistant", "fastembed")


@pytest.mark.needs_model
def test_chroma_retriever_round_trips(tmp_path):
    from uds_assistant.rag.chroma import ChromaRetriever

    chunks = [
        Chunk(
            id="standard:svc-0x22",
            collection="standard",
            source_path="data/sources/uds_reference_notes.md",
            ref="svc-0x22",
            text="ReadDataByIdentifier reads one or more DIDs such as 0xF190 VIN.",
            identifiers=["0xF190", "0x22"],
        ),
        Chunk(
            id="ecu_spec:did:wiper",
            collection="ecu_spec",
            source_path="data/bcm_spec.yaml",
            ref="did:wiper_sensitivity_level",
            text="DID 0x0130 wiper sensitivity level, writable in extended session.",
            identifiers=["0x0130"],
        ),
    ]
    retriever = ChromaRetriever(chunks, persist_dir=tmp_path / "chroma")
    hits = retriever.search("wiper sensitivity", k=2)
    assert hits
    assert hits[0].chunk.ref == "did:wiper_sensitivity_level"


# ---------------------------------------------------------------------------
# needs_model: real fastembed + chromadb over the real corpus
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def real_retriever(tmp_path_factory):
    from uds_assistant.rag.chroma import ChromaRetriever
    from uds_assistant.rag.ingest import build_corpus

    corpus = build_corpus(_REPO_ROOT)
    return ChromaRetriever(corpus, persist_dir=tmp_path_factory.mktemp("chroma"))


@pytest.mark.needs_model
def test_fastembed_embedder_dimension_and_similarity():
    from uds_assistant.rag.embedders import FastEmbedEmbedder

    emb = FastEmbedEmbedder()
    vecs = emb.embed(["read the VIN", "read vehicle identification number", "wiper motor"])
    assert len(vecs) == 3 and len(vecs[0]) == 384

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert dot(vecs[0], vecs[1]) > dot(vecs[0], vecs[2])


@pytest.mark.needs_model
def test_fastembed_cache_is_persistent_non_temp():
    from uds_assistant.rag.embedders import FastEmbedEmbedder, default_fastembed_cache_dir

    FastEmbedEmbedder()
    cache = default_fastembed_cache_dir()
    assert any(cache.glob("models--*"))


@pytest.mark.needs_model
def test_chroma_read_vin_surfaces_ecu_spec_did(real_retriever):
    hits = real_retriever.search("read VIN", k=3)
    assert any(h.chunk.collection == "ecu_spec" and h.chunk.ref == "did:VIN" for h in hits)


@pytest.mark.needs_model
def test_chroma_security_access_invalid_key_surfaces_standard_0x27(real_retriever):
    hits = real_retriever.search("security access invalid key", k=3)
    assert any(h.chunk.collection == "standard" and "0x27" in h.chunk.text for h in hits)


@pytest.mark.needs_model
def test_chroma_wiper_sensitivity_surfaces_did_0x0130(real_retriever):
    hits = real_retriever.search("wiper sensitivity", k=3)
    assert any("0x0130" in h.chunk.identifiers for h in hits)


@pytest.mark.needs_model
def test_chroma_collection_filter(real_retriever):
    hits = real_retriever.search("wiper sensitivity security session", k=10, collections=["ecu_spec"])
    assert hits
    assert all(h.chunk.collection == "ecu_spec" for h in hits)


@pytest.mark.needs_model
def test_chroma_persistence_reload_skips_reembedding(tmp_path):
    from uds_assistant.rag.chroma import ChromaRetriever
    from uds_assistant.rag.ingest import build_corpus

    corpus = build_corpus(_REPO_ROOT)
    first = ChromaRetriever(corpus, persist_dir=tmp_path)
    assert first.embedded_count == len(corpus)
    expected = [h.chunk.id for h in first.search("wiper sensitivity", k=5)]
    del first

    second = ChromaRetriever(corpus, persist_dir=tmp_path)
    assert second.embedded_count == 0
    assert [h.chunk.id for h in second.search("wiper sensitivity", k=5)] == expected


@pytest.mark.needs_model
def test_chroma_factory_uses_chroma_with_fastembed(monkeypatch, tmp_path):
    from uds_assistant.config import Config
    from uds_assistant.rag.chroma import ChromaRetriever
    from uds_assistant.rag.factory import get_retriever
    from uds_assistant.rag.ingest import build_corpus

    monkeypatch.chdir(tmp_path)
    retriever = get_retriever(
        Config(retriever="chroma", embedder="fastembed"), chunks=build_corpus(_REPO_ROOT)
    )
    assert isinstance(retriever, ChromaRetriever)
