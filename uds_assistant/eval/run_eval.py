"""End-to-end evaluation: generate tests for the seed requirements and score them.

CLI::

    python -m uds_assistant.eval.run_eval --mode mock [--out outputs] [--engine auto|plain|langgraph]
    python -m uds_assistant.eval.run_eval --mode ollama --noise-runs 3 --before-after

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
import re
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
from uds_assistant.eval.heldout_v2 import heldout_v2_analysis
from uds_assistant.eval.provenance import check_provenance
from uds_assistant.eval.report_md import provenance_failures, render_markdown
from uds_assistant.eval.retrieval_compare import run_retrieval_comparison
from uds_assistant.export import to_capl, to_pytest
from uds_assistant.llm.client import OllamaClient
from uds_assistant.llm.factory import get_llm
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.runner import run_bug_matrix, run_suite
from uds_assistant.simulator import (
    HELDOUT_BUG_CATALOG_PATH,
    HELDOUT_V2_BUG_CATALOG_PATH,
    load_bug_catalog,
)
from uds_assistant.spec.schema import load_spec
from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.model import TestCase, dump_tests, load_tests
from uds_assistant.testgen.templates import TEMPLATE_SET_NOTES, TEMPLATE_SET_VERSION, TEMPLATES

REPO_ROOT = Path(__file__).resolve().parents[2]
LLM_MODES = ("mock", "ollama")
BASELINE_FILENAME = "eval_report_baseline_v1.json"
IN_SAMPLE_LABEL = "in-sample (templates tuned on these)"
HELDOUT_V1_SEEN_LABEL = "seen (templates designed against these misses)"
HELDOUT_LABEL = (
    "held-out v1, now SEEN: bugs written by an independent subagent that could not see "
    "templates, gold tests, eval, LLM or agent code; the template-set-v3 coverage templates "
    "were then designed against the misses, so these 12 are no longer independent"
)
HELDOUT_V2_LABEL = (
    "held-out v2 (FRESH): 15 bugs written blind by a subagent after the Part C freeze, "
    "which could not see templates, gold tests, eval, LLM or agent code; nothing was changed "
    "after seeing these results"
)
NATURAL_V2_LABEL = (
    "natural v2 (FRESH, split test2): 16 requirements written blind after the Part C freeze "
    "by a subagent that could not see the v1 natural set"
)
NATURAL_V1_TEST_LABEL = "natural v1 test split (SEEN: templates were designed after its results)"
NATURAL_V1_DEV_LABEL = "natural v1 dev split (tuned on: the prompts were tuned on these rows)"
HEADLINE_ORDER = (
    "heldout_v2_bug_detection",
    "requirement_understanding_v2",
    "simulator_rules_agreement",
    "gold_clean_pass",
    "udsoncan_virtual_can",
    "coverage",
    "citation_validity",
    "heldout_bug_detection",
    "requirement_understanding",
    "requirement_understanding_dev",
    "in_sample_bug_detection",
)
REPORT_VERSION = 3
V2_DEFINITIONS: dict[str, str] = {
    "heldout_v2_bug_detection_rate": (
        "Same procedure as bug_detection_rate on the 15 held-out v2 bugs in "
        "data/bugs/heldout_v2_catalog.yaml (heldout_v2: true), written blind after the Part C "
        "freeze. HEADLINE = generated-suite detection, where the generated suite is the tests "
        "generated from the 15 seed requirements (the same definition as the held-out v1 "
        "headline). Supplementary: detection by the union of all generated tests (seed + natural "
        "v1 + natural v2) and by the natural-v2 tests alone. Missed-bug reasons come from "
        "eval/heldout_v2.py (static trigger predicates written before any v2 result)."
    ),
    "natural_v2_understanding": (
        "Requirement understanding on data/requirements_natural_v2.csv (16 rows, split test2, "
        "written blind after the freeze) with the same label schema and scoring as the v1 "
        "natural set; test2 is the headline split."
    ),
    "noise_check": (
        "ollama runs the pipeline over natural v2 --noise-runs times in total; run 1 feeds the "
        "tables, every run is listed, and the summary is the mean and min-max range over all "
        "runs. mock is deterministic: one run, plus an equality re-run as a check."
    ),
}
"""Extra metric definitions added in report version 3."""
PROGRESS_FILE = "PROGRESS.md"
FREEZE_SECTION = "Part C freeze"


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


NODE_ORDER = ("parse", "retrieve", "plan", "instantiate", "validate", "explain")
TRUNCATION_MARKER = "prompt likely truncated"
PROVENANCE_EXIT_CODE = 2


def parse_freeze_table(progress_text: str, section: str = FREEZE_SECTION) -> dict[str, Any]:
    """Parse the recorded freeze hashes from PROGRESS.md's "Part C freeze" table.

    Returns ``{"commit": <hash or None>, "paths": {path: object id}}``. Rows look like
    ``| `uds_assistant/testgen` tree | `a4b6...` |``; the row labelled ``Commit`` is the
    freeze commit. Only the section headed ``## <section> (...)`` is read.
    """
    commit: str | None = None
    paths: dict[str, str] = {}
    in_section = False
    for line in progress_text.splitlines():
        if line.startswith("## "):
            in_section = line[3:].strip().startswith(section)
            continue
        if not in_section:
            continue
        m = re.match(r"\|\s*(.+?)\s*\|\s*`([0-9a-f]{40})`\s*\|", line)
        if not m:
            continue
        label, digest = m.groups()
        pm = re.match(r"`([^`]+)`", label)
        if label.lower() == "commit":
            commit = digest
        elif pm:
            paths[pm.group(1)] = digest
    return {"commit": commit, "paths": paths}


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              timeout=10, check=check)
    except (OSError, subprocess.SubprocessError):
        return None


def freeze_info(root: Path) -> dict[str, Any]:
    """Compare HEAD's object ids with the hashes recorded in PROGRESS.md's "Part C freeze".

    ``worktree_clean`` is False when ``git status --porcelain`` lists any change under the
    path (modified, staged or untracked), i.e. the code that ran may differ from HEAD. The
    recorded freeze commit must be an ancestor of HEAD. ``all_ok`` is True only when the
    table was found and parsed, every path matches and is clean, and the commit is an
    ancestor of HEAD.
    """
    def out(*args: str) -> str | None:
        proc = _git(root, *args)
        return None if proc is None else proc.stdout.strip()

    progress = root / PROGRESS_FILE
    recorded: dict[str, Any] = {"commit": None, "paths": {}}
    error: str | None = None
    if progress.exists():
        recorded = parse_freeze_table(progress.read_text(encoding="utf-8"))
        if not recorded["paths"]:
            error = f"no '{FREEZE_SECTION}' hash table found in {PROGRESS_FILE}"
    else:
        error = f"{PROGRESS_FILE} not found"
    paths: dict[str, Any] = {}
    for path, expected in recorded["paths"].items():
        head = out("rev-parse", f"HEAD:{path}")
        status = out("status", "--porcelain", "--", path)
        paths[path] = {
            "expected": expected,
            "head": head,
            "matches": head == expected,
            "worktree_clean": status == "" if status is not None else None,
        }
    commit = recorded["commit"]
    anc = _git(root, "merge-base", "--is-ancestor", commit, "HEAD", check=False) if commit else None
    commit_info = {
        "recorded": commit,
        "head": out("rev-parse", "HEAD"),
        "recorded_is_ancestor_of_head": None if anc is None else anc.returncode == 0,
    }
    all_ok = (
        error is None and bool(paths)
        and all(v["matches"] and v["worktree_clean"] for v in paths.values())
        and commit_info["recorded_is_ancestor_of_head"] is True
    )
    return {"source": f"{PROGRESS_FILE} '{FREEZE_SECTION}' table", "error": error,
            "commit": commit_info, "paths": paths, "all_ok": all_ok}


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
            "node_llm_calls": dict(r.node_llm_calls),
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
        "explain_llm_calls": sum(int(x["node_llm_calls"].get("explain", 0)) for x in rows),
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


def _ru_headline(ru: dict[str, Any], split: str = "test") -> dict[str, Any]:
    if "splits" not in ru or split not in ru["splits"]:
        return {"status": "not run"}
    tsplit = ru["splits"][split]
    return {
        "split": split,
        "requirements": tsplit["requirements"],
        "target_exact_parsed": tsplit["targets_parsed"]["exact"],
        "target_exact_parsed_rate": tsplit["targets_parsed"]["exact_rate"],
        "target_precision_parsed": tsplit["targets_parsed"]["precision"],
        "target_recall_parsed": tsplit["targets_parsed"]["recall"],
        "target_f1_parsed": tsplit["targets_parsed"]["f1"],
        "target_tp_parsed": tsplit["targets_parsed"]["tp"],
        "target_fp_parsed": tsplit["targets_parsed"]["fp"],
        "target_fn_parsed": tsplit["targets_parsed"]["fn"],
        "target_exact_exercised": tsplit["targets_exercised"]["exact"],
        "target_exact_exercised_rate": tsplit["targets_exercised"]["exact_rate"],
        "target_precision_exercised": tsplit["targets_exercised"]["precision"],
        "target_recall_exercised": tsplit["targets_exercised"]["recall"],
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

    The two NEW HEADLINE rows come first (fresh held-out v2 bugs, fresh natural v2
    requirements), then the LLM-independent rows, coverage and citations, then the rows
    whose data has been seen (held-out v1, natural v1 test / dev) and the in-sample bugs.
    LLM-dependent rows carry a ``by_mode`` entry for every mode (a value dict for a
    completed mode, a "not run: ..." string otherwise); their top-level values are for
    ``report["actual_mode"]``.
    """
    mode = report["actual_mode"]
    blk = report["modes"][mode]
    agr = report["simulator_rules_agreement"]
    completed = [n for n in LLM_MODES if report["modes"][n].get("status") == "completed"]
    other = "ollama" if mode == "mock" else "mock"
    other_status = "completed" if other in completed else _not_run_status(report, other)

    def held_vals(key: str) -> Any:
        def fn(b: dict[str, Any]) -> dict[str, Any]:
            held = b[key]
            return {k: {"detected": held[k]["detected"], "rate": held[k]["rate"]}
                    for k in ("generated", "gold", "union")}
        return fn

    def supp_vals(b: dict[str, Any]) -> dict[str, Any]:
        supp = b["heldout_v2_bug_detection"].get("supplementary") or {}
        return {k: ({"detected": v["detected"], "bugs": v["bugs"], "rate": v["rate"],
                     "tests": v["tests"]} if isinstance(v, dict) and "detected" in v else v)
                for k, v in supp.items()}

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

    def ru_row(key: str, split: str) -> dict[str, Any]:
        return {"llm_dependent": True,
                **{n: _ru_headline(report["modes"][n].get(key, {}), split) if n in completed
                   else _not_run_status(report, n) for n in LLM_MODES}}

    gold_total = report["gold_tests"]
    rows: dict[str, Any] = {
        "heldout_v2_bug_detection": {
            "llm_dependent": True, "label": HELDOUT_V2_LABEL,
            "bugs": blk["heldout_v2_bug_detection"]["generated"]["bugs"],
            **held_vals("heldout_v2_bug_detection")(blk),
            "by_mode": by_mode(held_vals("heldout_v2_bug_detection")),
            "supplementary_by_mode": by_mode(supp_vals),
        },
        "requirement_understanding_v2": {**ru_row("requirement_understanding_v2", "test2"),
                                         "label": NATURAL_V2_LABEL},
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
        "coverage": {"llm_dependent": True, **cov_vals(blk), "by_mode": by_mode(cov_vals)},
        "citation_validity": {"llm_dependent": True, **cit_vals(blk),
                              "by_mode": by_mode(cit_vals)},
        "heldout_bug_detection": {
            "llm_dependent": True, "label": HELDOUT_V1_SEEN_LABEL,
            "bugs": blk["heldout_bug_detection"]["generated"]["bugs"],
            **held_vals("heldout_bug_detection")(blk),
            "by_mode": by_mode(held_vals("heldout_bug_detection")),
        },
        "requirement_understanding": {**ru_row("requirement_understanding", "test"),
                                      "label": NATURAL_V1_TEST_LABEL},
        "requirement_understanding_dev": {**ru_row("requirement_understanding", "dev"),
                                          "label": NATURAL_V1_DEV_LABEL},
        "in_sample_bug_detection": {
            "llm_dependent": True, "label": IN_SAMPLE_LABEL,
            "bugs": blk["bug_detection"]["generated"]["bugs"],
            **held_vals("bug_detection")(blk), "by_mode": by_mode(held_vals("bug_detection")),
        },
    }
    return {"mode": mode, "other_mode": other, "other_mode_status": other_status,
            "modes_completed": completed,
            "order": list(HEADLINE_ORDER), **{k: rows[k] for k in HEADLINE_ORDER}}


