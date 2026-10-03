"""End-to-end evaluation: generate tests for the seed requirements and score them.

CLI::

    python -m uds_assistant.eval.run_eval --mode mock [--out outputs] [--engine auto|plain|langgraph]

``--mode`` selects the LLM backend (``mock`` | ``ollama``). ``ollama`` falls back
to the mock LLM with a warning if the server is unreachable; the report records
the requested *and* the actually used mode. Results are written to
``<out>/eval_report.json`` and ``<out>/eval_report.md``; exports go to
``<out>/exports/`` and the exported generated-suite pytest file is run once in a
subprocess. The audit trail is ``<out>/audit.sqlite``.

Programmatic use (e.g. from an API endpoint): :func:`run_evaluation`.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from uds_assistant.agent import resolve_engine, run_pipeline
from uds_assistant.agent.state import PipelineResult
from uds_assistant.config import Config, get_config
from uds_assistant.eval import metrics as m
from uds_assistant.eval import understanding as u
from uds_assistant.eval.agreement import DEFAULT_REQUESTS, simulator_rules_agreement
from uds_assistant.eval.can_check import run_udsoncan_sequence
from uds_assistant.eval.heldout import heldout_analysis
from uds_assistant.eval.report_md import render_markdown
from uds_assistant.eval.retrieval_compare import run_retrieval_comparison
from uds_assistant.export import to_capl, to_pytest
from uds_assistant.llm.client import OllamaClient
from uds_assistant.llm.factory import get_llm
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.runner import run_bug_matrix, run_suite
from uds_assistant.simulator import HELDOUT_BUG_CATALOG_PATH, load_bug_catalog
from uds_assistant.spec.schema import load_spec
from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.model import TestCase, dump_tests, load_tests
from uds_assistant.testgen.templates import TEMPLATE_SET_NOTES, TEMPLATE_SET_VERSION, TEMPLATES

REPO_ROOT = Path(__file__).resolve().parents[2]
LLM_MODES = ("mock", "ollama")
BASELINE_FILENAME = "eval_report_baseline_v1.json"
IN_SAMPLE_LABEL = "in-sample (templates tuned on these)"
HELDOUT_LABEL = (
    "held-out (bugs written by an independent subagent that could not see templates, gold "
    "tests, eval, LLM or agent code; nothing was changed after seeing these results)"
)
HEADLINE_ORDER = (
    "simulator_rules_agreement",
    "gold_clean_pass",
    "udsoncan_virtual_can",
    "heldout_bug_detection",
    "requirement_understanding",
    "coverage",
    "citation_validity",
)


def load_requirements(path: Path) -> list[dict[str, str]]:
    """Read ``id,text,category`` rows from the requirements CSV."""
    with path.open(encoding="utf-8", newline="") as fh:
        return [row for row in csv.DictReader(fh) if row.get("id")]


def _git_info(root: Path) -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True, timeout=10, check=True
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip()

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return {
        "commit": commit,
        "dirty": bool(status) if status is not None else None,
        "note": "commit = HEAD when the evaluation ran; dirty=true means uncommitted changes "
        "were present (e.g. the phase being evaluated before its commit).",
    }


def run_export_check(pytest_file: Path, cwd: Path, timeout_s: int = 600) -> dict[str, Any]:
    """Run an exported pytest file in a subprocess and summarize the outcome."""
    env = dict(os.environ)
    env.setdefault("UDS_EXPORT_TRANSPORT", "inprocess")
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(pytest_file), "-q", "-p", "no:cacheprovider"],
        cwd=cwd, capture_output=True, text=True, timeout=timeout_s, env=env, check=False,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return {
        "file": pytest_file.name,
        "transport": env["UDS_EXPORT_TRANSPORT"],
        "returncode": proc.returncode,
        "passed": proc.returncode == 0,
        "summary": lines[-1] if lines else proc.stderr.strip()[-300:],
        "seconds": round(time.perf_counter() - start, 2),
    }


def _pipeline_stats(results: list[PipelineResult]) -> dict[str, Any]:
    rows = [
        {
            "requirement_id": r.requirement_id,
            "tests": len(r.tests),
            "dropped": len(r.dropped),
            "rejected": len(r.rejected),
            "plan_attempts": r.plan_attempts,
            "retries": max(0, r.plan_attempts - 1),
            "status": r.status,
            "engine": r.engine,
            "run_id": r.run_id,
        }
        for r in results
    ]
    return {
        "per_requirement": rows,
        "requirements": len(results),
        "tests_kept": sum(x["tests"] for x in rows),
        "dropped": sum(x["dropped"] for x in rows),
        "rejected": sum(x["rejected"] for x in rows),
        "retries": sum(x["retries"] for x in rows),
        "failed_runs": sum(1 for x in rows if x["status"] != "completed"),
        "dropped_reasons": [
            {"requirement_id": r.requirement_id, **d.model_dump()} for r in results for d in r.dropped
        ][:20],
    }


def _unique_count(tests: list[TestCase]) -> int:
    return len({(t.template_id, json.dumps(t.parameters, sort_keys=True)) for t in tests})


def _baseline_comparison(out_dir: Path, current: dict[str, Any]) -> dict[str, Any] | None:
    path = out_dir / BASELINE_FILENAME
    if not path.exists():
        return None
    try:
        base = json.loads(path.read_text(encoding="utf-8"))
        base_mode = base["modes"][base["actual_mode"]]
    except (ValueError, KeyError):
        return None

    def pick(rep: dict[str, Any]) -> dict[str, Any]:
        return {
            "template_set_version": rep.get("template_set_version"),
            "templates": rep.get("templates_registered"),
            "generated_tests": rep["generated_tests"]["count"],
            "generated_detection_rate": rep["bug_detection"]["generated"]["rate"],
            "generated_detected": rep["bug_detection"]["generated"]["detected"],
            "gold_detection_rate": rep["bug_detection"]["gold"]["rate"],
            "union_detection_rate": rep["bug_detection"]["union"]["rate"],
            "request_validity": rep["request_validity"]["rate"],
            "citation_validity": rep["citation_validity"]["rate"],
            "template_reuse_rate": rep["template_reuse"]["rate"],
            "generated_undetected": rep["bug_detection"]["generated"]["undetected"],
        }

    return {
        "baseline_file": BASELINE_FILENAME,
        "baseline_timestamp": base.get("timestamp"),
        "baseline": pick({**base_mode, "template_set_version": base.get("template_set_version"),
                          "templates_registered": base.get("templates_registered")}),
        "current": pick(current),
    }


def build_headline(report: dict[str, Any]) -> dict[str, Any]:
    """Headline metrics (rows in :data:`HEADLINE_ORDER`) from the finished report.

    Rows 1-3 and the gold half of row 4 do not depend on the LLM; the rest are for
    ``report["actual_mode"]``. The other LLM mode is marked pending / not run.
    """
    mode = report["actual_mode"]
    blk = report["modes"][mode]
    agr = report["simulator_rules_agreement"]
    held = blk["heldout_bug_detection"]
    cov = blk["coverage"]
    cv = blk["citation_validity"]
    ru = blk["requirement_understanding"]
    if "splits" in ru:
        tsplit = ru["splits"]["test"]
        ru_value: dict[str, Any] = {
            "split": "test",
            "requirements": tsplit["requirements"],
            "target_exact_parsed": tsplit["targets_parsed"]["exact"],
            "target_exact_parsed_rate": tsplit["targets_parsed"]["exact_rate"],
            "target_f1_parsed": tsplit["targets_parsed"]["f1"],
            "target_exact_exercised": tsplit["targets_exercised"]["exact"],
            "target_exact_exercised_rate": tsplit["targets_exercised"]["exact_rate"],
            "target_f1_exercised": tsplit["targets_exercised"]["f1"],
            "category_recall_micro": tsplit["categories"]["micro_recall"],
            "category_recall_macro": tsplit["categories"]["macro_recall"],
            "precondition_recall_micro": tsplit["preconditions"]["micro_recall"],
            "precondition_recall_macro": tsplit["preconditions"]["macro_recall"],
            "fallback": tsplit["fallback"]["count"],
            "fallback_unexpected": tsplit["fallback"]["unexpected_count"],
        }
    else:
        ru_value = {"status": "not run"}
    other = "ollama" if mode == "mock" else "mock"
    pending = "pending Part B" if other == "ollama" else "not run in this invocation"
    gold_total = report["gold_tests"]
    rows: dict[str, Any] = {
        "simulator_rules_agreement": {
            "llm_dependent": False, "agreed": agr["agreed"], "total": agr["requests"],
            "rate": agr["rate"], "seed": agr["seed"],
        },
        "gold_clean_pass": {
            "llm_dependent": False, "passed": report["gold_clean_passed"], "total": gold_total,
            "rate": report["gold_clean_pass_rate"],
        },
        "udsoncan_virtual_can": {
            "llm_dependent": False, "status": report["udsoncan_virtual_can"]["status"],
            "error": report["udsoncan_virtual_can"].get("error"),
        },
        "heldout_bug_detection": {
            "llm_dependent": True, "bugs": held["generated"]["bugs"],
            "generated": {"detected": held["generated"]["detected"],
                          "rate": held["generated"]["rate"]},
            "gold": {"detected": held["gold"]["detected"], "rate": held["gold"]["rate"]},
            "union": {"detected": held["union"]["detected"], "rate": held["union"]["rate"]},
        },
        "requirement_understanding": {"llm_dependent": True, mode: ru_value, other: pending},
        "coverage": {
            "llm_dependent": True, "category_totals": cov["category_totals"],
            "requirements_with_tests": cov["requirements_with_tests"],
            "requirements": cov["requirements"], "rate": cov["rate"],
        },
        "citation_validity": {
            "llm_dependent": True, "valid": cv["valid"], "citations": cv["citations"],
            "rate": cv["rate"],
        },
    }
    return {"mode": mode, "other_mode": other, "other_mode_status": pending,
            "order": list(HEADLINE_ORDER), **{k: rows[k] for k in HEADLINE_ORDER}}


def run_evaluation(
    mode: str = "mock",
    out_dir: str | Path = "outputs",
    engine: str = "auto",
    *,
    repo_root: str | Path | None = None,
    requirement_ids: list[str] | None = None,
    write_exports: bool = True,
    run_exported: bool = True,
    run_can: bool = True,
    natural: bool = True,
    run_retrieval_compare: bool = True,
    agreement_requests: int = DEFAULT_REQUESTS,
) -> dict[str, Any]:
    """Run the full evaluation and write ``eval_report.{json,md}`` into ``out_dir``.

    Returns the report as a dict (the same content as the JSON file).
    ``requirement_ids`` restricts the run to a subset of seed requirements (the
    natural-requirement section always uses all of ``requirements_natural.csv``
    unless ``natural`` is False). ``run_can=False`` skips the udsoncan
    virtual-CAN check (reported as "skipped"); ``run_retrieval_compare=False``
    records the BM25-vs-Chroma retrieval comparison as "not run".
    """
    if mode not in LLM_MODES:
        raise ValueError(f"mode must be one of {LLM_MODES}, got {mode!r}")
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    out = Path(out_dir)
    if not out.is_absolute():
        out = Path.cwd() / out
    out.mkdir(parents=True, exist_ok=True)

    # --- set-up -----------------------------------------------------------------------
    t = time.perf_counter()
    base_cfg = get_config()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        llm = get_llm(Config(llm_mode=mode, retriever=base_cfg.retriever))  # type: ignore[arg-type]
        corpus = build_corpus(root)
        retriever = get_retriever(base_cfg, chunks=corpus)
    setup_warnings = [str(w.message) for w in caught]
    for msg in setup_warnings:
        print(f"WARNING: {msg}", file=sys.stderr)
    actual_mode = "ollama" if isinstance(llm, OllamaClient) else "mock"
    spec = load_spec(root / "data" / "bcm_spec.yaml")
    requirements = load_requirements(root / "data" / "requirements_seed.csv")
    if requirement_ids is not None:
        wanted = set(requirement_ids)
        requirements = [r for r in requirements if r["id"] in wanted]
    gold = load_tests(root / "data" / "gold" / "gold_tests.yaml")
    catalog = load_bug_catalog()
    heldout_catalog = load_bug_catalog(HELDOUT_BUG_CATALOG_PATH)
    natural_reqs = (
        u.load_natural_requirements(root / "data" / "requirements_natural.csv") if natural else []
    )
    chosen_engine = resolve_engine(engine)
    timings["setup"] = time.perf_counter() - t

    # --- generation -------------------------------------------------------------------
    t = time.perf_counter()
    store = AuditStore(out / "audit.sqlite")
    results: list[PipelineResult] = []
    for req in requirements:
        results.append(
            run_pipeline(req["text"], req["id"], spec, llm, retriever, store, engine=chosen_engine)
        )
    generated = [test for r in results for test in r.tests]
    timings["generation"] = time.perf_counter() - t

    # --- requirement understanding (natural requirements) -----------------------------
    t = time.perf_counter()
    nat_rows: list[dict[str, Any]] = []
    for nreq in natural_reqs:
        res = run_pipeline(nreq.text, nreq.id, spec, llm, retriever, store, engine=chosen_engine)
        nat_rows.append(u.score_requirement(spec, nreq, res.parsed, res.tests, res.status))
    timings["requirement_understanding"] = time.perf_counter() - t

    # --- execution + bug matrices -----------------------------------------------------
    t = time.perf_counter()
    eval_run = store.start_run("EVAL", f"evaluation run mode={actual_mode}", llm.name,
                               type(retriever).__name__)
    clean = run_suite(generated, spec)
    gen_matrix = run_bug_matrix(generated, spec, catalog.ids, store, eval_run)
    gold_matrix = run_bug_matrix(gold, spec, catalog.ids)
    gold_clean = run_suite(gold, spec)
    store.finish_run(eval_run, "completed")
    timings["execution_and_bug_matrix"] = time.perf_counter() - t

    t = time.perf_counter()
    gen_heldout = run_bug_matrix(generated, spec, heldout_catalog.ids, catalog=heldout_catalog)
    gold_heldout = run_bug_matrix(gold, spec, heldout_catalog.ids, catalog=heldout_catalog)
    timings["heldout_bug_matrix"] = time.perf_counter() - t

    # --- LLM-independent checks ---------------------------------------------------------
    t = time.perf_counter()
    agreement = simulator_rules_agreement(spec, agreement_requests)
    timings["simulator_rules_agreement"] = time.perf_counter() - t
    if run_can:
        t = time.perf_counter()
        can_result = run_udsoncan_sequence(spec)
        timings["udsoncan_virtual_can"] = time.perf_counter() - t
    else:
        can_result = {"status": "skipped", "error": None, "steps": [],
                      "reason": "--skip-can given"}

    # --- metrics ----------------------------------------------------------------------
    t = time.perf_counter()
    heldout_block: dict[str, Any] = {
        "scope": HELDOUT_LABEL,
        "catalog": "data/bugs/heldout_catalog.yaml",
        "generated": m.bug_detection(gen_heldout),
        "gold": m.bug_detection(gold_heldout),
        "union": m.union_detection(gen_heldout, gold_heldout),
    }
    heldout_block["analysis"] = heldout_analysis(
        spec, {"generated": generated, "gold": gold},
        {"generated": heldout_block["generated"], "gold": heldout_block["gold"]},
    )
    req_ids = [r["id"] for r in requirements]
    metrics_block: dict[str, Any] = {
        "generated_tests": {
            "count": len(generated),
            "unique_template_instantiations": _unique_count(generated),
            "clean_simulator_passed": clean.passed_count,
            "clean_simulator_pass_rate": round(clean.pass_rate, 4) if generated else None,
            "p2_timing_warnings": clean.timing_warning_count,
        },
        "request_validity": m.request_validity(spec, generated),
        "expected_response_accuracy": m.expected_response_accuracy(
            spec, generated, gold, round(clean.pass_rate, 4) if generated else None
        ),
        "coverage": m.coverage(generated, req_ids),
        "template_reuse": m.template_reuse(spec, generated),
        "citation_validity": m.citation_validity(generated, corpus),
        "bug_detection": {
            "scope": IN_SAMPLE_LABEL,
            "generated": m.bug_detection(gen_matrix),
            "gold": m.bug_detection(gold_matrix),
            "union": m.union_detection(gen_matrix, gold_matrix),
        },
        "heldout_bug_detection": heldout_block,
        "requirement_understanding": {
            "source": "data/requirements_natural.csv",
            "per_requirement": nat_rows,
            "splits": u.aggregate_by_split(nat_rows),
        } if natural else {"status": "not run"},
        "pipeline": _pipeline_stats(results),
    }
    timings["metrics"] = time.perf_counter() - t

    # --- exports ----------------------------------------------------------------------
    export_info: dict[str, Any] = {"written": [], "run": None}
    if write_exports:
        t = time.perf_counter()
        exp_dir = out / "exports"
        files = [
            to_pytest(generated, exp_dir / "generated_tests_test.py"),
            to_pytest(gold, exp_dir / "gold_tests_test.py"),
            to_capl(generated, exp_dir / "generated_tests.can"),
            to_capl(gold, exp_dir / "gold_tests.can"),
        ]
        dump_tests(generated, out / "generated_tests.yaml")
        export_info["written"] = [str(f.relative_to(out)).replace("\\", "/") for f in files]
        if run_exported:
            export_info["run"] = run_export_check(files[0], cwd=root)
        timings["exports"] = time.perf_counter() - t
    t = time.perf_counter()
    if run_retrieval_compare:
        retrieval_comparison = run_retrieval_comparison(root)
    else:
        retrieval_comparison = {"status": "not run",
                                "reason": "--skip-retrieval-compare given"}
    timings["retrieval_compare"] = time.perf_counter() - t
    timings["total"] = time.perf_counter() - t_start

    mode_block = {"status": "completed", "llm": llm.name, **metrics_block}
    modes: dict[str, Any] = {
        name: {"status": "not run",
               "reason": "deferred: requires a local Ollama model (see MODEL_SETUP.md)"
               if name == "ollama" else "not requested in this invocation"}
        for name in LLM_MODES
    }
    modes[actual_mode] = mode_block
    report: dict[str, Any] = {
        "report_version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "git": _git_info(root),
        "requested_mode": mode,
        "actual_mode": actual_mode,
        "mode_fallback": mode != actual_mode,
        "setup_warnings": setup_warnings,
        "engine": chosen_engine,
        "retriever": type(retriever).__name__,
        "template_set_version": TEMPLATE_SET_VERSION,
        "template_set_note": TEMPLATE_SET_NOTES.get(TEMPLATE_SET_VERSION, ""),
        "templates_registered": len(TEMPLATES),
        "spec": {"name": spec.ecu_name, "synthetic": True},
        "requirements": len(requirements),
        "gold_tests": len(gold),
        "gold_clean_pass_rate": round(gold_clean.pass_rate, 4),
        "gold_clean_passed": gold_clean.passed_count,
        "bug_catalog_size": len(catalog.ids),
        "heldout_catalog_size": len(heldout_catalog.ids),
        "natural_requirements": len(natural_reqs),
        "retrieval_comparison": retrieval_comparison,
        "simulator_rules_agreement": agreement,
        "udsoncan_virtual_can": can_result,
        "metric_definitions": {**m.METRIC_DEFINITIONS, **u.UNDERSTANDING_DEFINITIONS},
        "precondition_mapping": u.PRECONDITION_MAPPING,
        "modes": modes,
        "exports": export_info,
        "runtime_seconds": {k: round(v, 3) for k, v in timings.items()},
        "audit_db": "audit.sqlite",
    }
    report["headline"] = build_headline(report)
    report["baseline_comparison"] = _baseline_comparison(
        out,
        {**mode_block, "template_set_version": TEMPLATE_SET_VERSION,
         "templates_registered": len(TEMPLATES)},
    )
    (out / "eval_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "eval_report.md").write_text(render_markdown(report), encoding="utf-8")
    store.close()
    return report


def build_parser() -> argparse.ArgumentParser:
    """CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m uds_assistant.eval.run_eval",
        description="Generate tests for the seed requirements and write the evaluation report.",
    )
    parser.add_argument("--mode", choices=LLM_MODES, default="mock", help="LLM mode (default mock)")
    parser.add_argument("--out", default="outputs", help="output directory (default outputs)")
    parser.add_argument("--engine", choices=("auto", "plain", "langgraph"), default="auto")
    parser.add_argument("--no-export-run", action="store_true",
                        help="write exports but do not run the exported pytest file")
    parser.add_argument("--skip-can", action="store_true",
                        help="skip the udsoncan virtual-CAN check (for fast test runs)")
    parser.add_argument("--skip-retrieval-compare", action="store_true",
                        help="skip the BM25-vs-Chroma retrieval comparison (for fast test runs)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    args = build_parser().parse_args(argv)
    report = run_evaluation(
        args.mode, args.out, args.engine, run_exported=not args.no_export_run,
        run_can=not args.skip_can, run_retrieval_compare=not args.skip_retrieval_compare,
    )
    block = report["modes"][report["actual_mode"]]
    det = block["bug_detection"]
    held = block["heldout_bug_detection"]
    print(
        f"mode={report['actual_mode']} (requested {report['requested_mode']}) "
        f"tests={block['generated_tests']['count']} "
        f"HELD-OUT bug detection: generated {held['generated']['detected']}/"
        f"{held['generated']['bugs']}, gold {held['gold']['detected']}/{held['gold']['bugs']}, "
        f"union {held['union']['detected']}/{held['union']['bugs']}; "
        f"in-sample (templates tuned on these): generated "
        f"{det['generated']['detected']}/{det['generated']['bugs']}, "
        f"gold {det['gold']['detected']}/{det['gold']['bugs']}, "
        f"union {det['union']['detected']}/{det['union']['bugs']}"
    )
    run = report["exports"].get("run")
    if run:
        print(f"exported pytest run: {run['summary']}")
    print(f"report: {Path(args.out) / 'eval_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
