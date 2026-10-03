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
import math
import os
import statistics
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
from uds_assistant.eval.provenance import check_provenance
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


FREEZE_EXPECTED: dict[str, str] = {
    "uds_assistant/llm/prompts.py": "98a4741604338c3a0ffc2b17dc433e9c90d47620",
    "uds_assistant/llm": "3559f7e7e0e53b5d08212b5cbccd5aa06e6bba71",
    "uds_assistant/agent": "1d678f0f41eb23962defd6c8ea387bea4fcffb59",
    "uds_assistant/testgen": "9a121b2742c5f85fa48fd4f5340caf3b85979c67",
}
"""Git object ids of the frozen prompt / agent / template code (B3 freeze), checked per run."""

NODE_ORDER = ("parse", "retrieve", "plan", "instantiate", "validate", "explain")
TRUNCATION_MARKER = "prompt likely truncated"
PROVENANCE_EXIT_CODE = 2


def freeze_info(root: Path) -> dict[str, Any]:
    """Compare HEAD's object ids for the frozen paths with :data:`FREEZE_EXPECTED`.

    ``worktree_clean`` is False when ``git status --porcelain`` lists any change under the
    path (modified, staged or untracked), i.e. the code that ran may differ from HEAD.
    """
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                                 timeout=10, check=True)
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip()

    paths: dict[str, Any] = {}
    for path, expected in FREEZE_EXPECTED.items():
        head = git("rev-parse", f"HEAD:{path}")
        status = git("status", "--porcelain", "--", path)
        paths[path] = {
            "expected": expected,
            "head": head,
            "matches": head == expected,
            "worktree_clean": status == "" if status is not None else None,
        }
    return {
        "paths": paths,
        "all_ok": all(v["matches"] and v["worktree_clean"] for v in paths.values()),
    }


