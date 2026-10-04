"""End-to-end terminal demo: requirement -> tests -> run with a bug -> caught -> export.

Run from the repo root (Ollama must be running with the model pulled)::

    python scripts/demo.py                      # REQ-005, default bug
    python scripts/demo.py --req REQ-010
    python scripts/demo.py --text "The tester shall be able to read the VIN."
    python scripts/demo.py --bug write_ignores_value_range --req REQ-006

Steps: load the synthetic spec -> retrieve evidence and let the Ollama model parse and plan
-> the rules engine builds every byte -> run on the clean simulator -> inject one bug and run
again -> export pytest and CAPL files to ``outputs/exports/demo_*``.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uds_assistant.agent import run_pipeline
from uds_assistant.export import render_capl, render_pytest
from uds_assistant.llm.factory import OllamaUnavailableError, get_llm
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.runner import run_suite, run_test
from uds_assistant.simulator import ALL_BUG_IDS, HELDOUT_V3_BUG_CATALOG_PATH, load_bug_catalog
from uds_assistant.spec.schema import load_spec
from uds_assistant.testgen import TestCase

DEFAULT_BUG = "accepts_any_key"


def header(n: int, title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 78}\n[{n}] {title}\n{'=' * 78}")


def show_test(test: TestCase) -> None:
    """Print a test's steps in hex plus its citations."""
    print(f"Test {test.id}  [{test.category}]  template={test.template_id}")
    print(f"Title: {test.title}")
    for i, s in enumerate(test.steps):
        if s.kind == "send":
            exp = " | ".join(s.expected_responses_hex)
            print(f"  step {i}: send {s.request_hex.upper():<18} expect {exp.upper():<22} # {s.description}")
        elif s.kind == "advance_time":
            print(f"  step {i}: advance clock {s.ms} ms")
        else:
            print(f"  step {i}: {s.kind} {s.description}")
    for c in test.citations[:3]:
        print(f"  cite: {c.source} :: {c.ref}")


def show_failure(test: TestCase, spec, bug: str) -> None:
    """Run one test with the bug; print the first failing step."""
    first = run_test(test, spec, {bug}).outcome.first_failure
    if first is None:
        print(f"  {test.id}: still passes with bug {bug}")
        return
    step = test.steps[first.index]
    print(f"  {test.id}: FAIL at step {first.index}")
    print(f"    request  : {step.request_hex.upper()}")
    print(f"    expected : {[h.upper() for h in first.expected_responses_hex]}")
    print(f"    actual   : {[h.upper() for h in first.actual_responses_hex]}")


def main(argv: list[str] | None = None) -> int:
    """Run the demo; returns a process exit code."""
    p = argparse.ArgumentParser(description="UDS assistant end-to-end demo (needs Ollama)")
    p.add_argument("--req", default="REQ-005", help="seed requirement id (default REQ-005)")
    p.add_argument("--text", help="free-text requirement instead of a seed one")
    p.add_argument("--bug", default=DEFAULT_BUG, help=f"bug id to inject (default {DEFAULT_BUG})")
    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    t0 = time.perf_counter()
    if args.bug not in ALL_BUG_IDS:
        print(f"Unknown bug {args.bug!r}. Choose from: {', '.join(sorted(ALL_BUG_IDS))}")
        return 2
    try:
        llm = get_llm()
    except OllamaUnavailableError as exc:
        print(f"ERROR: {exc}")
        return 2

    header(1, "Load the ECU spec")
    spec = load_spec(ROOT / "data" / "bcm_spec.yaml")
    print("NOTE: the spec is SYNTHETIC - a fictional Body Control Module written for this project.")
    print(f"Spec: {spec.ecu_name}: {len(spec.sessions)} sessions, {len(spec.dids)} DIDs, "
          f"{len(spec.routines)} routines, {len(spec.dtcs)} DTCs")

    header(2, "Pick a requirement and generate tests (RAG + Ollama + rules engine)")
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
    retriever = get_retriever(chunks=build_corpus(ROOT), persist_dir=ROOT / "outputs" / "chroma")
    result = run_pipeline(req_text, req_id, spec, llm, retriever)
    tests = result.tests
    print(f"model={llm.model} plan attempts={result.plan_attempts} dropped={len(result.dropped)}")
    if result.parsed is not None:
        print(f"Parsed: {result.parsed}")
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
    bug = load_bug_catalog().get(args.bug) or load_bug_catalog(HELDOUT_V3_BUG_CATALOG_PATH).get(args.bug)
    if bug is not None:
        print(f"Bug: {bug.title}")
    buggy = run_suite(tests, spec, {args.bug})
    clean_ok = {r.test_id for r in clean.results if r.passed}
    caught = [t for t in buggy.failed_ids if t in clean_ok]
    print(f"With bug: {buggy.passed_count}/{buggy.total} pass")
    if caught:
        print(f"Bug caught by {len(caught)} test(s): " + ", ".join(caught[:6]))
        chosen = next(t for t in tests if t.id == caught[0])
        print("\nOne catching test, steps in hex:")
        show_test(chosen)
        print("\nFirst failing step on the buggy simulator:")
        show_failure(chosen, spec, args.bug)
    else:
        print("This bug is NOT caught by the tests for this requirement (try --bug or --req).")

    header(5, "Export")
    out = ROOT / "outputs" / "exports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "demo_tests_test.py").write_text(
        render_pytest(tests, filename="demo_tests_test.py"), encoding="utf-8")
    (out / "demo_tests.can").write_text(render_capl(tests), encoding="utf-8")
    print(f"Wrote {out / 'demo_tests_test.py'} and {out / 'demo_tests.can'} "
          "(CAPL is an unverified template; review before use).")

    print(f"\nDemo finished in {time.perf_counter() - t0:.1f} s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
