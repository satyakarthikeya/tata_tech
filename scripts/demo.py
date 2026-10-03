"""End-to-end terminal demo of the UDS test-generation assistant.

Run from the repo root::

    python scripts/demo.py                      # REQ-005, mock LLM, default bug
    python scripts/demo.py --req REQ-010
    python scripts/demo.py --text "The tester shall be able to read the VIN."
    python scripts/demo.py --bug write_length_off_by_one
    python scripts/demo.py --req REQ-006 --bug write_range_upper_bound_exclusive   # a held-out v2 bug
    python scripts/demo.py --offline            # skip the pipeline, use outputs/generated_tests.yaml
    python scripts/demo.py --full-eval          # also re-run the full evaluation (~35 s)
    python scripts/demo.py --llm ollama         # local Qwen2.5-3B (~30 s per requirement)

--bug accepts any simulator bug id: in-sample, held-out v1 (seen) or held-out v2 (fresh, written
blind after the Part C freeze). Section [5] reads the headline from outputs/eval_report.json
(report version 3: the fresh v2 rows first; older layouts degrade gracefully).

Uses only public APIs. The LLM defaults to the deterministic mock. ``--llm ollama``
uses ``get_llm``; if Ollama is unreachable it prints a warning and continues with the
mock. Nothing is written to ``outputs/`` (the optional full evaluation writes to a
temporary directory and always uses the mock).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uds_assistant.agent import run_pipeline
from uds_assistant.config import Config
from uds_assistant.llm.factory import get_llm
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.runner import run_suite, run_test
from uds_assistant.simulator import (
    ALL_BUG_IDS,
    HELDOUT_BUG_CATALOG_PATH,
    HELDOUT_BUG_IDS,
    HELDOUT_V2_BUG_CATALOG_PATH,
    HELDOUT_V2_BUG_IDS,
    load_bug_catalog,
)
from uds_assistant.spec.schema import load_spec
from uds_assistant.testgen import TestCase, load_tests

DEFAULT_BUG = "write_ignores_value_range"


def bug_set_and_def(bug_id: str):
    """Return ``(label, BugDef or None)`` for any simulator bug id."""
    path = None
    if bug_id in HELDOUT_V2_BUG_IDS:
        label = "held-out v2 (FRESH: written blind after the Part C freeze)"
        path = HELDOUT_V2_BUG_CATALOG_PATH
    elif bug_id in HELDOUT_BUG_IDS:
        label = "held-out v1 (SEEN: templates were designed against these misses)"
        path = HELDOUT_BUG_CATALOG_PATH
    else:
        label = "in-sample (the templates were tuned on these)"
    try:
        catalog = load_bug_catalog(path) if path is not None else load_bug_catalog()
    except (OSError, ValueError):
        return label, None
    return label, catalog.get(bug_id)


def header(n: int, title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 78}\n[{n}] {title}\n{'=' * 78}")


def pick_test(tests: list[TestCase], failing: list[str]) -> TestCase | None:
    """Prefer a test that is caught by the bug, else the first one."""
    by_id = {t.id: t for t in tests}
    for tid in failing:
        if tid in by_id:
            return by_id[tid]
    return tests[0] if tests else None


def show_test(test: TestCase) -> None:
    """Print a test's steps in hex plus its citations."""
    print(f"Test {test.id}  [{test.category}]  template={test.template_id}")
    print(f"Title: {test.title}")
    for i, s in enumerate(test.steps):
        if s.kind == "send":
            exp = " | ".join(s.expected_responses_hex)
            print(
                f"  step {i}: send {s.request_hex.upper():<18} "
                f"expect {exp.upper():<22} # {s.description}"
            )
        elif s.kind == "advance_time":
            print(f"  step {i}: advance clock {s.ms} ms")
        else:
            print(f"  step {i}: {s.kind} {s.description}")
    for c in test.citations[:3]:
        print(f"  cite: {c.source} :: {c.ref}")