def percentile_nearest_rank(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (``pct`` in 0..100); ``None`` for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _r(value: float | None, nd: int) -> float | None:
    return None if value is None else round(value, nd)


def _latency_summary(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": _r(statistics.fmean(values), 3) if values else None,
        "p95": _r(percentile_nearest_rank(values, 95), 3),
        "max": _r(max(values), 3) if values else None,
        "total": round(sum(values), 3),
    }


def _split_events(events: list[str]) -> tuple[list[str], list[str]]:
    trunc = [e for e in events if TRUNCATION_MARKER in e]
    other = [e for e in events if TRUNCATION_MARKER not in e]
    return other, trunc


def _pipeline_stats(
    results: list[PipelineResult], wall_s: list[float] | None = None,
    splits: dict[str, str] | None = None,
) -> dict[str, Any]:
    wall = wall_s if wall_s is not None else [0.0] * len(results)
    rows = []
    for r, w in zip(results, wall, strict=True):
        fallbacks, truncs = _split_events(list(r.fallback_events))
        rows.append({
            "requirement_id": r.requirement_id,
            "split": (splits or {}).get(r.requirement_id, "seed"),
            "tests": len(r.tests),
            "dropped": len(r.dropped),
            "rejected": len(r.rejected),
            "plan_attempts": r.plan_attempts,
            "retries": max(0, r.plan_attempts - 1),
            "status": r.status,
            "engine": r.engine,
            "run_id": r.run_id,
            "wall_s": round(w, 3),
            "node_timings_ms": dict(r.node_timings),
            "node_calls": dict(r.node_calls),
            "llm_stats": dict(r.llm_stats),
            "fallback_events": fallbacks,
            "truncation_events": truncs,
            "rejected_reasons": [f"{x.node}: {x.template_id}[{x.option_index}]: {x.reason}"
                                 for x in r.rejected],
        })
    return {
        "per_requirement": rows,
        "requirements": len(results),
        "tests_kept": sum(x["tests"] for x in rows),
        "dropped": sum(x["dropped"] for x in rows),
        "rejected": sum(x["rejected"] for x in rows),
        "retries": sum(x["retries"] for x in rows),
        "plan_attempts": sum(x["plan_attempts"] for x in rows),
        "failed_runs": sum(1 for x in rows if x["status"] != "completed"),
        "llm_calls": sum(int(x["llm_stats"].get("calls", 0)) for x in rows),
        "llm_json_failures": sum(int(x["llm_stats"].get("json_failures", 0)) for x in rows),
        "llm_retries": sum(int(x["llm_stats"].get("retries", 0)) for x in rows),
        "llm_errors": sum(int(x["llm_stats"].get("errors", 0)) for x in rows),
        "truncations": sum(len(x["truncation_events"]) for x in rows),
        "fallback_events": sum(len(x["fallback_events"]) for x in rows),
        "dropped_reasons": [
            {"requirement_id": r.requirement_id, **d.model_dump()} for r in results for d in r.dropped
        ][:20],
    }


def _latency_block(seed: dict[str, Any], natural: dict[str, Any] | None) -> dict[str, Any]:
    rows = list(seed["per_requirement"]) + (list(natural["per_requirement"]) if natural else [])
    per_node: dict[str, Any] = {}
    for node in NODE_ORDER:
        vals = [float(r["node_timings_ms"].get(node, 0.0)) for r in rows]
        per_node[node] = {
            "mean_ms": _r(statistics.fmean(vals), 1) if vals else None,
            "p95_ms": _r(percentile_nearest_rank(vals, 95), 1),
        }
    llm_ms = [float(r["llm_stats"].get("latency_ms", 0.0)) for r in rows]
    return {
        "definition": ("wall clock seconds of one run_pipeline call per requirement (parse "
                       "through explain, including all LLM calls and re-plans); p95 is "
                       "nearest-rank; per-node values are per requirement in milliseconds."),
        "per_requirement_wall_s": {
            "seed": _latency_summary([r["wall_s"] for r in seed["per_requirement"]]),
            "natural": _latency_summary([r["wall_s"] for r in natural["per_requirement"]])
            if natural else None,
            "all": _latency_summary([r["wall_s"] for r in rows]),
        },
        "per_node_ms": per_node,
        "llm_latency_ms_per_requirement": {
            "mean": _r(statistics.fmean(llm_ms), 1) if llm_ms else None,
            "p95": _r(percentile_nearest_rank(llm_ms, 95), 1),
        },
    }


def _events_block(*stats: dict[str, Any] | None) -> dict[str, Any]:
    fallback: list[dict[str, str]] = []
    trunc: list[dict[str, str]] = []
    for st in stats:
        if not st:
            continue
        for row in st["per_requirement"]:
            fallback += [{"requirement_id": row["requirement_id"], "event": e}
                         for e in row["fallback_events"]]
            trunc += [{"requirement_id": row["requirement_id"], "event": e}
                      for e in row["truncation_events"]]
    return {"fallback": fallback, "truncation": trunc}


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
        "baseline_mode": base.get("actual_mode"),
        "baseline": pick({**base_mode, "template_set_version": base.get("template_set_version"),
                          "templates_registered": base.get("templates_registered")}),
        "current": pick(current),
    }


