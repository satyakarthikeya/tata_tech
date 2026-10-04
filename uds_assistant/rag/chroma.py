"""ChromaDB retrieval with BGE embeddings (fastembed): the only retriever.

The persistent store (``outputs/chroma``, gitignored) keeps one Chroma
collection per embedder+model for the core layers (standard / ecu / project) and
a separate Chroma collection per additional layer (``oem``), and re-embeds only chunks that are new or whose
text changed, so reloading an existing index is cheap.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from uds_assistant.rag.embedders import Embedder, FastEmbedEmbedder
from uds_assistant.rag.model import CORE_LAYERS, Chunk, Hit, normalize_layer

DEFAULT_PERSIST_DIR = "outputs/chroma"
DEFAULT_COLLECTION_NAME = "uds_assistant"


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _group_of(collection: str) -> str:
    return "core" if collection in CORE_LAYERS else collection


class ChromaRetriever:
    """Embeddings-backed retriever using ChromaDB with a persistent local store.

    The core layers share one Chroma collection (as before); every other layer
    (``oem``) lives in its own Chroma collection.
    """

    def __init__(
        self,
        chunks: list[Chunk],
        *,
        persist_dir: str | Path = DEFAULT_PERSIST_DIR,
        embedder: Embedder | None = None,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ) -> None:
        import chromadb

        self._embedder: Embedder = embedder or FastEmbedEmbedder()
        self._chunks_by_id = {c.id: c for c in chunks}
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection_name = collection_name
        groups: dict[str, list[Chunk]] = {}
        for chunk in chunks:
            groups.setdefault(_group_of(chunk.collection), []).append(chunk)
        groups.setdefault("core", [])
        self._collections = {g: self._open(g) for g in groups}
        self.embedded_count = 0
        for group, group_chunks in groups.items():
            self._sync(self._collections[group], group_chunks)

    def _open(self, group: str):
        base = self._collection_name if group == "core" else f"{self._collection_name}_{group}"
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{base}_{self._embedder.name}")[:60]
        return self._client.get_or_create_collection(safe, metadata={"hnsw:space": "cosine"})

    @property
    def chroma_collections(self) -> dict[str, str]:
        """Layer group (``core``, ``oem``) -> underlying Chroma collection name."""
        return {g: c.name for g, c in self._collections.items()}

    def _sync(self, collection, chunks: list[Chunk]) -> None:
        """Make one stored collection match ``chunks``, embedding only what changed."""
        ids_here = {c.id for c in chunks}
        existing = collection.get(include=["metadatas"])
        stored = {
            i: (m or {}).get("text_hash")
            for i, m in zip(existing["ids"], existing["metadatas"] or [], strict=False)
        }
        stale = [i for i in stored if i not in ids_here]
        if stale:
            collection.delete(ids=stale)
        todo = [c for c in chunks if stored.get(c.id) != _text_hash(c.text)]
        if todo:
            collection.upsert(
                ids=[c.id for c in todo],
                embeddings=self._embedder.embed([c.text for c in todo]),
                metadatas=[
                    {
                        "collection": c.collection,
                        "layer": c.layer,
                        "text_hash": _text_hash(c.text),
                    }
                    for c in todo
                ],
                documents=[c.text for c in todo],
            )
        self.embedded_count += len(todo)

    def search(
        self, query: str, k: int = 5, collections: list[str] | None = None
    ) -> list[Hit]:
        """Return the top ``k`` semantically nearest chunks, optionally layer-filtered."""
        wanted = [normalize_layer(c) for c in collections] if collections else None
        where = {"collection": {"$in": wanted}} if wanted else None
        query_embedding = self._embedder.embed([query])
        hits: list[Hit] = []
        for group, collection in self._collections.items():
            if wanted is not None and not any(_group_of(w) == group for w in wanted):
                continue
            if collection.count() == 0:
                continue
            result = collection.query(
                query_embeddings=query_embedding,
                n_results=min(k, collection.count()),
                where=where,
            )
            ids = (result.get("ids") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            for chunk_id, distance in zip(ids, distances, strict=False):
                chunk = self._chunks_by_id.get(chunk_id)
                if chunk is None:
                    continue
                # Chroma returns a distance (lower = more similar); convert to a
                # score where higher is better, matching the Retriever protocol.
                hits.append(Hit(chunk=chunk, score=1.0 - float(distance)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]