def show_failure(test: TestCase, spec, bug: str) -> bool:
    """Run one test with the bug; print the first failing step. Return True if it failed."""
    res = run_test(test, spec, {bug})
    first = res.outcome.first_failure
    if first is None:
        print(f"  {test.id}: still passes with bug {bug}")
        return False
    step = test.steps[first.index]
    print(f"  {test.id}: FAIL at step {first.index}")
    print(f"    request  : {step.request_hex.upper()}")
    print(f"    expected : {[h.upper() for h in first.expected_responses_hex]}")
    print(f"    actual   : {[h.upper() for h in first.actual_responses_hex]}")
    return True


def _und_line(label: str, ru: dict) -> str:
    return (
        f"  {label:<7} parsed exact {ru['target_exact_parsed']}/{ru['requirements']}, "
        f"P/R/F1 {ru['target_precision_parsed']:.3f}/{ru['target_recall_parsed']:.3f}/"
        f"{ru['target_f1_parsed']:.3f}"
    )


def _det_lines(title: str, row: dict, modes: list[str]) -> None:
    """Per-mode generated / gold / union lines for one held-out detection row."""
    bugs = row["bugs"]
    by_mode = row.get("by_mode") or {}
    print(title.replace("{bugs}", str(bugs)))
    for m in modes:
        b = by_mode.get(m, row)
        if not isinstance(b, dict):
            print(f"  {m:<7} {b}")
            continue
        print(
            f"  {m:<7} generated {b['generated']['detected']}/{bugs} "
            f"({b['generated']['rate']:.1%}), gold {b['gold']['detected']}/{bugs}, "
            f"union {b['union']['detected']}/{bugs}"
        )


def _und_lines(title: str, row: dict, modes: list[str]) -> None:
    ok = [m for m in modes if isinstance(row.get(m), dict)]
    n = row[ok[0]]["requirements"] if ok else "?"
    print(title.replace("{n}", str(n)))
    for m in modes:
        if isinstance(row.get(m), dict):
            print(_und_line(m, row[m]))
        elif m in row:
            print(f"  {m:<7} {row[m]}")


def _noise_lines(report: dict) -> None:
    for m in ("mock", "ollama"):
        nc = ((report.get("modes") or {}).get(m) or {}).get("noise_check") or {}
        if nc.get("status") != "completed":
            print(f"  noise check {m}: not run yet")
            continue
        f1 = (nc.get("summary") or {}).get("parsed_f1") or {}
        if nc.get("deterministic"):
            same = (nc.get("determinism_check") or {}).get("second_run_identical")
            print(f"  noise check {m}: deterministic, re-run identical = {same}")
        elif f1.get("mean") is not None:
            print(
                f"  noise check {m}: {len(nc.get('runs') or [])} runs, parsed F1 mean "
                f"{f1['mean']} (min-max {f1['min']} to {f1['max']})"
            )