def _ru_headline(blk: dict[str, Any]) -> dict[str, Any]:
    ru = blk["requirement_understanding"]
    if "splits" not in ru:
        return {"status": "not run"}
    tsplit = ru["splits"]["test"]
    return {
        "split": "test",
        "requirements": tsplit["requirements"],
        "target_exact_parsed": tsplit["targets_parsed"]["exact"],
        "target_exact_parsed_rate": tsplit["targets_parsed"]["exact_rate"],
        "target_precision_parsed": tsplit["targets_parsed"]["precision"],
        "target_recall_parsed": tsplit["targets_parsed"]["recall"],
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


def _not_run_status(report: dict[str, Any], name: str) -> str:
    return f"not run: {report['modes'][name].get('reason', 'not requested')}"


def build_headline(report: dict[str, Any]) -> dict[str, Any]:
    """Headline metrics (rows in :data:`HEADLINE_ORDER`) from the finished report.

    Rows 1-3 and the gold half of row 4 do not depend on the LLM. LLM-dependent rows carry
    a ``by_mode`` entry for every mode (a value dict for a completed mode, a "not run: ..."
    string otherwise); their top-level values are for ``report["actual_mode"]``.
    """
    mode = report["actual_mode"]
    blk = report["modes"][mode]
    agr = report["simulator_rules_agreement"]
    completed = [n for n in LLM_MODES if report["modes"][n].get("status") == "completed"]
    other = "ollama" if mode == "mock" else "mock"
    other_status = "completed" if other in completed else _not_run_status(report, other)

    def held_vals(b: dict[str, Any]) -> dict[str, Any]:
        held = b["heldout_bug_detection"]
        return {k: {"detected": held[k]["detected"], "rate": held[k]["rate"]}
                for k in ("generated", "gold", "union")}

    def cov_vals(b: dict[str, Any]) -> dict[str, Any]:
        cov = b["coverage"]
        return {"category_totals": cov["category_totals"],
                "requirements_with_tests": cov["requirements_with_tests"],
                "requirements": cov["requirements"], "rate": cov["rate"]}

    def cit_vals(b: dict[str, Any]) -> dict[str, Any]:
        cv = b["citation_validity"]
        return {"valid": cv["valid"], "citations": cv["citations"], "rate": cv["rate"]}

    def by_mode(fn: Any) -> dict[str, Any]:
        return {n: fn(report["modes"][n]) if n in completed else _not_run_status(report, n)
                for n in LLM_MODES}

    held = blk["heldout_bug_detection"]
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
            "llm_dependent": True, "bugs": held["generated"]["bugs"], **held_vals(blk),
            "by_mode": by_mode(held_vals),
        },
        "requirement_understanding": {
            "llm_dependent": True,
            **{n: _ru_headline(report["modes"][n]) if n in completed
               else _not_run_status(report, n) for n in LLM_MODES},
        },
        "coverage": {"llm_dependent": True, **cov_vals(blk), "by_mode": by_mode(cov_vals)},
        "citation_validity": {"llm_dependent": True, **cit_vals(blk),
                              "by_mode": by_mode(cit_vals)},
    }
    return {"mode": mode, "other_mode": other, "other_mode_status": other_status,
            "modes_completed": completed,
            "order": list(HEADLINE_ORDER), **{k: rows[k] for k in HEADLINE_ORDER}}


