"""Render the evaluation report dict (see :mod:`.run_eval`) as human-readable Markdown."""

from __future__ import annotations

from typing import Any

from uds_assistant.eval.metrics import CATEGORIES
from uds_assistant.eval.retrieval_compare import render_section as _retrieval_section


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


def _header(report: dict[str, Any]) -> list[str]:
    mode = report["actual_mode"]
    lines: list[str] = [
        "# Evaluation report — UDS test generation assistant",
        "",
        (f"- **Generated:** {report['timestamp']} (git `{report['git'].get('commit') or 'n/a'}`"
         f"{', uncommitted changes present' if report['git'].get('dirty') else ''})"),
        (f"- **LLM mode used:** `{mode}` (requested `{report['requested_mode']}`"
         f"{'; FELL BACK to mock because Ollama was unreachable' if report['mode_fallback'] else ''})"),
        f"- **Agent engine:** `{report['engine']}` · **Retriever:** `{report['retriever']}`",
        (f"- **Template set:** `{report['template_set_version']}` "
         f"({report['templates_registered']} templates)"),
        (f"- **Inputs:** {report['requirements']} seed requirements, "
         f"{report.get('natural_requirements', 0)} labelled natural requirements, "
         f"{report['gold_tests']} gold tests, {report.get('heldout_catalog_size', 0)} held-out + "
         f"{report['bug_catalog_size']} in-sample injectable simulator bugs"),
        "",
        ("> **The ECU spec is synthetic.** `data/bcm_spec.yaml` describes a fictional Body Control "
         "Module written for this project in an OEM-like style; no real OEM document or ISO 14229 "
         "text is used. All numbers below are measured against the project's own simulator."),
        ">",
        f"> **Mode:** LLM-dependent numbers are for `mode={mode}`. "
        + (
            "In mock mode the LLM is a deterministic keyword/rule stand-in; numbers for "
            "`mode=ollama` (local Qwen2.5-3B) are **pending Part B / not run** (no model "
            "download in the offline build)."
            if mode == "mock"
            else "Mock-mode numbers are not part of this invocation."
        ),
        "",
    ]
    if report.get("template_set_note"):
        lines += [(f"> **Template set {report['template_set_version']}:** "
                   f"{report['template_set_note']}"), ""]
    for w in report.get("setup_warnings", []):
        lines.append(f"> WARNING: {w}")
    if report.get("setup_warnings"):
        lines.append("")
    return lines


