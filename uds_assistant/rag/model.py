"""Shared data model for retrieval: chunks, hits, and the retriever protocol.

A :class:`Chunk` is one retrievable unit of text. Chunks live in one of three
layered collections (``standard``, ``ecu_spec``, ``project``), each sourced
from a different kind of document (see ``uds_assistant/rag/ingest.py``).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from uds_assistant.testgen.model import Citation

Collection = str  # "standard" | "ecu_spec" | "project" in this project


class Chunk(BaseModel):
    """One retrievable unit of text with enough metadata to cite it back."""

    id: str
    """Stable, unique id, e.g. ``"standard:svc-0x22"`` or ``"ecu_spec:did:0xF190"``."""
    collection: Collection
    source_path: str
    """Repo-relative path of the document this chunk came from."""
    ref: str
    """A locator within that source: section anchor, DID/service name, requirement id."""
    text: str
    identifiers: list[str] = Field(default_factory=list)
    """Normalized identifiers mentioned by this chunk, e.g. ``["0xF190", "0x22"]``."""


class Hit(BaseModel):
    """A chunk returned by a retriever, with its relevance score."""

    chunk: Chunk
    score: float

    def to_citation(self, quote: str | None = None) -> Citation:
        """Convert this hit into a :class:`testgen.model.Citation`."""
        return Citation(
            source=self.chunk.source_path,
            ref=self.chunk.ref,
            quote=quote if quote is not None else self.chunk.text[:200],
        )


class Retriever(Protocol):
    """Interface every retrieval backend (BM25, Chroma, ...) implements."""

    def search(
        self, query: str, k: int = 5, collections: list[str] | None = None
    ) -> list[Hit]:
        """Return the top ``k`` hits for ``query``, optionally restricted to ``collections``."""
        ...