def _run_mode(
    llm: Any,
    *,
    spec: Any,
    requirements: list[dict[str, str]],
    natural_reqs: list[Any],
    retriever: Any,
    store: AuditStore,
    engine: str,
    corpus: Any,
    catalog: Any,
    heldout_catalog: Any,
    gold: list[TestCase],
    gold_matrix: Any,
    gold_heldout: Any,
    natural: bool,
    timings: dict[str, float],
    label: str,
) -> tuple[dict[str, Any], list[TestCase]]:
    """Generate tests with one LLM backend and compute every LLM-dependent metric."""
    # --- generation (seed requirements) ------------------------------------------------
    t = time.perf_counter()
    results: list[PipelineResult] = []
    seed_wall: list[float] = []
    for req in requirements:
        t0 = time.perf_counter()
        results.append(run_pipeline(req["text"], req["id"], spec, llm, retriever, store,
                                    engine=engine))
        seed_wall.append(time.perf_counter() - t0)
        print(f"[{label}] {req['id']}: {len(results[-1].tests)} tests in {seed_wall[-1]:.1f} s",
              file=sys.stderr, flush=True)
    generated = [test for r in results for test in r.tests]
    timings[f"{label}.generation"] = time.perf_counter() - t

    # --- requirement understanding (natural requirements) ------------------------------
    t = time.perf_counter()
    nat_rows: list[dict[str, Any]] = []
    nat_results: list[PipelineResult] = []
    nat_wall: list[float] = []
    for nreq in natural_reqs:
        t0 = time.perf_counter()
        res = run_pipeline(nreq.text, nreq.id, spec, llm, retriever, store, engine=engine)
        nat_wall.append(time.perf_counter() - t0)
        nat_results.append(res)
        nat_rows.append(u.score_requirement(spec, nreq, res.parsed, res.tests, res.status))
        print(f"[{label}] {nreq.id} ({nreq.split}): {len(res.tests)} tests in "
              f"{nat_wall[-1]:.1f} s", file=sys.stderr, flush=True)
    timings[f"{label}.requirement_understanding"] = time.perf_counter() - t

    # --- execution + bug matrices ------------------------------------------------------
    t = time.perf_counter()
    eval_run = store.start_run("EVAL", f"evaluation run mode={label}", llm.name,
                               type(retriever).__name__)
    clean = run_suite(generated, spec)
    gen_matrix = run_bug_matrix(generated, spec, catalog.ids, store, eval_run)
    store.finish_run(eval_run, "completed")
    gen_heldout = run_bug_matrix(generated, spec, heldout_catalog.ids, catalog=heldout_catalog)
    timings[f"{label}.execution_and_bug_matrices"] = time.perf_counter() - t

    # --- byte provenance ---------------------------------------------------------------
    t = time.perf_counter()
    nat_tests = [test for r in nat_results for test in r.tests]
    prov_seed = check_provenance(spec, generated)
    prov_nat = check_provenance(spec, nat_tests)
    provenance = {
        "seed": prov_seed,
        "natural": prov_nat,
        "checked": prov_seed["checked"] + prov_nat["checked"],
        "passed": prov_seed["passed"] + prov_nat["passed"],
        "failed": prov_seed["failed"] + prov_nat["failed"],
        "ok": prov_seed["ok"] and prov_nat["ok"],
    }
    timings[f"{label}.provenance"] = time.perf_counter() - t

    # --- metrics -----------------------------------------------------------------------
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
    seed_stats = _pipeline_stats(results, seed_wall)
    nat_stats = (_pipeline_stats(nat_results, nat_wall, {n.id: n.split for n in natural_reqs})
                 if natural else None)
    block: dict[str, Any] = {
        "status": "completed",
        "llm": llm.name,
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
        "pipeline": seed_stats,
        "pipeline_natural": nat_stats if nat_stats is not None else {"status": "not run"},
        "latency": _latency_block(seed_stats, nat_stats),
        "events": _events_block(seed_stats, nat_stats),
        "provenance": provenance,
    }
    timings[f"{label}.metrics"] = time.perf_counter() - t
    return block, generated


