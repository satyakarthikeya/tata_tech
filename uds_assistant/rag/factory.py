"""Builds the retriever: ChromaDB + BGE embeddings (fastembed), the only backend."""

from __future__ import annotations

from pathlib import Path

from uds_assistant.rag.chroma import ChromaRetriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.rag.model import Chunk


def get_retriever(
    *,
    repo_root: str | Path | None = None,
    chunks: list[Chunk] | None = None,
    persist_dir: str | Path | None = None,
) -> ChromaRetriever:
    """Return a :class:`ChromaRetriever` over ``chunks`` (default: the corpus of ``repo_root``)."""
    if chunks is None:
        chunks = build_corpus(Path(repo_root) if repo_root is not None else Path.cwd())
    if persist_dir is None:
        return ChromaRetriever(chunks)
    return ChromaRetriever(chunks, persist_dir=persist_dir)