def _spread(values: list[float | None]) -> dict[str, Any]:
    """Mean and min-max range over the runs (``None`` values are skipped, never imputed)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "min": None, "max": None}
    return {"n": len(vals), "mean": round(statistics.fmean(vals), 4),
            "min": round(min(vals), 4), "max": round(max(vals), 4)}


NOISE_METRICS = (
    "parsed_precision", "parsed_recall", "parsed_f1", "exercised_f1",
    "category_recall_micro", "precondition_recall_micro",
    "tests_kept", "rejected", "fallback_events",
)


def _provenance_block(spec: Any, parts: dict[str, list[TestCase]]) -> dict[str, Any]:
    """Byte-provenance check of several test groups; totals are summed over the groups."""
    checked = {name: check_provenance(spec, tests) for name, tests in parts.items()}
    return {
        **checked,
        "checked": sum(p["checked"] for p in checked.values()),
        "passed": sum(p["passed"] for p in checked.values()),
        "failed": sum(p["failed"] for p in checked.values()),
        "ok": all(p["ok"] for p in checked.values()),
    }


def _noise_run_row(
    run_no: int, rows: list[dict[str, Any]], stats: dict[str, Any], prov: dict[str, Any],
    wall: list[float], main: bool,
) -> dict[str, Any]:
    agg = u.aggregate_by_split(rows)["all"]
    return {
        "run": run_no,
        "used_for_main_tables": main,
        "parsed_precision": agg["targets_parsed"]["precision"],
        "parsed_recall": agg["targets_parsed"]["recall"],
        "parsed_f1": agg["targets_parsed"]["f1"],
        "parsed_exact": agg["targets_parsed"]["exact"],
        "exercised_f1": agg["targets_exercised"]["f1"],
        "category_recall_micro": agg["categories"]["micro_recall"],
        "precondition_recall_micro": agg["preconditions"]["micro_recall"],
        "tests_kept": stats["tests_kept"],
        "rejected": stats["rejected"],
        "fallback_events": stats["fallback_events"],
        "understanding_fallback": agg["fallback"]["count"],
        "truncations": stats["truncations"],
        "requirements": agg["requirements"],
        "wall_total_s": round(sum(wall), 3),
        "provenance": {k: prov[k] for k in ("checked", "passed", "failed", "ok")},
    }


def _result_signature(results: list[PipelineResult]) -> list[Any]:
    """Everything a deterministic backend must reproduce: parse, and every kept test's steps."""
    return [
        (r.requirement_id, r.parsed.model_dump() if r.parsed else None, r.status,
         [(t.template_id, json.dumps(t.parameters, sort_keys=True, default=str),
           [s.model_dump(mode="json") for s in t.steps]) for t in r.tests])
        for r in results
    ]