def headline_lines() -> None:
    """Print the headline from the eval report (version 3 layout; older layouts degrade)."""
    path = Path(os.environ.get("UDS_EVAL_REPORT") or ROOT / "outputs" / "eval_report.json")
    if not path.exists():
        print("outputs/eval_report.json not found (run: python -m uds_assistant.eval.run_eval)")
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    version = report.get("report_version", 1)
    h = report["headline"]
    ho = h["heldout_bug_detection"]
    ru = h["requirement_understanding"]
    agr = h["simulator_rules_agreement"]
    by_mode = ho.get("by_mode") or {}
    modes = [m for m in ("mock", "ollama") if m in by_mode or (m in ru and isinstance(ru[m], dict))]
    print(f"Report version {version}. Modes in this report: {', '.join(modes) or h.get('mode')}")
    print(f"Simulator <-> rules agreement : {agr['agreed']}/{agr['total']}")
    print(f"Gold tests on clean simulator : {h['gold_clean_pass']['passed']}/{h['gold_clean_pass']['total']}")
    print(f"udsoncan virtual-CAN sequence : {h['udsoncan_virtual_can']['status'].upper()}")
    fr = report.get("freeze")
    if version >= 3 and isinstance(fr, dict) and "all_ok" in fr:
        print(f"Part C freeze: all recorded hashes match and are clean = {fr['all_ok']}")
    else:
        print("Part C freeze: n/a (report predates Part C)")
    v2_bug = h.get("heldout_v2_bug_detection")
    v2_und = h.get("requirement_understanding_v2")
    if version >= 3 and isinstance(v2_bug, dict) and isinstance(v2_und, dict):
        print("\nFRESH v2 headline (written blind after the freeze; nothing was tuned on it):")
        _det_lines("HELD-OUT v2 bug detection ({bugs} bugs; generated suite is the headline):", v2_bug, modes)
        _und_lines("Natural v2 requirement understanding (test2, n={n}):", v2_und, modes)
        _noise_lines(report)
        print("\nSEEN / tuned-on rows (not independent evidence):")
        _det_lines("HELD-OUT v1 bug detection ({bugs} bugs; SEEN: templates designed against these misses):", ho, modes)
        _und_lines("Natural v1 test split (n={n}; SEEN):", ru, modes)
    else:
        print("Fresh v2 headline: n/a - this report predates Part C (re-run the evaluation).")
        _det_lines("HELD-OUT bug detection ({bugs} bugs):", ho, modes)
        _und_lines("Requirement understanding (test split n={n}):", ru, modes)
    lat = ((report.get("modes") or {}).get("ollama") or {}).get("latency", {})
    lat_m = ((report.get("modes") or {}).get("mock") or {}).get("latency", {})
    w = (lat.get("per_requirement_wall_s") or {}).get("all")
    wm = (lat_m.get("per_requirement_wall_s") or {}).get("all")
    if w and wm:
        print(
            f"Latency per requirement (mean / p95): mock {wm['mean']:.2f} s / {wm['p95']:.2f} s, "
            f"ollama {w['mean']:.1f} s / {w['p95']:.1f} s"
        )
    ba = Path(os.environ.get("UDS_BEFORE_AFTER") or ROOT / "outputs" / "partC" / "before_after.md")
    print(
        f"Before/after table: {ba.relative_to(ROOT) if ba.is_relative_to(ROOT) else ba}"
        if ba.exists()
        else "Before/after table: not generated yet (run_eval --before-after)"
    )
    if version >= 3:
        print(
            "Read the table above: the v2 rows are the independent evidence; see docs/RESULTS.md "
            "for the interpretation."
        )
    elif "ollama" in modes:
        print(
            "Result: on the held-out TEST split the local 3B model did NOT beat the mock on any "
            "headline metric (higher parsed recall, much lower precision; held-out detection "
            "equal; much slower), so mock stays the default."
        )
    if version >= 3:
        print("Honest note: in-sample and v1 held-out numbers are optimistic (seen); trust the fresh v2 rows.")
    else:
        print("Honest note: the held-out number is the real one; in-sample detection was optimistic.")


