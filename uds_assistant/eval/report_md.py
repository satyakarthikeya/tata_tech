"""Render the evaluation report dict (see :mod:`.run_eval`) as human-readable Markdown.

When both LLM modes ran in one invocation (``--mode ollama``), the report starts with
side-by-side mock | ollama tables, followed by the full per-mode detail sections.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from uds_assistant.eval.metrics import CATEGORIES
from uds_assistant.eval.retrieval_compare import render_section as _retrieval_section

MODES = ("mock", "ollama")
NODES = ("parse", "retrieve", "plan", "instantiate", "validate", "explain")


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _frac(num: int, den: int, rate: float | None) -> str:
    return f"{num}/{den} ({_pct(rate)})"


def _table(header: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


def _tests_list(ids: list[str], limit: int = 3) -> str:
    if not ids:
        return "-"
    shown = ", ".join(f"`{i}`" for i in ids[:limit])
    return shown + (f" (+{len(ids) - limit} more)" if len(ids) > limit else "")


def _f(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _sec(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} s"


def _esc(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _completed(report: dict[str, Any]) -> list[str]:
    return [m for m in MODES if report["modes"].get(m, {}).get("status") == "completed"]


def _cells(report: dict[str, Any], fn: Callable[[dict[str, Any]], Any]) -> list[Any]:
    """One cell per mode: ``fn(block)`` for a completed mode, else "not run"."""
    out = []
    for name in MODES:
        blk = report["modes"].get(name, {})
        out.append(fn(blk) if blk.get("status") == "completed" else "not run")
    return out


# ----------------------------------------------------------------------------- header


def _header(report: dict[str, Any]) -> list[str]:
    mode = report["actual_mode"]
    done = _completed(report)
    lines: list[str] = [
        "# Evaluation report — UDS test generation assistant",
        "",
        (f"- **Generated:** {report['timestamp']} (git `{report['git'].get('commit') or 'n/a'}`"
         f"{', uncommitted changes present' if report['git'].get('dirty') else ''})"),
        (f"- **LLM mode used:** `{mode}` (requested `{report['requested_mode']}`"
         f"{'; FELL BACK to mock because Ollama was unreachable' if report['mode_fallback'] else ''})"),
        f"- **Modes evaluated in this invocation:** {', '.join(f'`{m}`' for m in done)}",
        f"- **Agent engine:** `{report['engine']}` · **Retriever:** `{report['retriever']}`",
        (f"- **Template set:** `{report['template_set_version']}` "
         f"({report['templates_registered']} templates)"),
        (f"- **Inputs:** {report['requirements']} seed requirements, "
         f"{report.get('natural_requirements', 0)} labelled natural requirements, "
         f"{report['gold_tests']} gold tests, {report.get('heldout_catalog_size', 0)} held-out + "
         f"{report['bug_catalog_size']} in-sample injectable simulator bugs"),
    ]
    st = report.get("llm_settings")
    if st:
        lines.append(f"- **Ollama settings:** model `{st.get('model')}`, num_ctx {st.get('num_ctx')}, "
                     f"temperature {st.get('temperature')}, keep_alive `{st.get('keep_alive')}`")
    if "provenance_ok" in report:
        lines.append(
            "- **Byte provenance:** "
            + ("all generated tests re-instantiate byte-identically from their templates"
               if report["provenance_ok"] else "**FAILED — see the byte-provenance section**")
        )
    lines += [
        "",
        ("> **The ECU spec is synthetic.** `data/bcm_spec.yaml` describes a fictional Body Control "
         "Module written for this project in an OEM-like style; no real OEM document or ISO 14229 "
         "text is used. All numbers below are measured against the project's own simulator."),
        ">",
    ]
    if "ollama" in done:
        lines.append(
            "> **Modes:** `mock` is a deterministic keyword/rule stand-in; `ollama` is the local "
            "Qwen2.5-3B model. Both columns come from this single invocation, on the same inputs, "
            "templates and retriever. LLM-independent rows are identical for both."
        )
    else:
        lines.append(
            f"> **Mode:** LLM-dependent numbers are for `mode={mode}` (mock = a deterministic "
            "keyword/rule stand-in). The `ollama` column was **not run** in this invocation: "
            f"{report['modes']['ollama'].get('reason', '')}."
        )
    lines.append("")
    if report.get("template_set_note"):
        lines += [(f"> **Template set {report['template_set_version']}:** "
                   f"{report['template_set_note']}"), ""]
    for w in report.get("setup_warnings", []):
        lines.append(f"> WARNING: {w}")
    if report.get("setup_warnings"):
        lines.append("")
    return lines


# ----------------------------------------------------------------------------- headline


def _ru_text(ru: dict[str, Any] | str) -> str:
    if isinstance(ru, str):
        return ru
    if "status" in ru:
        return ru["status"]
    k = ru["requirements"]
    return (f"test split (n={k}): target exact match parsed "
            f"{ru['target_exact_parsed']}/{k} (F1 {_f(ru['target_f1_parsed'])}), "
            f"exercised {ru['target_exact_exercised']}/{k} "
            f"(F1 {_f(ru['target_f1_exercised'])}); category recall "
            f"{_pct(ru['category_recall_micro'])} micro / "
            f"{_pct(ru['category_recall_macro'])} macro; precondition recall "
            f"{_pct(ru['precondition_recall_micro'])} micro / "
            f"{_pct(ru['precondition_recall_macro'])} macro; fallback/nothing {ru['fallback']}/{k} "
            f"({ru['fallback_unexpected']} excl. NAT-020-style empty-label rows)")


def _headline(report: dict[str, Any]) -> list[str]:
    h = report["headline"]
    same = "same (LLM-independent)"
    agr, gold, can = h["simulator_rules_agreement"], h["gold_clean_pass"], h["udsoncan_virtual_can"]
    held, cov, cit = h["heldout_bug_detection"], h["coverage"], h["citation_validity"]
    can_txt = can["status"].upper() + (f" — `{can['error']}`" if can.get("error") else "")
    n = held["bugs"]

    def by_mode(row: dict[str, Any], fmt: Callable[[dict[str, Any]], str]) -> list[str]:
        bm = row.get("by_mode", {})
        return [fmt(bm[m]) if isinstance(bm.get(m), dict) else str(bm.get(m, "not run"))
                for m in MODES]

    def held_fmt(v: dict[str, Any]) -> str:
        return (f"**generated {v['generated']['detected']}/{n} "
                f"({_pct(v['generated']['rate'])})** · gold {v['gold']['detected']}/{n} "
                f"({_pct(v['gold']['rate'])}) · union {v['union']['detected']}/{n} "
                f"({_pct(v['union']['rate'])})")

    def cov_fmt(v: dict[str, Any]) -> str:
        tot = v["category_totals"]
        return (", ".join(f"{c} {tot[c]}" for c in CATEGORIES)
                + "; requirements with ≥1 test "
                + _frac(v["requirements_with_tests"], v["requirements"], v["rate"]))

    def cit_fmt(v: dict[str, Any]) -> str:
        return _frac(v["valid"], v["citations"], v["rate"])

    ru = h["requirement_understanding"]
    rows = [
        ["1. Simulator ↔ rules-engine agreement (seeded random sample, live)",
         _frac(agr["agreed"], agr["total"], agr["rate"]), same],
        ["2. Gold tests passing on the bug-free simulator",
         _frac(gold["passed"], gold["total"], gold["rate"]), same],
        ["3. udsoncan virtual-CAN sequence (session → seed/key → read → write → read-back)",
         can_txt, same],
        ["**4. Held-out bug detection (12 bugs; HEADLINE = generated)**", *by_mode(held, held_fmt)],
        ["5. Requirement understanding (natural requirements)",
         *[_ru_text(ru.get(m, "not run")) for m in MODES]],
        ["6. Coverage (seed requirements; tests per category)", *by_mode(cov, cov_fmt)],
        ["7. Citation validity", *by_mode(cit, cit_fmt)],
    ]
    lines = ["## Headline metrics", ""]
    lines += _table(["Metric", "mock", "ollama"], rows)
    lines += [
        "",
        ("Rows 1-3 and the gold number in row 4 do not depend on the LLM; row 4 generated/union "
         "and rows 5-7 do. The self-consistency check (expected responses vs the oracle that "
         "produced them) is in the appendix, and the in-sample 26-bug detection is a "
         "secondary section, because the templates were tuned on those bugs."),
        "",
    ]
    return lines


def _interpretation(report: dict[str, Any]) -> list[str]:
    lines = ["## Interpretation: where the LLM helped and where it didn't", ""]
    interp = report.get("interpretation")
    if interp and interp.get("text"):
        lines += [interp["text"], ""]
        if interp.get("source"):
            lines += [(f"_Written after reading the measured numbers in this report "
                       f"(source `{interp['source']}`); no number was edited by hand._"), ""]
    elif "ollama" in _completed(report):
        lines += ["_Not written yet._", ""]
    else:
        lines += ["_Only one mode ran in this invocation; no mock-vs-ollama comparison._", ""]
    return lines


# ----------------------------------------------------------------------------- side by side


def _ru_split_rows(report: dict[str, Any], split: str) -> list[list[Any]]:
    def get(fn: Callable[[dict[str, Any]], str]) -> list[Any]:
        def inner(blk: dict[str, Any]) -> str:
            ru = blk.get("requirement_understanding", {})
            if "splits" not in ru:
                return "not run"
            return fn(ru["splits"][split])
        return _cells(report, inner)

    def n(a: dict[str, Any]) -> int:
        return a["requirements"]

    return [
        ["Requirements (n)", *get(lambda a: str(n(a)))],
        ["Target exact match — parsed",
         *get(lambda a: _frac(a["targets_parsed"]["exact"], n(a), a["targets_parsed"]["exact_rate"]))],
        ["Target exact match — exercised by kept tests",
         *get(lambda a: _frac(a["targets_exercised"]["exact"], n(a),
                              a["targets_exercised"]["exact_rate"]))],
        ["Parsed targets P / R / F1 (micro)",
         *get(lambda a: f"{_f(a['targets_parsed']['precision'])} / "
                        f"{_f(a['targets_parsed']['recall'])} / {_f(a['targets_parsed']['f1'])}")],
        ["Parsed targets tp / fp / fn",
         *get(lambda a: f"{a['targets_parsed']['tp']} / {a['targets_parsed']['fp']} / "
                        f"{a['targets_parsed']['fn']}")],
        ["Exercised targets P / R / F1 (micro)",
         *get(lambda a: f"{_f(a['targets_exercised']['precision'])} / "
                        f"{_f(a['targets_exercised']['recall'])} / "
                        f"{_f(a['targets_exercised']['f1'])}")],
        ["Category recall micro (hit/required) / macro",
         *get(lambda a: f"{_frac(a['categories']['hit'], a['categories']['required'], a['categories']['micro_recall'])}"
                        f" / {_pct(a['categories']['macro_recall'])}")],
        ["Precondition recall micro (hit/required) / macro",
         *get(lambda a: f"{_frac(a['preconditions']['hit'], a['preconditions']['required'], a['preconditions']['micro_recall'])}"
                        f" / {_pct(a['preconditions']['macro_recall'])}")],
        ["Fallback / nothing generated",
         *get(lambda a: f"{a['fallback']['count']} ({a['fallback']['unexpected_count']} excl. "
                        "empty-label rows)")],
    ]


def _per_req_understanding(report: dict[str, Any], split: str) -> list[str]:
    done = _completed(report)
    by_mode = {m: {r["id"]: r for r in report["modes"][m]["requirement_understanding"].get(
        "per_requirement", [])} for m in done}
    ids = [r["id"] for r in report["modes"][done[0]]["requirement_understanding"].get(
        "per_requirement", []) if r["split"] == split]
    rows = []
    for rid in ids:
        row: list[Any] = [rid]
        first = by_mode[done[0]][rid]
        row.append(", ".join(first["label_targets"]) or "(none)")
        for m in MODES:
            r = by_mode.get(m, {}).get(rid)
            if r is None:
                row += ["not run"] * 4
                continue
            row += [
                "yes" if r["parsed"]["exact"] else "no",
                (f"miss {', '.join(r['parsed']['missed']) or '-'}; "
                 f"extra {', '.join(r['parsed']['extra']) or '-'}"),
                f"{r['tests']} ({', '.join(r['categories']['missed']) or 'none'} missed)",
                ", ".join(r["preconditions"]["missed"]) or "-",
            ]
        rows.append(row)
    return _table(
        ["Req", "Label targets",
         "mock parsed exact", "mock parsed miss/extra", "mock tests (categories missed)",
         "mock preconds missed",
         "ollama parsed exact", "ollama parsed miss/extra", "ollama tests (categories missed)",
         "ollama preconds missed"], rows)


def _side_understanding(report: dict[str, Any]) -> list[str]:
    lines = [
        "### Requirement understanding — TEST split (headline)",
        "",
        ("Natural requirements from `data/requirements_natural.csv`. The prompts were tuned on "
         "the 8 dev rows only and frozen before the test split was run in Ollama mode."),
        "",
    ]
    lines += _table(["Metric", "mock", "ollama"], _ru_split_rows(report, "test"))
    lines += ["", "Per requirement, test split:", ""]
    lines += _per_req_understanding(report, "test")
    for split in ("dev", "all"):
        lines += ["", f"### Requirement understanding — {split} split"
                  + (" (the rows the prompts were tuned on)" if split == "dev" else ""), ""]
        lines += _table(["Metric", "mock", "ollama"], _ru_split_rows(report, split))
    lines += ["", "Per requirement, dev split:", ""]
    lines += _per_req_understanding(report, "dev")
    lines.append("")
    return lines


def _side_bugs(report: dict[str, Any]) -> list[str]:
    def det(key: str, which: str) -> Callable[[dict[str, Any]], str]:
        def fn(blk: dict[str, Any]) -> str:
            d = blk[key][which]
            return _frac(d["detected"], d["bugs"], d["rate"])
        return fn

    lines = ["### Held-out bug detection (12 bugs) — generated suite, gold, union", ""]
    lines += _table(["Suite", "mock", "ollama"], [
        ["**Generated (headline)**", *_cells(report, det("heldout_bug_detection", "generated"))],
        ["Gold (LLM-independent)", *_cells(report, det("heldout_bug_detection", "gold"))],
        ["Union generated ∪ gold", *_cells(report, det("heldout_bug_detection", "union"))],
        ["Generated tests (seed requirements)",
         *_cells(report, lambda b: str(b["generated_tests"]["count"]))],
        ["Invalid generated tests (fail on clean simulator)",
         *_cells(report, lambda b: str(len(b["heldout_bug_detection"]["generated"]["invalid_tests"])))],
    ])
    done = _completed(report)
    per = {m: {b["bug_id"]: b for b in report["modes"][m]["heldout_bug_detection"]["generated"]["per_bug"]}
           for m in done}
    gold_by = {b["bug_id"]: b for b in report["modes"][done[0]]["heldout_bug_detection"]["gold"]["per_bug"]}
    rows = []
    for bug_id, b in per[done[0]].items():
        cells = []
        for m in MODES:
            x = per.get(m, {}).get(bug_id)
            cells.append("not run" if x is None else
                         ("yes" if x["detected"] else "**no**") + f" ({len(x['detecting_tests'])} tests)")
        rows.append([f"`{bug_id}`", b["category"], *cells,
                     "yes" if gold_by.get(bug_id, {}).get("detected") else "**no**"])
    lines += ["", "Per held-out bug (generated suite):", ""]
    lines += _table(["Bug", "Category", "mock generated", "ollama generated", "gold"], rows)
    lines += ["", "### In-sample bug detection (26 bugs — templates tuned on these)", ""]
    lines += _table(["Suite", "mock", "ollama"], [
        ["Generated", *_cells(report, det("bug_detection", "generated"))],
        ["Gold", *_cells(report, det("bug_detection", "gold"))],
        ["Union", *_cells(report, det("bug_detection", "union"))],
        ["Undetected by the generated suite",
         *_cells(report, lambda b: ", ".join(b["bug_detection"]["generated"]["undetected"]) or "-")],
    ])
    lines.append("")
    return lines


def _pipe_rows(blk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {r["requirement_id"]: r for r in blk["pipeline"]["per_requirement"]}
    nat = blk.get("pipeline_natural", {})
    rows.update({r["requirement_id"]: r for r in nat.get("per_requirement", [])})
    return rows


def _side_validation(report: dict[str, Any]) -> list[str]:
    done = _completed(report)
    per = {m: _pipe_rows(report["modes"][m]) for m in done}
    ids = list(per[done[0]])
    rows = []
    for rid in ids:
        row: list[Any] = [rid, per[done[0]][rid].get("split", "seed")]
        for m in MODES:
            r = per.get(m, {}).get(rid)
            row += (["not run"] * 5 if r is None else
                    [r["tests"], r["rejected"], r["retries"], r["plan_attempts"], r["dropped"]])
        rows.append(row)

    def tot(blk: dict[str, Any], key: str) -> int:
        nat = blk.get("pipeline_natural", {})
        return int(blk["pipeline"].get(key, 0)) + int(nat.get(key, 0))

    tot_row: list[Any] = ["**total**", ""]
    for m in MODES:
        blk = report["modes"].get(m, {})
        tot_row += (["not run"] * 5 if m not in done else
                    [tot(blk, "tests_kept"), tot(blk, "rejected"), tot(blk, "retries"),
                     tot(blk, "plan_attempts"), tot(blk, "dropped")])
    rows.append(tot_row)
    lines = [
        "### Validation: rejections, re-plans (retries), plan attempts, dropped tests",
        "",
        ("Per requirement (15 seed + 20 natural). *rejected* = planner choices refused (unknown "
         "template/option, outside the shortlist, or failed validation); *retries* = re-plan "
         "rounds (plan attempts − 1); *dropped* = instantiated tests that failed validation."),
        "",
    ]
    lines += _table(["Req", "Split",
                     "mock tests", "mock rejected", "mock retries", "mock plan attempts",
                     "mock dropped",
                     "ollama tests", "ollama rejected", "ollama retries", "ollama plan attempts",
                     "ollama dropped"], rows)
    lines += ["", "LLM call counters (all 35 requirements):", ""]
    lines += _table(["Counter", "mock", "ollama"], [
        [label, *_cells(report, lambda b, k=key: str(tot(b, k)))]
        for label, key in (("LLM calls", "llm_calls"), ("JSON/schema failures", "llm_json_failures"),
                           ("LLM re-prompts/retries", "llm_retries"), ("LLM errors", "llm_errors"),
                           ("Failed pipeline runs", "failed_runs"))
    ])
    for m in done:
        reasons = []
        for rid, r in per[m].items():
            reasons += [f"- {rid}: {_esc(x)}" for x in r.get("rejected_reasons", [])]
        lines += ["", f"Rejection reasons — `{m}` ({len(reasons)}):", ""]
        lines += reasons[:60] or ["- none"]
        if len(reasons) > 60:
            lines.append(f"- … {len(reasons) - 60} more (see eval_report.json)")
    lines.append("")
    return lines


def _side_events(report: dict[str, Any]) -> list[str]:
    lines = ["### Fallback-to-mock and truncation events (verbatim)", ""]
    for m in MODES:
        blk = report["modes"].get(m, {})
        if blk.get("status") != "completed":
            lines += [f"- `{m}`: not run ({blk.get('reason', '')})"]
            continue
        ev = blk.get("events", {"fallback": [], "truncation": []})
        lines += [f"**`{m}` — fallback events ({len(ev['fallback'])}):**", ""]
        lines += [f"- {e['requirement_id']}: `{_esc(e['event'])}`" for e in ev["fallback"]] or ["- none"]
        lines += ["", f"**`{m}` — truncation events ({len(ev['truncation'])}):**", ""]
        lines += [f"- {e['requirement_id']}: `{_esc(e['event'])}`" for e in ev["truncation"]] or ["- none"]
        lines.append("")
    if report.get("mode_fallback"):
        lines += ["**The requested ollama mode fell back to mock for the whole invocation.**", ""]
    return lines


def _side_latency(report: dict[str, Any]) -> list[str]:
    def lat(scope: str, key: str) -> Callable[[dict[str, Any]], str]:
        def fn(blk: dict[str, Any]) -> str:
            v = blk["latency"]["per_requirement_wall_s"].get(scope)
            return "n/a" if not v else _sec(v[key])
        return fn

    lines = ["### Latency per requirement (wall clock)", ""]
    lines += _table(["Scope", "mock mean", "ollama mean", "mock p95", "ollama p95", "mock max",
                     "ollama max"], [
        [f"{scope} (n={n})",
         *_cells(report, lat(scope, "mean")), *_cells(report, lat(scope, "p95")),
         *_cells(report, lat(scope, "max"))]
        for scope, n in (("seed", report["requirements"]),
                         ("natural", report.get("natural_requirements", 0)),
                         ("all", report["requirements"] + report.get("natural_requirements", 0)))
    ])
    lines += ["", "Per-node mean latency per requirement (ms; p95 in brackets):", ""]
    rows = []
    for node in NODES:
        rows.append([node, *_cells(
            report, lambda b, nd=node: f"{b['latency']['per_node_ms'][nd]['mean_ms']:.1f} "
                                       f"[{b['latency']['per_node_ms'][nd]['p95_ms']:.1f}]")])
    rows.append(["time inside LLM calls", *_cells(
        report, lambda b: f"{b['latency']['llm_latency_ms_per_requirement']['mean']:.1f} "
                          f"[{b['latency']['llm_latency_ms_per_requirement']['p95']:.1f}]")])
    lines += _table(["Node", "mock", "ollama"], rows)
    done = _completed(report)
    if done:
        lines += ["", f"_{report['modes'][done[0]]['latency']['definition']}_"]
    lines.append("")
    return lines


def _side_other(report: dict[str, Any]) -> list[str]:
    def prov(part: str) -> Callable[[dict[str, Any]], str]:
        def fn(blk: dict[str, Any]) -> str:
            p = blk["provenance"] if part == "total" else blk["provenance"][part]
            return f"{p['passed']}/{p['checked']} passed" + ("" if p["ok"] else " — **FAILED**")
        return fn

    lines = ["### Coverage, citations, request validity, byte provenance", ""]
    rows = [
        [f"Coverage: tests per category ({', '.join(CATEGORIES)})",
         *_cells(report, lambda b: " / ".join(str(b["coverage"]["category_totals"][c])
                                              for c in CATEGORIES))],
        ["Coverage: seed requirements with ≥1 test",
         *_cells(report, lambda b: _frac(b["coverage"]["requirements_with_tests"],
                                         b["coverage"]["requirements"], b["coverage"]["rate"]))],
        ["Citation validity",
         *_cells(report, lambda b: _frac(b["citation_validity"]["valid"],
                                         b["citation_validity"]["citations"],
                                         b["citation_validity"]["rate"]))],
        ["Request validity (adjusted)",
         *_cells(report, lambda b: _frac(b["request_validity"]["well_formed"],
                                         b["request_validity"]["send_steps"],
                                         b["request_validity"]["rate"]))],
        ["Generated tests passing on the clean simulator",
         *_cells(report, lambda b: _frac(b["generated_tests"]["clean_simulator_passed"],
                                         b["generated_tests"]["count"],
                                         b["generated_tests"]["clean_simulator_pass_rate"]))],
        ["Byte provenance — seed-requirement tests", *_cells(report, prov("seed"))],
        ["Byte provenance — natural-requirement tests", *_cells(report, prov("natural"))],
        ["**Byte provenance — all generated tests**", *_cells(report, prov("total"))],
    ]
    lines += _table(["Metric", "mock", "ollama"], rows)
    done = _completed(report)
    if done:
        lines += ["", f"_Byte provenance: {report['modes'][done[0]]['provenance']['seed']['definition']}_"]
    for m in done:
        p = report["modes"][m]["provenance"]
        fails = p["seed"]["failures"] + p["natural"]["failures"]
        if fails:
            lines += ["", f"**Byte-provenance failures — `{m}`:**", ""]
            lines += [f"- `{f['test_id']}` ({f['template_id']}): {_esc('; '.join(f['problems']))}"
                      for f in fails]
    lines.append("")
    return lines


def _side_by_side(report: dict[str, Any]) -> list[str]:
    lines = ["## Mock vs Ollama — side by side", ""]
    if "ollama" not in _completed(report):
        lines += [(f"Only `{report['actual_mode']}` ran in this invocation; the ollama column "
                   "is \"not run\". Run `python -m uds_assistant.eval.run_eval --mode ollama` "
                   "for the comparison."), ""]
    lines += _side_understanding(report)
    lines += _side_bugs(report)
    lines += _side_validation(report)
    lines += _side_events(report)
    lines += _side_latency(report)
    lines += _side_other(report)
    return lines


# ----------------------------------------------------------------------------- per-mode detail


def _heldout(blk: dict[str, Any], mode: str) -> list[str]:
    held = blk["heldout_bug_detection"]
    gen, gold, union = held["generated"], held["gold"], held["union"]
    ana = held["analysis"]
    gold_by = {b["bug_id"]: b for b in gold["per_bug"]}
    lines = [
        f"## Held-out bug detection (12 bugs, not seen when templates/gold were written) — mode={mode}",
        "",
        f"Scope: {held['scope']}. Catalog: `{held['catalog']}`.",
        "",
    ]
    rows = []
    for b in gen["per_bug"]:
        g = gold_by.get(b["bug_id"], {})
        rows.append([
            f"`{b['bug_id']}`", b["category"],
            "yes" if b["detected"] else "**no**",
            _tests_list(b["detecting_tests"], 2),
            ana["generated"]["trigger_counts"].get(b["bug_id"], "n/a"),
            "yes" if g.get("detected") else "**no**",
            _tests_list(g.get("detecting_tests", []), 2),
            ana["gold"]["trigger_counts"].get(b["bug_id"], "n/a"),
        ])
    lines += _table(
        ["Bug", "Category", "Generated", "Generated detecting tests", "Gen. tests applying trigger",
         "Gold", "Gold detecting tests", "Gold tests applying trigger"], rows)
    lines += [
        "",
        (f"Totals: generated {_frac(gen['detected'], gen['bugs'], gen['rate'])}, gold "
         f"{_frac(gold['detected'], gold['bugs'], gold['rate'])}, union "
         f"{_frac(union['detected'], union['bugs'], union['rate'])}. Invalid tests (fail on "
         f"the clean simulator): generated {len(gen['invalid_tests'])}, gold "
         f"{len(gold['invalid_tests'])}."),
        "",
        f"### Missed held-out bugs — generated suite (mode={mode})",
        "",
    ]
    lines += [f"- `{m['bug_id']}`: {m['reason']}" for m in ana["generated"]["missed"]] or ["- none"]
    lines += ["", "### Missed held-out bugs — gold suite", ""]
    lines += [f"- `{m['bug_id']}`: {m['reason']}" for m in ana["gold"]["missed"]] or ["- none"]
    lines += [
        "",
        ("_Reasons come from a static trigger analysis (`uds_assistant/eval/heldout.py`): for "
         "each held-out bug, a predicate written from its catalog description checks whether a "
         "test applies the stimulus the bug needs. Reporting only — nothing in templates, gold "
         "tests, mock LLM or planner was changed in response._"),
        "",
    ]
    return lines


def _understanding(report: dict[str, Any], blk: dict[str, Any], mode: str) -> list[str]:
    ru = blk.get("requirement_understanding", {})
    lines = [f"## Requirement understanding (natural requirements) — mode={mode}", ""]
    if "splits" not in ru:
        return [*lines, "Not run in this invocation.", ""]
    lines += [
        (f"Source: `{ru['source']}` ({report.get('natural_requirements', 0)} labelled rows). "
         f"Each requirement was run through the agent pipeline (`mode={mode}`, "
         f"{report['retriever']}). **The TEST split is the main number.**"),
        "",
    ]
    rows = []
    for split in ("test", "dev", "all"):
        a = ru["splits"][split]
        tp, te = a["targets_parsed"], a["targets_exercised"]
        cat, pre = a["categories"], a["preconditions"]
        rows.append([
            f"**{split}**" if split == "test" else split, a["requirements"],
            _frac(tp["exact"], a["requirements"], tp["exact_rate"]),
            f"{_f(tp['precision'])} / {_f(tp['recall'])} / {_f(tp['f1'])}",
            _frac(te["exact"], a["requirements"], te["exact_rate"]),
            f"{_f(te['precision'])} / {_f(te['recall'])} / {_f(te['f1'])}",
            f"{_frac(cat['hit'], cat['required'], cat['micro_recall'])} / {_pct(cat['macro_recall'])}",
            f"{_frac(pre['hit'], pre['required'], pre['micro_recall'])} / {_pct(pre['macro_recall'])}",
            f"{a['fallback']['count']} ({a['fallback']['unexpected_count']} excl. empty-label rows)",
        ])
    lines += _table(
        ["Split", "n", "Targets exact (parsed)", "Parsed P / R / F1", "Targets exact (exercised)",
         "Exercised P / R / F1", "Category recall micro / macro",
         "Precondition recall micro / macro", "Fallback / nothing"], rows)
    lines += ["", f"### Per requirement (mode={mode})", ""]
    prow = []
    for r in ru["per_requirement"]:
        prow.append([
            r["id"], r["split"] + (" (ambiguous)" if r["ambiguous"] else ""), r["tests"],
            ", ".join(r["label_targets"]) or "(none)",
            "yes" if r["parsed"]["exact"] else "no",
            ", ".join(r["parsed"]["missed"]) or "-",
            ", ".join(r["parsed"]["extra"]) or "-",
            "yes" if r["exercised"]["exact"] else "no",
            ", ".join(r["exercised"]["missed"]) or "-",
            len(r["exercised"]["extra"]),
            ", ".join(r["categories"]["missed"]) or "-",
            ", ".join(r["preconditions"]["missed"]) or "-",
            _esc("; ".join(r["fallback_reasons"])) or "-",
        ])
    lines += _table(
        ["Req", "Split", "Tests", "Label targets", "Parsed exact", "Parsed missed", "Parsed extra",
         "Exercised exact", "Exercised missed", "Exercised extra (n)", "Categories missed",
         "Preconditions missed", "Fallback"], prow)
    lines.append("")
    return lines


def _in_sample(report: dict[str, Any], blk: dict[str, Any], mode: str) -> list[str]:
    det = blk["bug_detection"]
    gen, gold, union = det["generated"], det["gold"], det["union"]
    lines = [
        f"## Secondary: in-sample bug detection (26 bugs — templates tuned on these) — mode={mode}",
        "",
        (f"Scope: {det.get('scope', 'in-sample')}. Generated "
         f"{_frac(gen['detected'], gen['bugs'], gen['rate'])}, gold "
         f"{_frac(gold['detected'], gold['bugs'], gold['rate'])}, union "
         f"{_frac(union['detected'], union['bugs'], union['rate'])}. This is an optimistic, "
         "non-independent number: template set v2 was written after seeing which of these "
         "bugs v1 missed, by the same author as the catalog."),
        "",
    ]
    comp = report.get("baseline_comparison")
    if comp and mode == "mock":
        b, c = comp["baseline"], comp["current"]
        lines += [
            "### Before / after template additions (in-sample, mock)",
            "",
            f"Baseline read from `{comp['baseline_file']}` (run {comp['baseline_timestamp']}).",
            "",
        ]
        lines += _table(
            ["", f"baseline ({b['template_set_version']}, {b['templates']} templates)",
             f"current ({c['template_set_version']}, {c['templates']} templates)"],
            [
                ["Generated tests", b["generated_tests"], c["generated_tests"]],
                ["Generated-suite bug detection (in-sample)",
                 f"{b['generated_detected']} ({_pct(b['generated_detection_rate'])})",
                 f"{c['generated_detected']} ({_pct(c['generated_detection_rate'])})"],
                ["Gold bug detection (in-sample)", _pct(b["gold_detection_rate"]),
                 _pct(c["gold_detection_rate"])],
                ["Union bug detection (in-sample)", _pct(b["union_detection_rate"]),
                 _pct(c["union_detection_rate"])],
                ["Request validity", _pct(b["request_validity"]), _pct(c["request_validity"])],
                ["Citation validity", _pct(b["citation_validity"]), _pct(c["citation_validity"])],
                ["Template reuse", _pct(b["template_reuse_rate"]), _pct(c["template_reuse_rate"])],
                ["Undetected (generated)", ", ".join(b["generated_undetected"]) or "-",
                 ", ".join(c["generated_undetected"]) or "-"],
            ],
        )
        lines.append("")
    gold_by = {b["bug_id"]: b for b in gold["per_bug"]}
    lines += [f"### Bug detection per injected bug (in-sample) — mode={mode}", ""]
    rows = []
    for b in gen["per_bug"]:
        g = gold_by.get(b["bug_id"], {})
        rows.append([
            f"`{b['bug_id']}`", b["category"],
            "yes" if b["detected"] else "**no**",
            f"{len(b['detecting_tests'])}: {_tests_list(b['detecting_tests'])}",
            "yes" if g.get("detected") else "**no**",
            f"{len(g.get('detecting_tests', []))}: {_tests_list(g.get('detecting_tests', []))}",
        ])
    lines += _table(
        ["Bug", "Category", "Generated", "Generated detecting tests", "Gold",
         "Gold detecting tests"], rows)
    lines += [
        "",
        (f"Invalid tests (fail on the clean simulator, excluded from credit): generated "
         f"{len(gen['invalid_tests'])}, gold {len(gold['invalid_tests'])}."),
        (f"Detected only by the generated suite: {', '.join(union['only_generated']) or '-'}. "
         f"Only by gold: {', '.join(union['only_gold']) or '-'}. "
         f"Undetected by both: {', '.join(union['undetected']) or '-'}."),
        "",
    ]
    return lines


def _checks(report: dict[str, Any]) -> list[str]:
    agr = report["simulator_rules_agreement"]
    can = report["udsoncan_virtual_can"]
    lines = [
        "## LLM-independent checks (details)",
        "",
        (f"- Simulator ↔ rules engine: {agr['agreed']}/{agr['requests']} requests agreed over "
         f"{agr['walks']} seeded walks (seed {agr['seed']})."
         + (f" First mismatches: {agr['mismatch_examples']}" if agr["mismatch_examples"] else "")),
        (f"- Gold tests on the bug-free simulator: {report['gold_clean_passed']}/"
         f"{report['gold_tests']}."),
        f"- udsoncan virtual-CAN sequence: **{can['status'].upper()}**"
        + (f" — {can.get('reason')}" if can.get("reason") else ""),
    ]
    lines += [f"  - {s}" for s in can.get("steps", [])]
    lines.append("")
    return lines


def _mode_details(report: dict[str, Any], mode: str) -> list[str]:
    blk = report["modes"][mode]
    rv = blk["request_validity"]
    cov = blk["coverage"]
    tr = blk["template_reuse"]
    cv = blk["citation_validity"]
    gt = blk["generated_tests"]
    lines = [
        f"# Details — mode={mode}",
        "",
        (f"Generated tests (seed requirements): **{gt['count']}** "
         f"({gt['unique_template_instantiations']} unique template instantiations); "
         f"{_frac(gt['clean_simulator_passed'], gt['count'], gt['clean_simulator_pass_rate'])} "
         f"pass on the clean simulator; P2/P2* wall-clock warnings: {gt['p2_timing_warnings']}."),
        "",
    ]
    lines += _heldout(blk, mode)
    lines += _understanding(report, blk, mode)
    lines += _in_sample(report, blk, mode)
    lines += [f"## Coverage (generated tests per category per seed requirement) — mode={mode}", ""]
    cov_rows = []
    for rid, counts in cov["per_requirement"].items():
        cov_rows.append([rid, *[counts[c] for c in CATEGORIES], sum(counts.values())])
    totals = cov["category_totals"]
    cov_rows.append(["**total**", *[totals[c] for c in CATEGORIES], sum(totals.values())])
    lines += _table(["Requirement", *CATEGORIES, "total"], cov_rows)
    lines += [
        "",
        (f"Categories present: {_pct(cov['category_presence'])}; requirements covered by ≥2 "
         f"categories: {cov['requirements_with_2plus_categories']}/{cov['requirements']}."),
        "",
        f"## Request validity — mode={mode}",
        "",
        (f"- Send steps: {rv['send_steps']}; decodable: {rv['decodable']}; not rejected with a "
         f"format NRC (0x11/0x12/0x13): {rv['not_format_rejected']} "
         f"(unadjusted rate {_pct(rv['unadjusted_rate'])})."),
        (f"- Intentional format probes (NRC in the template's `intended_nrcs`): "
         f"{rv['intentional_format_probes']}. Adjusted validity: "
         f"**{_frac(rv['well_formed'], rv['send_steps'], rv['rate'])}**."),
        "",
        f"## Template reuse and citations — mode={mode}",
        "",
        (f"- Template reuse: {_frac(tr['template_instantiations'], tr['tests'], tr['rate'])}; "
         f"templates used: {tr['templates_used']}/{tr['templates_registered']}; per template: "
         + ", ".join(f"`{k}` {v}" for k, v in tr["per_template"].items())),
        (f"- Citations: {cv['valid']}/{cv['citations']} valid; tests with ≥1 valid citation: "
         f"{_pct(cv['tests_with_valid_citation_rate'])}."),
        "",
    ]
    p = blk["pipeline"]
    lines += [f"## Pipeline statistics (seed requirements) — mode={mode}", ""]
    lines += _table(
        ["Requirement", "tests", "dropped", "rejected", "plan attempts", "status", "wall s"],
        [[r["requirement_id"], r["tests"], r["dropped"], r["rejected"], r["plan_attempts"],
          r["status"], r.get("wall_s", "n/a")] for r in p["per_requirement"]],
    )
    lines += [
        "",
        (f"Totals: {p['tests_kept']} kept, {p['dropped']} dropped, {p['rejected']} rejected, "
         f"{p['retries']} re-plans, {p['failed_runs']} failed runs."),
        "",
    ]
    era = blk["expected_response_accuracy"]
    lines += [
        f"## Appendix: Self-consistency check (circular by construction) — mode={mode}",
        "",
        ("Expected bytes in generated tests are produced by the rules-engine oracle, so "
         "agreement with a fresh oracle re-run is a consistency check, not an independent "
         "accuracy measure. Kept here for completeness; it is not a headline metric."),
        "",
        (f"- Expected-response accuracy vs oracle: "
         f"{_frac(era['oracle']['agreeing_steps'], era['oracle']['send_steps'], era['oracle']['step_rate'])} "
         f"steps; {_frac(era['oracle']['tests_fully_agreeing'], era['oracle']['tests'], era['oracle']['test_rate'])} tests."),
        (f"- Independent simulator (clean): {_pct(era['simulator']['clean_pass_rate'])} of "
         "generated tests pass."),
        (f"- Gold, exact overlap: "
         f"{_frac(era['gold_exact_overlap']['agreeing_pairs'], era['gold_exact_overlap']['overlapping_pairs'], era['gold_exact_overlap']['rate'])} "
         "generated/gold pairs with identical step sequences agree."),
        (f"- Gold, shared prefix: "
         f"{_frac(era['gold_shared_prefix']['agreeing'], era['gold_shared_prefix']['distinct_shared_send_steps'], era['gold_shared_prefix']['rate'])} "
         "distinct send steps reached by an identical prefix in both suites agree."),
        "",
    ]
    return lines


def _exports(report: dict[str, Any]) -> list[str]:
    lines = ["## Exports", ""]
    exp = report["exports"]
    by_mode = exp.get("by_mode") or {report["actual_mode"]: exp}
    for mode, info in by_mode.items():
        for f in info.get("written", []):
            lines.append(f"- `{f}` (mode={mode})")
        run = info.get("run")
        if run:
            lines.append(
                f"- Ran `{run['file']}` for mode={mode} (transport `{run['transport']}`) with "
                f"pytest in a subprocess: **{'PASSED' if run['passed'] else 'FAILED'}** — "
                f"`{run['summary']}` ({run['seconds']} s)."
            )
    lines += ["- CAPL files (`*.can`) are **UNVERIFIED TEMPLATES — not compiled or run in CANoe**.",
              ""]
    return lines


def _freeze(report: dict[str, Any]) -> list[str]:
    fr = report.get("freeze")
    if not fr:
        return []
    lines = ["## Freeze verification (prompts / agent / templates)", ""]
    lines += _table(["Path", "expected object id", "HEAD object id", "matches", "worktree clean"],
                    [[f"`{p}`", f"`{v['expected']}`", f"`{v['head']}`", v["matches"],
                      v["worktree_clean"]] for p, v in fr["paths"].items()])
    lines += ["", f"All frozen paths unchanged: **{fr['all_ok']}**.", ""]
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    """Return the Markdown report text."""
    lines = _header(report)
    lines += _headline(report)
    lines += _interpretation(report)
    lines += _side_by_side(report)
    if "retrieval_comparison" in report:
        lines += _retrieval_section(report["retrieval_comparison"])
    lines += _checks(report)
    lines += _freeze(report)
    for mode in _completed(report):
        lines += _mode_details(report, mode)
    lines += ["# Shared", ""]
    lines += ["### Precondition mapping (how 'established' is derived from test steps)", ""]
    lines += [f"- `{k}`: {v}" for k, v in report.get("precondition_mapping", {}).items()]
    lines.append("")
    lines += _exports(report)
    lines += ["## Runtime", ""]
    lines += _table(["Phase", "seconds"], [[k, v] for k, v in report["runtime_seconds"].items()])
    lines += ["", "## Metric definitions", ""]
    for key, text in report["metric_definitions"].items():
        lines.append(f"- **{key}**: {text}")
    lines.append("")
    return "\n".join(lines)