def _run_natural(
    label: str, reqs: list[Any], *, llm: Any, spec: Any, retriever: Any, store: AuditStore,
    engine: str, tag: str,
) -> tuple[list[dict[str, Any]], list[PipelineResult], list[float]]:
    """Run the pipeline over labelled natural requirements and score each one."""
    rows: list[dict[str, Any]] = []
    results: list[PipelineResult] = []
    wall: list[float] = []
    for nreq in reqs:
        t0 = time.perf_counter()
        res = run_pipeline(nreq.text, nreq.id, spec, llm, retriever, store, engine=engine)
        wall.append(time.perf_counter() - t0)
        results.append(res)
        rows.append(u.score_requirement(spec, nreq, res.parsed, res.tests, res.status))
        print(f"[{label}{tag}] {nreq.id} ({nreq.split}): {len(res.tests)} tests in "
              f"{wall[-1]:.1f} s", file=sys.stderr, flush=True)
    return rows, results, wall


def _heldout_v2_block(
    spec: Any, v2_catalog: Any, gold: list[TestCase], gold_v2: Any, generated: list[TestCase],
    nat_v1_tests: list[TestCase], nat_v2_tests: list[TestCase] | None,
) -> dict[str, Any]:
    """Held-out v2 detection: the headline generated suite, gold, union and two supplements."""
    gen_matrix = run_bug_matrix(generated, spec, v2_catalog.ids, catalog=v2_catalog)
    gen = m.bug_detection(gen_matrix)
    gold_det = m.bug_detection(gold_v2)
    suites: dict[str, list[TestCase]] = {"generated": generated, "gold": gold}
    dets: dict[str, Any] = {"generated": gen, "gold": gold_det}
    supplementary: dict[str, Any] = {}
    if nat_v2_tests is not None:
        extra = {"all_generated": generated + nat_v1_tests + nat_v2_tests,
                 "natural_v2_generated": nat_v2_tests}
        for name, tests in extra.items():
            det = m.bug_detection(run_bug_matrix(tests, spec, v2_catalog.ids, catalog=v2_catalog))
            suites[name], dets[name] = tests, det
            supplementary[name] = {
                "tests": len(tests), "bugs": det["bugs"], "detected": det["detected"],
                "rate": det["rate"], "undetected": det["undetected"],
                "per_bug": det["per_bug"], "invalid_tests": len(det["invalid_tests"]),
                "definition": (
                    "union of ALL generated tests (seed + natural v1 + natural v2 requirements)"
                    if name == "all_generated" else
                    "tests generated from the 16 natural-v2 requirements alone"),
            }
    else:
        supplementary = {"all_generated": "not run (natural requirements skipped)",
                         "natural_v2_generated": "not run (natural requirements skipped)"}
    return {
        "scope": HELDOUT_V2_LABEL,
        "catalog": "data/bugs/heldout_v2_catalog.yaml",
        "generated": gen,
        "gold": gold_det,
        "union": m.union_detection(gen_matrix, gold_v2),
        "analysis": heldout_v2_analysis(spec, suites, dets),
        "supplementary": supplementary,
    }


