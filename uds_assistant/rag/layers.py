"""Per-layer retrieval API: standard / oem / ecu / project, with layer-tagged citations.

Thin helpers over any :class:`~uds_assistant.rag.model.Retriever`. The four
layers are kept in separate collections (the case study's risk control: do not
mix standard, OEM, ECU and project knowledge); these helpers make it easy to
ask one layer, or every layer separately, and to get citations that say which
layer each piece of evidence came from.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence

from uds_assistant.rag.model import (
    LAYERS,
    Chunk,
    Hit,
    LayeredCitation,
    Retriever,
    normalize_layer,
)

LAYER_SOURCES: dict[str, tuple[str, ...]] = {
    "standard": ("data/sources/uds_reference_notes.md",),
    "oem": ("data/oem_diagnostic_guidelines.md",),
    "ecu": ("data/bcm_spec.yaml",),
    "project": ("docs/behaviour_contract.md", "data/requirements_seed.csv"),
}
"""Source files feeding each layer (see :func:`uds_assistant.rag.ingest.build_corpus`)."""


def search_layer(retriever: Retriever, query: str, layer: str, k: int = 5) -> list[Hit]:
    """Top ``k`` hits for ``query`` from exactly one layer."""
    layer = normalize_layer(layer)
    if layer not in LAYERS:
        raise ValueError(f"unknown layer {layer!r}; expected one of {LAYERS}")
    return retriever.search(query, k=k, collections=[layer])


def search_layers(
    retriever: Retriever,
    query: str,
    k_per_layer: int = 3,
    layers: Sequence[str] = LAYERS,
) -> dict[str, list[Hit]]:
    """Top ``k_per_layer`` hits from each layer, searched separately, keyed by layer."""
    return {
        normalize_layer(layer): search_layer(retriever, query, layer, k_per_layer)
        for layer in layers
    }


def cite_hits(hits: Iterable[Hit], quote: str | None = None) -> list[LayeredCitation]:
    """Citations (source, ref, quote, layer) for ``hits``; ``quote`` defaults to the chunk start."""
    return [h.to_layered_citation(quote) for h in hits]


def layer_counts(chunks: Iterable[Chunk]) -> dict[str, int]:
    """Number of chunks per layer, in canonical layer order (absent layers count 0)."""
    counts = Counter(c.layer for c in chunks)
    return {layer: counts.get(layer, 0) for layer in LAYERS}
