"""Chroma backend: import-cleanliness without the package, plus needs_model tests."""

from __future__ import annotations

import subprocess
import sys

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
