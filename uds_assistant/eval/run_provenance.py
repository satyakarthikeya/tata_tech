"""Run provenance for ``eval_report.json`` / ``eval_report.md`` (Part E2).

Every data source in the report (the main evaluation, the diagnostic Q&A run, the tool-side
timing run, and the historical Part C / Part D before-after tables) is labelled with its own
date and git hash. Nothing here recomputes a metric: values are copied from the existing JSON
files, and a missing input is recorded as absent, never invented.

Keys added to ``eval_report.json`` by :func:`attach_extras`:

- ``provenance``: ``{"main_eval", "qa", "timing"}`` run refs (each ``{label, source, timestamp,
  date, git_commit, git_short, dirty, note}`` or ``None``) plus ``"history"`` run refs.
- ``qa``: ``{"run", "source", "modes": {mode: summary}}`` (summary = scores without per-question rows).
- ``timing``: ``{"run", "source", "repeats", "requirements", "modes": {mode: {...}}}``.
- ``history``: ``{"part_c" | "part_d": {"label": "historical", "title", "source", "run_hashes",
  "timestamps", "text"}}``.
- ``headline_cards``: UI-ready cards, each with ``id``, ``label``, ``run`` (a key of
  ``provenance``), ``run_date``, ``git_short``, ``values`` per mode (numbers) and ``display``.
- ``success_metrics``: the five case-study metrics, each with ``definition``, ``how_measured``,
  ``status``, per-mode ``values`` and its ``run``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MODES = ("mock", "ollama")
_HASH = re.compile(r"\b[0-9a-f]{40}\b")
_TS = re.compile(r"\b\d{4}-\d{2}-\d{2}T[\d:.]+\+00:00")


def short_hash(value: str | None) -> str:
    """Seven-character hash; a ``+dirty`` suffix is kept."""
    if not value:
        return "n/a"
    dirty = value.endswith("+dirty")
    return value.replace("+dirty", "")[:7] + ("+dirty" if dirty else "")


def _ref(label: str, source: str, timestamp: str | None, commit: str | None,
         dirty: bool | None, note: str = "") -> dict[str, Any]:
    clean = (commit or "").replace("+dirty", "") or None
    if commit and commit.endswith("+dirty"):
        dirty = True
    return {
        "label": label, "source": source, "timestamp": timestamp,
        "date": (timestamp or "")[:10] or None, "git_commit": clean,
        "git_short": short_hash(clean), "dirty": dirty, "note": note,
    }


def run_tag(ref: dict[str, Any] | None) -> str:
    """Text such as ``run 2026-10-04 · git `1f0c293` `` for a section header."""
    if not ref:
        return "run: not available"
    dirty = ", uncommitted changes" if ref.get("dirty") else ""
    return f"run {ref.get('date') or 'n/a'} · git `{ref.get('git_short')}`{dirty}"


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _rel(path: Path, out: Path) -> str:
    try:
        return str(path.relative_to(out.parent)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def qa_summary(qa: dict[str, Any], source: str) -> dict[str, Any]:
    """Per-mode Q&A scores (no per-question rows) plus the run ref."""
    ref = _ref("Diagnostic Q&A run", source, qa.get("timestamp"), qa.get("git_hash"), None,
               "dirty flag not recorded in the Q&A json (the tree was checked clean before the run)")
    modes = {m: {k: v for k, v in r.items() if k != "rows"}
             for m, r in qa.get("results", {}).items()}
    return {"run": ref, "source": source, "modes": modes}


def timing_summary(tm: dict[str, Any], source: str) -> dict[str, Any]:
    """Per-mode tool-side timing summary: mean of per-requirement means, min and max of them."""
    ref = _ref("Tool-side timing run", source, tm.get("timestamp"), tm.get("git_hash"), None,
               "dirty flag not recorded in the timing json")
    modes: dict[str, Any] = {}
    for r in tm.get("results", []):
        m = modes.setdefault(r["mode"], {"llm_used": r.get("llm_used"), "per_requirement": {}})
        m["per_requirement"][r["requirement"]] = {
            "mean_s": r["total_s"]["mean"], "min_s": r["total_s"]["min"],
            "max_s": r["total_s"]["max"], "tests_generated": r["tests_generated"],
            "stages_mean_s": {k: v["mean"] for k, v in r.get("stages_s", {}).items()},
        }
    for m in modes.values():
        means = [v["mean_s"] for v in m["per_requirement"].values()]
        m["requirements"] = len(means)
        m["mean_of_requirement_means_s"] = round(sum(means) / len(means), 3)
        m["min_requirement_mean_s"] = min(means)
        m["max_requirement_mean_s"] = max(means)
        m["tests_generated_total"] = sum(v["tests_generated"] for v in m["per_requirement"].values())
        m["seconds_per_test_mean"] = round(
            sum(v["mean_s"] for v in m["per_requirement"].values()) / m["tests_generated_total"], 3)
    return {"run": ref, "source": source, "repeats": tm.get("repeats"),
            "requirements": tm.get("requirements"), "skipped_modes": tm.get("skipped_modes"),
            "modes": modes}


def history_entry(path: Path, title: str, out: Path) -> dict[str, Any] | None:
    """One historical before/after table, stored with the run hashes found in its own text."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    hashes: list[str] = []
    for h in _HASH.findall(text):
        if h[:7] not in hashes:
            hashes.append(h[:7])
    stamps: list[str] = []
    for t in _TS.findall(text):
        if t not in stamps:
            stamps.append(t)
    return {"label": "historical", "title": title, "source": _rel(path, out),
            "run_hashes": hashes, "timestamps": stamps, "text": text}


