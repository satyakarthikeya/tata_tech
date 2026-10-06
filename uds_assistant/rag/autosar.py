"""AUTOSAR Dcm SWS loader: one ``standard`` chunk per SWS requirement, with page and section.

The PDF is not redistributable, so it is never committed: the owner puts a local copy in
``data/sources/`` (git-ignored) or points ``UDS_AUTOSAR_PDF`` at it. Without the PDF the
``standard`` layer falls back to the own-words notes (``data/sources/uds_reference_notes.md``)
alone; with it, the requirement chunks are added next to the notes (the notes keep the
deterministic chunk ids that Q&A and the request check look up, e.g. ``standard:svc-0x22``).

Parsing is pure text work on the per-page text (:func:`parse_sws_pages`), so it can be checked
on a plain text file without the PDF. Rules:

- Lines repeated on most pages (running header/footer, page numbers) are dropped.
- A requirement starts at a line beginning with ``[SWS_Dcm_NNNNN]``. When the document uses the
  AUTOSAR requirement brackets (U+2308 / U+230B), only a line whose id is followed by the opening
  bracket counts, so ids quoted in tracing tables or in other requirements' text are ignored.
- A requirement ends at its closing bracket (the upstream ``(SRS_...)`` trace right after it is
  kept as metadata), at the next requirement, or at the next section heading.
- Each chunk records the page it starts on, the last numbered section heading above it, the
  document release (e.g. ``R24-11``) and the upstream SRS ids.
- If an id is defined twice (e.g. a change-history table), the longest body wins.

The parsed result is cached in ``data/sources/.cache/`` (git-ignored), keyed by the PDF's SHA-256
and :data:`PARSER_VERSION`, so only the first build pays for the PDF extraction.

Check the real PDF with ``python -m uds_assistant.rag.ingest --check``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from uds_assistant.rag.model import Chunk

PARSER_VERSION = 1
AUTOSAR_PDF_ENV = "UDS_AUTOSAR_PDF"
"""Path to the SWS PDF, or ``off`` to ignore any PDF in ``data/sources/``."""
SOURCES_DIR = Path("data") / "sources"
CACHE_DIR = SOURCES_DIR / ".cache"
PDF_GLOBS = ("*DiagnosticCommunicationManager*.pdf", "*SWS*Dcm*.pdf", "*Dcm*SWS*.pdf")

OPEN_BRACKET = "⌈"  # ⌈
CLOSE_BRACKET = "⌋"  # ⌋

_REQ_ID = r"SWS_Dcm_(?:CONSTR_)?\d{5}"
_REQ_START_RE = re.compile(rf"^\s*\[({_REQ_ID})\]\s*(.*)$")
_SECTION_RE = re.compile(r"^([1-9]\d?(?:\.\d{1,3}){1,6})\.?\s+([A-Z][^\n]{1,150}?)\s*$")
_TOC_LINE_RE = re.compile(r"(\.\s*){4,}\s*\d+\s*$|\s\d{1,4}\s*$")
_PAGE_NO_RE = re.compile(r"^\s*(page\s*)?\d+\s*(of\s*\d+)?\s*$", re.IGNORECASE)
_RELEASE_RE = re.compile(r"\bR(\d{2})-(\d{2})\b")
_SRS_RE = re.compile(r"\b(?:SRS|RS)_[A-Za-z]+_\d{3,5}\b")
_WS_RE = re.compile(r"\s+")

#: A line on at least this share of pages (min 3 pages) is treated as header/footer.
BOILERPLATE_SHARE = 0.5
#: Header/footer lines are looked for only this many lines from the top and bottom of a page.
EDGE_LINES = 3
#: Requirement bodies are cut after this many lines if no end marker is found.
MAX_REQ_LINES = 60


@dataclass
class SwsRequirement:
    """One parsed SWS requirement."""

    req_id: str
    text: str
    """Requirement body (brackets and upstream trace stripped, whitespace collapsed)."""
    page: int
    """1-based page the requirement starts on."""
    section: str = ""
    """Last numbered heading above it, e.g. ``"7.4.2.1 Verification of the Service Identifier"``."""
    upstream: list[str] = field(default_factory=list)
    """Upstream ``SRS_...`` ids traced right after the requirement."""


@dataclass
class SwsDocument:
    """The parsed SWS: its requirements plus document-level metadata."""

    source_path: str
    release: str = ""
    title: str = ""
    pages: int = 0
    bracket_mode: bool = False
    requirements: list[SwsRequirement] = field(default_factory=list)

    def by_id(self) -> dict[str, SwsRequirement]:
        return {r.req_id: r for r in self.requirements}


# --------------------------------------------------------------------------- locating the PDF


def find_sws_pdf(repo_root: Path) -> Path | None:
    """The SWS PDF to use: ``$UDS_AUTOSAR_PDF`` if set (``off`` disables), else a glob match."""
    env = os.environ.get(AUTOSAR_PDF_ENV, "").strip()
    if env.lower() in {"off", "0", "none", "false"}:
        return None
    if env:
        p = Path(env)
        if not p.is_absolute():
            p = repo_root / p
        return p if p.is_file() else None
    src = repo_root / SOURCES_DIR
    if not src.is_dir():
        return None
    for pattern in PDF_GLOBS:
        hits = sorted(src.glob(pattern))
        if hits:
            return hits[0]
    return None


def sws_status(repo_root: Path) -> dict[str, object]:
    """What feeds the ``standard`` layer, for display (UI sidebar, API ``/config``)."""
    pdf = find_sws_pdf(Path(repo_root))
    notes = Path(repo_root) / SOURCES_DIR / "uds_reference_notes.md"
    env = os.environ.get(AUTOSAR_PDF_ENV, "").strip()
    if pdf is not None:
        mode = "pdf+notes" if notes.exists() else "pdf"
        reason = f"AUTOSAR SWS requirements from {pdf.name}"
    else:
        mode = "notes" if notes.exists() else "none"
        reason = (
            f"{AUTOSAR_PDF_ENV}={env} does not point at a readable PDF"
            if env and env.lower() not in {"off", "0", "none", "false"}
            else ("AUTOSAR PDF disabled" if env else "no AUTOSAR SWS PDF in data/sources/")
        ) + ("; using the own-words notes" if notes.exists() else "; standard layer is empty")
    return {"mode": mode, "pdf": str(pdf) if pdf else None, "notes": notes.exists(),
            "detail": reason}


# --------------------------------------------------------------------------- text extraction


def extract_pdf_pages(pdf_path: Path) -> list[str]:
    """Text of every page (pypdf, imported lazily so the package works without it)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency listed in pyproject
        raise RuntimeError("pypdf is required to read the AUTOSAR PDF (pip install pypdf)") from exc
    reader = PdfReader(str(pdf_path))
    return [(page.extract_text() or "") for page in reader.pages]