def _write_exports(
    generated: list[TestCase], gold: list[TestCase], out: Path, sub: str, yaml_name: str,
    root: Path, run_exported: bool,
) -> dict[str, Any]:
    exp_dir = out / "exports" / sub if sub else out / "exports"
    files = [
        to_pytest(generated, exp_dir / "generated_tests_test.py"),
        to_pytest(gold, exp_dir / "gold_tests_test.py"),
        to_capl(generated, exp_dir / "generated_tests.can"),
        to_capl(gold, exp_dir / "gold_tests.can"),
    ]
    dump_tests(generated, out / yaml_name)
    info: dict[str, Any] = {
        "written": [str(f.relative_to(out)).replace("\\", "/") for f in files] + [yaml_name],
        "run": None,
    }
    if run_exported:
        info["run"] = run_export_check(files[0], cwd=root)
    return info


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
    compare_mock: bool = True,
) -> dict[str, Any]:
    """Run the full evaluation and write ``eval_report.{json,md}`` into ``out_dir``.

    Returns the report as a dict (the same content as the JSON file).
    With ``mode="ollama"`` (and Ollama reachable) the mock backend is evaluated too in the
    same invocation (``compare_mock=False`` skips it), so the report has side-by-side
    columns. If Ollama is unreachable, ``get_llm`` falls back to mock; the report then
    records ``actual_mode="mock"``, ``mode_fallback=True`` and the ollama column as not run.
    ``requirement_ids`` restricts the run to a subset of seed requirements (the
    natural-requirement section always uses all of ``requirements_natural.csv``
    unless ``natural`` is False). ``run_can=False`` skips the udsoncan
    virtual-CAN check (reported as "skipped"); ``run_retrieval_compare=False``
    records the BM25-vs-Chroma retrieval comparison as "not run". Every generated test
    of every mode is checked for byte provenance (:mod:`.provenance`);
    ``report["provenance_ok"]`` is False if any test fails.
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
    freeze = freeze_info(root)
    timings["setup"] = time.perf_counter() - t

    # --- LLM-independent: gold suites ---------------------------------------------------
    t = time.perf_counter()
    gold_matrix = run_bug_matrix(gold, spec, catalog.ids)
    gold_clean = run_suite(gold, spec)
    gold_heldout = run_bug_matrix(gold, spec, heldout_catalog.ids, catalog=heldout_catalog)
    timings["gold_suites"] = time.perf_counter() - t

    # --- per-mode generation + metrics ------------------------------------------------
    store = AuditStore(out / "audit.sqlite")
    llms: list[tuple[str, Any]] = []
    if actual_mode == "ollama" and compare_mock:
        llms.append(("mock", get_llm(Config(llm_mode="mock", retriever=base_cfg.retriever))))
    llms.append((actual_mode, llm))
    common: dict[str, Any] = {
        "spec": spec, "requirements": requirements, "natural_reqs": natural_reqs,
        "retriever": retriever, "store": store, "engine": chosen_engine, "corpus": corpus,
        "catalog": catalog, "heldout_catalog": heldout_catalog, "gold": gold,
        "gold_matrix": gold_matrix, "gold_heldout": gold_heldout, "natural": natural,
        "timings": timings,
    }
    modes: dict[str, Any] = {}
    generated_by_mode: dict[str, list[TestCase]] = {}
    for name, backend in llms:
        t = time.perf_counter()
        modes[name], generated_by_mode[name] = _run_mode(backend, label=name, **common)
        timings[f"{name}.total"] = time.perf_counter() - t
    for name in LLM_MODES:
        if name in modes:
            continue
        if name == "ollama":
            reason = ("Ollama requested but unreachable; fell back to mock" if mode == "ollama"
                      else "not requested in this invocation (run with --mode ollama)")
        else:
            reason = "skipped (--no-mock-compare)"
        modes[name] = {"status": "not run", "reason": reason}

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

    # --- exports ----------------------------------------------------------------------
    export_info: dict[str, Any] = {"written": [], "run": None, "by_mode": {}}
    if write_exports:
        t = time.perf_counter()
        for name, gen in generated_by_mode.items():
            sub, yaml_name = ("", "generated_tests.yaml") if name == "mock" else (
                name, f"generated_tests_{name}.yaml")
            export_info["by_mode"][name] = _write_exports(gen, gold, out, sub, yaml_name, root,
                                                          run_exported)
        primary = export_info["by_mode"][actual_mode]
        export_info["written"], export_info["run"] = primary["written"], primary["run"]
        timings["exports"] = time.perf_counter() - t
    t = time.perf_counter()
    if run_retrieval_compare:
        retrieval_comparison = run_retrieval_comparison(root)
    else:
        retrieval_comparison = {"status": "not run",
                                "reason": "--skip-retrieval-compare given"}
    timings["retrieval_compare"] = time.perf_counter() - t
    timings["total"] = time.perf_counter() - t_start

    report: dict[str, Any] = {
        "report_version": 2,
        "timestamp": datetime.now(UTC).isoformat(),
        "git": _git_info(root),
        "freeze": freeze,
        "requested_mode": mode,
        "actual_mode": actual_mode,
        "mode_fallback": mode != actual_mode,
        "modes_run": list(generated_by_mode),
        "setup_warnings": setup_warnings,
        "engine": chosen_engine,
        "retriever": type(retriever).__name__,
        "llm_settings": {
            "model": getattr(llm, "model", None),
            "num_ctx": getattr(llm, "num_ctx", None),
            "temperature": getattr(llm, "temperature", None),
            "keep_alive": getattr(llm, "keep_alive", None),
        } if actual_mode == "ollama" else None,
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
        "provenance_ok": all(modes[n]["provenance"]["ok"] for n in generated_by_mode),
        "exports": export_info,
        "runtime_seconds": {k: round(v, 3) for k, v in timings.items()},
        "audit_db": "audit.sqlite",
        "interpretation": None,
    }
    report["headline"] = build_headline(report)
    report["baseline_comparison"] = _baseline_comparison(
        out,
        {**modes["mock"], "template_set_version": TEMPLATE_SET_VERSION,
         "templates_registered": len(TEMPLATES)},
    ) if modes["mock"].get("status") == "completed" else None
    write_report(report, out)
    store.close()
    return report


def write_report(report: dict[str, Any], out: Path) -> None:
    """Write ``eval_report.json`` and ``eval_report.md`` for ``report`` into ``out``."""
    (out / "eval_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "eval_report.md").write_text(render_markdown(report), encoding="utf-8")


def rerender(out: Path, interpretation_file: Path | None = None) -> dict[str, Any]:
    """Re-render the Markdown from an existing ``eval_report.json`` (no metric is recomputed).

    With ``interpretation_file``, its text is stored as ``report["interpretation"]`` (prose
    written after reading the measured numbers) before both files are rewritten.
    """
    report = json.loads((out / "eval_report.json").read_text(encoding="utf-8"))
    if interpretation_file is not None:
        report["interpretation"] = {
            "source": str(interpretation_file).replace("\\", "/"),
            "text": interpretation_file.read_text(encoding="utf-8").strip(),
        }
    write_report(report, out)
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
    parser.add_argument("--no-mock-compare", action="store_true",
                        help="with --mode ollama, do not also evaluate the mock backend")
    parser.add_argument("--rerender", action="store_true",
                        help="only re-render eval_report.md from the existing eval_report.json")
    parser.add_argument("--interpretation", default=None,
                        help="with --rerender: a text file stored as the interpretation section")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code.

    Returns :data:`PROVENANCE_EXIT_CODE` (after the report is written) when any generated
    test of any mode fails the byte-provenance check.
    """
    args = build_parser().parse_args(argv)
    if args.rerender:
        rerender(Path(args.out), Path(args.interpretation) if args.interpretation else None)
        print(f"re-rendered {Path(args.out) / 'eval_report.md'}")
        return 0
    report = run_evaluation(
        args.mode, args.out, args.engine, run_exported=not args.no_export_run,
        run_can=not args.skip_can, run_retrieval_compare=not args.skip_retrieval_compare,
        compare_mock=not args.no_mock_compare,
    )
    for name in report["modes_run"]:
        block = report["modes"][name]
        det = block["bug_detection"]
        held = block["heldout_bug_detection"]
        prov = block["provenance"]
        print(
            f"mode={name} tests={block['generated_tests']['count']} "
            f"HELD-OUT bug detection: generated {held['generated']['detected']}/"
            f"{held['generated']['bugs']}, gold {held['gold']['detected']}/{held['gold']['bugs']}, "
            f"union {held['union']['detected']}/{held['union']['bugs']}; "
            f"in-sample (templates tuned on these): generated "
            f"{det['generated']['detected']}/{det['generated']['bugs']}, "
            f"gold {det['gold']['detected']}/{det['gold']['bugs']}, "
            f"union {det['union']['detected']}/{det['union']['bugs']}; "
            f"byte provenance {prov['passed']}/{prov['checked']}"
        )
    print(f"actual mode={report['actual_mode']} (requested {report['requested_mode']})")
    run = report["exports"].get("run")
    if run:
        print(f"exported pytest run: {run['summary']}")
    print(f"report: {Path(args.out) / 'eval_report.md'}")
    if not report["provenance_ok"]:
        for name in report["modes_run"]:
            prov = report["modes"][name]["provenance"]
            for f in prov["seed"]["failures"] + prov["natural"]["failures"]:
                print(f"BYTE PROVENANCE FAILURE [{name}] {f['test_id']}: {f['problems']}",
                      file=sys.stderr)
        return PROVENANCE_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