def _frac(x: dict[str, Any]) -> str:
    return f"{x['detected']}/{x['bugs']} ({x['rate'] * 100:.1f}%)"


def headline_cards(report: dict[str, Any], prov: dict[str, Any], qa: dict[str, Any] | None,
                   timing: dict[str, Any] | None) -> list[dict[str, Any]]:
    """UI-ready headline cards copied from existing report numbers (nothing recomputed)."""
    h = report["headline"]
    main = prov["main_eval"]
    cards: list[dict[str, Any]] = []

    def add(cid: str, label: str, run_key: str, ref: dict[str, Any] | None,
            values: dict[str, Any], display: dict[str, str]) -> None:
        cards.append({"id": cid, "label": label, "run": run_key,
                      "run_date": (ref or {}).get("date"), "git_short": (ref or {}).get("git_short"),
                      "values": values, "display": display})

    bugs = report["modes"]
    v3: dict[str, dict[str, Any]] = {}
    for m in MODES:
        blk = bugs.get(m, {}).get("heldout_v3_bug_detection")
        pdd = bugs.get(m, {}).get("part_d_detection", {}).get("heldout_v3")
        if isinstance(pdd, dict):
            v3[m] = {"full_output": pdd["full_output"], "requirement_driven": pdd["requirement_driven"],
                     "conformance": pdd["conformance"], "gold": pdd.get("gold")}
        elif isinstance(blk, dict) and "full_output" in blk:
            v3[m] = blk
    for key, label in (("full_output", "Fresh v3 bugs found (full output)"),
                       ("requirement_driven", "Fresh v3 bugs found (generated, requirement-driven)"),
                       ("conformance", "Fresh v3 bugs found (conformance sweep)"),
                       ("gold", "Fresh v3 bugs found (gold tests)")):
        vals = {m: v3[m][key] for m in v3 if isinstance(v3[m].get(key), dict)}
        if vals:
            add(f"v3_bugs_{key}", label, "main_eval", main, vals,
                {m: _frac(x) for m, x in vals.items()})
    ru = h.get("requirement_understanding_v3", {})
    for key, label, fmt in (("target_f1_parsed", "Natural v3: parsed F1", "{:.3f}"),
                            ("category_recall_micro", "Natural v3: category recall", "{:.1%}"),
                            ("precondition_recall_micro", "Natural v3: precondition recall", "{:.1%}")):
        vals = {m: ru[m][key] for m in MODES if isinstance(ru.get(m), dict) and key in ru[m]}
        if vals:
            add(f"natural_v3_{key}", label, "main_eval", main, vals,
                {m: fmt.format(v) for m, v in vals.items()})
    agr, gold, can = h["simulator_rules_agreement"], h["gold_clean_pass"], h["udsoncan_virtual_can"]
    add("simulator_rules_agreement", "Simulator vs rules engine agreement", "main_eval", main,
        {"all": {"agreed": agr["agreed"], "total": agr["total"], "rate": agr["rate"]}},
        {"all": f"{agr['agreed']}/{agr['total']} ({agr['rate'] * 100:.1f}%)"})
    add("gold_clean_pass", "Gold tests passing on the clean simulator", "main_eval", main,
        {"all": {"passed": gold["passed"], "total": gold["total"], "rate": gold["rate"]}},
        {"all": f"{gold['passed']}/{gold['total']} ({gold['rate'] * 100:.1f}%)"})
    add("udsoncan_virtual_can", "udsoncan virtual-CAN sequence", "main_eval", main,
        {"all": {"status": can["status"]}}, {"all": str(can["status"]).upper()})
    if qa:
        qref = qa["run"]
        for key, label in (("answer_accuracy", "Q&A answer accuracy"),
                           ("citation_correctness", "Q&A citation correctness"),
                           ("citation_precision", "Q&A citation precision"),
                           ("correct_not_found_rate", "Q&A correct not-found rate")):
            vals = {m: qa["modes"][m][key] for m in qa["modes"] if key in qa["modes"][m]}
            add(f"qa_{key}", label, "qa", qref, vals, {m: f"{v:.1%}" for m, v in vals.items()})
    if timing:
        tref = timing["run"]
        vals = {m: timing["modes"][m]["mean_of_requirement_means_s"] for m in timing["modes"]}
        add("timing_mean_s", "Tool-side generation time per requirement (mean of 5)", "timing", tref,
            vals, {m: f"{v:.2f} s" for m, v in vals.items()})
    return cards