def _norm_line(line: str) -> str:
    return re.sub(r"\d+", "#", _WS_RE.sub(" ", line).strip())


def strip_boilerplate(pages: list[str]) -> list[list[str]]:
    """Per page, its non-empty lines minus running headers/footers and bare page numbers.

    Only the first and last :data:`EDGE_LINES` lines of a page can be header/footer: a line there
    whose digit-normalized form is in that zone on at least :data:`BOILERPLATE_SHARE` of the pages
    is dropped. Lines carrying requirement brackets or an SWS id are never dropped.
    """
    split = [[ln.rstrip() for ln in p.splitlines() if ln.strip()] for p in pages]
    counts: Counter[str] = Counter()
    for lines in split:
        counts.update({_norm_line(ln) for ln in _edges(lines)})
    limit = max(3, int(len(pages) * BOILERPLATE_SHARE))
    common = {k for k, n in counts.items() if n >= limit
              and OPEN_BRACKET not in k and CLOSE_BRACKET not in k and "SWS_" not in k}
    if len(pages) < 3:
        common = set()
    out: list[list[str]] = []
    for lines in split:
        edge = set(range(min(EDGE_LINES, len(lines)))) | set(
            range(max(0, len(lines) - EDGE_LINES), len(lines)))
        out.append([ln for i, ln in enumerate(lines)
                    if not (i in edge and (_norm_line(ln) in common or _PAGE_NO_RE.match(ln)))])
    return out


def _edges(lines: list[str]) -> list[str]:
    return lines[:EDGE_LINES] + lines[EDGE_LINES:][-EDGE_LINES:]


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", text.replace(OPEN_BRACKET, " ").replace(CLOSE_BRACKET, " ")).strip()


def _section_of(line: str) -> str | None:
    m = _SECTION_RE.match(line)
    if not m or _TOC_LINE_RE.search(line):
        return None
    title = m.group(2)
    # A numbered heading has a short title and no sentence punctuation at the end.
    if len(title.split()) > 14 or title.endswith((".", ",", ";", ":")):
        return None
    return f"{m.group(1)} {title}"


def _metadata(pages: list[str]) -> tuple[str, str]:
    head = "\n".join(pages[:3])
    rel = _RELEASE_RE.search(head)
    release = f"R{rel.group(1)}-{rel.group(2)}" if rel else ""
    title = ""
    for line in head.splitlines():
        if "Specification of" in line:
            title = _clean(line)
            break
    return release, title


