"""ChromaDB retrieval backend with a pluggable embedder (model-dependent).

``chromadb`` and the embedding package (``fastembed`` by default, or
``sentence-transformers``) are optional and never imported at module load
time (AGENT.md: lazy imports inside functions). Tests that instantiate
:class:`ChromaRetriever` are marked ``needs_model``.

The persistent store (``outputs/chroma``, gitignored) keeps one Chroma
collection per embedder+model, and re-embeds only chunks that are new or whose
text changed, so reloading an existing index is cheap.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from uds_assistant.rag.embedders import Embedder, embedder_available, get_embedder
from uds_assistant.rag.model import Chunk, Hit

DEFAULT_PERSIST_DIR = "outputs/chroma"
DEFAULT_COLLECTION_NAME = "uds_assistant"


def chroma_available(embedder: str = "fastembed") -> bool:
    """Check that ``chromadb`` and the chosen embedder's package are importable."""
    try:
        import chromadb  # noqa: F401
    except ImportError:
        return False
    return embedder_available(embedder)


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class ChromaRetriever:
    """Embeddings-backed retriever using ChromaDB with a persistent local store."""

    def __init__(
        self,
        chunks: list[Chunk],
        *,
        persist_dir: str | Path = DEFAULT_PERSIST_DIR,
        embedder: Embedder | str = "fastembed",
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ) -> None:
        import chromadb

        self._embedder: Embedder = (
            get_embedder(embedder) if isinstance(embedder, str) else embedder
        )
        self._chunks_by_id = {c.id: c for c in chunks}
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{collection_name}_{self._embedder.name}")[:60]
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            safe, metadata={"hnsw:space": "cosine"}
        )
        self.embedded_count = 0
        self._sync(chunks)

    def _sync(self, chunks: list[Chunk]) -> None:
        """Make the stored collection match ``chunks``, embedding only what changed."""
        existing = self._collection.get(include=["metadatas"])
        stored = {
            i: (m or {}).get("text_hash")
            for i, m in zip(existing["ids"], existing["metadatas"] or [], strict=False)
        }
        stale = [i for i in stored if i not in self._chunks_by_id]
        if stale:
            self._collection.delete(ids=stale)
        todo = [c for c in chunks if stored.get(c.id) != _text_hash(c.text)]
        if todo:
            self._collection.upsert(
                ids=[c.id for c in todo],
                embeddings=self._embedder.embed([c.text for c in todo]),
                metadatas=[
                    {"collection": c.collection, "text_hash": _text_hash(c.text)} for c in todo
                ],
                documents=[c.text for c in todo],
            )
        self.embedded_count = len(todo)

    def search(
        self, query: str, k: int = 5, collections: list[str] | None = None
    ) -> list[Hit]:
        """Return the top ``k`` semantically nearest chunks, optionally collection-filtered."""
        where = {"collection": {"$in": collections}} if collections else None
        result = self._collection.query(
            query_embeddings=self._embedder.embed([query]),
            n_results=k,
            where=where,
        )
        hits: list[Hit] = []
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        for chunk_id, distance in zip(ids, distances, strict=False):
            chunk = self._chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            # Chroma returns a distance (lower = more similar); convert to a
            # score where higher is better, matching the Retriever protocol.
            hits.append(Hit(chunk=chunk, score=1.0 - float(distance)))
        return hits
