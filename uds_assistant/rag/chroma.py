"""ChromaDB retrieval with BGE embeddings (fastembed): the only retriever.

The persistent store (``outputs/chroma``, gitignored) keeps FOUR physical Chroma collections
per embedder+model, one per layer (standard / oem / ecu / project), and re-embeds only chunks
that are new or whose text changed, so reloading an existing index is cheap.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from uds_assistant.rag.embedders import Embedder, FastEmbedEmbedder
from uds_assistant.rag.model import LAYERS, Chunk, Hit, normalize_layer

DEFAULT_PERSIST_DIR = "outputs/chroma"
DEFAULT_COLLECTION_NAME = "uds_assistant"


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _metadata(c: Chunk) -> dict[str, str | int]:
    """Chroma metadata for one chunk (Chroma rejects ``None``, so unset fields are left out)."""
    meta: dict[str, str | int] = {
        "collection": c.collection,
        "layer": c.layer,
        "text_hash": _text_hash(c.text),
        "source": c.source_path,
        "ref": c.ref,
    }
    for key in ("page", "section", "release"):
        value = getattr(c, key)
        if value is not None:
            meta[key] = value
    if c.upstream:
        meta["upstream"] = ",".join(c.upstream)
    return meta


class ChromaRetriever:
    """Embeddings-backed retriever using ChromaDB with a persistent local store.

    Each layer (``standard``, ``oem``, ``ecu``, ``project``) lives in its own Chroma collection;
    a search names the layers it wants and only those collections are queried.
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
        groups: dict[str, list[Chunk]] = {layer: [] for layer in LAYERS}
        for chunk in chunks:
            groups.setdefault(normalize_layer(chunk.collection), []).append(chunk)
        self._drop_legacy_shared_collection()
        self._collections = {g: self._open(g) for g in groups}
        self.embedded_count = 0
        for group, group_chunks in groups.items():
            self._sync(self._collections[group], group_chunks)

    def _name(self, group: str | None) -> str:
        base = self._collection_name if group is None else f"{self._collection_name}_{group}"
        return re.sub(r"[^a-zA-Z0-9_-]", "_", f"{base}_{self._embedder.name}")[:60]

    def _drop_legacy_shared_collection(self) -> None:
        """Remove the old shared standard/ecu/project collection (derived data, rebuilt per layer)."""
        legacy = self._name(None)
        if any(getattr(c, "name", c) == legacy for c in self._client.list_collections()):
            self._client.delete_collection(legacy)

    def _open(self, group: str):
        return self._client.get_or_create_collection(
            self._name(group), metadata={"hnsw:space": "cosine"}
        )

    @property
    def chroma_collections(self) -> dict[str, str]:
        """Layer (``standard``, ``oem``, ``ecu``, ``project``) -> its Chroma collection name."""
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
                metadatas=[_metadata(c) for c in todo],
                documents=[c.text for c in todo],
            )
        self.embedded_count += len(todo)

    def search(
        self, query: str, k: int = 5, collections: list[str] | None = None
    ) -> list[Hit]:
        """Return the top ``k`` semantically nearest chunks, optionally layer-filtered."""
        wanted = [normalize_layer(c) for c in collections] if collections else None
        query_embedding = self._embedder.embed([query])
        hits: list[Hit] = []
        for group, collection in self._collections.items():
            if wanted is not None and group not in wanted:
                continue
            if collection.count() == 0:
                continue
            result = collection.query(
                query_embeddings=query_embedding,
                n_results=min(k, collection.count()),
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