# --------------------------------------------------------------------------- parsing


def parse_sws_pages(pages: list[str], *, source_path: str) -> SwsDocument:
    """Parse per-page text into one :class:`SwsRequirement` per defined SWS id."""
    release, title = _metadata(pages)
    full = "\n".join(pages)
    bracket_mode = OPEN_BRACKET in full and CLOSE_BRACKET in full
    lines: list[tuple[int, str]] = [
        (page_no, ln) for page_no, page_lines in enumerate(strip_boilerplate(pages), start=1)
        for ln in page_lines
    ]

    found: dict[str, SwsRequirement] = {}
    section = ""
    i = 0
    while i < len(lines):
        page_no, line = lines[i]
        heading = _section_of(line)
        if heading is not None:
            section = heading
            i += 1
            continue
        m = _REQ_START_RE.match(line)
        if m is None:
            i += 1
            continue
        req_id, rest = m.group(1), m.group(2)
        if bracket_mode:
            lookahead = rest + " " + (lines[i + 1][1] if i + 1 < len(lines) else "")
            if OPEN_BRACKET not in lookahead[:120]:
                i += 1
                continue
        body: list[str] = [rest]
        j = i + 1
        closed = CLOSE_BRACKET in rest
        while not closed and j < len(lines) and j - i < MAX_REQ_LINES:
            nxt = lines[j][1]
            if _REQ_START_RE.match(nxt) or _section_of(nxt) is not None:
                break
            body.append(nxt)
            closed = CLOSE_BRACKET in nxt
            j += 1
        joined = "\n".join(body)
        upstream: list[str] = []
        if CLOSE_BRACKET in joined:
            joined, after = joined.split(CLOSE_BRACKET, 1)
            trail = after
            if j < len(lines) and not _REQ_START_RE.match(lines[j][1]):
                trail += " " + lines[j][1]  # the trace often wraps onto the next line
            upstream = list(dict.fromkeys(_SRS_RE.findall(trail.split("[SWS_", 1)[0])))
        text = _clean(joined)
        if text:
            req = SwsRequirement(req_id=req_id, text=text, page=page_no, section=section,
                                 upstream=upstream)
            old = found.get(req_id)
            if old is None or len(req.text) > len(old.text):
                found[req_id] = req
        i = max(j, i + 1)

    reqs = sorted(found.values(), key=lambda r: (r.page, r.req_id))
    return SwsDocument(source_path=source_path, release=release, title=title, pages=len(pages),
                       bracket_mode=bracket_mode, requirements=reqs)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_sws(pdf_path: Path, *, source_path: str, cache_dir: Path | None = None,
             use_cache: bool = True) -> SwsDocument:
    """Parse the PDF, reusing the JSON cache when the PDF and parser version are unchanged."""
    cache_file = None
    if cache_dir is not None and use_cache:
        cache_file = cache_dir / f"sws_{_sha256(pdf_path)[:16]}_v{PARSER_VERSION}.json"
        if cache_file.is_file():
            raw = json.loads(cache_file.read_text(encoding="utf-8"))
            raw["requirements"] = [SwsRequirement(**r) for r in raw["requirements"]]
            raw["source_path"] = source_path
            return SwsDocument(**raw)
    doc = parse_sws_pages(extract_pdf_pages(pdf_path), source_path=source_path)
    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(asdict(doc)), encoding="utf-8")
    return doc


# --------------------------------------------------------------------------- chunks


def sws_chunks(doc: SwsDocument) -> list[Chunk]:
    """One ``standard`` chunk per requirement; ``ref`` is the SWS id (e.g. ``SWS_Dcm_00197``)."""
    from uds_assistant.rag.ingest import extract_identifiers

    chunks: list[Chunk] = []
    for r in doc.requirements:
        where = f" ({r.section})" if r.section else ""
        text = f"{r.req_id}{where}: {r.text}"
        chunks.append(Chunk(
            id=f"standard:{r.req_id}",
            collection="standard",
            source_path=doc.source_path,
            ref=r.req_id,
            text=text,
            identifiers=extract_identifiers(text),
            page=r.page,
            section=r.section or None,
            release=doc.release or None,
            upstream=r.upstream,
        ))
    return chunks


def load_sws_chunks(repo_root: Path) -> list[Chunk]:
    """Requirement chunks from the local SWS PDF, or ``[]`` when there is none (notes fallback)."""
    pdf = find_sws_pdf(repo_root)
    if pdf is None:
        return []
    try:
        rel = pdf.resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        rel = pdf.name
    doc = load_sws(pdf, source_path=rel, cache_dir=Path(repo_root) / CACHE_DIR)
    return sws_chunks(doc)
