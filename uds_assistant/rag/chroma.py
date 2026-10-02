"""ChromaDB + sentence-transformers retrieval backend (model-dependent).

``chromadb`` and ``sentence-transformers`` are optional heavy dependencies
that must not be imported at module load time (AGENT.md: "model-dependent
modules use lazy imports inside functions"). Every import of them here
happens inside a function or method body, so this module — and the whole
``uds_assistant`` package — imports cleanly even when neither package is
installed. Tests that actually instantiate :class:`ChromaRetriever` are
marked ``needs_model`` and skipped unless ``RUN_MODEL_TESTS=1``.
"""

from __future__ import annotations

from pathlib import Path

from uds_assistant.rag.model import Chunk, Hit

DEFAULT_PERSIST_DIR = "outputs/chroma"
DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"
DEFAULT_COLLECTION_NAME = "uds_assistant"


def chroma_available() -> bool:
    """Check whether both ``chromadb`` and ``sentence-transformers`` are importable."""
    try:
        import chromadb  # noqa: F401
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


class ChromaRetriever:
    """Embeddings-backed retriever using ChromaDB with a persistent local store.

    All heavy imports happen inside ``__init__``, never at module scope.
    """

    def __init__(
        self,
        chunks: list[Chunk],
        *,
        persist_dir: str | Path = DEFAULT_PERSIST_DIR,
        model_name: str = DEFAULT_MODEL_NAME,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ) -> None:
        import chromadb
        from sentence_transformers import SentenceTransformer

        self._chunks_by_id = {c.id: c for c in chunks}
        self._model = SentenceTransformer(model_name)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(collection_name)

        if chunks:
            embeddings = self._model.encode([c.text for c in chunks]).tolist()
            self._collection.upsert(
                ids=[c.id for c in chunks],
                embeddings=embeddings,
                metadatas=[{"collection": c.collection} for c in chunks],
                documents=[c.text for c in chunks],
            )

    def search(
        self, query: str, k: int = 5, collections: list[str] | None = None
    ) -> list[Hit]:
        """Return the top ``k`` semantically nearest chunks, optionally collection-filtered."""
        query_embedding = self._model.encode([query]).tolist()
        where = {"collection": {"$in": collections}} if collections else None
        result = self._collection.query(
            query_embeddings=query_embedding,
            n_results=k,
            where=where,
        )
        hits: list[Hit] = []
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for chunk_id, distance in zip(ids, distances, strict=False):
            chunk = self._chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            # Chroma returns a distance (lower = more similar); convert to a
            # score where higher is better, matching the Retriever protocol.
            hits.append(Hit(chunk=chunk, score=1.0 - float(distance)))
        return hits