def success_metrics(report: dict[str, Any], prov: dict[str, Any],
                    timing: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The five case-study success metrics, defined from data that exists in the report."""
    main = prov["main_eval"]
    rows: list[dict[str, Any]] = []
    done = [m for m in MODES if report["modes"].get(m, {}).get("status") == "completed"]

    def per(fn: Any) -> dict[str, Any]:
        return {m: fn(report["modes"][m]) for m in done}

    # 1. test design time
    if timing:
        vals = {m: {"mean_of_requirement_means_s": t["mean_of_requirement_means_s"],
                    "min_s": t["min_requirement_mean_s"], "max_s": t["max_requirement_mean_s"],
                    "tests_generated": t["tests_generated_total"]}
                for m, t in timing["modes"].items()}
        status = "tool side measured; manual comparison pending owner measurement"
    else:
        vals, status = {}, "not measured (no timing run found)"
    rows.append({
        "id": "test_design_time", "label": "Test design time",
        "definition": ("Tool side: wall-clock seconds to generate the tests for one requirement "
                       "(mean over repeats, then mean over the 5 timed requirements). Manual side: "
                       "hand-writing time per docs/TEST_DESIGN_TIME.md."),
        "how_measured": "scripts/time_generation.py, in-process, repeats per requirement; no human review time included",
        "status": status, "values": vals, "run": "timing",
        "run_ref": timing["run"] if timing else None,
        "manual_comparison": "pending owner measurement"})
    # 2. generation accuracy
    rows.append({
        "id": "generation_accuracy", "label": "Generation accuracy",
        "definition": ("Fraction of generated send-steps whose expected response bytes equal what the "
                       "rules-engine oracle predicts, and fraction of generated tests passing on the "
                       "bug-free simulator."),
        "how_measured": ("expected_response_accuracy in the main eval. Circular by construction (bytes "
                         "come from the oracle); independent evidence is the simulator/rules agreement."),
        "status": "measured (proxy)", "run": "main_eval", "run_ref": main,
        "values": per(lambda b: {
            "oracle_agreeing_steps": b["expected_response_accuracy"]["oracle"]["agreeing_steps"],
            "oracle_send_steps": b["expected_response_accuracy"]["oracle"]["send_steps"],
            "tests_fully_agreeing": b["expected_response_accuracy"]["oracle"]["tests_fully_agreeing"],
            "tests": b["expected_response_accuracy"]["oracle"]["tests"],
            "clean_simulator_pass_rate": b["expected_response_accuracy"]["simulator"]["clean_pass_rate"],
            "gold_exact_overlap": b["expected_response_accuracy"]["gold_exact_overlap"]["rate"]})})
    # 3. coverage
    conf = report.get("conformance", {})
    ph = conf.get("stats", {}).get("phases", []) if conf.get("status") == "completed" else []
    rows.append({
        "id": "coverage", "label": "Coverage",
        "definition": ("(a) seed requirements with at least one generated test; (b) for the conformance "
                       "sweep, oracle-observable coverage items covered by its 1200 tests (phase 1 = "
                       "every stimulus/response-class pair and setup x service pair)."),
        "how_measured": "coverage block of each mode and conformance.stats.phases; not code coverage",
        "status": "measured", "run": "main_eval", "run_ref": main,
        "values": {**per(lambda b: {
            "requirements_with_tests": b["coverage"]["requirements_with_tests"],
            "requirements": b["coverage"]["requirements"],
            "category_totals": b["coverage"]["category_totals"]}),
            "sweep_phases": [{"phase": p["phase"], "items": p["items"], "covered": p["covered"]}
                             for p in ph]}})
    # 4. reuse
    rows.append({
        "id": "reuse_rate", "label": "Reuse rate (proxy)",
        "definition": ("Fraction of generated tests instantiated from the reusable template catalog, "
                       "and how many of the registered templates were used. 100% by construction "
                       "(the LLM never writes bytes), so it shows catalog coverage, not saved effort."),
        "how_measured": "template_reuse in the main eval; exported pytest files also ran green",
        "status": "measured (proxy)", "run": "main_eval", "run_ref": main,
        "values": per(lambda b: {
            "tests": b["template_reuse"]["tests"],
            "template_instantiations": b["template_reuse"]["template_instantiations"],
            "templates_used": b["template_reuse"]["templates_used"],
            "templates_registered": b["template_reuse"]["templates_registered"]})})
    # 5. defect detection
    v3 = {}
    for m in done:
        r = report["modes"][m].get("part_d_detection", {}).get("heldout_v3")
        if isinstance(r, dict):
            v3[m] = {"full_output": r["full_output"], "requirement_driven": r["requirement_driven"],
                     "conformance": r["conformance"], "gold": r.get("gold")}
    rows.append({
        "id": "defect_detection", "label": "Defect detection",
        "definition": ("Held-out v3 bugs (15, written blind after the Part D freeze) found by the "
                       "system's full output = requirement-driven tests + conformance sweep."),
        "how_measured": "heldout_v3 in part_d_detection; a bug counts if any test fails with it injected",
        "status": "measured", "run": "main_eval", "run_ref": main, "values": v3})
    return rows


def attach_extras(report: dict[str, Any], out: Path, qa_json: Path | None = None,
                  timing_json: Path | None = None) -> dict[str, Any]:
    """Add provenance, Q&A, timing, history, headline cards and success metrics to ``report``.

    Inputs default to ``<out>/qa/qa_eval.json``, ``<out>/timing/tool_timing.json`` and the
    Part C / Part D before-after files under ``<out>``; absent inputs are simply omitted.
    """
    git = report.get("git", {})
    main = _ref("Main evaluation run", "outputs/eval_report.json", report.get("timestamp"),
                git.get("commit"), git.get("dirty"), git.get("note", ""))
    qa_path = qa_json if qa_json is not None else out / "qa" / "qa_eval.json"
    tm_path = timing_json if timing_json is not None else out / "timing" / "tool_timing.json"
    qa_raw, tm_raw = _read_json(qa_path), _read_json(tm_path)
    qa = qa_summary(qa_raw, _rel(qa_path, out)) if qa_raw else None
    tm = timing_summary(tm_raw, _rel(tm_path, out)) if tm_raw else None
    history: dict[str, Any] = {}
    for key, title in (("part_d", "Part D before / after"), ("part_c", "Part C before / after")):
        sub = "partD" if key == "part_d" else "partC"
        entry = history_entry(out / sub / "before_after.md", title, out)
        if entry:
            history[key] = entry
    prov: dict[str, Any] = {"main_eval": main, "qa": qa["run"] if qa else None,
                            "timing": tm["run"] if tm else None,
                            "history": {k: {"run_hashes": v["run_hashes"], "timestamps": v["timestamps"],
                                            "source": v["source"]} for k, v in history.items()}}
    report["provenance"] = prov
    if qa:
        report["qa"] = qa
    else:
        report.pop("qa", None)
    if tm:
        report["timing"] = tm
    else:
        report.pop("timing", None)
    report["history"] = history
    report["headline_cards"] = headline_cards(report, prov, qa, tm)
    report["success_metrics"] = success_metrics(report, prov, tm)
    return report