def _headline(report: dict[str, Any]) -> list[str]:
    h = report["headline"]
    mode, other = h["mode"], h["other_mode"]
    other_cell = h["other_mode_status"]
    same = "same (LLM-independent)"

    def cells(value: str, llm_dependent: bool) -> list[str]:
        cols = {mode: value, other: other_cell if llm_dependent else same}
        return [cols["mock"], cols["ollama"]]

    agr, gold, can = h["simulator_rules_agreement"], h["gold_clean_pass"], h["udsoncan_virtual_can"]
    held, cov, cit = h["heldout_bug_detection"], h["coverage"], h["citation_validity"]
    can_txt = can["status"].upper() + (f" — `{can['error']}`" if can.get("error") else "")
    n = held["bugs"]
    held_txt = (f"**generated {held['generated']['detected']}/{n} "
                f"({_pct(held['generated']['rate'])})** · gold {held['gold']['detected']}/{n} "
                f"({_pct(held['gold']['rate'])}) · union {held['union']['detected']}/{n} "
                f"({_pct(held['union']['rate'])})")
    ru = h["requirement_understanding"][mode]
    if "status" in ru:
        ru_txt = ru["status"]
    else:
        k = ru["requirements"]
        ru_txt = (f"test split (n={k}): target exact match parsed "
                  f"{ru['target_exact_parsed']}/{k} (F1 {_f(ru['target_f1_parsed'])}), "
                  f"exercised {ru['target_exact_exercised']}/{k} "
                  f"(F1 {_f(ru['target_f1_exercised'])}); category recall "
                  f"{_pct(ru['category_recall_micro'])} micro / "
                  f"{_pct(ru['category_recall_macro'])} macro; precondition recall "
                  f"{_pct(ru['precondition_recall_micro'])} micro / "
                  f"{_pct(ru['precondition_recall_macro'])} macro; fallback/nothing {ru['fallback']}/{k} "
                  f"({ru['fallback_unexpected']} excl. NAT-020-style empty-label rows)")
    tot = cov["category_totals"]
    cov_txt = (", ".join(f"{c} {tot[c]}" for c in CATEGORIES)
               + f"; requirements with ≥1 test {_frac(cov['requirements_with_tests'], cov['requirements'], cov['rate'])}")
    rows = [
        ["1. Simulator ↔ rules-engine agreement (seeded random sample, live)",
         *cells(_frac(agr["agreed"], agr["total"], agr["rate"]), False)],
        ["2. Gold tests passing on the bug-free simulator",
         *cells(_frac(gold["passed"], gold["total"], gold["rate"]), False)],
        ["3. udsoncan virtual-CAN sequence (session → seed/key → read → write → read-back)",
         *cells(can_txt, False)],
        ["**4. Held-out bug detection (12 bugs; HEADLINE = generated)**",
         *cells(held_txt, True)],
        ["5. Requirement understanding (natural requirements)", *cells(ru_txt, True)],
        ["6. Coverage (seed requirements; tests per category)", *cells(cov_txt, True)],
        ["7. Citation validity", *cells(_frac(cit["valid"], cit["citations"], cit["rate"]), True)],
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


def _heldout(blk: dict[str, Any]) -> list[str]:
    held = blk["heldout_bug_detection"]
    gen, gold, union = held["generated"], held["gold"], held["union"]
    ana = held["analysis"]
    gold_by = {b["bug_id"]: b for b in gold["per_bug"]}
    lines = [
        "## Held-out bug detection (12 bugs, not seen when templates/gold were written)",
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
        "### Missed held-out bugs — generated suite",
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


def _understanding(report: dict[str, Any], blk: dict[str, Any]) -> list[str]:
    ru = blk.get("requirement_understanding", {})
    mode = report["actual_mode"]
    lines = ["## Requirement understanding (natural requirements)", ""]
    if "splits" not in ru:
        return [*lines, "Not run in this invocation.", ""]
    lines += [
        (f"Source: `{ru['source']}` ({report.get('natural_requirements', 0)} labelled rows). "
         f"Each requirement was run through the agent pipeline (`mode={mode}`, "
         f"{report['retriever']}). **The TEST split is the main number.** Ollama: pending Part B."),
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
    lines += ["", "### Per requirement", ""]
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
            "; ".join(r["fallback_reasons"]) or "-",
        ])
    lines += _table(
        ["Req", "Split", "Tests", "Label targets", "Parsed exact", "Parsed missed", "Parsed extra",
         "Exercised exact", "Exercised missed", "Exercised extra (n)", "Categories missed", "Preconditions missed",
         "Fallback"], prow)
    lines += ["", "### Precondition mapping (how 'established' is derived from test steps)", ""]
    lines += [f"- `{k}`: {v}" for k, v in report.get("precondition_mapping", {}).items()]
    lines.append("")
    return lines


def _in_sample(report: dict[str, Any], blk: dict[str, Any]) -> list[str]:
    det = blk["bug_detection"]
    gen, gold, union = det["generated"], det["gold"], det["union"]
    lines = [
        "## Secondary: in-sample bug detection (26 bugs — templates tuned on these)",
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
    if comp:
        b, c = comp["baseline"], comp["current"]
        lines += [
            "### Before / after template additions (in-sample)",
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
    lines += ["### Bug detection per injected bug (in-sample)", ""]
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


def render_markdown(report: dict[str, Any]) -> str:
    """Return the Markdown report text."""
    mode = report["actual_mode"]
    blk = report["modes"][mode]
    rv = blk["request_validity"]
    era = blk["expected_response_accuracy"]
    cov = blk["coverage"]
    tr = blk["template_reuse"]
    cv = blk["citation_validity"]
    gt = blk["generated_tests"]

    lines = _header(report)
    lines += _headline(report)
    lines += [
        (f"Generated tests (seed requirements): **{gt['count']}** "
         f"({gt['unique_template_instantiations']} unique template instantiations); "
         f"{_frac(gt['clean_simulator_passed'], gt['count'], gt['clean_simulator_pass_rate'])} "
         f"pass on the clean simulator; P2/P2* wall-clock warnings: {gt['p2_timing_warnings']}."),
        "",
    ]
    lines += _heldout(blk)
    lines += _understanding(report, blk)
    if "retrieval_comparison" in report:
        lines += _retrieval_section(report["retrieval_comparison"])
    lines += _checks(report)
    lines += _in_sample(report, blk)

    lines += ["## Coverage (generated tests per category per seed requirement)", ""]
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
        "## Request validity",
        "",
        (f"- Send steps: {rv['send_steps']}; decodable: {rv['decodable']}; not rejected with a "
         f"format NRC (0x11/0x12/0x13): {rv['not_format_rejected']} "
         f"(unadjusted rate {_pct(rv['unadjusted_rate'])})."),
        (f"- Intentional format probes (NRC in the template's `intended_nrcs`): "
         f"{rv['intentional_format_probes']}. Adjusted validity: "
         f"**{_frac(rv['well_formed'], rv['send_steps'], rv['rate'])}**."),
        "",
        "## Template reuse and citations",
        "",
        (f"- Template reuse: {_frac(tr['template_instantiations'], tr['tests'], tr['rate'])}; "
         f"templates used: {tr['templates_used']}/{tr['templates_registered']}; per template: "
         + ", ".join(f"`{k}` {v}" for k, v in tr["per_template"].items())),
        (f"- Citations: {cv['valid']}/{cv['citations']} valid; tests with ≥1 valid citation: "
         f"{_pct(cv['tests_with_valid_citation_rate'])}."),
        "",
    ]

    p = blk["pipeline"]
    lines += ["## Pipeline statistics (seed requirements)", ""]
    lines += _table(
        ["Requirement", "tests", "dropped", "rejected", "plan attempts", "status"],
        [[r["requirement_id"], r["tests"], r["dropped"], r["rejected"], r["plan_attempts"],
          r["status"]] for r in p["per_requirement"]],
    )
    lines += [
        "",
        (f"Totals: {p['tests_kept']} kept, {p['dropped']} dropped, {p['rejected']} rejected, "
         f"{p['retries']} re-plans, {p['failed_runs']} failed runs."),
        "",
        "## Exports",
        "",
    ]
    exp = report["exports"]
    for f in exp.get("written", []):
        lines.append(f"- `{f}`")
    run = exp.get("run")
    if run:
        lines.append(
            f"- Ran `{run['file']}` (transport `{run['transport']}`) with pytest in a subprocess: "
            f"**{'PASSED' if run['passed'] else 'FAILED'}** — `{run['summary']}` ({run['seconds']} s)."
        )
    lines += [
        "- CAPL files (`*.can`) are **UNVERIFIED TEMPLATES — not compiled or run in CANoe**.",
        "",
        "## Runtime",
        "",
    ]
    lines += _table(["Phase", "seconds"], [[k, v] for k, v in report["runtime_seconds"].items()])
    lines += [
        "",
        "## Appendix: Self-consistency check (circular by construction)",
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
        "## Metric definitions",
        "",
    ]
    for key, text in report["metric_definitions"].items():
        lines.append(f"- **{key}**: {text}")
    lines.append("")
    return "\n".join(lines)
