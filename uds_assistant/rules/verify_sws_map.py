"""Check :mod:`uds_assistant.rules.sws_map` against the local AUTOSAR Dcm SWS PDF.

    python -m uds_assistant.rules.verify_sws_map [--pdf PATH] [--no-cache] [--mark-verified]

For every SWS id the rules cite: PASS if the id is a requirement in the PDF and its text contains
every keyword of the entry (case, space and hyphen insensitive), else FAIL with the reason and the
start of the requirement text. Two checks need no PDF and always run: every id cited in the rules
source is in the map and vice versa. The PDF's release must be the one the map was built from.

``--mark-verified`` rewrites ``sws_map.py`` so that exactly the ids that passed carry
``verified=True`` (and the rest ``verified=False``). Exit code 0 only when nothing failed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from uds_assistant.rag.autosar import CACHE_DIR, find_sws_pdf, load_sws
from uds_assistant.rules import sws_map
from uds_assistant.rules.sws_map import SWS_RELEASE, SWS_REQUIREMENTS, ids_cited_in_code

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP_FILE = Path(sws_map.__file__)


def _norm(text: str) -> str:
    return re.sub(r"[\s\-­]+", "", text).lower()


def check_entries(by_id: dict[str, str]) -> list[tuple[str, bool, str]]:
    """``(sws_id, ok, detail)`` per map entry, given parsed requirement texts keyed by id."""
    rows: list[tuple[str, bool, str]] = []
    for sws_id, req in sorted(SWS_REQUIREMENTS.items()):
        text = by_id.get(sws_id)
        if text is None:
            rows.append((sws_id, False, "id not found as a requirement in the PDF"))
            continue
        missing = [k for k in req.keywords if _norm(k) not in _norm(text)]
        if missing:
            excerpt = text[:160] + ("..." if len(text) > 160 else "")
            rows.append((sws_id, False, f"keywords missing {missing}; text: {excerpt}"))
        else:
            rows.append((sws_id, True, f"keywords {list(req.keywords)} found"))
    return rows


def mark_verified(passed: set[str], path: Path = MAP_FILE) -> int:
    """Set ``verified=`` on each map line to whether its id passed; returns lines changed."""
    out, changed = [], 0
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        m = re.search(r'SwsReq\("(SWS_Dcm_\d{5})"', line)
        if m and "verified=" in line:
            new = re.sub(r"verified=(True|False)", f"verified={m.group(1) in passed}", line)
            changed += new != line
            line = new
        out.append(line)
    path.write_text("".join(out), encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify rules/sws_map.py against the local SWS PDF.")
    ap.add_argument("--pdf", help="path to the SWS PDF (default: UDS_AUTOSAR_PDF or data/sources/)")
    ap.add_argument("--no-cache", action="store_true", help="re-parse the PDF, ignore the cache")
    ap.add_argument("--mark-verified", action="store_true",
                    help="write verified=True/False into sws_map.py from this run's results")
    args = ap.parse_args(argv)

    results: list[tuple[str, bool, str]] = []
    code_ids, map_ids = ids_cited_in_code(), set(SWS_REQUIREMENTS)
    results.append(("code ids are in the map", not (code_ids - map_ids),
                    f"{len(code_ids)} ids cited in rules/*.py"
                    + (f"; missing from map: {sorted(code_ids - map_ids)}" if code_ids - map_ids else "")))
    results.append(("map ids are cited in code", not (map_ids - code_ids),
                    f"{len(map_ids)} map entries"
                    + (f"; not cited in code: {sorted(map_ids - code_ids)}" if map_ids - code_ids else "")))

    pdf = Path(args.pdf) if args.pdf else find_sws_pdf(REPO_ROOT)
    entry_rows: list[tuple[str, bool, str]] = []
    if pdf is None or not pdf.is_file():
        results.append(("SWS PDF found", False,
                        "put the AUTOSAR CP R24-11 Dcm SWS PDF in data/sources/ or set UDS_AUTOSAR_PDF"))
    else:
        results.append(("SWS PDF found", True, str(pdf)))
        doc = load_sws(pdf, source_path=pdf.name, cache_dir=REPO_ROOT / CACHE_DIR,
                       use_cache=not args.no_cache)
        results.append(("PDF release matches the map", doc.release == SWS_RELEASE,
                        f"PDF release {doc.release or 'not detected'}, map built from {SWS_RELEASE}"))
        results.append(("requirements parsed", len(doc.requirements) > 0,
                        (f"{len(doc.requirements)} requirements from {doc.pages} pages "
                         f"(bracket markers {'found' if doc.bracket_mode else 'NOT found'})")))
        entry_rows = check_entries({r.req_id: r.text for r in doc.requirements})

    print("verify_sws_map")
    for name, ok, detail in results + entry_rows:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    n_fail = sum(1 for _, ok, _ in results + entry_rows if not ok)
    n_pass = len(results) + len(entry_rows) - n_fail
    passed_ids = {i for i, ok, _ in entry_rows if ok}
    print(f"\n{n_pass} PASS, {n_fail} FAIL; map entries verified: {len(passed_ids)}/{len(map_ids)}")
    if args.mark_verified:
        if not entry_rows:
            print("--mark-verified: nothing written (no PDF was checked)")
        else:
            changed = mark_verified(passed_ids)
            print(f"--mark-verified: {changed} line(s) changed in {MAP_FILE.name}")
    print("RESULT:", "PASS" if n_fail == 0 else "FAIL")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