def _noise_check(
    label: str, *, natural: bool, noise_runs: int, spec: Any, natural_v2_reqs: list[Any],
    nat2_rows: list[dict[str, Any]], nat2_results: list[PipelineResult], nat2_wall: list[float],
    nat2_stats: dict[str, Any] | None, run_kw: dict[str, Any], timings: dict[str, float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run-to-run noise on natural v2: ollama runs ``noise_runs`` times, mock is deterministic."""
    if not natural or nat2_stats is None:
        return {"status": "not run"}, []
    splits = {n.id: n.split for n in natural_v2_reqs}
    nat2_tests = [test for r in nat2_results for test in r.tests]
    runs = [_noise_run_row(1, nat2_rows, nat2_stats, check_provenance(spec, nat2_tests),
                           nat2_wall, True)]
    extra_provenance: list[dict[str, Any]] = []
    common: dict[str, Any] = {"status": "completed", "mode": label, "requested_runs": noise_runs}
    if label != "ollama":
        _, res_b, _ = _run_natural(label, natural_v2_reqs, tag=" v2 determinism check", **run_kw)
        identical = _result_signature(res_b) == _result_signature(nat2_results)
        return {
            **common, "deterministic": True, "runs": runs,
            "determinism_check": {
                "second_run_identical": identical,
                "compared": "parsed requirement, status and every kept test's template, "
                            "parameters and steps, over all natural-v2 requirements",
            },
            "summary": {k: _spread([r[k] for r in runs]) for k in NOISE_METRICS},
            "note": ("mock is deterministic (keyword rules, no sampling), so it was run once "
                     "for the tables; a second run was compared for equality as a check."),
        }, extra_provenance
    for k in range(2, noise_runs + 1):
        rows_k, res_k, wall_k = _run_natural(label, natural_v2_reqs, tag=f" v2 run{k}", **run_kw)
        prov_k = check_provenance(spec, [test for r in res_k for test in r.tests])
        extra_provenance.append({"run": k, "provenance": prov_k})
        runs.append(_noise_run_row(k, rows_k, _pipeline_stats(res_k, wall_k, splits), prov_k,
                                   wall_k, False))
        timings[f"{label}.noise_run_{k}"] = sum(wall_k)
    return {
        **common, "deterministic": False, "runs": runs,
        "summary": {k: _spread([r[k] for r in runs]) for k in NOISE_METRICS},
        "note": ("Run 1 is the run used for every main table. Every run is listed; the summary "
                 "is the mean and the min-max range over all runs, never the best run."),
    }, extra_provenance


def _run_mode(
    llm: Any,
    *,
    spec: Any,
    requirements: list[dict[str, str]],
    natural_reqs: list[Any],
    natural_v2_reqs: list[Any],
    retriever: Any,
    store: AuditStore,
    engine: str,
    corpus: Any,
    catalog: Any,
    heldout_catalog: Any,
    heldout_v2_catalog: Any,
    gold: list[TestCase],
    gold_matrix: Any,
    gold_heldout: Any,
    gold_heldout_v2: Any,
    natural: bool,
    noise_runs: int,
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

    # --- requirement understanding (natural v1, then natural v2) ------------------------
    t = time.perf_counter()
    run_kw: dict[str, Any] = {"llm": llm, "spec": spec, "retriever": retriever, "store": store,
                              "engine": engine}
    nat_rows, nat_results, nat_wall = _run_natural(label, natural_reqs, tag="", **run_kw)
    timings[f"{label}.requirement_understanding"] = time.perf_counter() - t
    t = time.perf_counter()
    nat2_rows, nat2_results, nat2_wall = _run_natural(label, natural_v2_reqs, tag=" v2", **run_kw)
    timings[f"{label}.requirement_understanding_v2"] = time.perf_counter() - t

    # --- execution + bug matrices ------------------------------------------------------
    t = time.perf_counter()
    eval_run = store.start_run("EVAL", f"evaluation run mode={label}", llm.name,
                               type(retriever).__name__)
    clean = run_suite(generated, spec)
    gen_matrix = run_bug_matrix(generated, spec, catalog.ids, store, eval_run)
    store.finish_run(eval_run, "completed")
    gen_heldout = run_bug_matrix(generated, spec, heldout_catalog.ids, catalog=heldout_catalog)
    nat_tests = [test for r in nat_results for test in r.tests]
    nat2_tests = [test for r in nat2_results for test in r.tests]
    heldout_v2_block = _heldout_v2_block(
        spec, heldout_v2_catalog, gold, gold_heldout_v2, generated, nat_tests,
        nat2_tests if natural else None)
    timings[f"{label}.execution_and_bug_matrices"] = time.perf_counter() - t

    # --- noise check (extra runs over natural v2; ollama only) ---------------------------
    t = time.perf_counter()
    nat2_stats = (_pipeline_stats(nat2_results, nat2_wall,
                                  {n.id: n.split for n in natural_v2_reqs}) if natural else None)
    noise_check, extra_provenance = _noise_check(
        label, natural=natural, noise_runs=noise_runs, spec=spec,
        natural_v2_reqs=natural_v2_reqs, nat2_rows=nat2_rows, nat2_results=nat2_results,
        nat2_wall=nat2_wall, nat2_stats=nat2_stats, run_kw=run_kw, timings=timings)
    timings[f"{label}.noise_check"] = time.perf_counter() - t

    # --- byte provenance ---------------------------------------------------------------
    t = time.perf_counter()
    provenance = _provenance_block(
        spec, {"seed": generated, "natural": nat_tests, "natural_v2": nat2_tests})
    provenance["noise_extra_runs"] = extra_provenance
    for extra in extra_provenance:
        for key in ("checked", "passed", "failed"):
            provenance[key] += extra["provenance"][key]
        provenance["ok"] = provenance["ok"] and extra["provenance"]["ok"]
    timings[f"{label}.provenance"] = time.perf_counter() - t

    # --- metrics -----------------------------------------------------------------------
    t = time.perf_counter()
    heldout_block: dict[str, Any] = {
        "scope": HELDOUT_LABEL,
        "label": HELDOUT_V1_SEEN_LABEL,
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
    latency = _latency_block(seed_stats, nat_stats)
    if nat2_stats is not None:
        v1_rows = seed_stats["per_requirement"] + (nat_stats["per_requirement"] if nat_stats else [])
        wall_v2 = [r["wall_s"] for r in nat2_stats["per_requirement"]]
        latency["per_requirement_wall_s"]["natural_v2"] = _latency_summary(wall_v2)
        latency["per_requirement_wall_s"]["all_with_v2"] = _latency_summary(
            [r["wall_s"] for r in v1_rows] + wall_v2)
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
        "heldout_v2_bug_detection": heldout_v2_block,
        "requirement_understanding": {
            "source": "data/requirements_natural.csv",
            "label": NATURAL_V1_TEST_LABEL,
            "per_requirement": nat_rows,
            "splits": u.aggregate_by_split(nat_rows),
        } if natural else {"status": "not run"},
        "requirement_understanding_v2": {
            "source": "data/requirements_natural_v2.csv",
            "label": NATURAL_V2_LABEL,
            "per_requirement": nat2_rows,
            "splits": u.aggregate_by_split(nat2_rows),
        } if natural else {"status": "not run"},
        "noise_check": noise_check,
        "pipeline": seed_stats,
        "pipeline_natural": nat_stats if nat_stats is not None else {"status": "not run"},
        "pipeline_natural_v2": nat2_stats if nat2_stats is not None else {"status": "not run"},
        "latency": latency,
        "events": _events_block(seed_stats, nat_stats, nat2_stats),
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
    noise_runs: int = 1,
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
    records the BM25-vs-Chroma retrieval comparison as "not run". ``noise_runs`` is the total
    number of times the ollama pipeline runs over natural v2 (run 1 feeds the tables, the
    rest only the noise check; mock is deterministic and runs once, plus an equality
    re-run). Every generated test
    of every mode is checked for byte provenance (:mod:`.provenance`);
    ``report["provenance_ok"]`` is False if any test fails.
    """
    if mode not in LLM_MODES:
        raise ValueError(f"mode must be one of {LLM_MODES}, got {mode!r}")
    if noise_runs < 1:
        raise ValueError(f"noise_runs must be >= 1, got {noise_runs}")
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
    heldout_v2_catalog = load_bug_catalog(HELDOUT_V2_BUG_CATALOG_PATH)
    natural_reqs = (
        u.load_natural_requirements(root / "data" / "requirements_natural.csv") if natural else []
    )
    natural_v2_reqs = (
        u.load_natural_requirements(root / "data" / "requirements_natural_v2.csv")
        if natural else []
    )
    chosen_engine = resolve_engine(engine)
    freeze = freeze_info(root)
    timings["setup"] = time.perf_counter() - t

    # --- LLM-independent: gold suites ---------------------------------------------------
    t = time.perf_counter()
    gold_matrix = run_bug_matrix(gold, spec, catalog.ids)
    gold_clean = run_suite(gold, spec)
    gold_heldout = run_bug_matrix(gold, spec, heldout_catalog.ids, catalog=heldout_catalog)
    gold_heldout_v2 = run_bug_matrix(gold, spec, heldout_v2_catalog.ids,
                                     catalog=heldout_v2_catalog)
    timings["gold_suites"] = time.perf_counter() - t

    # --- per-mode generation + metrics ------------------------------------------------
    store = AuditStore(out / "audit.sqlite")
    llms: list[tuple[str, Any]] = []
    if actual_mode == "ollama" and compare_mock:
        llms.append(("mock", get_llm(Config(llm_mode="mock", retriever=base_cfg.retriever))))
    llms.append((actual_mode, llm))
    common: dict[str, Any] = {
        "spec": spec, "requirements": requirements, "natural_reqs": natural_reqs,
        "natural_v2_reqs": natural_v2_reqs,
        "retriever": retriever, "store": store, "engine": chosen_engine, "corpus": corpus,
        "catalog": catalog, "heldout_catalog": heldout_catalog,
        "heldout_v2_catalog": heldout_v2_catalog, "gold": gold,
        "gold_matrix": gold_matrix, "gold_heldout": gold_heldout,
        "gold_heldout_v2": gold_heldout_v2, "natural": natural, "noise_runs": noise_runs,
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
        "report_version": REPORT_VERSION,
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
        "heldout_v2_catalog_size": len(heldout_v2_catalog.ids),
        "natural_requirements": len(natural_reqs),
        "natural_requirements_v2": len(natural_v2_reqs),
        "noise_runs_requested": noise_runs,
        "retrieval_comparison": retrieval_comparison,
        "simulator_rules_agreement": agreement,
        "udsoncan_virtual_can": can_result,
        "metric_definitions": {**m.METRIC_DEFINITIONS, **u.UNDERSTANDING_DEFINITIONS,
                               **V2_DEFINITIONS},
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


def write_before_after(out: Path, baseline: Path | None = None) -> Path:
    """Render ``<out>/partC/before_after.md`` from the frozen baseline and ``out``'s report."""
    from uds_assistant.eval import before_after as ba

    report = json.loads((out / "eval_report.json").read_text(encoding="utf-8"))
    base = json.loads((baseline or REPO_ROOT / ba.BASELINE_PATH).read_text(encoding="utf-8"))
    target = out / "partC" / "before_after.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    sws_text = (REPO_ROOT / "docs" / "SWS_DISAGREEMENTS.md").read_text(encoding="utf-8")
    target.write_text(ba.render_before_after(base, report, ba.sws_open_count(sws_text)),
                      encoding="utf-8")
    return target


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
    parser.add_argument("--noise-runs", type=int, default=1, metavar="N",
                        help="ollama only: run the pipeline over natural v2 N times in total "
                        "(run 1 feeds the tables, all runs go into the noise check; default 1)")
    parser.add_argument("--before-after", action="store_true",
                        help="also render <out>/partC/before_after.md from the frozen baseline")
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
        if args.before_after:
            print(f"rendered {write_before_after(Path(args.out))}")
        return 0
    if args.noise_runs < 1:
        build_parser().error("--noise-runs must be >= 1")
    report = run_evaluation(
        args.mode, args.out, args.engine, run_exported=not args.no_export_run,
        run_can=not args.skip_can, run_retrieval_compare=not args.skip_retrieval_compare,
        compare_mock=not args.no_mock_compare, noise_runs=args.noise_runs,
    )
    for name in report["modes_run"]:
        block = report["modes"][name]
        det = block["bug_detection"]
        held = block["heldout_bug_detection"]
        held2 = block["heldout_v2_bug_detection"]
        prov = block["provenance"]
        ru2 = block["requirement_understanding_v2"].get("splits", {}).get("test2")
        ru2_txt = ("n/a" if ru2 is None else
                   f"parsed exact {ru2['targets_parsed']['exact']}/{ru2['requirements']}, "
                   f"P/R/F1 {ru2['targets_parsed']['precision']}/{ru2['targets_parsed']['recall']}/"
                   f"{ru2['targets_parsed']['f1']}, exercised F1 {ru2['targets_exercised']['f1']}, "
                   f"category recall {ru2['categories']['micro_recall']}, precondition recall "
                   f"{ru2['preconditions']['micro_recall']}")
        print(
            f"mode={name} tests={block['generated_tests']['count']} "
            f"HELD-OUT v2 (fresh) bug detection: generated {held2['generated']['detected']}/"
            f"{held2['generated']['bugs']}, gold {held2['gold']['detected']}/"
            f"{held2['gold']['bugs']}, union {held2['union']['detected']}/"
            f"{held2['union']['bugs']}; natural v2 (fresh) understanding: {ru2_txt}; "
            f"held-out v1 (seen): generated {held['generated']['detected']}/"
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
    print(f"freeze: all recorded Part C hashes match and are clean = {report['freeze']['all_ok']}")
    if args.before_after:
        print(f"before/after: {write_before_after(Path(args.out))}")
    if not report["provenance_ok"]:
        for name in report["modes_run"]:
            for f in provenance_failures(report["modes"][name]["provenance"]):
                print(f"BYTE PROVENANCE FAILURE [{name}] {f['test_id']}: {f['problems']}",
                      file=sys.stderr)
        return PROVENANCE_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
