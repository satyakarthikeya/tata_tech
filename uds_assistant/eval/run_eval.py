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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from uds_assistant.agent import resolve_engine, run_pipeline
from uds_assistant.agent.state import PipelineResult
from uds_assistant.config import Config, get_config
from uds_assistant.eval import breakdown as bd
from uds_assistant.eval import metrics as m
from uds_assistant.eval import understanding as u
from uds_assistant.eval.agreement import DEFAULT_REQUESTS, simulator_rules_agreement
from uds_assistant.eval.can_check import run_udsoncan_sequence
from uds_assistant.eval.heldout import heldout_analysis
from uds_assistant.eval.heldout_v2 import heldout_v2_analysis
from uds_assistant.eval.heldout_v3 import heldout_v3_analysis
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
    HELDOUT_V3_BUG_CATALOG_PATH,
    HELDOUT_V3_BUG_IDS,
    load_bug_catalog,
)
from uds_assistant.spec.schema import load_spec
from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.conformance import (
    CONFORMANCE_TEMPLATE_ID,
    SELECTION_METHOD,
    build_conformance_suite,
)
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
    "held-out v2, now SEEN: 15 bugs written blind by a subagent after the Part C freeze (fresh "
    "in Part C); their Part C results were known before Part D, so they are no longer "
    "independent evidence"
)
NATURAL_V2_LABEL = (
    "natural v2 (SEEN, split test2): 16 requirements written blind after the Part C freeze "
    "(fresh in Part C); their Part C results were known before Part D"
)
HELDOUT_V3_LABEL = (
    "held-out v3 (FRESH): 15 bugs written blind by a subagent after the Part D freeze, which "
    "could not see templates, the conformance sweep, prompts, eval code or any report; nothing "
    "was changed after seeing these results"
)
NATURAL_V3_LABEL = (
    "natural v3 (FRESH, split test3): 16 requirements written blind after the Part D freeze by "
    "a subagent that could not see any natural set or any code; nothing was tuned on them"
)
NATURAL_V1_TEST_LABEL = "natural v1 test split (SEEN: templates were designed after its results)"
NATURAL_V1_DEV_LABEL = "natural v1 dev split (tuned on: the prompts were tuned on these rows)"
HEADLINE_ORDER = (
    "heldout_v3_bug_detection",
    "requirement_understanding_v3",
    "simulator_rules_agreement",
    "gold_clean_pass",
    "udsoncan_virtual_can",
    "coverage",
    "citation_validity",
    "conformance_sweep",
    "heldout_v2_bug_detection",
    "requirement_understanding_v2",
    "heldout_bug_detection",
    "requirement_understanding",
    "requirement_understanding_dev",
    "in_sample_bug_detection",
)
REPORT_VERSION = 5
V2_DEFINITIONS: dict[str, str] = {
    "heldout_v2_bug_detection_rate": (
        "Same procedure as bug_detection_rate on the 15 held-out v2 bugs in "
        "data/bugs/heldout_v2_catalog.yaml (heldout_v2: true), written blind after the Part C "
        "freeze and SEEN since Part D. Generated-suite detection, where the generated suite is the tests "
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
}
"""Extra metric definitions added in report version 3 (v2 sets; SEEN since Part D)."""

PART_D_CATALOGS: tuple[tuple[str, str, str | None], ...] = (
    ("heldout_v2", "held-out v2 (15 bugs, SEEN: their Part C results were known before Part D)",
     "HELDOUT_V2_BUG_CATALOG_PATH"),
    ("heldout_v1", "held-out v1 (12 bugs, SEEN)", "HELDOUT_BUG_CATALOG_PATH"),
    ("in_sample", "in-sample (26 bugs, templates tuned on these)", None),
    ("heldout_v3", "held-out v3 (FRESH, written blind after the Part D freeze)",
     "HELDOUT_V3_BUG_CATALOG_PATH"),
)
"""Part D detection catalogs: (key, label, path constant in ``uds_assistant.simulator``).

``None`` is the default (in-sample) catalog. A catalog whose path constant is not exported by
the simulator, or whose file does not exist, is skipped: this is the hook for a later v3 set.
"""
PART_D_DEFINITIONS: dict[str, str] = {
    "part_d_detection": (
        "Per bug catalog and LLM mode: (a) requirement_driven = the tests generated from the 15 "
        "seed requirements (exactly the Part C 'generated' suite, comparable with Part C); "
        "(b) conformance = the requirement-independent conformance sweep alone "
        "(uds_assistant/testgen/conformance.py, generated deterministically from the spec; it "
        "uses no LLM and is the same in every mode); (c) full_output = (a) union (b), the "
        "system's full output. A bug counts as detected by a suite when a test that passes on "
        "the clean simulator fails with the bug enabled; (c) is computed per bug from (a) and "
        "(b) because every test runs on a fresh simulator."
    ),
    "conformance_sweep": (
        "Setups (spec-derived states) x stimuli (spec-derived requests and mutations), each "
        "followed by a fixed probe set; every expected byte from the rules engine; reduced by "
        "deterministic greedy covering. " + SELECTION_METHOD
    ),
}
"""Metric definitions added in report version 4 (Part D)."""
PART_D2_DEFINITIONS: dict[str, str] = {
    "heldout_v3_bug_detection": (
        "FRESH headline for bugs: the 15 held-out v3 bugs in data/bugs/heldout_v3_catalog.yaml "
        "(heldout_v3: true), written blind after the Part D freeze. HEADLINE = detection by the "
        "system's FULL OUTPUT = (c) the requirement-driven tests from the 15 seed requirements "
        "UNION (per bug) the conformance sweep. Reported next to it and clearly labelled: (a) "
        "requirement-driven only (comparable with Part C), (b) the sweep alone, (d) gold. "
        "Supplementary: all generated tests (seed + natural v1 + v2 + v3) and the natural-v3 "
        "tests alone. Missed-bug reasons come from eval/heldout_v3.py (static trigger predicates "
        "written from the bug descriptions before any v3 result existed)."
    ),
    "natural_v3_understanding": (
        "Requirement understanding on data/requirements_natural_v3.csv (16 rows, split test3, "
        "written blind after the Part D freeze) with the same label schema and scoring as v1 / "
        "v2. test3 is the requirement headline. Nothing was tuned on it."
    ),
    "noise_check": (
        "ollama runs the pipeline over natural v3 --noise-runs times in total; run 1 feeds the "
        "tables, every run is listed, and the summary is the mean and min-max range over ALL "
        "runs (never only the best). mock is deterministic: one run, plus an equality re-run "
        "as a check. natural v2 (SEEN) keeps its single run."
    ),
    "by_kind": (
        "Parsed (and exercised) false positives and false negatives by identifier kind "
        "(service / did / routine / dtc), per requirement set, from each requirement's missed "
        "and extra identifiers. tp = label items of that kind minus the missed ones."
    ),
    "rejected_by_reason": (
        "Rejected planner choices by reason: unknown template id; option index out of range; "
        "option not in the offered shortlist; duplicate / other (a choice that previously "
        "failed, or an instantiate / validate failure). Counted per requirement set."
    ),
    "seen_sets": (
        "SEEN = their results were known when Part D was designed or tuned: held-out v1 and v2 "
        "bugs, natural v1 (test and dev) and v2 requirements. The 26 in-sample bugs were tuned "
        "on. Only the v3 rows are independent evidence."
    ),
}
"""Metric definitions added in report version 5 (Part D evaluation)."""


@dataclass(frozen=True)
class NaturalSet:
    """One labelled natural-requirement set and where its results go in the report."""

    key: str
    csv: str
    ru_key: str
    pipe_key: str
    prov_key: str
    label: str
    headline_split: str
    tag: str
    seen: bool


NATURAL_SETS: tuple[NaturalSet, ...] = (
    NaturalSet("v1", "requirements_natural.csv", "requirement_understanding", "pipeline_natural",
               "natural", NATURAL_V1_TEST_LABEL, "test", "", True),
    NaturalSet("v2", "requirements_natural_v2.csv", "requirement_understanding_v2",
               "pipeline_natural_v2", "natural_v2", NATURAL_V2_LABEL, "test2", " v2", True),
    NaturalSet("v3", "requirements_natural_v3.csv", "requirement_understanding_v3",
               "pipeline_natural_v3", "natural_v3", NATURAL_V3_LABEL, "test3", " v3", False),
)
NOISE_SET = "v3"
"""The natural set that gets the ``--noise-runs`` repeats (the fresh one; v1 / v2 are SEEN)."""
PROGRESS_FILE = "PROGRESS.md"
FREEZE_SECTION = "Part C freeze"
FREEZE_SECTIONS = ("Part D freeze", "Part C freeze")
"""Freeze tables to look for in PROGRESS.md, newest first: the first one found is used."""


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
    section = FREEZE_SECTIONS[0]
    error: str | None = None
    if progress.exists():
        text = progress.read_text(encoding="utf-8")
        for candidate in FREEZE_SECTIONS:
            found = parse_freeze_table(text, candidate)
            if found["paths"]:
                recorded, section = found, candidate
                break
        if not recorded["paths"]:
            error = (f"no hash table found in {PROGRESS_FILE} under any of: "
                     + ", ".join(f"'{c}'" for c in FREEZE_SECTIONS))
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
    return {"source": f"{PROGRESS_FILE} '{section}' table", "section": section,
            "error": error, "commit": commit_info, "paths": paths, "all_ok": all_ok}


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
        "rejected_by_reason": bd.rejected_by_reason(
            reason for x in rows for reason in x["rejected_reasons"]),
        "rejected_by_reason_by_split": {
            split: bd.rejected_by_reason(
                reason for x in rows if x["split"] == split for reason in x["rejected_reasons"])
            for split in dict.fromkeys(x["split"] for x in rows)},
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


def _ru_headline(
    ru: dict[str, Any], split: str = "test", pipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if "splits" not in ru or split not in ru["splits"]:
        return {"status": "not run"}
    tsplit = ru["splits"][split]
    kinds = tsplit.get("by_kind", {}).get("parsed", {})
    out = {
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
        "fp_by_kind": {k: v["fp"] for k, v in kinds.items()},
        "fn_by_kind": {k: v["fn"] for k, v in kinds.items()},
    }
    if pipe is not None and "rejected" in pipe:
        reasons = pipe.get("rejected_by_reason_by_split", {}).get(split, {})
        out["rejected"] = sum(reasons.values())
        out["rejected_by_reason"] = reasons
    return out


def _not_run_status(report: dict[str, Any], name: str) -> str:
    return f"not run: {report['modes'][name].get('reason', 'not requested')}"


def build_headline(report: dict[str, Any]) -> dict[str, Any]:
    """Headline metrics (rows in :data:`HEADLINE_ORDER`) from the finished report.

    The FRESH v3 rows come first (bug detection by the system's full output, with the
    requirement-driven / sweep-alone / gold figures next to it; natural v3 understanding),
    then the LLM-independent rows (agreement, gold, CAN, coverage, citations, conformance
    sweep), then the SEEN rows (held-out v2 bugs, natural v2, held-out v1, natural v1 test /
    dev), then the in-sample bugs. LLM-dependent rows carry a ``by_mode`` entry for every
    mode (a value dict for a completed mode, a "not run: ..." string otherwise); their
    top-level values are for ``report["actual_mode"]``.
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

    def supp_cells(supp: dict[str, Any]) -> dict[str, Any]:
        return {k: ({"detected": v["detected"], "bugs": v["bugs"], "rate": v["rate"],
                     "tests": v["tests"]} if isinstance(v, dict) and "detected" in v else v)
                for k, v in supp.items()}

    def supp_vals(b: dict[str, Any]) -> dict[str, Any]:
        return supp_cells(b["heldout_v2_bug_detection"].get("supplementary") or {})

    def v3_vals(b: dict[str, Any]) -> dict[str, Any]:
        v3 = b["heldout_v3_bug_detection"]
        if v3.get("status"):
            return {"status": v3["status"]}

        def cell(x: Any) -> Any:
            if isinstance(x, dict) and "detected" in x:
                return {"detected": x["detected"], "bugs": v3["bugs"], "rate": x["rate"]}
            return x
        return {
            "bugs": v3["bugs"],
            "full_output": cell(v3["full_output"]),
            "requirement_driven": cell(v3["requirement_driven"]),
            "conformance": cell(v3["conformance"]),
            "gold": cell(v3["gold"]),
            "suite_sizes": v3["suite_sizes"],
            "missed_by_headline": v3.get("missed_by_headline"),
        }

    def v3_supp(b: dict[str, Any]) -> dict[str, Any]:
        return supp_cells(b["heldout_v3_bug_detection"].get("supplementary") or {})

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

    def full_by_mode(key: str) -> dict[str, Any]:
        return by_mode(lambda b: _part_d_cell(b, key))

    by_key = {ns.ru_key: ns for ns in NATURAL_SETS}

    def ru_row(key: str, split: str) -> dict[str, Any]:
        ns = by_key[key]
        return {"llm_dependent": True,
                **{n: _ru_headline(report["modes"][n].get(key, {}), split,
                                   report["modes"][n].get(ns.pipe_key))
                   if n in completed else _not_run_status(report, n) for n in LLM_MODES}}

    gold_total = report["gold_tests"]
    conf = report.get("conformance", {})
    conf_row: dict[str, Any] = {"llm_dependent": False, "status": conf.get("status", "not run"),
                                "reason": conf.get("reason")}
    if conf.get("status") == "completed":
        conf_row.update({
            "tests": conf["tests"], "steps": conf["steps"],
            "generation_s": conf["generation_s"], "clean_run_s": conf["clean_run_s"],
            "bug_matrix_runtime_s": conf["bug_matrix_runtime_s"],
            "clean_simulator_passed": conf["clean_simulator_passed"],
            "provenance_ok": conf["provenance"]["ok"],
        })
    rows: dict[str, Any] = {
        "heldout_v3_bug_detection": {
            "llm_dependent": True, "label": HELDOUT_V3_LABEL,
            "definition": ("headline = full output (c) = requirement-driven tests UNION the "
                           "conformance sweep, per bug; (a) requirement-driven only, (b) sweep "
                           "alone and gold are in the same row"),
            **v3_vals(blk), "by_mode": by_mode(v3_vals),
            "supplementary_by_mode": by_mode(v3_supp),
        },
        "requirement_understanding_v3": {**ru_row("requirement_understanding_v3", "test3"),
                                         "label": NATURAL_V3_LABEL},
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
        "conformance_sweep": conf_row,
        "heldout_v2_bug_detection": {
            "llm_dependent": True, "label": HELDOUT_V2_LABEL,
            "bugs": blk["heldout_v2_bug_detection"]["generated"]["bugs"],
            **held_vals("heldout_v2_bug_detection")(blk),
            "by_mode": by_mode(held_vals("heldout_v2_bug_detection")),
            "supplementary_by_mode": by_mode(supp_vals),
            "full_output_by_mode": full_by_mode("heldout_v2"),
        },
        "requirement_understanding_v2": {**ru_row("requirement_understanding_v2", "test2"),
                                         "label": NATURAL_V2_LABEL},
        "heldout_bug_detection": {
            "llm_dependent": True, "label": HELDOUT_V1_SEEN_LABEL,
            "bugs": blk["heldout_bug_detection"]["generated"]["bugs"],
            **held_vals("heldout_bug_detection")(blk),
            "by_mode": by_mode(held_vals("heldout_bug_detection")),
            "full_output_by_mode": full_by_mode("heldout_v1"),
        },
        "requirement_understanding": {**ru_row("requirement_understanding", "test"),
                                      "label": NATURAL_V1_TEST_LABEL},
        "requirement_understanding_dev": {**ru_row("requirement_understanding", "dev"),
                                          "label": NATURAL_V1_DEV_LABEL},
        "in_sample_bug_detection": {
            "llm_dependent": True, "label": IN_SAMPLE_LABEL,
            "bugs": blk["bug_detection"]["generated"]["bugs"],
            **held_vals("bug_detection")(blk), "by_mode": by_mode(held_vals("bug_detection")),
            "full_output_by_mode": full_by_mode("in_sample"),
        },
    }
    return {"mode": mode, "other_mode": other, "other_mode_status": other_status,
            "modes_completed": completed,
            "order": list(HEADLINE_ORDER), **{k: rows[k] for k in HEADLINE_ORDER}}


def _part_d_cell(blk: dict[str, Any], key: str) -> Any:
    """Full-output detection of one catalog for the headline (or why it is not there)."""
    row = blk.get("part_d_detection", {}).get(key)
    if not isinstance(row, dict):
        return "not run (conformance sweep skipped)"
    full = row["full_output"]
    return {"detected": full["detected"], "bugs": full["bugs"],
            "rate": round(full["detected"] / full["bugs"], 4) if full["bugs"] else None}


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


def _supplementary_detection(
    spec: Any, catalog: Any, tests: list[TestCase], definition: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(report entry, bug_detection dict) of an extra test group against ``catalog``."""
    det = m.bug_detection(run_bug_matrix(tests, spec, catalog.ids, catalog=catalog))
    return {
        "tests": len(tests), "bugs": det["bugs"], "detected": det["detected"],
        "rate": det["rate"], "undetected": det["undetected"], "per_bug": det["per_bug"],
        "invalid_tests": len(det["invalid_tests"]), "definition": definition,
    }, det


def _heldout_v3_block(
    spec: Any, catalog: Any, *, gold: list[TestCase], gold_det: dict[str, Any],
    generated: list[TestCase], conformance_tests: list[TestCase] | None,
    conformance_det: dict[str, Any] | None, natural_tests: dict[str, list[TestCase]] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Held-out v3 detection: (a) requirement-driven, (b) sweep alone, (c) full output, gold.

    Returns the report block and the raw (a) ``bug_detection`` dict (None if not run).

    ``natural_tests`` maps the natural-set key to its tests (None when natural was skipped).
    """
    ids = list(catalog.ids)
    if set(ids) != set(HELDOUT_V3_BUG_IDS):
        return {"status": "not run: catalog ids differ from HELDOUT_V3_BUG_IDS"}, None
    req_det = m.bug_detection(run_bug_matrix(generated, spec, ids, catalog=catalog))
    suites: dict[str, list[TestCase]] = {"requirement_driven": generated, "gold": gold}
    dets: dict[str, Any] = {"requirement_driven": req_det, "gold": gold_det}
    conformance: Any = "not run (conformance sweep skipped)"
    full: Any = "not run (conformance sweep skipped)"
    conf_tests = conformance_tests or []
    if conformance_tests is not None and conformance_det is not None:
        conformance = _det_summary(conformance_det)
        full = union_from_detections(req_det, conformance_det)
        suites["conformance"], dets["conformance"] = conformance_tests, conformance_det
        suites["full_output"] = generated + conformance_tests
        dets["full_output"] = {"per_bug": [
            {"bug_id": b["bug_id"], "detected": b["bug_id"] not in full["undetected"]}
            for b in req_det["per_bug"]]}
    supplementary: dict[str, Any] = {}
    if natural_tests is not None:
        all_nat = [t for key in sorted(natural_tests) for t in natural_tests[key]]
        extra = {
            "all_generated": (
                generated + all_nat,
                "union of ALL generated tests (seed + natural v1 + natural v2 + natural v3)"),
            "natural_v3_generated": (
                natural_tests.get("v3", []),
                "tests generated from the 16 natural-v3 requirements alone"),
        }
        for name, (tests, definition) in extra.items():
            supplementary[name], dets[name] = _supplementary_detection(
                spec, catalog, tests, definition)
            suites[name] = tests
    else:
        supplementary = {"all_generated": "not run (natural requirements skipped)",
                         "natural_v3_generated": "not run (natural requirements skipped)"}
    analysis = heldout_v3_analysis(spec, suites, dets)
    headline_suite = "full_output" if "full_output" in suites else "requirement_driven"
    reasons = {x["bug_id"]: x["reason"] for x in analysis[headline_suite]["missed"]}

    def flag(det: dict[str, Any] | None, bug_id: str) -> bool | None:
        if det is None:
            return None
        row = next((b for b in det["per_bug"] if b["bug_id"] == bug_id), None)
        return None if row is None else bool(row["detected"])

    def n_detecting(det: dict[str, Any] | None, bug_id: str) -> int | None:
        if det is None:
            return None
        row = next((b for b in det["per_bug"] if b["bug_id"] == bug_id), None)
        return None if row is None else len(row.get("detecting_tests", []))

    per_bug = []
    for b in req_det["per_bug"]:
        bid = b["bug_id"]
        entry: dict[str, Any] = {
            "bug_id": bid, "title": b["title"], "category": b["category"],
            "requirement_driven": flag(req_det, bid),
            "requirement_driven_detecting_tests": n_detecting(req_det, bid),
            "conformance": flag(conformance_det, bid),
            "conformance_detecting_tests": n_detecting(conformance_det, bid),
            "full_output": flag(dets.get("full_output"), bid),
            "gold": flag(gold_det, bid),
            "natural_v3": flag(dets.get("natural_v3_generated"), bid),
            "all_generated": flag(dets.get("all_generated"), bid),
            "trigger_counts": {name: analysis[name]["trigger_counts"][bid] for name in suites},
            "reason_if_missed": reasons.get(bid),
        }
        entry["detected_by"] = [n for n in ("requirement_driven", "conformance", "gold")
                                if entry[n]]
        per_bug.append(entry)
    block = {
        "scope": HELDOUT_V3_LABEL,
        "catalog": "data/bugs/heldout_v3_catalog.yaml",
        "bugs": len(ids),
        "headline_suite": headline_suite,
        "requirement_driven": _det_summary(req_det),
        "conformance": conformance,
        "full_output": full,
        "gold": _det_summary(gold_det),
        "suite_sizes": {
            "requirement_driven": len(generated),
            "conformance": len(conf_tests) if conformance_tests is not None else None,
            "full_output": (len(generated) + len(conf_tests)
                            if conformance_tests is not None else None),
            "gold": len(gold),
        },
        "per_bug": per_bug,
        "missed_by_headline": [{"bug_id": k, "reason": v} for k, v in reasons.items()],
        "analysis": analysis,
        "trigger_summary": {
            name: {"bugs_with_stimulus": sum(1 for c in analysis[name]["trigger_counts"].values()
                                              if c > 0),
                   "bugs": len(ids),
                   "stimulus_applications": sum(max(c, 0) for c in
                                                analysis[name]["trigger_counts"].values())}
            for name in suites},
        "supplementary": supplementary,
    }
    return block, req_det


def _noise_check(
    label: str, *, natural: bool, noise_runs: int, spec: Any, ns: NaturalSet,
    reqs: list[Any], rows: list[dict[str, Any]], results: list[PipelineResult],
    wall: list[float], stats: dict[str, Any] | None, run_kw: dict[str, Any],
    timings: dict[str, float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run-to-run noise on the fresh natural set: ollama runs ``noise_runs`` times, mock once."""
    if not natural or stats is None:
        return {"status": "not run"}, []
    splits = {n.id: n.split for n in reqs}
    tests = [test for r in results for test in r.tests]
    runs = [_noise_run_row(1, rows, stats, check_provenance(spec, tests), wall, True)]
    extra_provenance: list[dict[str, Any]] = []
    common: dict[str, Any] = {"status": "completed", "mode": label, "requested_runs": noise_runs,
                              "set": ns.key, "set_label": ns.label}
    if label != "ollama":
        _, res_b, _ = _run_natural(label, reqs, tag=f"{ns.tag} determinism check", **run_kw)
        identical = _result_signature(res_b) == _result_signature(results)
        return {
            **common, "deterministic": True, "runs": runs,
            "determinism_check": {
                "second_run_identical": identical,
                "compared": f"parsed requirement, status and every kept test's template, "
                            f"parameters and steps, over all natural-{ns.key} requirements",
            },
            "summary": {k: _spread([r[k] for r in runs]) for k in NOISE_METRICS},
            "note": ("mock is deterministic (keyword rules, no sampling), so it was run once "
                     "for the tables; a second run was compared for equality as a check."),
        }, extra_provenance
    for k in range(2, noise_runs + 1):
        rows_k, res_k, wall_k = _run_natural(label, reqs, tag=f"{ns.tag} run{k}", **run_kw)
        prov_k = check_provenance(spec, [test for r in res_k for test in r.tests])
        extra_provenance.append({"run": k, "provenance": prov_k})
        runs.append(_noise_run_row(k, rows_k, _pipeline_stats(res_k, wall_k, splits), prov_k,
                                   wall_k, False))
        timings[f"{label}.noise_run_{k}"] = sum(wall_k)
    return {
        **common, "deterministic": False, "runs": runs,
        "summary": {k: _spread([r[k] for r in runs]) for k in NOISE_METRICS},
        "note": ("Run 1 is the run used for every main table. Every run is listed; the summary "
                 "is the mean and the min-max range over ALL runs, never the best run."),
    }, extra_provenance


def _det_summary(det: dict[str, Any]) -> dict[str, Any]:
    return {"tests": det["tests"], "valid_tests": det["valid_tests"],
            "invalid_tests": len(det["invalid_tests"]), "bugs": det["bugs"],
            "detected": det["detected"], "rate": det["rate"], "undetected": det["undetected"]}


def union_from_detections(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Per-bug union of two ``metrics.bug_detection`` dicts over the same catalog."""
    da = {p["bug_id"]: bool(p["detected"]) for p in a["per_bug"]}
    db = {p["bug_id"]: bool(p["detected"]) for p in b["per_bug"]}
    bugs = [p["bug_id"] for p in a["per_bug"]]
    detected = [x for x in bugs if da[x] or db.get(x, False)]
    return {
        "tests": a["tests"] + b["tests"],
        "bugs": len(bugs),
        "detected": len(detected),
        "rate": round(len(detected) / len(bugs), 4) if bugs else None,
        "undetected": [x for x in bugs if x not in detected],
        "only_requirement_driven": [x for x in bugs if da[x] and not db.get(x, False)],
        "only_conformance": [x for x in bugs if db.get(x, False) and not da[x]],
    }


def _part_d_row(
    label: str, req: dict[str, Any], conf: dict[str, Any], gold: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {"label": label, "requirement_driven": _det_summary(req),
           "conformance": _det_summary(conf), "full_output": union_from_detections(req, conf)}
    if gold is not None:
        row["gold"] = _det_summary(gold)
    return row


def resolve_part_d_catalogs(default_catalog: Any) -> dict[str, tuple[str, Any]]:
    """Load every Part D catalog that exists (see :data:`PART_D_CATALOGS`), in order."""
    import uds_assistant.simulator as sim

    out: dict[str, tuple[str, Any]] = {}
    for key, label, attr in PART_D_CATALOGS:
        if attr is None:
            out[key] = (label, default_catalog)
            continue
        path = getattr(sim, attr, None)
        if path is None or not Path(path).exists():
            continue
        out[key] = (label, load_bug_catalog(path))
    return out


def _conformance_block(
    spec: Any, catalogs: dict[str, tuple[str, Any]],
) -> tuple[dict[str, Any], list[TestCase], dict[str, dict[str, Any]]]:
    """Generate the conformance sweep (LLM-independent) and run it against every catalog."""
    t0 = time.perf_counter()
    suite = build_conformance_suite(spec)
    gen_s = time.perf_counter() - t0
    tests = suite.tests
    t = time.perf_counter()
    clean = run_suite(tests, spec)
    clean_s = time.perf_counter() - t
    t = time.perf_counter()
    prov = check_provenance(spec, tests)
    prov_s = time.perf_counter() - t
    dets: dict[str, dict[str, Any]] = {}
    runtimes: dict[str, float] = {}
    for key, (_label, cat) in catalogs.items():
        t = time.perf_counter()
        dets[key] = m.bug_detection(run_bug_matrix(tests, spec, cat.ids, catalog=cat))
        runtimes[key] = round(time.perf_counter() - t, 3)
    block = {
        "status": "completed",
        "llm_independent": True,
        "note": ("The conformance sweep is generated from the spec alone (no requirement, no "
                 "LLM, no bug catalog), so it is identical in every LLM mode."),
        "template_id": CONFORMANCE_TEMPLATE_ID,
        "tests": len(tests),
        "steps": suite.stats["steps"],
        "clean_simulator_passed": clean.passed_count,
        "generation_s": round(gen_s, 3),
        "clean_run_s": round(clean_s, 3),
        "provenance_s": round(prov_s, 3),
        "bug_matrix_runtime_s": {**runtimes, "total": round(sum(runtimes.values()), 3)},
        "bugs_per_catalog": {k: len(c.ids) for k, (_l, c) in catalogs.items()},
        "provenance": prov,
        "stats": suite.stats,
        "detection": {k: _det_summary(d) for k, d in dets.items()},
    }
    return block, tests, dets


def _run_mode(
    llm: Any,
    *,
    spec: Any,
    requirements: list[dict[str, str]],
    natural_sets: dict[str, list[Any]],
    retriever: Any,
    store: AuditStore,
    engine: str,
    corpus: Any,
    catalog: Any,
    heldout_catalog: Any,
    heldout_v2_catalog: Any,
    heldout_v3_catalog: Any,
    gold: list[TestCase],
    gold_matrix: Any,
    gold_heldout: Any,
    gold_heldout_v2: Any,
    gold_dets: dict[str, dict[str, Any]],
    natural: bool,
    noise_runs: int,
    timings: dict[str, float],
    label: str,
    part_d_catalogs: dict[str, tuple[str, Any]] | None = None,
    conformance_dets: dict[str, dict[str, Any]] | None = None,
    conformance_tests: list[TestCase] | None = None,
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

    # --- requirement understanding (natural v1, v2, v3; one run each) -----------------
    run_kw: dict[str, Any] = {"llm": llm, "spec": spec, "retriever": retriever, "store": store,
                              "engine": engine}
    nat_runs: dict[str, tuple[list[dict[str, Any]], list[PipelineResult], list[float]]] = {}
    for ns in NATURAL_SETS:
        t = time.perf_counter()
        nat_runs[ns.key] = _run_natural(label, natural_sets[ns.key], tag=ns.tag, **run_kw)
        timings[f"{label}.{ns.ru_key}"] = time.perf_counter() - t
    nat_tests = {ns.key: [test for r in nat_runs[ns.key][1] for test in r.tests]
                 for ns in NATURAL_SETS}

    # --- execution + bug matrices ------------------------------------------------------
    t = time.perf_counter()
    eval_run = store.start_run("EVAL", f"evaluation run mode={label}", llm.name,
                               type(retriever).__name__)
    clean = run_suite(generated, spec)
    gen_matrix = run_bug_matrix(generated, spec, catalog.ids, store, eval_run)
    store.finish_run(eval_run, "completed")
    gen_heldout = run_bug_matrix(generated, spec, heldout_catalog.ids, catalog=heldout_catalog)
    heldout_v2_block = _heldout_v2_block(
        spec, heldout_v2_catalog, gold, gold_heldout_v2, generated, nat_tests["v1"],
        nat_tests["v2"] if natural else None)
    heldout_v3_block, v3_req_det = _heldout_v3_block(
        spec, heldout_v3_catalog, gold=gold, gold_det=gold_dets["heldout_v3"],
        generated=generated,
        conformance_tests=conformance_tests if conformance_dets is not None else None,
        conformance_det=(conformance_dets or {}).get("heldout_v3"),
        natural_tests=nat_tests if natural else None)
    timings[f"{label}.execution_and_bug_matrices"] = time.perf_counter() - t

    # --- Part D: requirement-driven vs conformance sweep vs full output ------------------
    t = time.perf_counter()
    part_d: dict[str, Any] = {"status": "not run (conformance sweep skipped)"}
    if conformance_dets is not None and part_d_catalogs is not None:
        req_dets: dict[str, dict[str, Any]] = {
            "in_sample": m.bug_detection(gen_matrix),
            "heldout_v1": m.bug_detection(gen_heldout),
            "heldout_v2": heldout_v2_block["generated"],
        }
        if v3_req_det is not None:
            req_dets["heldout_v3"] = v3_req_det
        for key, (_lbl, cat) in part_d_catalogs.items():
            if key not in req_dets:
                req_dets[key] = m.bug_detection(
                    run_bug_matrix(generated, spec, cat.ids, catalog=cat))
        part_d = {key: _part_d_row(lbl, req_dets[key], conformance_dets[key], gold_dets.get(key))
                  for key, (lbl, _cat) in part_d_catalogs.items()}
    timings[f"{label}.part_d_detection"] = time.perf_counter() - t

    # --- per-set pipeline stats ---------------------------------------------------------
    nat_stats: dict[str, dict[str, Any] | None] = {
        ns.key: (_pipeline_stats(nat_runs[ns.key][1], nat_runs[ns.key][2],
                                 {n.id: n.split for n in natural_sets[ns.key]})
                 if natural else None) for ns in NATURAL_SETS}

    # --- noise check (extra runs over the fresh natural set; ollama only) -----------------
    t = time.perf_counter()
    noise_ns = next(ns for ns in NATURAL_SETS if ns.key == NOISE_SET)
    n_rows, n_results, n_wall = nat_runs[noise_ns.key]
    noise_check, extra_provenance = _noise_check(
        label, natural=natural, noise_runs=noise_runs, spec=spec, ns=noise_ns,
        reqs=natural_sets[noise_ns.key], rows=n_rows, results=n_results, wall=n_wall,
        stats=nat_stats[noise_ns.key], run_kw=run_kw, timings=timings)
    timings[f"{label}.noise_check"] = time.perf_counter() - t

    # --- byte provenance ---------------------------------------------------------------
    t = time.perf_counter()
    provenance = _provenance_block(
        spec, {"seed": generated, **{ns.prov_key: nat_tests[ns.key] for ns in NATURAL_SETS}})
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
    latency = _latency_block(seed_stats, nat_stats["v1"])
    v1_rows = seed_stats["per_requirement"] + (
        nat_stats["v1"]["per_requirement"] if nat_stats["v1"] else [])
    all_rows = list(v1_rows)
    for ns in NATURAL_SETS[1:]:
        st = nat_stats[ns.key]
        if st is None:
            continue
        wall_k = [r["wall_s"] for r in st["per_requirement"]]
        latency["per_requirement_wall_s"]["natural" + ns.tag.replace(" ", "_")] = (
            _latency_summary(wall_k))
        all_rows += st["per_requirement"]
        if ns.key == "v2":
            latency["per_requirement_wall_s"]["all_with_v2"] = _latency_summary(
                [r["wall_s"] for r in all_rows])
    if nat_stats["v3"] is not None:
        latency["per_requirement_wall_s"]["all_with_v3"] = _latency_summary(
            [r["wall_s"] for r in all_rows])
    n_conf = len(conformance_tests) if conformance_tests is not None else None
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
        "suite_sizes": {
            "requirement_driven": len(generated),
            "conformance": n_conf,
            "full_output": None if n_conf is None else len(generated) + n_conf,
            "definition": ("requirement-driven = tests generated from the seed requirements; "
                           "full output = those plus the conformance sweep"),
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
        "heldout_v3_bug_detection": heldout_v3_block,
        "noise_check": noise_check,
        "pipeline": seed_stats,
        "latency": latency,
        "events": _events_block(seed_stats, *nat_stats.values()),
        "provenance": provenance,
        "part_d_detection": part_d,
    }
    for ns in NATURAL_SETS:
        rows_k = nat_runs[ns.key][0]
        block[ns.ru_key] = {
            "source": f"data/{ns.csv}",
            "label": ns.label,
            "seen": ns.seen,
            "per_requirement": rows_k,
            "splits": u.aggregate_by_split(rows_k),
        } if natural else {"status": "not run"}
        stats_k = nat_stats[ns.key]
        block[ns.pipe_key] = stats_k if stats_k is not None else {"status": "not run"}
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
    conformance: bool = True,
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
    number of times the ollama pipeline runs over natural v3 (run 1 feeds the tables, the
    rest only the noise check; mock is deterministic and runs once, plus an equality
    re-run). Every generated test
    of every mode is checked for byte provenance (:mod:`.provenance`);
    ``report["provenance_ok"]`` is False if any test fails. ``conformance=False`` skips the
    Part D conformance sweep (reported as "not run"); otherwise it is generated once (it is
    LLM-independent), checked for byte provenance and run against every Part D catalog.
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
    heldout_v3_catalog = load_bug_catalog(HELDOUT_V3_BUG_CATALOG_PATH)
    natural_sets = {
        ns.key: (u.load_natural_requirements(root / "data" / ns.csv) if natural else [])
        for ns in NATURAL_SETS
    }
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
    gold_heldout_v3 = run_bug_matrix(gold, spec, heldout_v3_catalog.ids,
                                     catalog=heldout_v3_catalog)
    gold_dets = {
        "in_sample": m.bug_detection(gold_matrix),
        "heldout_v1": m.bug_detection(gold_heldout),
        "heldout_v2": m.bug_detection(gold_heldout_v2),
        "heldout_v3": m.bug_detection(gold_heldout_v3),
    }
    timings["gold_suites"] = time.perf_counter() - t

    # --- LLM-independent: Part D conformance sweep --------------------------------------
    t = time.perf_counter()
    part_d_catalogs = resolve_part_d_catalogs(catalog)
    conformance_dets: dict[str, dict[str, Any]] | None = None
    conformance_tests: list[TestCase] | None = None
    if conformance:
        conformance_report, conformance_tests, conformance_dets = _conformance_block(
            spec, part_d_catalogs)
    else:
        conformance_report = {"status": "not run",
                              "reason": "conformance=False / --skip-conformance given"}
    timings["conformance_sweep"] = time.perf_counter() - t

    # --- per-mode generation + metrics ------------------------------------------------
    store = AuditStore(out / "audit.sqlite")
    llms: list[tuple[str, Any]] = []
    if actual_mode == "ollama" and compare_mock:
        llms.append(("mock", get_llm(Config(llm_mode="mock", retriever=base_cfg.retriever))))
    llms.append((actual_mode, llm))
    common: dict[str, Any] = {
        "spec": spec, "requirements": requirements, "natural_sets": natural_sets,
        "retriever": retriever, "store": store, "engine": chosen_engine, "corpus": corpus,
        "catalog": catalog, "heldout_catalog": heldout_catalog,
        "heldout_v2_catalog": heldout_v2_catalog,
        "heldout_v3_catalog": heldout_v3_catalog, "gold": gold,
        "gold_matrix": gold_matrix, "gold_heldout": gold_heldout,
        "gold_heldout_v2": gold_heldout_v2, "gold_dets": gold_dets, "natural": natural,
        "noise_runs": noise_runs, "timings": timings, "part_d_catalogs": part_d_catalogs,
        "conformance_dets": conformance_dets, "conformance_tests": conformance_tests,
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
        "heldout_v3_catalog_size": len(heldout_v3_catalog.ids),
        "natural_requirements": len(natural_sets["v1"]),
        "natural_requirements_v2": len(natural_sets["v2"]),
        "natural_requirements_v3": len(natural_sets["v3"]),
        "noise_runs_requested": noise_runs,
        "retrieval_comparison": retrieval_comparison,
        "simulator_rules_agreement": agreement,
        "udsoncan_virtual_can": can_result,
        "metric_definitions": {**m.METRIC_DEFINITIONS, **u.UNDERSTANDING_DEFINITIONS,
                               **V2_DEFINITIONS, **PART_D_DEFINITIONS, **PART_D2_DEFINITIONS},
        "precondition_mapping": u.PRECONDITION_MAPPING,
        "modes": modes,
        "conformance": conformance_report,
        "part_d_catalogs": {k: {"label": lbl, "bugs": len(c.ids)}
                            for k, (lbl, c) in part_d_catalogs.items()},
        "provenance_ok": (all(modes[n]["provenance"]["ok"] for n in generated_by_mode)
                          and conformance_report.get("provenance", {"ok": True})["ok"]),
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
    """Render ``<out>/partD/before_after.md``: the frozen Part C baseline vs ``out``'s report."""
    from uds_assistant.eval import before_after as ba

    report = json.loads((out / "eval_report.json").read_text(encoding="utf-8"))
    base = json.loads((baseline or REPO_ROOT / ba.BASELINE_D_PATH).read_text(encoding="utf-8"))
    target = out / "partD" / "before_after.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    sws_text = (REPO_ROOT / "docs" / "SWS_DISAGREEMENTS.md").read_text(encoding="utf-8")
    target.write_text(ba.render_before_after_d(base, report, ba.sws_open_count(sws_text)),
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
                        help="ollama only: run the pipeline over natural v3 (the fresh set) N times in "
                        "total (run 1 feeds the tables, all runs go into the noise check; "
                        "natural v2 / v1 are SEEN and keep a single run; default 1)")
    parser.add_argument("--skip-conformance", action="store_true",
                        help="skip the Part D conformance sweep (for fast test runs)")
    parser.add_argument("--before-after", action="store_true",
                        help="also render <out>/partD/before_after.md (Part C final report vs this run)")
    parser.add_argument("--rerender", action="store_true",
                        help="only re-render eval_report.md from the existing eval_report.json")
    parser.add_argument("--interpretation", default=None,
                        help="with --rerender: a text file stored as the interpretation section")
    return parser


def _det_cell(x: Any) -> str:
    if isinstance(x, dict) and "detected" in x:
        return f"{x['detected']}/{x['bugs']}"
    return str(x)


def _ru_line(ru: dict[str, Any] | None) -> str:
    if ru is None:
        return "n/a"
    tp, te = ru["targets_parsed"], ru["targets_exercised"]
    kinds = ru.get("by_kind", {}).get("parsed", {})
    return (f"parsed exact {tp['exact']}/{ru['requirements']}, P/R/F1 "
            f"{tp['precision']}/{tp['recall']}/{tp['f1']}, exercised F1 {te['f1']}, category "
            f"recall {ru['categories']['micro_recall']}, precondition recall "
            f"{ru['preconditions']['micro_recall']}, fallback/nothing {ru['fallback']['count']}; "
            f"parsed FP by kind [{bd.fp_fn_text(kinds, 'fp')}], FN by kind "
            f"[{bd.fp_fn_text(kinds, 'fn')}]")


def summary_lines(report: dict[str, Any]) -> list[str]:
    """The console summary: FRESH v3 rows first, then the SEEN rows (labelled as such)."""
    out: list[str] = []
    for name in report["modes_run"]:
        block = report["modes"][name]
        v3 = block["heldout_v3_bug_detection"]
        if "bugs" in v3:
            out.append(
                f"mode={name} FRESH held-out v3 bugs ({v3['bugs']}): FULL OUTPUT (headline) "
                f"{_det_cell(v3['full_output'])}; (a) requirement-driven {_det_cell(v3['requirement_driven'])}"
                f"; (b) conformance sweep alone {_det_cell(v3['conformance'])}; gold "
                f"{_det_cell(v3['gold'])}; suite sizes {v3['suite_sizes']}")
        else:
            out.append(f"mode={name} FRESH held-out v3 bugs: {v3.get('status')}")
        ru3 = block["requirement_understanding_v3"].get("splits", {}).get("test3")
        out.append(f"mode={name} FRESH natural v3 (test3) understanding: {_ru_line(ru3)}")
        pipe3 = block["pipeline_natural_v3"]
        if "rejected" in pipe3:
            out.append(f"mode={name} natural v3 rejected planner choices {pipe3['rejected']}: "
                       f"{bd.reason_text(pipe3['rejected_by_reason'])}")
        nc = block["noise_check"]
        if nc.get("status") == "completed":
            sp = nc["summary"]["parsed_f1"]
            out.append(f"mode={name} natural v3 noise check: {len(nc['runs'])} run(s), parsed F1 "
                       f"mean {sp['mean']} (min-max {sp['min']}-{sp['max']})")
        det, held = block["bug_detection"], block["heldout_bug_detection"]
        held2 = block["heldout_v2_bug_detection"]
        ru2 = block["requirement_understanding_v2"].get("splits", {}).get("test2")
        pdd = block.get("part_d_detection", {})
        full2 = _det_cell(_part_d_cell(block, "heldout_v2")) if "status" not in pdd else "not run"
        out.append(
            f"mode={name} SEEN: held-out v2 requirement-driven {held2['generated']['detected']}/"
            f"{held2['generated']['bugs']}, full output {full2}, gold {held2['gold']['detected']}/"
            f"{held2['gold']['bugs']}; natural v2 {_ru_line(ru2)}; held-out v1 generated "
            f"{held['generated']['detected']}/{held['generated']['bugs']}, gold "
            f"{held['gold']['detected']}/{held['gold']['bugs']}; in-sample (tuned on) generated "
            f"{det['generated']['detected']}/{det['generated']['bugs']}, gold "
            f"{det['gold']['detected']}/{det['gold']['bugs']}; tests "
            f"{block['generated_tests']['count']}; byte provenance "
            f"{block['provenance']['passed']}/{block['provenance']['checked']}")
        if "status" not in pdd:
            out.append(f"mode={name} Part D (a) requirement-driven / (b) sweep / (c) full output: "
                       + "; ".join(
                           f"{k} {r['requirement_driven']['detected']}/{r['requirement_driven']['bugs']}"
                           f" / {r['conformance']['detected']}/{r['conformance']['bugs']}"
                           f" / {r['full_output']['detected']}/{r['full_output']['bugs']}"
                           for k, r in pdd.items()))
    return out


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
        conformance=not args.skip_conformance,
    )
    for line in summary_lines(report):
        print(line)
    conf = report["conformance"]
    if conf.get("status") == "completed":
        print(f"conformance sweep (LLM-independent): {conf['tests']} tests, generated in "
              f"{conf['generation_s']} s, bug matrices {conf['bug_matrix_runtime_s']['total']} s, "
              f"byte provenance {conf['provenance']['passed']}/{conf['provenance']['checked']}")
    print(f"actual mode={report['actual_mode']} (requested {report['requested_mode']})")
    run = report["exports"].get("run")
    if run:
        print(f"exported pytest run: {run['summary']}")
    print(f"report: {Path(args.out) / 'eval_report.md'}")
    print(f"freeze ({report['freeze'].get('section')}): all recorded hashes match and are clean = "
          f"{report['freeze']['all_ok']}")
    if args.before_after:
        print(f"before/after: {write_before_after(Path(args.out))}")
    if not report["provenance_ok"]:
        for name in report["modes_run"]:
            for f in provenance_failures(report["modes"][name]["provenance"]):
                print(f"BYTE PROVENANCE FAILURE [{name}] {f['test_id']}: {f['problems']}",
                      file=sys.stderr)
        for f in report["conformance"].get("provenance", {}).get("failures", []):
            print(f"BYTE PROVENANCE FAILURE [conformance] {f['test_id']}: {f['problems']}",
                  file=sys.stderr)
        return PROVENANCE_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
