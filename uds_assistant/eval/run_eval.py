"""One simple evaluation, matching the success metrics of the case-study PDF.

    python -m uds_assistant.eval.run_eval [--out outputs]

Needs Ollama (the pipeline and Q&A call the model). Writes ``<out>/eval_report.json`` and
``<out>/eval_report.md`` (one page, eight sections) plus the exported pytest / CAPL files in
``<out>/exports/``. When ``<out>`` is the repository's ``outputs/`` the report is also copied
to ``docs/RESULTS.md``.

Sections: 1 correctness (sanity), 2 generation accuracy, 3 coverage, 4 reuse rate,
5 defect detection (blind v3 bug set), 6 requirement understanding (natural v3), 7 Q&A quality,
8 test design time. Every number is measured in this run; nothing is estimated.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from uds_assistant.agent import run_pipeline
from uds_assistant.eval import metrics as m
from uds_assistant.eval import understanding as u
from uds_assistant.eval.agreement import DEFAULT_REQUESTS, simulator_rules_agreement
from uds_assistant.eval.can_check import run_udsoncan_sequence
from uds_assistant.eval.coverage import coverage_markdown, coverage_report
from uds_assistant.eval.qa_eval import load_questions, run_qa
from uds_assistant.export import render_capl, render_pytest
from uds_assistant.llm.factory import OllamaUnavailableError, get_llm
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.runner import run_bug_matrix, run_suite
from uds_assistant.simulator import HELDOUT_V3_BUG_CATALOG_PATH, load_bug_catalog
from uds_assistant.spec.schema import load_spec
from uds_assistant.testgen.conformance import build_conformance_suite
from uds_assistant.testgen.model import TestCase, load_tests
from uds_assistant.testgen.review_gate import select_for_run
from uds_assistant.testgen.templates import TEMPLATE_SET_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = 1
MANUAL_TIME_NOTE = "owner to fill (see docs/TEST_DESIGN_TIME.md)"


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                             timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def git_label(root: Path) -> str:
    """Short git hash, with ``+dirty`` if tracked files are modified."""
    h = _git(root, "rev-parse", "--short", "HEAD") or "unknown"
    return h + ("+dirty" if _git(root, "status", "--porcelain", "--untracked-files=no") else "")


def load_requirements(path: Path) -> list[dict[str, str]]:
    """Read ``id,text,category`` rows from the seed requirements CSV."""
    import csv

    with path.open(encoding="utf-8", newline="") as fh:
        return [row for row in csv.DictReader(fh) if row.get("id")]


def _timed_pipeline(text: str, rid: str, label: str, **kw: Any) -> tuple[Any, float]:
    t0 = time.perf_counter()
    res = run_pipeline(text, rid, **kw)
    wall = time.perf_counter() - t0
    print(f"[{label}] {rid}: {len(res.tests)} tests in {wall:.1f} s", file=sys.stderr, flush=True)
    return res, wall


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _detection(matrix: Any) -> dict[str, Any]:
    return {"bugs": len(matrix.bug_ids), "detected": len(matrix.detected_bug_ids),
            "caught": matrix.detected_bug_ids, "missed": matrix.undetected_bug_ids}


def run_evaluation(
    out_dir: str | Path = "outputs",
    *,
    repo_root: str | Path | None = None,
    requirement_ids: list[str] | None = None,
    run_can: bool = True,
    agreement_requests: int = DEFAULT_REQUESTS,
) -> dict[str, Any]:
    """Run the whole evaluation and write the report. Raises if Ollama is down."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    out = Path(out_dir)
    if not out.is_absolute():
        out = Path.cwd() / out
    (out / "exports").mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()
    git = git_label(root)  # taken before this run writes any file, so it names the code that ran

    llm = get_llm()
    corpus = build_corpus(root)
    retriever = get_retriever(chunks=corpus, persist_dir=root / "outputs" / "chroma")
    spec = load_spec(root / "data" / "bcm_spec.yaml")
    requirements = load_requirements(root / "data" / "requirements_seed.csv")
    if requirement_ids is not None:
        requirements = [r for r in requirements if r["id"] in set(requirement_ids)]
    natural = u.load_natural_requirements(root / "data" / "requirements_natural_v3.csv")
    gold = load_tests(root / "data" / "gold" / "gold_tests.yaml", spec)
    v3_catalog = load_bug_catalog(HELDOUT_V3_BUG_CATALOG_PATH)
    pipe: dict[str, Any] = {"spec": spec, "llm": llm, "retriever": retriever}

    # 1. correctness (sanity) ------------------------------------------------------------
    agreement = simulator_rules_agreement(spec, agreement_requests)
    gold_clean = run_suite(gold, spec)
    can = (run_udsoncan_sequence(spec) if run_can
           else {"status": "skipped", "steps": [], "error": None})

    # 2-4. generate from the seed requirements ----------------------------------------------
    results, walls = [], []
    for req in requirements:
        res, wall = _timed_pipeline(req["text"], req["id"], "seed", **pipe)
        results.append(res)
        walls.append(wall)
    # The evaluation measures every generated test; nobody reviews them here, so the review gate
    # is bypassed explicitly (it applies to the UI and API, not to measurement).
    generated: list[TestCase] = select_for_run(
        [t for r in results for t in r.tests], include_unreviewed=True)
    clean = run_suite(generated, spec)
    validity = m.request_validity(spec, generated)
    cov = m.coverage(generated, [r["id"] for r in requirements])
    reuse = m.template_reuse(spec, generated)
    cites = m.citation_validity(generated, corpus)

    # 5. defect detection on the blind v3 bug set: generated tests + conformance sweep -------
    sweep = build_conformance_suite(spec).tests
    ids = v3_catalog.ids
    det_gen = run_bug_matrix(generated, spec, ids, catalog=v3_catalog)
    det_sweep = run_bug_matrix(sweep, spec, ids, catalog=v3_catalog)
    caught = set(det_gen.detected_bug_ids) | set(det_sweep.detected_bug_ids)
    missed = [b for b in ids if b not in caught]
    missed_rows = [{"bug_id": b, "title": v3_catalog.get(b).title,
                    "category": v3_catalog.get(b).category} for b in missed]

    # 6. requirement understanding on natural v3 ----------------------------------------------
    rows, nat_walls = [], []
    for nreq in natural:
        res, wall = _timed_pipeline(nreq.text, nreq.id, "natural-v3", **pipe)
        nat_walls.append(wall)
        rows.append(u.score_requirement(spec, nreq, res.parsed, res.tests, res.status))
    understanding = u.aggregate(rows)

    # 7. Q&A ---------------------------------------------------------------------------------
    qa = run_qa(load_questions(root / "data" / "qa_eval.csv"),
                spec=spec, chunks=corpus, retriever=retriever, llm=llm)

    gen_cov = coverage_report(generated, spec)
    sweep_cov = coverage_report(sweep, spec)

    # exports (the pytest file is run by scripts/demo.py and the end-to-end check) -------------
    (out / "exports" / "generated_tests_test.py").write_text(
        render_pytest(generated, filename="generated_tests_test.py"), encoding="utf-8")
    (out / "exports" / "generated_tests.can").write_text(render_capl(generated), encoding="utf-8")

    (out / "exports" / "coverage_report.md").write_text(
        coverage_markdown(gen_cov, "# Coverage report (generated tests, seed requirements)"),
        encoding="utf-8")

    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "git": git,
        "llm": {"backend": llm.name, "model": llm.model, "num_ctx": llm.num_ctx},
        "retriever": "ChromaDB + BAAI/bge-small-en-v1.5 (fastembed)",
        "template_set": TEMPLATE_SET_VERSION,
        "requirements": len(requirements),
        "correctness": {
            "simulator_rules_agreement": {
                k: agreement[k] for k in ("requests", "agreed") if k in agreement},
            "gold_clean": {"passed": gold_clean.passed_count, "total": gold_clean.total},
            "udsoncan_virtual_can": {"status": can["status"], "error": can["error"]},
        },
        "generation_accuracy": {
            "tests": len(generated),
            "send_steps": validity["send_steps"],
            "well_formed_steps": validity["well_formed"],
            "valid_request_rate": validity["rate"],
            "clean_pass": clean.passed_count,
            "clean_pass_rate": round(clean.pass_rate, 4) if generated else None,
            "citations": cites["citations"],
            "citations_valid": cites["valid"],
        },
        "coverage": {
            "category_totals": cov["category_totals"],
            "requirements": cov["requirements"],
            "requirements_with_tests": cov["requirements_with_tests"],
        },
        "spec_coverage": {"generated": _cov_summary(gen_cov), "sweep": _cov_summary(sweep_cov)},
        "reuse": {"tests": reuse["tests"], "from_templates": reuse["template_instantiations"],
                  "rate": reuse["rate"], "templates_registered": reuse["templates_registered"]},
        "defect_detection": {
            "blind_set": "data/bugs/heldout_v3_catalog.yaml (written blind, not tuned on)",
            "bugs": len(ids), "caught": len(caught),
            "generated_tests": _detection(det_gen), "sweep": _detection(det_sweep),
            "generated_tests_count": len(generated), "sweep_tests_count": len(sweep),
            "missed": missed_rows,
        },
        "understanding": {
            "requirements": understanding["requirements"],
            "target_precision": understanding["targets_parsed"]["precision"],
            "target_recall": understanding["targets_parsed"]["recall"],
            "target_f1": understanding["targets_parsed"]["f1"],
            "category_recall": understanding["categories"]["micro_recall"],
            "precondition_recall": understanding["preconditions"]["micro_recall"],
            "precondition_recall_field": understanding["preconditions_field"]["micro_recall"],
            "per_requirement": rows,
        },
        "qa": {k: qa[k] for k in (
            "n_questions", "n_answerable", "n_unanswerable", "answer_accuracy",
            "answer_accuracy_n", "citation_correctness", "citation_correctness_n",
            "correct_not_found_rate", "correct_not_found_n", "false_not_found")},
        "test_design_time": {
            "tool_seconds_per_requirement_mean": round(statistics.mean(walls), 1) if walls else None,
            "tool_seconds_per_requirement_median": (
                round(statistics.median(walls), 1) if walls else None),
            "tool_seconds_per_requirement_max": round(max(walls), 1) if walls else None,
            "natural_v3_mean": round(statistics.mean(nat_walls), 1) if nat_walls else None,
            "requirements_timed": len(walls),
            "manual_minutes_per_requirement": MANUAL_TIME_NOTE,
        },
        "runtime_seconds": round(time.perf_counter() - t_start, 1),
    }
    (out / "eval_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = render_markdown(report)
    (out / "eval_report.md").write_text(md, encoding="utf-8")
    if out == (root / "outputs").resolve():
        (root / "docs" / "RESULTS.md").write_text(md, encoding="utf-8")
    return report


def _cov_summary(cov: dict[str, Any]) -> dict[str, Any]:
    """Per kind: items in the spec, items touched, and the zero-test items."""
    return {"tests": cov["tests"], "kinds": {
        kind: {"items": len(rows), "touched": sum(1 for r in rows if r["tests"]),
               "zero_tests": cov["uncovered"][kind]}
        for kind, rows in cov["items"].items()}}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def render_markdown(r: dict[str, Any]) -> str:
    """One-page Markdown report from the report dict."""
    c, g, cov, ru, dd, un, qa, td = (
        r["correctness"], r["generation_accuracy"], r["coverage"], r["reuse"],
        r["defect_detection"], r["understanding"], r["qa"], r["test_design_time"])
    ag = c["simulator_rules_agreement"]
    totals = cov["category_totals"]
    missed = ", ".join(f"`{x['bug_id']}` ({x['category']})" for x in dd["missed"]) or "none"
    llm = r["llm"]
    tool = (f"{td['tool_seconds_per_requirement_mean']} s / "
            f"{td['tool_seconds_per_requirement_median']} s / "
            f"{td['tool_seconds_per_requirement_max']} s (n={td['requirements_timed']})")
    rows = [
        ("1", "Simulator vs rules engine agreement",
         f"{ag.get('agreed')}/{ag.get('requests')} requests identical"),
        ("1", "Gold tests passing on clean simulator",
         f"{c['gold_clean']['passed']}/{c['gold_clean']['total']}"),
        ("1", "udsoncan over virtual CAN", c["udsoncan_virtual_can"]["status"]),
        ("2", "Valid requests (well-formed send steps)",
         f"{g['well_formed_steps']}/{g['send_steps']} = {_pct(g['valid_request_rate'])}"),
        ("2", "Generated tests passing on the clean simulator",
         f"{g['clean_pass']}/{g['tests']} = {_pct(g['clean_pass_rate'])}"),
        ("2", "Citations resolving to a real chunk", f"{g['citations_valid']}/{g['citations']}"),
        ("3", "Tests by type",
         ", ".join(f"{k} {v}" for k, v in totals.items())),
        ("3", "Requirements with at least one test",
         f"{cov['requirements_with_tests']}/{cov['requirements']}"),
        ("4", "Reuse rate (tests built from approved templates)",
         f"{ru['from_templates']}/{ru['tests']} = {_pct(ru['rate'])} ({ru['templates_registered']} templates)"),
        ("5", "Blind-set bugs caught (generated tests + sweep)", f"{dd['caught']}/{dd['bugs']}"),
        ("5", f"... generated tests alone ({dd['generated_tests_count']} tests)",
         f"{dd['generated_tests']['detected']}/{dd['bugs']}"),
        ("5", f"... conformance sweep alone ({dd['sweep_tests_count']} tests)",
         f"{dd['sweep']['detected']}/{dd['bugs']}"),
        ("6", "Target identification F1 (precision / recall)",
         f"{_pct(un['target_f1'])} ({_pct(un['target_precision'])} / {_pct(un['target_recall'])})"),
        ("6", "Category recall", _pct(un["category_recall"])),
        ("6", "Precondition recall (derived from steps)", _pct(un["precondition_recall"])),
        ("6", "Precondition recall (real `preconditions` field)",
         _pct(un["precondition_recall_field"])),
        ("7", "Answer accuracy",
         f"{qa['answer_accuracy_n']}/{qa['n_answerable']} = {_pct(qa['answer_accuracy'])}"),
        ("7", "Citation correctness",
         f"{qa['citation_correctness_n']}/{qa['n_answerable']} = {_pct(qa['citation_correctness'])}"),
        ("7", 'Correct "not found"', f"{qa['correct_not_found_n']}/{qa['n_unanswerable']}"),
        ("8", "Tool time per requirement (mean / median / max)", tool),
        ("8", "Manual time per requirement", td["manual_minutes_per_requirement"]),
    ]
    head = (
        f"Run: {r['timestamp']} | git `{r['git']}` | model `{llm['model']}` "
        f"(num_ctx {llm['num_ctx']}) | retriever: {r['retriever']} | "
        f"{r['requirements']} seed requirements | runtime {r['runtime_seconds']} s"
    )
    notes = " ".join([
        "Notes: (2) a request is well-formed if it decodes and the rules engine does not reject",
        "it with a format NRC (except deliberate malformed-request probes). (5) A bug counts as",
        "caught when a test that passes on the clean simulator fails with the bug injected; the",
        "blind v3 set was written without seeing templates or code. (6) Natural v3: "
        + f"{un['requirements']} blind requirements; preconditions are derived from the generated",
        "steps and, separately, read from each test's `preconditions` field. (7) Blind questions",
        "in `data/qa_eval.csv`. (8) Tool time includes the local 3B",
        "model on this machine.",
    ])
    banner = (
        "Synthetic ECU spec. Every number is measured in this run. "
        "The LLM never produces bytes; the rules engine builds them."
    )
    sc = r["spec_coverage"]

    def _cov_line(label: str, c: dict[str, Any]) -> str:
        parts = [f"{k.replace('_', ' ')} {v['touched']}/{v['items']}" for k, v in c["kinds"].items()]
        return f"- {label} ({c['tests']} tests): " + "; ".join(parts) + "."

    zero = [f"{k.replace('_', ' ')}: {', '.join(v['zero_tests'])}"
            for k, v in sc["generated"]["kinds"].items() if v["zero_tests"]]
    lines = [
        "# Evaluation report",
        "",
        head,
        "",
        banner,
        "",
        "| # | Metric | Result |",
        "|---|---|---|",
        *[f"| {n} | {metric} | {value} |" for n, metric, value in rows],
        "",
        f"**Missed blind-set bugs ({len(dd['missed'])}):** {missed}.",
        "",
        "## Spec coverage (`coverage_report`, items touched / items in `data/bcm_spec.yaml`)",
        "",
        _cov_line("Generated tests (seed requirements)", sc["generated"]),
        _cov_line("Conformance sweep", sc["sweep"]),
        "- Zero tests in the generated set: " + ("; ".join(zero) or "none") + ".",
        "- Full per-item table with positive/negative split: `outputs/exports/coverage_report.md`.",
        "",
        notes,
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description="Run the UDS assistant evaluation (needs Ollama).")
    ap.add_argument("--out", default="outputs", help="output directory (default: outputs)")
    ap.add_argument("--requirements", help="comma-separated seed requirement ids (smoke runs)")
    ap.add_argument("--skip-can", action="store_true", help="skip the udsoncan virtual-CAN check")
    args = ap.parse_args(argv)
    ids = [x.strip() for x in args.requirements.split(",")] if args.requirements else None
    try:
        report = run_evaluation(args.out, requirement_ids=ids, run_can=not args.skip_can)
    except OllamaUnavailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
