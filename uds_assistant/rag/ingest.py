"""Builds the retrieval corpus: markdown, YAML spec, and CSV requirements chunks.

Four layered collections are produced:

- ``standard``: ``data/sources/uds_reference_notes.md`` (own-words protocol notes) plus, when a
  local copy of the AUTOSAR Dcm SWS PDF is present, one chunk per SWS requirement
  (:mod:`uds_assistant.rag.autosar`). Without the PDF the notes are used alone.
- ``oem``: ``data/oem_diagnostic_guidelines.md`` (synthetic OEM-style diagnostic policy).
- ``ecu``: one chunk per session / security level / DID / routine / DTC / timing
  entry in ``data/bcm_spec.yaml``.
- ``project``: sections of ``docs/behaviour_contract.md`` and rows of
  ``data/requirements_seed.csv``.

``python -m uds_assistant.rag.ingest --check`` builds the corpus and the Chroma index and prints
chunk counts, build time, sample AUTOSAR citations and a PASS/FAIL list.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import yaml

from uds_assistant.rag.autosar import load_sws_chunks
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
    standard (notes, then AUTOSAR SWS requirements), ecu, project, then oem, so
    the original layers keep the positions they had before the OEM layer and the
    SWS chunks existed. Missing optional source files are skipped silently.
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

    if "standard" in wanted:
        # AUTOSAR SWS requirements (local PDF only); [] when absent, so the notes are the fallback.
        chunks.extend(load_sws_chunks(repo_root))

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


# ----------------------------------------------------------------------------- --check

#: Queries whose top standard-layer hits should include an AUTOSAR requirement.
CHECK_QUERIES: tuple[str, ...] = (
    "service identifier not supported negative response 0x11",
    "security access invalid key attempt counter 0x35",
    "S3 server timeout return to default session",
    "write data by identifier security level 0x33",
)
MIN_SWS_REQUIREMENTS = 500
"""The Dcm SWS defines well over this many requirements; fewer means the parser lost some."""


def check(repo_root: Path, *, build_index: bool = True, persist_dir: Path | None = None) -> int:
    """Build the corpus (and the Chroma index), print counts, timings, samples and PASS/FAIL."""
    import time

    from uds_assistant.rag.autosar import sws_status
    from uds_assistant.rag.layers import layer_counts
    from uds_assistant.rules.sws_map import SWS_RELEASE, SWS_REQUIREMENTS

    results: list[tuple[str, bool, str]] = []
    status = sws_status(repo_root)
    print(f"standard layer source: {status['mode']} ({status['detail']})")

    t0 = time.perf_counter()
    corpus = build_corpus(repo_root)
    t_corpus = time.perf_counter() - t0
    sws = [c for c in corpus if c.id.startswith("standard:SWS_")]
    counts = layer_counts(corpus)
    print(f"corpus built in {t_corpus:.1f} s: {len(corpus)} chunks "
          + ", ".join(f"{k} {v}" for k, v in counts.items())
          + f" (of which AUTOSAR SWS requirements: {len(sws)})")

    results.append(("SWS PDF found", status["pdf"] is not None, str(status["pdf"] or status["detail"])))
    results.append(("own-words notes present (deterministic standard ids)", bool(status["notes"]),
                    "data/sources/uds_reference_notes.md"))
    results.append((f"at least {MIN_SWS_REQUIREMENTS} SWS requirement chunks",
                    len(sws) >= MIN_SWS_REQUIREMENTS, f"{len(sws)} chunks"))
    if sws:
        releases = sorted({c.release or "?" for c in sws})
        results.append(("release detected and matches the rules", releases == [SWS_RELEASE],
                        f"{releases}, rules cite {SWS_RELEASE}"))
        with_page = sum(1 for c in sws if c.page)
        with_section = sum(1 for c in sws if c.section)
        results.append(("every SWS chunk has a page", with_page == len(sws),
                        f"{with_page}/{len(sws)}"))
        results.append(("at least 95% of SWS chunks have a section", with_section >= 0.95 * len(sws),
                        f"{with_section}/{len(sws)}"))
        ids = {c.ref for c in sws}
        cited = set(SWS_REQUIREMENTS)
        results.append(("every SWS id the rules cite is a chunk", cited <= ids,
                        f"{len(cited & ids)}/{len(cited)}"
                        + (f"; missing {sorted(cited - ids)}" if cited - ids else "")))
        print("\nsample chunks:")
        for c in sws[:: max(1, len(sws) // 3)][:3]:
            print(f"  {c.ref} | page {c.page} | {c.section} | {c.text[:110]}...")

    if build_index:
        from uds_assistant.rag.chroma import DEFAULT_PERSIST_DIR, ChromaRetriever

        persist = persist_dir or repo_root / DEFAULT_PERSIST_DIR
        t0 = time.perf_counter()
        retriever = ChromaRetriever(corpus, persist_dir=persist)
        t_index = time.perf_counter() - t0
        print(f"\nChroma index at {persist} built/synced in {t_index:.1f} s "
              f"({retriever.embedded_count} chunks embedded this run)")
        stored = {g: c.count() for g, c in retriever._collections.items()}
        results.append(("Chroma collections match the corpus", stored == counts,
                        f"stored {stored}"))
        print("\nsample citations (standard layer, top 3):")
        for q in CHECK_QUERIES:
            hits = retriever.search(q, k=3, collections=["standard"])
            print(f"  Q: {q}")
            for h in hits:
                c = h.to_layered_citation()
                where = f"page {c.page}, {c.section}" if c.page else "notes"
                print(f"    {h.score:.3f} {c.source} #{c.ref} ({where})")
            if sws:
                ok = any(h.chunk.id.startswith("standard:SWS_") for h in hits)
                results.append((f"query returns an SWS citation: {q!r}", ok,
                                ", ".join(h.chunk.ref for h in hits)))

    print("\nchecks:")
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    n_fail = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{len(results) - n_fail} PASS, {n_fail} FAIL")
    print("RESULT:", "PASS" if n_fail == 0 else "FAIL")
    return 0 if n_fail == 0 else 1


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m uds_assistant.rag.ingest --check [--no-index] [--root DIR]``."""
    import argparse

    ap = argparse.ArgumentParser(description="Build and check the retrieval corpus and index.")
    ap.add_argument("--check", action="store_true", help="build, print counts and PASS/FAIL list")
    ap.add_argument("--no-index", action="store_true", help="skip the Chroma index (no embeddings)")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]),
                    help="repository root (default: this checkout)")
    ap.add_argument("--persist-dir", help="Chroma directory (default: <root>/outputs/chroma)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if not args.check:
        corpus = build_corpus(root)
        print(f"{len(corpus)} chunks; use --check for the full report")
        return 0
    return check(root, build_index=not args.no_index,
                 persist_dir=Path(args.persist_dir) if args.persist_dir else None)


if __name__ == "__main__":
    raise SystemExit(main())
