"""Builds the configured :class:`Retriever` from runtime config, with a safe fallback.

``RETRIEVER=bm25`` (the default) always works offline. ``RETRIEVER=chroma``
needs ``chromadb`` and the embedder chosen by ``EMBEDDER`` (``fastembed`` by default,
or ``sentence-transformers``) installed; if either is
missing, this falls back to BM25 and emits a warning rather than crashing
(AGENT.md: "fall back to bm25 if chromadb or embeddings are missing").
"""

from __future__ import annotations

import warnings
from pathlib import Path

from uds_assistant.config import Config, get_config
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.rag.model import Chunk, Retriever


def get_retriever(
    config: Config | None = None,
    *,
    repo_root: str | Path | None = None,
    chunks: list[Chunk] | None = None,
) -> Retriever:
    """Return the retriever backend selected by ``config.retriever`` (default: BM25).

    ``chunks`` can be passed directly (e.g. in tests); otherwise the corpus is
    built from ``repo_root`` (default: the current working directory) via
    :func:`uds_assistant.rag.ingest.build_corpus`.
    """
    cfg = config or get_config()
    if chunks is None:
        root = Path(repo_root) if repo_root is not None else Path.cwd()
        chunks = build_corpus(root)

    if cfg.retriever == "chroma":
        from uds_assistant.rag.chroma import chroma_available

        if chroma_available(cfg.embedder):
            from uds_assistant.rag.chroma import ChromaRetriever

            try:
                return ChromaRetriever(chunks, embedder=cfg.embedder)
            except Exception as exc:  # noqa: BLE001 - model missing/offline, corrupt store, ...
                warnings.warn(
                    f"RETRIEVER=chroma could not start ({type(exc).__name__}: {exc}); "
                    "falling back to the bm25 retriever.",
                    stacklevel=2,
                )
                return Bm25Retriever(chunks)
        warnings.warn(
            f"RETRIEVER=chroma requested but chromadb or the {cfg.embedder} embedder is "
            "not installed; falling back to the bm25 retriever.",
            stacklevel=2,
        )

    return Bm25Retriever(chunks)
