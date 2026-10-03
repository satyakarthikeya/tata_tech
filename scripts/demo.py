"""End-to-end terminal demo of the UDS test-generation assistant.

Run from the repo root::

    python scripts/demo.py                      # REQ-005, mock LLM, default bug
    python scripts/demo.py --req REQ-010
    python scripts/demo.py --text "The tester shall be able to read the VIN."
    python scripts/demo.py --bug write_length_off_by_one
    python scripts/demo.py --offline            # skip the pipeline, use outputs/generated_tests.yaml
    python scripts/demo.py --full-eval          # also re-run the full evaluation (~35 s)

Uses only public APIs. The LLM is always the deterministic mock; nothing is written
to ``outputs/`` (the optional full evaluation writes to a temporary directory).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import time
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
from uds_assistant.simulator import IMPLEMENTED_BUG_IDS, load_bug_catalog
from uds_assistant.spec.schema import load_spec
from uds_assistant.testgen import TestCase, load_tests

DEFAULT_BUG = "write_ignores_value_range"


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


def headline_lines() -> None:
    """Print the held-out headline numbers from the committed eval report."""
    path = ROOT / "outputs" / "eval_report.json"
    if not path.exists():
        print("outputs/eval_report.json not found (run: python -m uds_assistant.eval.run_eval)")
        return
    h = json.loads(path.read_text(encoding="utf-8"))["headline"]
    ho = h["heldout_bug_detection"]
    ru = h["requirement_understanding"]["mock"]
    agr = h["simulator_rules_agreement"]
    print(f"Mode: {h['mode']} (ollama: {h['other_mode_status']})")
    print(f"Simulator <-> rules agreement : {agr['agreed']}/{agr['total']}")
    print(f"Gold tests on clean simulator : {h['gold_clean_pass']['passed']}/{h['gold_clean_pass']['total']}")
    print(f"udsoncan virtual-CAN sequence : {h['udsoncan_virtual_can']['status'].upper()}")
    print(
        f"HELD-OUT bug detection ({ho['bugs']} bugs): generated "
        f"{ho['generated']['detected']}/{ho['bugs']} ({ho['generated']['rate']:.1%}), "
        f"gold {ho['gold']['detected']}/{ho['bugs']}, union {ho['union']['detected']}/{ho['bugs']}"
    )
    print(
        f"Requirement understanding (test split n={ru['requirements']}): parsed exact "
        f"{ru['target_exact_parsed']}/{ru['requirements']}, F1 {ru['target_f1_parsed']:.3f}"
    )
    print("Honest note: the held-out number is the real one; in-sample 25/26 was optimistic.")


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
    args = p.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    t0 = time.perf_counter()
    if args.bug not in IMPLEMENTED_BUG_IDS:
        print(f"Unknown bug {args.bug!r}. Choose from: {', '.join(IMPLEMENTED_BUG_IDS)}")
        return 2

    header(1, "Load the ECU spec")
    spec = load_spec(ROOT / "data" / "bcm_spec.yaml")
    print("NOTE: the spec is SYNTHETIC - a fictional Body Control Module written for this project.")
    print(f"Spec: {spec.ecu_name}")
    print(
        f"Sessions {len(spec.sessions)}, security levels {len(spec.security_levels)}, "
        f"DIDs {len(spec.dids)}, routines {len(spec.routines)}, DTCs {len(spec.dtcs)}"
    )

    header(2, "Pick a requirement and generate tests (mock LLM)")
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
        cfg = Config(llm_mode="mock", retriever="bm25")
        retriever = get_retriever(cfg, chunks=build_corpus(ROOT))
        result = run_pipeline(req_text, req_id, spec, get_llm(cfg), retriever)
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
    bug_def = load_bug_catalog().get(args.bug)
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

    header(5, "Held-out evaluation headline (from outputs/eval_report.json)")
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
