"""Shared data model for retrieval: chunks, hits, and the retriever protocol.

A :class:`Chunk` is one retrievable unit of text. Chunks live in one of four
layered collections (``standard``, ``oem``, ``ecu``, ``project``), each sourced
from a different kind of document (see ``uds_assistant/rag/ingest.py``). The
collection name *is* the layer name; :attr:`Chunk.layer` exposes it, and
citations built from hits carry it (:class:`LayeredCitation`).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from uds_assistant.testgen.model import Citation

Collection = str  # "standard" | "oem" | "ecu" | "project" in this project

LAYERS: tuple[str, ...] = ("standard", "oem", "ecu", "project")
"""The four knowledge layers, each stored in its own physical Chroma collection."""

LAYER_ALIASES: dict[str, str] = {"ecu_spec": "ecu"}
"""Old layer names still accepted in ``collections=`` filters."""


def normalize_layer(name: str) -> str:
    """Map a legacy layer name (``ecu_spec``) to its current name (``ecu``)."""
    return LAYER_ALIASES.get(name, name)


class Chunk(BaseModel):
    """One retrievable unit of text with enough metadata to cite it back."""

    id: str
    """Stable, unique id, e.g. ``"standard:svc-0x22"`` or ``"ecu:did:0xF190"``."""
    collection: Collection
    source_path: str
    """Repo-relative path of the document this chunk came from."""
    ref: str
    """A locator within that source: section anchor, DID/service name, requirement id."""
    text: str
    identifiers: list[str] = Field(default_factory=list)
    """Normalized identifiers mentioned by this chunk, e.g. ``["0xF190", "0x22"]``."""
    page: int | None = None
    """1-based page in the source document (AUTOSAR SWS chunks only)."""
    section: str | None = None
    """Numbered section heading above the chunk in the source (AUTOSAR SWS chunks only)."""
    release: str | None = None
    """Document release, e.g. ``"R24-11"`` (AUTOSAR SWS chunks only)."""
    upstream: list[str] = Field(default_factory=list)
    """Upstream requirement ids traced by this chunk, e.g. ``["SRS_Diag_04058"]``."""

    @property
    def layer(self) -> str:
        """The knowledge layer of this chunk (same as its collection)."""
        return self.collection


class LayeredCitation(Citation):
    """A :class:`Citation` that also says which knowledge layer it came from."""

    layer: str
    page: int | None = None
    section: str | None = None
    release: str | None = None


def citation_location(chunk: Chunk) -> dict[str, object]:
    """The optional page / section / release fields of ``chunk`` (only those that are set)."""
    loc = {"page": chunk.page, "section": chunk.section, "release": chunk.release}
    return {k: v for k, v in loc.items() if v is not None}


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

    def to_layered_citation(self, quote: str | None = None) -> LayeredCitation:
        """Like :meth:`to_citation`, but the result carries the chunk's ``layer``."""
        base = self.to_citation(quote)
        return LayeredCitation(
            **base.model_dump(), layer=self.chunk.layer, **citation_location(self.chunk)
        )


class Retriever(Protocol):
    """Interface every retrieval backend (Chroma) implements."""

    def search(
        self, query: str, k: int = 5, collections: list[str] | None = None
    ) -> list[Hit]:
        """Return the top ``k`` hits for ``query``, optionally restricted to ``collections``."""
        ...
