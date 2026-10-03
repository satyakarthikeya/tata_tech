"""Before / after table for Part C: baseline numbers frozen in JSON vs. the new report.

CLI (render the table from the checked-in baseline and an evaluation report)::

    python -m uds_assistant.eval.before_after [--report outputs/eval_report.json]
        [--out outputs/partC/before_after.md] [--baseline outputs/partC/baseline_before_partC.json]

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

    rows: list[list[str]] = [
        ["**Held-out v2, FRESH (15 bugs): generated / gold / union**",
         *cells(None, held("heldout_v2_bug_detection"))],
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


# --------------------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    """CLI argument parser."""
    p = argparse.ArgumentParser(prog="python -m uds_assistant.eval.before_after")
    p.add_argument("--report", default=str(REPO_ROOT / "outputs" / "eval_report.json"))
    p.add_argument("--out", default=str(REPO_ROOT / "outputs" / "partC" / "before_after.md"))
    p.add_argument("--baseline", default=str(REPO_ROOT / BASELINE_PATH))
    p.add_argument("--sws-doc", default=str(REPO_ROOT / "docs" / "SWS_DISAGREEMENTS.md"),
                   help="SWS disagreements doc whose FIXED/open rows are counted for 'after'")
    p.add_argument("--make-baseline", default=None, metavar="OLD_REPORT_JSON",
                   help="write --baseline from this pre-Part-C report instead of rendering")
    p.add_argument("--commit", default="38aa7197d0a330f6f2f8f550fb3796ea5ae9db20",
                   help="with --make-baseline: the commit the old report comes from")
    p.add_argument("--baseline-sws", default=None,
                   help="with --make-baseline: the SWS doc at that commit")
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    if args.make_baseline:
        if not args.baseline_sws:
            raise SystemExit("--make-baseline needs --baseline-sws (the SWS doc at that commit)")
        old = json.loads(Path(args.make_baseline).read_text(encoding="utf-8"))
        sws = sws_open_count(Path(args.baseline_sws).read_text(encoding="utf-8"))
        data = extract_baseline(old, sws, args.commit)
        Path(args.baseline).parent.mkdir(parents=True, exist_ok=True)
        Path(args.baseline).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.baseline}")
        return 0
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    sws = sws_open_count(Path(args.sws_doc).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_before_after(baseline, report, sws), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
