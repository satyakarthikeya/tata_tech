"""Access to the AUTOSAR Dcm SWS text, used only to verify requirement citations.

The SWS PDF (AUTOSAR CP R24-11 "Specification of Diagnostic Communication
Manager") is *not* committed: AUTOSAR's redistribution terms forbid it, so the
owner downloads it into ``data/sources/``. Both the PDF and the extracted-text
cache (``data/sources/.cache/``) are git-ignored. Nothing here copies SWS text
into the repository; the text is read only at test time to check that every
``SWS_Dcm_xxxxx`` ID cited in ``rules/*.py`` really exists.

``pypdf`` is imported lazily so the package imports cleanly without it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SWS_PDF = REPO_ROOT / "data" / "sources" / "AUTOSAR_CP_SWS_DiagnosticCommunicationManager.pdf"
SWS_CACHE = REPO_ROOT / "data" / "sources" / ".cache" / "dcm_sws.txt"

#: Requirement IDs as they appear in the SWS, e.g. ``[SWS_Dcm_00273]``.
SWS_ID_RE = re.compile(r"SWS_Dcm_\d{5}")
#: Upper bound on one requirement's text (tables can be long).
_MAX_REQ_CHARS = 4000
#: A requirement body closes with U+230B (right floor bracket), optionally
#: followed by its traceability list, e.g. ``(SRS_Diag_04010)`` or ``()``.
_OPEN, _CLOSE = "\u2308", "\u230b"
_REQ_END_RE = re.compile(_CLOSE + r"(?:\s*\([^)]*\))?")


def _extract_pdf_text(pdf: Path) -> str:
    """Extract all page text from ``pdf`` with pypdf (lazy import)."""
    from pypdf import PdfReader  # lazy: optional dependency

    reader = PdfReader(str(pdf))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def load_sws_text(pdf: Path = SWS_PDF, cache: Path = SWS_CACHE) -> str | None:
    """Return the extracted SWS text, or ``None`` if the PDF is absent.

    Extraction runs once; the cache is reused while it is newer than the PDF.
    """
    if not pdf.is_file():
        return None
    if cache.is_file() and cache.stat().st_mtime >= pdf.stat().st_mtime:
        return cache.read_text(encoding="utf-8")
    text = _extract_pdf_text(pdf)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


def find_requirement(sws_id: str, text: str | None = None) -> str | None:
    """Return the paragraph of requirement ``sws_id`` (e.g. ``"SWS_Dcm_00273"``).

    The paragraph runs from the defining (line-initial) bracketed ID to the
    closing bracket of the requirement body, at most 4000 characters.
    Returns ``None`` if the PDF is absent or the ID is not defined in it.
    """
    if text is None:
        text = load_sws_text()
    if text is None:
        return None
    # A definition starts a line and its body opens (U+2308) before any body
    # closes (U+230B); other occurrences are cross-references or trace tables.
    for match in re.finditer(rf"^\[{re.escape(sws_id)}\]", text, re.MULTILINE):
        rest = text[match.end() : match.end() + _MAX_REQ_CHARS]
        opening, closing = rest.find(_OPEN), rest.find(_CLOSE)
        if opening < 0 or (0 <= closing < opening):
            continue
        end = _REQ_END_RE.search(rest, opening)
        body = rest if end is None else rest[: end.end()]
        return f"[{sws_id}] " + " ".join(body.split())
    return None
