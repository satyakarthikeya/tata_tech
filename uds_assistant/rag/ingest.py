"""Builds the retrieval corpus: markdown, YAML spec, and CSV requirements chunks.

Four layered collections are produced:

- ``standard``: ``data/sources/uds_reference_notes.md`` (own-words protocol notes).
- ``oem``: ``data/oem_diagnostic_guidelines.md`` (synthetic OEM-style diagnostic policy).
- ``ecu``: one chunk per session / security level / DID / routine / DTC / timing
  entry in ``data/bcm_spec.yaml``.
- ``project``: sections of ``docs/behaviour_contract.md`` and rows of
  ``data/requirements_seed.csv``.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import yaml

from uds_assistant.rag.model import LAYERS, Chunk, normalize_layer

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_ANCHOR_RE = re.compile(r"\{#([^}]+)\}")
_HEX_RE = re.compile(r"\b0[xX][0-9A-Fa-f]+\b")


def _slugify(text: str) -> str:
    text = _ANCHOR_RE.sub("", text).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "section"


def normalize_identifier(raw: str) -> str:
    """Normalize a hex identifier to canonical ``"0xF190"`` upper-hex form."""
    cleaned = raw.strip()
    if cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    cleaned = cleaned.replace(" ", "")
    return "0x" + cleaned.upper()


def extract_identifiers(text: str) -> list[str]:
    """Pull out and normalize every ``0x..`` hex token mentioned in ``text``."""
    seen: list[str] = []
    for match in _HEX_RE.findall(text):
        norm = normalize_identifier(match)
        if norm not in seen:
            seen.append(norm)
    return seen


def chunk_markdown(path: Path, *, source_path: str, collection: str) -> list[Chunk]:
    """Split a markdown file into one chunk per heading (any level).

    Each chunk's text runs from just after its own heading line to just
    before the next heading line of any level. ``ref`` is the heading's
    explicit ``{#anchor}`` if present, else a slug of the heading text.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    headings: list[tuple[int, str, str]] = []  # (line_index, heading_text, anchor)
    for idx, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            heading_text = m.group(2)
            anchor_match = _ANCHOR_RE.search(heading_text)
            anchor = anchor_match.group(1) if anchor_match else _slugify(heading_text)
            headings.append((idx, _ANCHOR_RE.sub("", heading_text).strip(), anchor))

    chunks: list[Chunk] = []
    for i, (line_idx, heading_text, anchor) in enumerate(headings):
        end = headings[i + 1][0] if i + 1 < len(headings) else len(lines)
        body = "\n".join(lines[line_idx + 1 : end]).strip()
        text = f"{heading_text}\n{body}".strip()
        if not text:
            continue
        chunks.append(
            Chunk(
                id=f"{collection}:{anchor}",
                collection=collection,
                source_path=source_path,
                ref=anchor,
                text=text,
                identifiers=extract_identifiers(text) + extract_identifiers(heading_text),
            )
        )
    return chunks


def _fmt_hex(value: int, width: int = 2) -> str:
    return "0x" + format(value, f"0{width}X")


def chunk_ecu_spec(path: Path, *, source_path: str) -> list[Chunk]:
    """Build one human-readable ``ecu`` chunk per session/security level/
    DID/routine/DTC/timing entry in the BCM spec YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    chunks: list[Chunk] = []

    for sess in raw.get("sessions", []):
        sid = sess["id"]
        timing = sess.get("timing", {})
        services = ", ".join(_fmt_hex(s) for s in sess.get("allowed_services", []))
        text = (
            f"Session {_fmt_hex(sid)} {sess['name']}: allowed services [{services}]. "
            f"Timing: P2={timing.get('p2_ms')}ms, P2*={timing.get('p2_star_ms')}ms, "
            f"S3={timing.get('s3_ms')}ms."
        )
        ref = f"session:{sess['name']}"
        chunks.append(
            Chunk(
                id=f"ecu:{ref}",
                collection="ecu",
                source_path=source_path,
                ref=ref,
                text=text,
                identifiers=sorted(set(extract_identifiers(text) + [_fmt_hex(sid)])),
            )
        )

    for level in raw.get("security_levels", []):
        lvl = level["level"]
        text = (
            f"Security level {_fmt_hex(lvl)} {level['name']}: seed sub-function "
            f"{_fmt_hex(level['seed_subfunction'])}, key sub-function "
            f"{_fmt_hex(level['key_subfunction'])}, seed length {level['seed_length']} bytes, "
            f"max attempts {level['max_attempts']}, lockout delay {level['delay_ms']}ms, "
            f"allowed in sessions {[_fmt_hex(s) for s in level['allowed_sessions']]}."
        )
        ref = f"security_level:{level['name']}"
        chunks.append(
            Chunk(
                id=f"ecu:{ref}",
                collection="ecu",
                source_path=source_path,
                ref=ref,
                text=text,
                identifiers=sorted(set(extract_identifiers(text) + [_fmt_hex(lvl), "0x27"])),
            )
        )

    for did in raw.get("dids", []):
        did_id = did["id"]
        write_sessions = did.get("write_sessions", [])
        write_bit = (
            f"writable in sessions {[_fmt_hex(s) for s in write_sessions]} "
            f"requiring security level {_fmt_hex(did['write_security_level'])}"
            if write_sessions and "write_security_level" in did
            else ("writable (no security required)" if write_sessions else "read-only")
        )
        rng = did.get("value_range")
        range_bit = f" Value range {rng['min']}-{rng['max']}." if rng else ""
        text = (
            f"DID {_fmt_hex(did_id, 4)} {did['name']}: length {did['length']} bytes, "
            f"encoding {did['encoding']}, readable in sessions "
            f"{[_fmt_hex(s) for s in did['read_sessions']]}, {write_bit}.{range_bit}"
        )
        ref = f"did:{did['name']}"
        chunks.append(
            Chunk(
                id=f"ecu:{ref}",
                collection="ecu",
                source_path=source_path,
                ref=ref,
                text=text,
                identifiers=sorted(set(extract_identifiers(text) + [_fmt_hex(did_id, 4), "0x22"] + (["0x2E"] if write_sessions else []))),
            )
        )

    for routine in raw.get("routines", []):
        rid = routine["id"]
        text = (
            f"Routine {_fmt_hex(rid, 4)} {routine['name']}: allowed sub-functions "
            f"{[_fmt_hex(s) for s in routine['allowed_subfunctions']]}, sessions "
            f"{[_fmt_hex(s) for s in routine['sessions']]}, requires security level "
            f"{_fmt_hex(routine['security_level'])}, option record length "
            f"{routine['option_record_length']} bytes"
            + (", long-running (responds with 0x78 then a final response)" if routine.get("long_running") else "")
            + "."
        )
        ref = f"routine:{routine['name']}"
        chunks.append(
            Chunk(
                id=f"ecu:{ref}",
                collection="ecu",
                source_path=source_path,
                ref=ref,
                text=text,
                identifiers=sorted(set(extract_identifiers(text) + [_fmt_hex(rid, 4), "0x31"])),
            )
        )

    for dtc in raw.get("dtcs", []):
        text = (
            f"DTC {dtc['code']} {dtc['name']}: initial status "
            f"{_fmt_hex(dtc['initial_status'])}."
        )
        ref = f"dtc:{dtc['code']}"
        chunks.append(
            Chunk(
                id=f"ecu:{ref}",
                collection="ecu",
                source_path=source_path,
                ref=ref,
                text=text,
                identifiers=sorted(set(extract_identifiers(text) + [dtc["code"], "0x19", "0x14"])),
            )
        )

    return chunks


def chunk_requirements_csv(path: Path, *, source_path: str) -> list[Chunk]:
    """One ``project`` chunk per row of ``data/requirements_seed.csv``."""
    chunks: list[Chunk] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            text = f"{row['id']} ({row['category']}): {row['text']}"
            chunks.append(
                Chunk(
                    id=f"project:{row['id']}",
                    collection="project",
                    source_path=source_path,
                    ref=row["id"],
                    text=text,
                    identifiers=extract_identifiers(text),
                )
            )
    return chunks


def build_corpus(repo_root: Path, layers: tuple[str, ...] | list[str] | None = None) -> list[Chunk]:
    """Build the layered corpus from the repo's data/docs files.

    Returns chunks from the ``standard``, ``oem``, ``ecu`` and ``project``
    collections (restricted to ``layers`` if given). Chunk order is stable:
    standard, ecu, project, then oem, so the original three layers keep the
    positions they had before the OEM layer existed. Missing optional source
    files are skipped silently.
    """
    repo_root = Path(repo_root)
    wanted = set(LAYERS if layers is None else (normalize_layer(x) for x in layers))
    chunks: list[Chunk] = []

    standard_path = repo_root / "data" / "sources" / "uds_reference_notes.md"
    if "standard" in wanted and standard_path.exists():
        chunks.extend(
            chunk_markdown(
                standard_path,
                source_path="data/sources/uds_reference_notes.md",
                collection="standard",
            )
        )

    spec_path = repo_root / "data" / "bcm_spec.yaml"
    if "ecu" in wanted and spec_path.exists():
        chunks.extend(chunk_ecu_spec(spec_path, source_path="data/bcm_spec.yaml"))

    contract_path = repo_root / "docs" / "behaviour_contract.md"
    if "project" in wanted and contract_path.exists():
        chunks.extend(
            chunk_markdown(
                contract_path,
                source_path="docs/behaviour_contract.md",
                collection="project",
            )
        )

    req_path = repo_root / "data" / "requirements_seed.csv"
    if "project" in wanted and req_path.exists():
        chunks.extend(chunk_requirements_csv(req_path, source_path="data/requirements_seed.csv"))

    oem_path = repo_root / "data" / "oem_diagnostic_guidelines.md"
    if "oem" in wanted and oem_path.exists():
        chunks.extend(
            chunk_markdown(
                oem_path,
                source_path="data/oem_diagnostic_guidelines.md",
                collection="oem",
            )
        )

    return chunks
