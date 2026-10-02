"""Citation validity: used by the "citation validity" evaluation metric.

A citation is valid if it points at a chunk that actually exists in the
corpus (matched by ``source_path`` + ``ref``) and, when the citation carries
a quote, that quote is genuinely drawn from the chunk (and any hex
identifier it mentions is one the chunk actually carries).
"""

from __future__ import annotations

from uds_assistant.rag.ingest import extract_identifiers
from uds_assistant.rag.model import Chunk
from uds_assistant.testgen.model import Citation


def citation_is_valid(citation: Citation, corpus: list[Chunk]) -> bool:
    """Check that ``citation`` points at a real chunk in ``corpus``.

    The chunk is matched by ``source_path`` + ``ref``. If the citation's
    ``quote`` is set, it must appear verbatim in the matched chunk's text
    (so a fabricated or mismatched quote is caught) and any hex identifier
    it mentions (e.g. ``"0xF190"``) must be one the chunk actually carries.
    A citation with no matching chunk is invalid.
    """
    matches = [
        c for c in corpus if c.source_path == citation.source and c.ref == citation.ref
    ]
    if not matches:
        return False

    if citation.quote:
        quoted_ids = extract_identifiers(citation.quote)
        for chunk in matches:
            if citation.quote not in chunk.text:
                continue
            if quoted_ids and not all(qid in chunk.identifiers for qid in quoted_ids):
                continue
            return True
        return False
    return True
