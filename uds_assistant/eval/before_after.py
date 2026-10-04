"""Before / after tables: baseline numbers frozen in JSON vs. the new report.

Part D (the default, ``--part d``) compares the Part C final report with the new report and
writes ``outputs/partD/before_after.md``; Part C (``--part c``) is the older comparison with
the pre-Part-C baseline.

CLI (render the table from the checked-in baseline and an evaluation report)::

    python -m uds_assistant.eval.before_after [--report outputs/eval_report.json]
        [--out outputs/partD/before_after.md] [--baseline outputs/partD/baseline_before_partD.json]

Re-create the frozen Part D baseline from the Part C final report (re-runnable)::

    python -m uds_assistant.eval.before_after --part d --make-baseline-from-git

Part C notes:

Re-create the frozen baseline from the report of the commit before Part C::

    git show 38aa719:outputs/eval_report.json > old.json
    git show 38aa719:docs/SWS_DISAGREEMENTS.md > old_sws.md
    python -m uds_assistant.eval.before_after --make-baseline old.json --commit 38aa719... \
        --baseline-sws old_sws.md

Nothing here recomputes a metric: every cell is read from the baseline JSON or the new report
JSON (the open SWS disagreements are counted by parsing ``docs/SWS_DISAGREEMENTS.md``). A mode
that did not run in the new report shows "not run".
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = "outputs/partC/baseline_before_partC.json"
MODES = ("mock", "ollama")

FIXED_NOTE = (
    "**Comparability.** (1) The v2 bug set (15) and the natural-v2 set (16) are different "
    "from the v1 sets, so v2 rows are not 'after' values of the v1 rows; there was no v2 "
    "'before'. (2) The v1 numbers are SEEN: the Part C templates were designed against the v1 "
    "held-out misses, so v1 'after' is not independent evidence; only the v2 rows are fresh. "
    "(3) mock is deterministic: its numbers repeat exactly. (4) ollama output varies from run "
    "to run (about +-0.05 F1 on parsed targets), so small ollama differences are noise; see the "
    "noise-check section of the report. (5) Latency and explain calls are wall-clock / call "
    "counts over the 35 seed + natural-v1 requirements in both reports, so they are comparable; "
    "the baseline's explain calls are derived from tests kept (explain was one call per kept "
    "test)."
)


# ------------------------------------------------------------------------------- SWS parsing


def sws_open_count(sws_text: str) -> dict[str, Any]:
    """Count open vs FIXED disagreements in the summary table of ``SWS_DISAGREEMENTS.md``.

    A summary-table row is ``| Dn | ... |``; it is FIXED when the row contains ``**FIXED``.
    """
    open_ids: list[str] = []
    fixed_ids: list[str] = []
    for line in sws_text.splitlines():
        m = re.match(r"\|\s*(D\d+)\s*\|", line)
        if not m:
            continue
        (fixed_ids if "**FIXED" in line else open_ids).append(m.group(1))
    return {"open": len(open_ids), "fixed": len(fixed_ids), "total": len(open_ids) + len(fixed_ids),
            "open_ids": open_ids, "fixed_ids": fixed_ids}


# --------------------------------------------------------------------------- baseline extract


def _det(block: dict[str, Any]) -> dict[str, Any]:
    return {k: {"detected": block[k]["detected"], "bugs": block[k]["bugs"],
                "rate": block[k]["rate"]} for k in ("generated", "gold", "union")}


def _ru(split: dict[str, Any]) -> dict[str, Any]:
    tp, te = split["targets_parsed"], split["targets_exercised"]
    return {
        "requirements": split["requirements"],
        "parsed_exact": tp["exact"], "parsed_precision": tp["precision"],
        "parsed_recall": tp["recall"], "parsed_f1": tp["f1"],
        "parsed_tp": tp["tp"], "parsed_fp": tp["fp"], "parsed_fn": tp["fn"],
        "exercised_exact": te["exact"], "exercised_f1": te["f1"],
        "category_recall_micro": split["categories"]["micro_recall"],
        "category_recall_macro": split["categories"]["macro_recall"],
        "precondition_recall_micro": split["preconditions"]["micro_recall"],
        "precondition_recall_macro": split["preconditions"]["macro_recall"],
        "fallback": split["fallback"]["count"],
    }


def extract_baseline(old: dict[str, Any], sws: dict[str, Any], commit: str) -> dict[str, Any]:
    """Pull the baseline numbers out of the pre-Part-C report (exact values, nothing rounded)."""
    modes: dict[str, Any] = {}
    for name in MODES:
        blk = old["modes"].get(name)
        if not blk or blk.get("status") != "completed":
            continue
        rows = blk["pipeline"]["per_requirement"] + blk["pipeline_natural"]["per_requirement"]
        explain = [r["node_llm_calls"]["explain"] if "node_llm_calls" in r else r["tests"]
                   for r in rows]
        derived = not all("node_llm_calls" in r for r in rows)
        lat = blk["latency"]["per_requirement_wall_s"]["all"]
        modes[name] = {
            "heldout_v1": _det(blk["heldout_bug_detection"]),
            "in_sample": _det(blk["bug_detection"]),
            "understanding_v1_test": _ru(blk["requirement_understanding"]["splits"]["test"]),
            "understanding_v1_dev": _ru(blk["requirement_understanding"]["splits"]["dev"]),
            "rejected": {"seed": blk["pipeline"]["rejected"],
                         "natural_v1": blk["pipeline_natural"]["rejected"],
                         "total": blk["pipeline"]["rejected"] + blk["pipeline_natural"]["rejected"]},
            "latency_per_requirement_s": {"requirements": lat["n"], "mean": lat["mean"],
                                          "p95": lat["p95"], "max": lat["max"]},
            "explain_calls_per_requirement": {
                "derived_from_tests_kept": derived,
                "requirements": len(explain), "total": sum(explain),
                "mean": round(statistics.fmean(explain), 4), "min": min(explain),
                "max": max(explain),
            },
            "tests_kept_seed": blk["pipeline"]["tests_kept"],
        }
    return {
        "source": {
            "commit": commit,
            "file": "outputs/eval_report.json at that commit",
            "report_timestamp": old.get("timestamp"),
            "report_version": old.get("report_version"),
            "actual_mode": old.get("actual_mode"),
            "template_set_version": old.get("template_set_version"),
            "note": ("Frozen once from the commit before Part C; never regenerated from a later "
                     "report. Values are copied exactly."),
        },
        "modes": modes,
        "sws_disagreements": {**sws, "source": "docs/SWS_DISAGREEMENTS.md at that commit"},
    }


# ------------------------------------------------------------------------------ formatting


def _f(v: float | None, nd: int = 3) -> str:
    return "n/a" if v is None else f"{v:.{nd}f}"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _s(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.2f} s"


def _det_txt(d: dict[str, Any]) -> str:
    return " / ".join(f"{d[k]['detected']}/{d[k]['bugs']}" for k in ("generated", "gold", "union"))


def _ru_parts(r: dict[str, Any]) -> dict[str, str]:
    return {
        "exact": f"{r['parsed_exact']}/{r['requirements']}",
        "prf": f"{_f(r['parsed_precision'])} / {_f(r['parsed_recall'])} / {_f(r['parsed_f1'])}",
        "ex_f1": _f(r["exercised_f1"]),
        "cat": _pct(r["category_recall_micro"]),
        "pre": _pct(r["precondition_recall_micro"]),
        "prec_fp": f"{_f(r['parsed_precision'])} / {r['parsed_fp']} FP",
    }


def _after_ru(blk: dict[str, Any], key: str, split: str) -> dict[str, Any] | None:
    ru = blk.get(key, {})
    if "splits" not in ru or split not in ru["splits"]:
        return None
    sp = ru["splits"][split]
    return _ru(sp)


def _after_explain(blk: dict[str, Any]) -> dict[str, Any] | None:
    rows = blk["pipeline"]["per_requirement"] + blk["pipeline_natural"].get("per_requirement", [])
    if not rows or any("node_llm_calls" not in r for r in rows):
        return None
    vals = [int(r["node_llm_calls"].get("explain", 0)) for r in rows]
    return {"mean": statistics.fmean(vals), "min": min(vals), "max": max(vals),
            "requirements": len(vals)}


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return out + ["| " + " | ".join(r) + " |" for r in rows]


def render_before_after(baseline: dict[str, Any], report: dict[str, Any],
                        sws_after: dict[str, Any]) -> str:
    """Render the before / after Markdown from the baseline JSON, the new report and SWS counts."""
    NA_BEFORE = "n/a (no v2 before)"
    NOT_RUN = "not run"
    base = baseline["modes"]
    after: dict[str, dict[str, Any] | None] = {
        m: (report["modes"][m] if report["modes"].get(m, {}).get("status") == "completed"
            else None) for m in MODES}

    def cells(before_fn: Any, after_fn: Any) -> list[str]:
        """mock before | mock after | ollama before | ollama after."""
        out: list[str] = []
        for m in MODES:
            b = base.get(m)
            out.append(NA_BEFORE if before_fn is None else
                       (before_fn(b) if b is not None else NOT_RUN))
            a = after[m]
            out.append(NOT_RUN if a is None else after_fn(a))
        return out

    def ru_row(label: str, part: str, key: str, split: str, base_key: str | None) -> list[str]:
        def after_fn(a: dict[str, Any]) -> str:
            r = _after_ru(a, key, split)
            return "n/a" if r is None else _ru_parts(r)[part]
        before_fn = None if base_key is None else (lambda b: _ru_parts(b[base_key])[part])
        return [label, *cells(before_fn, after_fn)]

    def held(key: str) -> Any:
        return lambda a: _det_txt(_det(a[key]))

    def part_d(a: dict[str, Any]) -> str:
        r = (a.get("part_d_detection") or {}).get("heldout_v2")
        if not isinstance(r, dict):
            return "n/a (no Part D rows in this report)"
        b, c = r["conformance"], r["full_output"]
        return f"{b['detected']}/{b['bugs']} / {c['detected']}/{c['bugs']}"

    rows: list[list[str]] = [
        ["**Held-out v2, FRESH (15 bugs): generated / gold / union**",
         *cells(None, held("heldout_v2_bug_detection"))],
        ["Part D, held-out v2 (SEEN after Part C): conformance sweep alone / full output",
         *cells(None, part_d)],
        ["Held-out v1, SEEN (12 bugs): generated / gold / union",
         *cells(lambda b: _det_txt(b["heldout_v1"]), held("heldout_bug_detection"))],
        ["In-sample (26 bugs): generated / gold / union",
         *cells(lambda b: _det_txt(b["in_sample"]), held("bug_detection"))],
        ru_row("**Natural v2, FRESH (test2, n=16): parsed exact**", "exact",
               "requirement_understanding_v2", "test2", None),
        ru_row("Natural v2, FRESH: parsed P / R / F1", "prf",
               "requirement_understanding_v2", "test2", None),
        ru_row("Natural v2, FRESH: exercised F1", "ex_f1",
               "requirement_understanding_v2", "test2", None),
        ru_row("Natural v2, FRESH: category recall (micro)", "cat",
               "requirement_understanding_v2", "test2", None),
        ru_row("Natural v2, FRESH: precondition recall (micro)", "pre",
               "requirement_understanding_v2", "test2", None),
        ru_row("Natural v1 test split, SEEN (n=12): parsed exact", "exact",
               "requirement_understanding", "test", "understanding_v1_test"),
        ru_row("Natural v1 test split, SEEN: parsed P / R / F1", "prf",
               "requirement_understanding", "test", "understanding_v1_test"),
        ru_row("Natural v1 test split, SEEN: exercised F1", "ex_f1",
               "requirement_understanding", "test", "understanding_v1_test"),
        ru_row("Natural v1 test split, SEEN: category recall (micro)", "cat",
               "requirement_understanding", "test", "understanding_v1_test"),
        ru_row("Natural v1 test split, SEEN: precondition recall (micro)", "pre",
               "requirement_understanding", "test", "understanding_v1_test"),
        ru_row("Parsed precision / false positives, v1 test split (SEEN)", "prec_fp",
               "requirement_understanding", "test", "understanding_v1_test"),
        ru_row("**Parsed precision / false positives, v2 (FRESH)**", "prec_fp",
               "requirement_understanding_v2", "test2", None),
    ]

    def rej_after(a: dict[str, Any]) -> str:
        v1 = a["pipeline"]["rejected"] + a["pipeline_natural"].get("rejected", 0)
        return str(v1)

    def rej_v2(a: dict[str, Any]) -> str:
        v2 = a.get("pipeline_natural_v2", {})
        return str(v2["rejected"]) if "rejected" in v2 else "n/a"

    rows.append(["Rejected planner choices (15 seed + 20 natural v1)",
                 *cells(lambda b: str(b["rejected"]["total"]), rej_after)])
    rows.append(["Rejected planner choices, natural v2 (16, FRESH)", *cells(None, rej_v2)])

    def lat_before(b: dict[str, Any]) -> str:
        v = b["latency_per_requirement_s"]
        return f"{_s(v['mean'])} / {_s(v['p95'])}"

    def lat_after(a: dict[str, Any]) -> str:
        v = a["latency"]["per_requirement_wall_s"]["all"]
        return f"{_s(v['mean'])} / {_s(v['p95'])}"

    rows.append(["Latency per requirement, mean / p95 (35 requirements)",
                 *cells(lat_before, lat_after)])

    def exp_before(b: dict[str, Any]) -> str:
        e = b["explain_calls_per_requirement"]
        tag = " (derived from tests kept)" if e["derived_from_tests_kept"] else ""
        return f"{e['mean']:.2f} ({e['min']}-{e['max']}){tag}"

    def exp_after(a: dict[str, Any]) -> str:
        e = _after_explain(a)
        return "n/a" if e is None else f"{e['mean']:.2f} ({e['min']}-{e['max']})"

    rows.append(["Explain LLM calls per requirement, mean (min-max)",
                 *cells(exp_before, exp_after)])
    sws_before = baseline["sws_disagreements"]["open"]
    rows.append(["SWS disagreements open",
                 str(sws_before), str(sws_after["open"]), str(sws_before), str(sws_after["open"])])

    lines = [
        "# Part C: before / after",
        "",
        (f"Before = frozen baseline `{BASELINE_PATH}` (commit "
         f"`{baseline['source']['commit']}`, report {baseline['source']['report_timestamp']}). "
         f"After = `eval_report.json` generated {report.get('timestamp')} (git "
         f"`{report.get('git', {}).get('commit')}`, template set "
         f"`{report.get('template_set_version')}`)."),
        "",
    ]
    lines += _table(["Metric", "mock before", "mock after", "ollama before", "ollama after"], rows)
    lines += [
        "",
        (f"SWS disagreements: counted from `docs/SWS_DISAGREEMENTS.md`: open "
         f"{', '.join(sws_after['open_ids']) or '-'} ({sws_after['open']}), FIXED "
         f"{', '.join(sws_after['fixed_ids']) or '-'} ({sws_after['fixed']}); baseline open "
         f"{', '.join(baseline['sws_disagreements']['open_ids']) or '-'} ({sws_before})."),
        "",
        FIXED_NOTE,
        "",
    ]
    if after["ollama"] is None:
        lines += [("The ollama 'after' cells are \"not run\": this report has no completed "
                   "ollama mode."), ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------------ Part D
#
# Part D compares the committed Part C final report (before) with the new report (after).
# Every cell is derived by :func:`summarise_mode` from a report's per-mode block, the same
# function for both sides, so "before" and "after" use identical definitions (false
# positives by kind and rejected choices by reason are re-derived from each report's
# per-requirement rows; the Part C report predates the ``by_kind`` fields).

BASELINE_D_PATH = "outputs/partD/baseline_before_partD.json"
PART_C_FINAL_COMMIT = "942f43898de38361f0797c5009e3cfcfd6f042c0"
"""The Part C final report: ``git show <commit>:outputs/eval_report.json``."""

FIXED_NOTE_D = (
    "**Comparability.** (1) The v3 bug set (15) and the natural-v3 set (16) are fresh and "
    "different from the v1 and v2 sets, so the v3 rows have only an 'after' value; they are not "
    "'after' values of the v2 rows. (2) v1 and v2 (bugs and natural requirements) are SEEN: "
    "their Part C results were known when Part D was designed, so the v2 before/after rows are "
    "context, not independent evidence; only the v3 rows are. (3) mock is deterministic: its "
    "numbers repeat exactly. (4) ollama output varies from run to run, so small ollama "
    "differences are noise; the v3 noise check (mean and min-max over all runs) is in the "
    "report. (5) The conformance sweep is LLM-independent: it is identical in every mode, so "
    "'full output' differs between modes only through the requirement-driven part. (6) Part C "
    "had no sweep, so its 'full output' equals its requirement-driven suite. (7) Latency, "
    "explain calls and the rejected-choice rows over the 35 seed + natural-v1 requirements use "
    "the same requirements in both reports; the baseline's explain calls are derived from "
    "tests kept only if the report lacks per-node LLM call counts."
)


def _by_kind_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    from uds_assistant.eval import breakdown as bd

    kinds = bd.by_kind(rows)["parsed"]
    return {"fp": {k: v["fp"] for k, v in kinds.items()},
            "fn": {k: v["fn"] for k, v in kinds.items()}}


def _ru_d(blk: dict[str, Any], key: str, split: str) -> dict[str, Any] | None:
    ru = blk.get(key, {})
    if "splits" not in ru or split not in ru["splits"]:
        return None
    out = _ru(ru["splits"][split])
    rows = [r for r in ru["per_requirement"] if r["split"] == split]
    out["by_kind"] = _by_kind_rows(rows)
    return out


def _rejections(blk: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any] | None:
    from uds_assistant.eval import breakdown as bd

    reasons: list[str] = []
    for key in keys:
        pipe = blk.get(key, {})
        if "per_requirement" not in pipe:
            return None
        reasons += [x for r in pipe["per_requirement"] for x in r.get("rejected_reasons", [])]
    by_reason = bd.rejected_by_reason(reasons)
    return {"total": sum(by_reason.values()), "by_reason": by_reason}


def _full_output(blk: dict[str, Any], key: str) -> dict[str, Any] | None:
    row = (blk.get("part_d_detection") or {}).get(key)
    if not isinstance(row, dict):
        return None
    return {"detected": row["full_output"]["detected"], "bugs": row["full_output"]["bugs"]}


def summarise_mode(blk: dict[str, Any]) -> dict[str, Any]:
    """The Part D comparison values of one completed mode block (Part C or Part D report)."""
    v2 = blk["heldout_v2_bug_detection"]
    rows = (blk["pipeline"]["per_requirement"]
            + blk.get("pipeline_natural", {}).get("per_requirement", []))
    explain = [r["node_llm_calls"]["explain"] if "node_llm_calls" in r else r["tests"]
               for r in rows]
    sizes = blk.get("suite_sizes") or {}
    req_n = blk["generated_tests"]["count"]
    return {
        "heldout_v2": {
            "requirement_driven": {"detected": v2["generated"]["detected"],
                                   "bugs": v2["generated"]["bugs"]},
            "gold": {"detected": v2["gold"]["detected"], "bugs": v2["gold"]["bugs"]},
            "union": {"detected": v2["union"]["detected"], "bugs": v2["union"]["bugs"]},
            "full_output": _full_output(blk, "heldout_v2"),
        },
        "understanding_v2": _ru_d(blk, "requirement_understanding_v2", "test2"),
        "understanding_v1_test": _ru_d(blk, "requirement_understanding", "test"),
        "rejected": {
            "seed_and_natural_v1": _rejections(blk, ("pipeline", "pipeline_natural")),
            "natural_v2": _rejections(blk, ("pipeline_natural_v2",)),
        },
        "latency_per_requirement_s": {
            k: blk["latency"]["per_requirement_wall_s"]["all"][k] for k in ("n", "mean", "p95")},
        "explain_calls_per_requirement": {
            "derived_from_tests_kept": not all("node_llm_calls" in r for r in rows),
            "requirements": len(explain), "mean": round(statistics.fmean(explain), 4),
            "min": min(explain), "max": max(explain),
        },
        "suite_sizes": {"requirement_driven": sizes.get("requirement_driven", req_n),
                        "full_output": sizes.get("full_output")},
    }


def extract_baseline_d(old: dict[str, Any], sws: dict[str, Any], commit: str) -> dict[str, Any]:
    """Pull the Part D baseline values out of the Part C final report (exact values)."""
    modes = {name: summarise_mode(old["modes"][name]) for name in MODES
             if old["modes"].get(name, {}).get("status") == "completed"}
    return {
        "source": {
            "commit": commit,
            "file": "outputs/eval_report.json at that commit (the Part C final report)",
            "report_timestamp": old.get("timestamp"),
            "report_version": old.get("report_version"),
            "actual_mode": old.get("actual_mode"),
            "template_set_version": old.get("template_set_version"),
            "note": ("Frozen once from the Part C final report; never regenerated from a later "
                     "report. Values are copied exactly; false positives by kind and rejections "
                     "by reason are derived from that report's per-requirement rows."),
        },
        "modes": modes,
        "sws_disagreements": {**sws, "source": "docs/SWS_DISAGREEMENTS.md at that commit"},
    }


def _git_show(root: Path, commit: str, path: str) -> str:
    import subprocess

    proc = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=root, capture_output=True,
                          text=True, encoding="utf-8", check=True)
    return proc.stdout


def extract_baseline_d_from_git(root: Path = REPO_ROOT,
                                commit: str = PART_C_FINAL_COMMIT) -> dict[str, Any]:
    """Re-extract the Part D baseline from git (the report and the SWS doc at ``commit``)."""
    old = json.loads(_git_show(root, commit, "outputs/eval_report.json"))
    sws = sws_open_count(_git_show(root, commit, "docs/SWS_DISAGREEMENTS.md"))
    return extract_baseline_d(old, sws, commit)


def _frac_d(d: dict[str, Any] | None) -> str:
    return "n/a" if not d else f"{d['detected']}/{d['bugs']}"


def _kinds_txt(counts: dict[str, int] | None) -> str:
    if counts is None:
        return "n/a"
    parts = [f"{k} {v}" for k, v in counts.items() if v]
    return ", ".join(parts) or "none"


def _reasons_txt(r: dict[str, Any] | None) -> str:
    from uds_assistant.eval import breakdown as bd

    if r is None:
        return "n/a"
    return f"{r['total']} ({bd.reason_text(r['by_reason'])})"


def _v3_after(blk: dict[str, Any]) -> dict[str, Any]:
    """The fresh v3 values of one completed mode block of a version 5 report."""
    v3 = blk.get("heldout_v3_bug_detection", {})
    out: dict[str, Any] = {"present": "bugs" in v3}
    if "bugs" in v3:
        def cell(x: Any) -> str:
            return (f"{x['detected']}/{x['bugs']}" if isinstance(x, dict)
                    else f"n/a ({x})")
        out.update({"full": cell(v3["full_output"]), "req": cell(v3["requirement_driven"]),
                    "conf": cell(v3["conformance"]), "gold": cell(v3["gold"]),
                    "sizes": v3["suite_sizes"]})
    out["ru"] = _ru_d(blk, "requirement_understanding_v3", "test3")
    out["rejected"] = _rejections(blk, ("pipeline_natural_v3",))
    nc = blk.get("noise_check", {})
    out["noise"] = nc if nc.get("status") == "completed" else None
    return out


def render_before_after_d(baseline: dict[str, Any], report: dict[str, Any],
                          sws_after: dict[str, Any]) -> str:
    """Render ``partD/before_after.md``: Part C (before) vs this report (after)."""
    NOT_RUN = "not run"
    NA = "n/a"
    base = baseline["modes"]
    done = {m: report["modes"].get(m, {}).get("status") == "completed" for m in MODES}
    after = {m: summarise_mode(report["modes"][m]) if done[m] else None for m in MODES}
    v3 = {m: _v3_after(report["modes"][m]) if done[m] else None for m in MODES}

    def four(before_fn: Any, after_fn: Any) -> list[str]:
        out: list[str] = []
        for m in MODES:
            b, a = base.get(m), after[m]
            out.append(NA if before_fn is None else (before_fn(b) if b is not None else NOT_RUN))
            out.append(NOT_RUN if a is None else after_fn(a))
        return out

    def two(fn: Any) -> list[str]:
        return [NOT_RUN if v3[m] is None else fn(v3[m]) for m in MODES]

    lines = [
        "# Part D: before / after",
        "",
        (f"Before = frozen baseline `{BASELINE_D_PATH}` (the Part C final report, commit "
         f"`{baseline['source']['commit']}`, report {baseline['source']['report_timestamp']}). "
         f"After = `eval_report.json` generated {report.get('timestamp')} (git "
         f"`{report.get('git', {}).get('commit')}`, report version "
         f"{report.get('report_version')}, template set `{report.get('template_set_version')}`)."),
        "",
        "## (i) FRESH v3 rows (written blind after the Part D freeze; after only)",
        "",
    ]

    def ru3(fn: Any) -> Any:
        return lambda x: NA if x["ru"] is None else fn(x["ru"])

    def sized(x: dict[str, Any]) -> str:
        s = x["sizes"]
        return (f"{s['requirement_driven']} requirement-driven, "
                f"{s['conformance'] if s['conformance'] is not None else NA} sweep, "
                f"{s['full_output'] if s['full_output'] is not None else NA} full output")

    def noise(x: dict[str, Any]) -> str:
        nc = x["noise"]
        if nc is None:
            return NA
        sp = nc["summary"]["parsed_f1"]
        return (f"{len(nc['runs'])} run(s), parsed F1 mean {_f(sp['mean'])} "
                f"(min-max {_f(sp['min'])}-{_f(sp['max'])})")

    def present(fn: Any) -> Any:
        return lambda x: fn(x) if x["present"] else NA

    rows3 = [
        ["**Held-out v3 bugs (15): FULL OUTPUT = requirement-driven + sweep (headline)**",
         *two(present(lambda x: f"**{x['full']}**"))],
        ["(a) requirement-driven only (comparable with Part C)", *two(present(lambda x: x["req"]))],
        ["(b) conformance sweep alone (LLM-independent)", *two(present(lambda x: x["conf"]))],
        ["(d) gold (LLM-independent)", *two(present(lambda x: x["gold"]))],
        ["Suite sizes (tests)", *two(present(sized))],
        ["**Natural v3 (test3, n=16): parsed exact**",
         *two(ru3(lambda r: f"{r['parsed_exact']}/{r['requirements']}"))],
        ["Natural v3: parsed P / R / F1",
         *two(ru3(lambda r: f"{_f(r['parsed_precision'])} / {_f(r['parsed_recall'])} / "
                            f"{_f(r['parsed_f1'])}"))],
        ["Natural v3: exercised F1", *two(ru3(lambda r: _f(r["exercised_f1"])))],
        ["Natural v3: category recall (micro)", *two(ru3(lambda r: _pct(r["category_recall_micro"])))],
        ["Natural v3: precondition recall (micro)",
         *two(ru3(lambda r: _pct(r["precondition_recall_micro"])))],
        ["Natural v3: fallback / nothing generated", *two(ru3(lambda r: str(r["fallback"])))],
        ["Natural v3: parsed false positives by kind",
         *two(ru3(lambda r: _kinds_txt(r["by_kind"]["fp"])))],
        ["Natural v3: parsed false negatives by kind",
         *two(ru3(lambda r: _kinds_txt(r["by_kind"]["fn"])))],
        ["Natural v3: rejected planner choices by reason",
         *two(lambda x: _reasons_txt(x["rejected"]))],
        ["Natural v3: noise check", *two(noise)],
    ]
    lines += _table(["Metric", "mock after", "ollama after"], rows3)

    lines += ["", "## (ii) SEEN v2 rows, before / after (context only: v2 is seen)", ""]

    def ru_cell(key: str, part: str) -> tuple[Any, Any]:
        def get(d: dict[str, Any]) -> str:
            r = d[key]
            return NA if r is None else _ru_parts(r)[part]
        return get, get

    seen_rows: list[list[str]] = [
        ["Held-out v2 bugs (15, SEEN): requirement-driven (generated)",
         *four(lambda b: _frac_d(b["heldout_v2"]["requirement_driven"]),
               lambda a: _frac_d(a["heldout_v2"]["requirement_driven"]))],
        ["Held-out v2 bugs (SEEN): FULL OUTPUT (Part C had no sweep: = requirement-driven)",
         *four(lambda b: _frac_d(b["heldout_v2"]["requirement_driven"]),
               lambda a: _frac_d(a["heldout_v2"]["full_output"]))],
        ["Held-out v2 bugs (SEEN): gold",
         *four(lambda b: _frac_d(b["heldout_v2"]["gold"]),
               lambda a: _frac_d(a["heldout_v2"]["gold"]))],
    ]
    for label, part in (("parsed exact", "exact"), ("parsed P / R / F1", "prf"),
                        ("exercised F1", "ex_f1"), ("category recall (micro)", "cat"),
                        ("precondition recall (micro)", "pre")):
        g, _ = ru_cell("understanding_v2", part)
        seen_rows.append([f"Natural v2 (test2, n=16, SEEN): {label}", *four(g, g)])

    def kinds_cell(key: str, which: str) -> Any:
        return lambda d: NA if d[key] is None else _kinds_txt(d[key]["by_kind"][which])

    seen_rows.append(["Natural v2 (SEEN): parsed false positives by kind",
                      *four(kinds_cell("understanding_v2", "fp"),
                            kinds_cell("understanding_v2", "fp"))])
    seen_rows.append(["Natural v2 (SEEN): parsed false negatives by kind",
                      *four(kinds_cell("understanding_v2", "fn"),
                            kinds_cell("understanding_v2", "fn"))])
    lines += _table(["Metric", "mock before", "mock after", "ollama before", "ollama after"],
                    seen_rows)

    lines += ["", "## (iii) Rejected planner choices by reason", ""]

    def rej(key: str) -> Any:
        return lambda d: _reasons_txt(d["rejected"][key])

    lines += _table(["Set", "mock before", "mock after", "ollama before", "ollama after"], [
        ["15 seed + 20 natural v1 requirements (SEEN)",
         *four(rej("seed_and_natural_v1"), rej("seed_and_natural_v1"))],
        ["Natural v2 (16, SEEN)", *four(rej("natural_v2"), rej("natural_v2"))],
    ])
    lines += ["", "Natural v3 (FRESH, after only): "
              + "; ".join(f"{m}: {NOT_RUN if v3[m] is None else _reasons_txt(v3[m]['rejected'])}"
                          for m in MODES), ""]

    lines += ["## (iv) Parsed false positives by kind", ""]
    fp_rows = [
        ["Natural v1 test split (n=12, SEEN)",
         *four(kinds_cell("understanding_v1_test", "fp"), kinds_cell("understanding_v1_test", "fp"))],
        ["Natural v2 (n=16, SEEN)",
         *four(kinds_cell("understanding_v2", "fp"), kinds_cell("understanding_v2", "fp"))],
    ]
    lines += _table(["Set", "mock before", "mock after", "ollama before", "ollama after"], fp_rows)
    lines += ["", "Natural v3 (FRESH, after only): "
              + "; ".join(f"{m}: " + (NOT_RUN if v3[m] is None else
                                      (NA if v3[m]["ru"] is None
                                       else _kinds_txt(v3[m]["ru"]["by_kind"]["fp"])))
                          for m in MODES), ""]

    def lat(d: dict[str, Any]) -> str:
        v = d["latency_per_requirement_s"]
        return f"{_s(v['mean'])} / {_s(v['p95'])}"

    def exp(d: dict[str, Any]) -> str:
        e = d["explain_calls_per_requirement"]
        tag = " (derived from tests kept)" if e["derived_from_tests_kept"] else ""
        return f"{e['mean']:.2f} ({e['min']}-{e['max']}){tag}"

    sws_before = baseline["sws_disagreements"]["open"]
    lines += ["", "## (v) Latency and explain calls (35 seed + natural-v1 requirements)", ""]
    lines += _table(["Metric", "mock before", "mock after", "ollama before", "ollama after"], [
        ["Latency per requirement, mean / p95", *four(lat, lat)],
        ["Explain LLM calls per requirement, mean (min-max)", *four(exp, exp)],
    ])
    lines += ["", "## (vi) SWS disagreements", ""]
    lines += _table(["Metric", "before", "after"], [
        ["SWS disagreements open", str(sws_before), str(sws_after["open"])]])
    lines += [
        "",
        (f"Counted from `docs/SWS_DISAGREEMENTS.md`: open {', '.join(sws_after['open_ids']) or '-'}"
         f" ({sws_after['open']}), FIXED {', '.join(sws_after['fixed_ids']) or '-'} "
         f"({sws_after['fixed']}); baseline open "
         f"{', '.join(baseline['sws_disagreements']['open_ids']) or '-'} ({sws_before})."),
        "",
        "## (vii) Test counts: requirement-driven suite vs full output",
        "",
    ]

    def sizes(d: dict[str, Any]) -> str:
        s = d["suite_sizes"]
        full = s["full_output"] if s["full_output"] is not None else s["requirement_driven"]
        return f"{s['requirement_driven']} requirement-driven / {full} full output"

    lines += _table(["Suite (tests)", "mock before", "mock after", "ollama before", "ollama after"],
                    [["requirement-driven / full output (Part C: no sweep)", *four(sizes, sizes)]])
    lines += ["", FIXED_NOTE_D, ""]
    if not done["ollama"]:
        lines += [("The ollama 'after' cells are \"not run\": this report has no completed "
                   "ollama mode."), ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    """CLI argument parser."""
    p = argparse.ArgumentParser(prog="python -m uds_assistant.eval.before_after")
    p.add_argument("--part", choices=("c", "d"), default="d",
                   help="d (default): Part C final report vs now; c: pre-Part-C baseline vs Part C")
    p.add_argument("--report", default=str(REPO_ROOT / "outputs" / "eval_report.json"))
    p.add_argument("--out", default=None,
                   help="default outputs/partD/before_after.md (outputs/partC/... with --part c)")
    p.add_argument("--baseline", default=None,
                   help=f"default {BASELINE_D_PATH} ({BASELINE_PATH} with --part c)")
    p.add_argument("--sws-doc", default=str(REPO_ROOT / "docs" / "SWS_DISAGREEMENTS.md"),
                   help="SWS disagreements doc whose FIXED/open rows are counted for 'after'")
    p.add_argument("--make-baseline", default=None, metavar="OLD_REPORT_JSON",
                   help="write --baseline from this old report instead of rendering")
    p.add_argument("--make-baseline-from-git", action="store_true",
                   help="--part d: write --baseline from `git show <--commit>:outputs/"
                   "eval_report.json` and the SWS doc at that commit")
    p.add_argument("--commit", default=None,
                   help="with --make-baseline*: the commit the old report comes from (default: "
                   "the pre-Part-C commit for --part c, the Part C final report for --part d)")
    p.add_argument("--baseline-sws", default=None,
                   help="with --make-baseline: the SWS doc at that commit")
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    part_d = args.part == "d"
    baseline_path = Path(args.baseline or REPO_ROOT / (BASELINE_D_PATH if part_d else BASELINE_PATH))
    if args.make_baseline_from_git or args.make_baseline:
        if part_d and args.make_baseline_from_git:
            data = extract_baseline_d_from_git(REPO_ROOT, args.commit or PART_C_FINAL_COMMIT)
        else:
            if not args.baseline_sws:
                raise SystemExit("--make-baseline needs --baseline-sws (the SWS doc at that commit)")
            old = json.loads(Path(args.make_baseline).read_text(encoding="utf-8"))
            sws = sws_open_count(Path(args.baseline_sws).read_text(encoding="utf-8"))
            if part_d:
                data = extract_baseline_d(old, sws, args.commit or PART_C_FINAL_COMMIT)
            else:
                data = extract_baseline(
                    old, sws, args.commit or "38aa7197d0a330f6f2f8f550fb3796ea5ae9db20")
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {baseline_path}")
        return 0
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    sws = sws_open_count(Path(args.sws_doc).read_text(encoding="utf-8"))
    out = Path(args.out or REPO_ROOT / "outputs" / ("partD" if part_d else "partC")
               / "before_after.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    render = render_before_after_d if part_d else render_before_after
    out.write_text(render(baseline, report, sws), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