def main(argv: list[str] | None = None) -> int:
    """Run the demo; return the exit code."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--req", default="REQ-005", help="seed requirement id (default REQ-005)")
    p.add_argument("--text", help="free-text requirement (overrides --req)")
    p.add_argument("--bug", default=DEFAULT_BUG, help=f"bug id to inject (default {DEFAULT_BUG})")
    p.add_argument(
        "--offline",
        action="store_true",
        help="use outputs/generated_tests.yaml instead of running the pipeline",
    )
    p.add_argument("--full-eval", action="store_true", help="also re-run the full evaluation")
    p.add_argument(
        "--llm",
        choices=("mock", "ollama"),
        default="mock",
        help="LLM backend for section [2] (default mock; ollama falls back to mock with a warning)",
    )
    args = p.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    t0 = time.perf_counter()
    if args.bug not in ALL_BUG_IDS:
        print(f"Unknown bug {args.bug!r}. Choose from: {', '.join(sorted(ALL_BUG_IDS))}")
        return 2

    header(1, "Load the ECU spec")
    spec = load_spec(ROOT / "data" / "bcm_spec.yaml")
    print("NOTE: the spec is SYNTHETIC - a fictional Body Control Module written for this project.")
    print(f"Spec: {spec.ecu_name}")
    print(
        f"Sessions {len(spec.sessions)}, security levels {len(spec.security_levels)}, "
        f"DIDs {len(spec.dids)}, routines {len(spec.routines)}, DTCs {len(spec.dtcs)}"
    )

    header(2, f"Pick a requirement and generate tests ({args.llm} LLM)")
    if args.text:
        req_id, req_text = "REQ-FREE", args.text
    else:
        with (ROOT / "data" / "requirements_seed.csv").open(encoding="utf-8", newline="") as fh:
            rows = {r["id"]: r["text"] for r in csv.DictReader(fh) if r.get("id")}
        if args.req not in rows:
            print(f"Unknown requirement {args.req!r}. Choose from: {', '.join(rows)}")
            return 2
        req_id, req_text = args.req, rows[args.req]
    print(f"{req_id}: {req_text}")

    if args.offline:
        print("(--offline: loading pre-generated tests from outputs/generated_tests.yaml)")
        all_tests = load_tests(ROOT / "outputs" / "generated_tests.yaml")
        tests = [t for t in all_tests if req_id in t.requirement_ids]
    else:
        cfg = Config(llm_mode=args.llm, retriever="bm25")
        retriever = get_retriever(cfg, chunks=build_corpus(ROOT))
        if args.llm == "ollama":
            print("(ollama mode: about 30 s per requirement on a 4 GB GPU; please wait)")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            llm = get_llm(cfg)
        if args.llm == "ollama" and llm.name != "ollama":
            msgs = [str(w.message) for w in caught] or ["Ollama unavailable"]
            print(f"WARNING: {msgs[0]}")
            print("WARNING: continuing with the deterministic mock LLM, NOT ollama.")
        result = run_pipeline(req_text, req_id, spec, llm, retriever)
        tests = result.tests
        print(
            f"Engine={result.engine} llm={result.llm} plan attempts={result.plan_attempts} "
            f"dropped={len(result.dropped)}"
        )
        if result.parsed is not None:
            print(f"Parsed: {result.parsed}")
        for note in result.notes:
            print(f"Note: {note}")
    counts = {c: sum(1 for t in tests if t.category == c) for c in sorted({t.category for t in tests})}
    print(f"\n{len(tests)} tests kept. Categories: {counts}")
    for t in tests:
        print(f"  {t.id:<46} {t.category:<9} {t.template_id}")
    if not tests:
        print("No tests were generated for this requirement (an honest outcome, not a crash).")
        return 0

    header(3, "Run the suite on the CLEAN simulator")
    clean = run_suite(tests, spec)
    print(f"Clean simulator: {clean.passed_count}/{clean.total} tests pass")

    header(4, f"Inject bug '{args.bug}' and re-run")
    bug_set, bug_def = bug_set_and_def(args.bug)
    print(f"Bug set: {bug_set}")
    if bug_def is not None:
        print(f"Bug: {bug_def.title}")
    buggy = run_suite(tests, spec, {args.bug})
    print(f"With bug: {buggy.passed_count}/{buggy.total} pass; {len(buggy.failed_ids)} FAIL")
    if buggy.failed_ids:
        more = " ..." if len(buggy.failed_ids) > 6 else ""
        print("Failing tests: " + ", ".join(buggy.failed_ids[:6]) + more)
    else:
        print("This bug is NOT caught by the tests for this requirement (try --bug or another --req).")
    chosen = pick_test(tests, buggy.failed_ids)
    if chosen is not None:
        print("\nOne test, steps in hex:")
        show_test(chosen)
        if buggy.failed_ids:
            print("\nFirst failing step on the buggy simulator:")
            show_failure(chosen, spec, args.bug)

    header(5, "Evaluation headline (from outputs/eval_report.json)")
    headline_lines()
    if args.full_eval:
        from uds_assistant.eval.run_eval import main as eval_main

        with tempfile.TemporaryDirectory() as tmp:
            print(f"\n--full-eval: running full evaluation into {tmp} ...")
            eval_main(["--mode", "mock", "--out", tmp, "--no-export-run", "--skip-can"])

    print(f"\nDemo finished in {time.perf_counter() - t0:.1f} s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
