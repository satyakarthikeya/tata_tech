"""Render the evaluation report dict (see :mod:`.run_eval`) as human-readable Markdown."""

from __future__ import annotations

from typing import Any

from uds_assistant.eval.metrics import CATEGORIES


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


def render_markdown(report: dict[str, Any]) -> str:
    """Return the Markdown report text."""
    mode = report["actual_mode"]
    blk = report["modes"][mode]
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
        (f"- **Inputs:** {report['requirements']} seed requirements, {report['gold_tests']} gold "
        f"tests, {report['bug_catalog_size']} injectable simulator bugs"),
        "",
        ("> **The ECU spec is synthetic.** `data/bcm_spec.yaml` describes a fictional Body Control "
        "Module written for this project in an OEM-like style; no real OEM document or ISO 14229 "
        "text is used. All numbers below are measured against the project's own simulator."),
        ">",
        f"> **Mode:** these numbers are for `mode={mode}`. "
        + (
            "In mock mode the LLM is a deterministic keyword/rule stand-in; numbers for "
            "`mode=ollama` (local Qwen2.5-3B) are **deferred / not run** (no model download in "
            "the offline build)."
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

    det = blk["bug_detection"]
    gen, gold, union = det["generated"], det["gold"], det["union"]
    rv = blk["request_validity"]
    era = blk["expected_response_accuracy"]
    cov = blk["coverage"]
    tr = blk["template_reuse"]
    cv = blk["citation_validity"]
    gt = blk["generated_tests"]

    lines += ["## Headline metrics", ""]
    lines += _table(
        ["Metric", "mock", "ollama"],
        [
            ["**Bug detection rate — generated suite**",
             f"**{_frac(gen['detected'], gen['bugs'], gen['rate'])}**", "not run"],
            ["Bug detection rate — gold baseline",
             _frac(gold["detected"], gold["bugs"], gold["rate"]), "not run"],
            ["Bug detection rate — union", _frac(union["detected"], union["bugs"], union["rate"]),
             "not run"],
            ["Request validity", _frac(rv["well_formed"], rv["send_steps"], rv["rate"]), "not run"],
            ["Expected-response accuracy vs oracle (steps)",
             _frac(era["oracle"]["agreeing_steps"], era["oracle"]["send_steps"],
                   era["oracle"]["step_rate"]), "not run"],
            ["Expected-response accuracy vs gold (exact overlap)",
             _frac(era["gold_exact_overlap"]["agreeing_pairs"],
                   era["gold_exact_overlap"]["overlapping_pairs"],
                   era["gold_exact_overlap"]["rate"]), "not run"],
            ["Expected-response accuracy vs gold (shared-prefix steps)",
             _frac(era["gold_shared_prefix"]["agreeing"],
                   era["gold_shared_prefix"]["distinct_shared_send_steps"],
                   era["gold_shared_prefix"]["rate"]), "not run"],
            ["Generated tests passing on clean simulator",
             _frac(gt["clean_simulator_passed"], gt["count"], gt["clean_simulator_pass_rate"]),
             "not run"],
            ["Coverage (requirements with ≥1 test)",
             _frac(cov["requirements_with_tests"], cov["requirements"], cov["rate"]), "not run"],
            ["Template reuse rate", _frac(tr["template_instantiations"], tr["tests"], tr["rate"]),
             "not run"],
            ["Citation validity", _frac(cv["valid"], cv["citations"], cv["rate"]), "not run"],
        ],
    )
    if mode != "mock":
        lines.append("")
        lines.append("_(Column headers are fixed; in this invocation the measured column is "
                     f"`{mode}`.)_")
    lines += [
        "",
        (f"Generated tests: **{gt['count']}** ({gt['unique_template_instantiations']} unique "
        f"template instantiations; the same check can be generated for several requirements). "
        f"P2/P2* wall-clock warnings on the clean run: {gt['p2_timing_warnings']}."),
        "",
    ]

    comp = report.get("baseline_comparison")
    if comp:
        b, c = comp["baseline"], comp["current"]
        lines += [
            "## Before / after template additions",
            "",
            f"Baseline read from `{comp['baseline_file']}` (run {comp['baseline_timestamp']}).",
            "",
        ]
        lines += _table(
            ["", f"baseline ({b['template_set_version']}, {b['templates']} templates)",
             f"current ({c['template_set_version']}, {c['templates']} templates)"],
            [
                ["Generated tests", b["generated_tests"], c["generated_tests"]],
                ["Generated-suite bug detection", f"{b['generated_detected']} ({_pct(b['generated_detection_rate'])})",
                 f"{c['generated_detected']} ({_pct(c['generated_detection_rate'])})"],
                ["Gold bug detection", _pct(b["gold_detection_rate"]), _pct(c["gold_detection_rate"])],
                ["Union bug detection", _pct(b["union_detection_rate"]), _pct(c["union_detection_rate"])],
                ["Request validity", _pct(b["request_validity"]), _pct(c["request_validity"])],
                ["Citation validity", _pct(b["citation_validity"]), _pct(c["citation_validity"])],
                ["Template reuse", _pct(b["template_reuse_rate"]), _pct(c["template_reuse_rate"])],
                ["Undetected (generated)", ", ".join(b["generated_undetected"]) or "-",
                 ", ".join(c["generated_undetected"]) or "-"],
            ],
        )
        lines.append("")

    # Per-bug table
    gold_by = {b["bug_id"]: b for b in gold["per_bug"]}
    lines += ["## Bug detection per injected bug", ""]
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

    # Coverage table
    lines += ["## Coverage (generated tests per category per requirement)", ""]
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
        f"{rv['intentional_format_probes']}. Adjusted validity: **{_pct(rv['rate'])}**."),
        "",
        "## Expected-response accuracy",
        "",
        (f"- Oracle re-run: {_frac(era['oracle']['agreeing_steps'], era['oracle']['send_steps'], era['oracle']['step_rate'])} "
        f"steps; {_frac(era['oracle']['tests_fully_agreeing'], era['oracle']['tests'], era['oracle']['test_rate'])} tests. "
        "(Expected bytes are produced by the oracle, so this is a consistency check, not an "
        "independent accuracy measure.)"),
        (f"- Independent simulator (clean): {_pct(era['simulator']['clean_pass_rate'])} of "
        "generated tests pass."),
        (f"- Gold, exact overlap: {era['gold_exact_overlap']['overlapping_pairs']} generated/gold "
        f"pairs with identical step sequences; agreement {_pct(era['gold_exact_overlap']['rate'])}."),
        (f"- Gold, shared prefix: {era['gold_shared_prefix']['distinct_shared_send_steps']} distinct "
        f"send steps reached by an identical prefix in both suites; agreement "
        f"{_pct(era['gold_shared_prefix']['rate'])}."),
        "",
        "## Template reuse and citations",
        "",
        f"- Templates used: {tr['templates_used']}/{tr['templates_registered']}; per template: "
        + ", ".join(f"`{k}` {v}" for k, v in tr["per_template"].items()),
        (f"- Citations: {cv['valid']}/{cv['citations']} valid; tests with ≥1 valid citation: "
        f"{_pct(cv['tests_with_valid_citation_rate'])}."),
        "",
    ]

    p = blk["pipeline"]
    lines += ["## Pipeline statistics", ""]
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
    lines += ["", "## Metric definitions", ""]
    for key, text in report["metric_definitions"].items():
        lines.append(f"- **{key}**: {text}")
    lines.append("")
    return "\n".join(lines)
