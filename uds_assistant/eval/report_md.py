"""Render the evaluation report dict (see :mod:`.run_eval`) as human-readable Markdown.

When both LLM modes ran in one invocation (``--mode ollama``), the report starts with
side-by-side mock | ollama tables, followed by the full per-mode detail sections.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from uds_assistant.eval.breakdown import REJECTION_LABELS, REJECTION_REASONS
from uds_assistant.eval.metrics import CATEGORIES
from uds_assistant.eval.retrieval_compare import render_section as _retrieval_section
from uds_assistant.eval.run_provenance import run_tag

MODES = ("mock", "ollama")
HELDOUT_V3_NOTE = (
    "15 bugs written blind after the Part D freeze by a subagent that could not see templates, "
    "the conformance sweep, prompts, eval code or any report; nothing was changed after seeing "
    "these results."
)
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


def provenance_failures(prov: dict[str, Any]) -> list[dict[str, Any]]:
    """Every stored failure record of a provenance block (all groups and noise runs)."""
    out: list[dict[str, Any]] = []
    for group in ("seed", "natural", "natural_v2", "natural_v3"):
        out += prov.get(group, {}).get("failures", [])
    for extra in prov.get("noise_extra_runs", []):
        out += extra["provenance"]["failures"]
    return out


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
         f"{report.get('natural_requirements_v3', 0)} natural v3 (FRESH) + "
         f"{report.get('natural_requirements_v2', 0)} natural v2 (seen) + "
         f"{report.get('natural_requirements', 0)} natural v1 (seen) labelled requirements, "
         f"{report['gold_tests']} gold tests, {report.get('heldout_v3_catalog_size', 0)} held-out "
         f"v3 (FRESH) + {report.get('heldout_v2_catalog_size', 0)} held-out v2 (seen) + "
         f"{report.get('heldout_catalog_size', 0)} held-out v1 (seen) + "
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


def _ru_text(ru: dict[str, Any] | str, label: str) -> str:
    if isinstance(ru, str):
        return ru
    if "status" in ru:
        return ru["status"]
    k = ru["requirements"]
    return (f"{label} (n={k}): parsed exact {ru['target_exact_parsed']}/{k}, P/R/F1 "
            f"{_f(ru['target_precision_parsed'])}/{_f(ru['target_recall_parsed'])}/"
            f"{_f(ru['target_f1_parsed'])}; exercised exact {ru['target_exact_exercised']}/{k}, "
            f"F1 {_f(ru['target_f1_exercised'])}; category recall "
            f"{_pct(ru['category_recall_micro'])} micro / "
            f"{_pct(ru['category_recall_macro'])} macro; precondition recall "
            f"{_pct(ru['precondition_recall_micro'])} micro / "
            f"{_pct(ru['precondition_recall_macro'])} macro; fallback/nothing {ru['fallback']}/{k} "
            f"({ru['fallback_unexpected']} excl. empty-label rows)")


def _kinds_text(counts: dict[str, int] | None) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{k} {v}" for k, v in counts.items() if v) or "none"


def _reasons_text(counts: dict[str, int] | None) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{REJECTION_LABELS[k].split(' (')[0]} {v}"
                     for k, v in counts.items() if v) or "none"


def _headline(report: dict[str, Any]) -> list[str]:
    h = report["headline"]
    same = "same (LLM-independent)"
    agr, gold, can = h["simulator_rules_agreement"], h["gold_clean_pass"], h["udsoncan_virtual_can"]
    held, cov, cit = h["heldout_bug_detection"], h["coverage"], h["citation_validity"]
    held2, ins = h["heldout_v2_bug_detection"], h["in_sample_bug_detection"]
    held3, conf = h["heldout_v3_bug_detection"], h["conformance_sweep"]
    can_txt = can["status"].upper() + (f" — `{can['error']}`" if can.get("error") else "")

    def by_mode(row: dict[str, Any], fmt: Callable[[dict[str, Any]], str],
                key: str = "by_mode") -> list[str]:
        bm = row.get(key, {})
        return [fmt(bm[m]) if isinstance(bm.get(m), dict) else str(bm.get(m, "not run"))
                for m in MODES]

    def det_fmt(n: int, bold: bool = True) -> Callable[[dict[str, Any]], str]:
        def fmt(v: dict[str, Any]) -> str:
            gen = (f"generated {v['generated']['detected']}/{n} ({_pct(v['generated']['rate'])})")
            return (f"**{gen}**" if bold else gen) + (
                f" · gold {v['gold']['detected']}/{n} ({_pct(v['gold']['rate'])}) · union "
                f"{v['union']['detected']}/{n} ({_pct(v['union']['rate'])})")
        return fmt

    def cell3(key: str, bold: bool = False) -> Callable[[dict[str, Any]], str]:
        def fmt(v: dict[str, Any]) -> str:
            if "status" in v:
                return str(v["status"])
            x = v[key]
            if not isinstance(x, dict):
                return str(x)
            txt = f"{x['detected']}/{x['bugs']} ({_pct(x['rate'])})"
            return f"**{txt}**" if bold else txt
        return fmt

    def v3_missed(v: dict[str, Any]) -> str:
        miss = v.get("missed_by_headline")
        if miss is None:
            return str(v.get("status", "n/a"))
        return ", ".join(f"`{x['bug_id']}`" for x in miss) or "none"

    def supp_fmt(prefix: str, pairs: tuple[tuple[str, str], ...]) -> Callable[[dict[str, Any]], str]:
        def fmt(v: dict[str, Any]) -> str:
            parts = []
            for key, label in pairs:
                x = v.get(key)
                parts.append(f"{label} {x['detected']}/{x['bugs']} ({_pct(x['rate'])}), "
                             f"{x['tests']} tests" if isinstance(x, dict) else f"{label}: {x}")
            return prefix + "; ".join(parts)
        return fmt

    def sizes_fmt(v: dict[str, Any]) -> str:
        s = v.get("suite_sizes")
        if not s:
            return str(v.get("status", "n/a"))
        full = s["full_output"] if s["full_output"] is not None else "n/a"
        sweep = s["conformance"] if s["conformance"] is not None else "n/a"
        return (f"requirement-driven {s['requirement_driven']} · sweep {sweep} · full output "
                f"{full} · gold {s['gold']}")

    def full_cell(v: Any) -> str:
        if isinstance(v, dict):
            return f"{v['detected']}/{v['bugs']} ({_pct(v['rate'])})"
        return str(v)

    def cov_fmt(v: dict[str, Any]) -> str:
        tot = v["category_totals"]
        return (", ".join(f"{c} {tot[c]}" for c in CATEGORIES)
                + "; requirements with ≥1 test "
                + _frac(v["requirements_with_tests"], v["requirements"], v["rate"]))

    def cit_fmt(v: dict[str, Any]) -> str:
        return _frac(v["valid"], v["citations"], v["rate"])

    def ru(key: str, label: str) -> list[str]:
        return [_ru_text(h[key].get(m, "not run"), label) for m in MODES]

    def ru_extra(key: str, fn: Callable[[dict[str, Any]], str]) -> list[str]:
        return [fn(h[key][m]) if isinstance(h[key].get(m), dict) and "status" not in h[key][m]
                else str(h[key].get(m, "not run")) for m in MODES]

    def noise_cell(m: str) -> str:
        nc = report["modes"].get(m, {}).get("noise_check", {})
        if report["modes"].get(m, {}).get("status") != "completed":
            return "not run"
        if nc.get("status") != "completed":
            return "not run"
        sp = nc["summary"]
        if nc.get("deterministic"):
            return (f"deterministic: {len(nc['runs'])} run + equality re-run "
                    f"(identical = {nc['determinism_check']['second_run_identical']})")

        def c(key: str, fmt: Callable[[float | None], str]) -> str:
            x = sp[key]
            return "n/a" if x["mean"] is None else f"{fmt(x['mean'])} ({fmt(x['min'])}–{fmt(x['max'])})"
        return (f"{len(nc['runs'])} runs, mean (min–max) over ALL runs: parsed F1 "
                f"{c('parsed_f1', _f)}; category recall {c('category_recall_micro', _pct)}; "
                f"precondition recall {c('precondition_recall_micro', _pct)}")

    if conf.get("status") == "completed":
        rt = conf["bug_matrix_runtime_s"]
        conf_txt = (f"{conf['tests']} tests ({conf['steps']} steps), generated in "
                    f"{conf['generation_s']} s, clean run {conf['clean_run_s']} s, bug-matrix "
                    f"runtime {rt['total']} s over all catalogs; "
                    f"{conf['clean_simulator_passed']}/{conf['tests']} pass on the clean "
                    f"simulator; byte provenance {'OK' if conf['provenance_ok'] else 'FAILED'}")
    else:
        conf_txt = f"not run ({conf.get('reason', conf.get('status'))})"

    rows = [
        [("**1. FRESH HEADLINE — Held-out v3 bugs (15 fresh bugs): detection by the system's FULL "
          "OUTPUT = requirement-driven tests ∪ conformance sweep**"),
         *by_mode(held3, cell3("full_output", bold=True))],
        ["1a. (a) requirement-driven tests only (the Part C 'generated' suite)",
         *by_mode(held3, cell3("requirement_driven"))],
        ["1b. (b) conformance sweep alone (LLM-independent)",
         *by_mode(held3, cell3("conformance"))],
        ["1c. gold tests (LLM-independent)", *by_mode(held3, cell3("gold"))],
        ["1d. suite sizes (tests)", *by_mode(held3, sizes_fmt)],
        ["1e. missed by the headline suite (the full output; requirement-driven if the sweep was skipped)", *by_mode(held3, v3_missed)],
        ["1f. supplementary: v3 bugs detected by other suites",
         *by_mode(held3, supp_fmt("", (
             ("all_generated", "all generated tests (seed + natural v1 + v2 + v3)"),
             ("natural_v3_generated", "natural-v3 tests alone"))), "supplementary_by_mode")],
        ["**2. FRESH HEADLINE — Requirement understanding, natural v3 (split test3)**",
         *ru("requirement_understanding_v3", "test3")],
        ["2a. natural v3: parsed false positives / false negatives by kind",
         *ru_extra("requirement_understanding_v3",
                   lambda r: f"FP [{_kinds_text(r.get('fp_by_kind'))}]; "
                             f"FN [{_kinds_text(r.get('fn_by_kind'))}]")],
        ["2b. natural v3: rejected planner choices by reason",
         *ru_extra("requirement_understanding_v3",
                   lambda r: f"{r.get('rejected', 'n/a')} ({_reasons_text(r.get('rejected_by_reason'))})")],
        ["2c. natural v3: run-to-run noise check", *[noise_cell(m) for m in MODES]],
        ["3. Simulator ↔ rules-engine agreement (seeded random sample, live)",
         _frac(agr["agreed"], agr["total"], agr["rate"]), same],
        ["4. Gold tests passing on the bug-free simulator",
         _frac(gold["passed"], gold["total"], gold["rate"]), same],
        ["5. udsoncan virtual-CAN sequence (session → seed/key → read → write → read-back)",
         can_txt, same],
        ["6. Coverage (seed requirements; tests per category)", *by_mode(cov, cov_fmt)],
        ["7. Citation validity", *by_mode(cit, cit_fmt)],
        ["8. Conformance sweep (size, time, runtime; no LLM)", conf_txt, same],
        [(f"9. Held-out v2 bug detection ({held2['bugs']} bugs) — **SEEN (Part C headline; "
          "its results were known before Part D)**"),
         *by_mode(held2, det_fmt(held2["bugs"], bold=False))],
        ["9a. held-out v2 (SEEN): full output = requirement-driven ∪ sweep",
         *[full_cell(held2["full_output_by_mode"].get(m, "not run")) for m in MODES]],
        ["10. Requirement understanding, natural v2 (split test2) — **SEEN**",
         *ru("requirement_understanding_v2", "test2")],
        [(f"11. Held-out v1 bug detection ({held['bugs']} bugs) — **SEEN (templates designed "
          "against these misses)**"), *by_mode(held, det_fmt(held["bugs"], bold=False))],
        ["11a. held-out v1 (SEEN): full output",
         *[full_cell(held["full_output_by_mode"].get(m, "not run")) for m in MODES]],
        ["12. Requirement understanding, natural v1 test split — **SEEN**",
         *ru("requirement_understanding", "test split")],
        ["13. Requirement understanding, natural v1 dev split — **dev (tuned on)**",
         *ru("requirement_understanding_dev", "dev split")],
        [(f"14. In-sample bug detection ({ins['bugs']} bugs) — **in-sample (templates tuned on "
          "these)**"), *by_mode(ins, det_fmt(ins["bugs"], bold=False))],
        ["14a. in-sample (tuned on): full output",
         *[full_cell(ins["full_output_by_mode"].get(m, "not run")) for m in MODES]],
    ]
    lines = ["## Headline metrics", ""]
    lines += _table(["Metric", "mock", "ollama"], rows)
    lines += [
        "",
        ("Rows 1-2 are the FRESH HEADLINE: both v3 data sets were written blind, after the Part D "
         "freeze, and nothing was tuned on them. The bug headline is the system's FULL OUTPUT "
         "(requirement-driven tests plus the conformance sweep, per bug); rows 1a-1c report its "
         "parts separately so Part C numbers stay comparable. Rows 3-5, 8 and the gold figures "
         "do not depend on the LLM; everything else is measured per mode. Rows 9-14 are SEEN or "
         "tuned-on sets (v1 and v2 results were known when Part D was designed; the natural v1 "
         "dev split shaped the prompts; the 26 in-sample bugs shaped the templates) and are not "
         "independent evidence. The self-consistency check (expected responses vs the oracle "
         "that produced them) is in the appendix."),
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


# ----------------------------------------------------------------------------- noise check


def _noise_section(report: dict[str, Any]) -> list[str]:
    lines = ["## Noise check — natural v3 (FRESH), run-to-run variation", ""]
    any_shown = False
    for mode in _completed(report):
        nc = report["modes"][mode].get("noise_check", {})
        if nc.get("status") != "completed":
            lines += [f"- `{mode}`: not run", ""]
            continue
        any_shown = True
        runs, summ = nc["runs"], nc["summary"]
        lines += [(f"### mode={mode}: {len(runs)} run(s) over the 16 natural-v3 requirements "
                   f"(requested {nc['requested_runs']})"), ""]
        rows = [[f"{r['run']}" + (" (used for the main tables)" if r["used_for_main_tables"]
                                    else " (extra)"),
                 _f(r["parsed_precision"]), _f(r["parsed_recall"]), _f(r["parsed_f1"]),
                 _f(r["exercised_f1"]), _pct(r["category_recall_micro"]),
                 _pct(r["precondition_recall_micro"]), r["tests_kept"], r["rejected"],
                 r["fallback_events"],
                 f"{r['provenance']['passed']}/{r['provenance']['checked']}"
                 + ("" if r["provenance"]["ok"] else " **FAILED**")] for r in runs]

        def cell(key: str, fmt: Callable[[float | None], str], summ: dict[str, Any] = summ) -> str:
            sp = summ[key]
            if sp["mean"] is None:
                return "n/a"
            return f"{fmt(sp['mean'])} ({fmt(sp['min'])}–{fmt(sp['max'])})"

        def num(v: float | None) -> str:
            return "n/a" if v is None else f"{v:.2f}".rstrip("0").rstrip(".")

        rows.append(["**mean (min–max) over all runs**",
                     cell("parsed_precision", _f), cell("parsed_recall", _f),
                     cell("parsed_f1", _f), cell("exercised_f1", _f),
                     cell("category_recall_micro", _pct), cell("precondition_recall_micro", _pct),
                     cell("tests_kept", num), cell("rejected", num), cell("fallback_events", num),
                     "-"])
        lines += _table(["Run", "Parsed P", "Parsed R", "Parsed F1", "Exercised F1",
                         "Category recall (micro)", "Precondition recall (micro)", "Tests kept",
                         "Rejected choices", "Fallback events", "Byte provenance"], rows)
        lines += ["", f"_{nc['note']}_"]
        dc = nc.get("determinism_check")
        if dc:
            lines += ["", (f"Determinism check: a second `{mode}` run over natural v3 was "
                          f"identical = **{dc['second_run_identical']}** (compared: "
                          f"{dc['compared']}).")]
        lines.append("")
    if not any_shown:
        lines += ["No mode produced a noise check in this invocation.", ""]
    return lines


# ----------------------------------------------------------------------------- side by side


def _ru_split_rows(report: dict[str, Any], split: str,
                   key: str = "requirement_understanding") -> list[list[Any]]:
    def get(fn: Callable[[dict[str, Any]], str]) -> list[Any]:
        def inner(blk: dict[str, Any]) -> str:
            ru = blk.get(key, {})
            if "splits" not in ru or split not in ru["splits"]:
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


def _per_req_understanding(report: dict[str, Any], split: str,
                           key: str = "requirement_understanding") -> list[str]:
    done = _completed(report)
    by_mode = {m: {r["id"]: r for r in report["modes"][m][key].get("per_requirement", [])}
               for m in done}
    ids = [r["id"] for r in report["modes"][done[0]][key].get("per_requirement", [])
           if r["split"] == split]
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
    v3, v2, v1 = ("requirement_understanding_v3", "requirement_understanding_v2",
                  "requirement_understanding")
    lines = [
        "### Requirement understanding — natural v3 (split test3): FRESH HEADLINE",
        "",
        ("Natural requirements from `data/requirements_natural_v3.csv`: 16 rows written blind "
         "after the Part D freeze, by a subagent that could not see any natural set or any code. "
         "Nothing was tuned on them. Same label schema and scoring as v1 and v2."),
        "",
    ]
    lines += _table(["Metric", "mock", "ollama"], _ru_split_rows(report, "test3", v3))
    lines += ["", "Per requirement, natural v3 (misses shown):", ""]
    lines += _per_req_understanding(report, "test3", v3)
    lines += [
        "",
        "### Requirement understanding — natural v2 (split test2): SEEN",
        "",
        ("Natural requirements from `data/requirements_natural_v2.csv`. Fresh in Part C; their "
         "Part C results were known before Part D, so they are SEEN. A single run per mode."),
        "",
    ]
    lines += _table(["Metric", "mock", "ollama"], _ru_split_rows(report, "test2", v2))
    lines += ["", "Per requirement, natural v2 (misses shown):", ""]
    lines += _per_req_understanding(report, "test2", v2)
    lines += [
        "",
        "### Requirement understanding — natural v1 TEST split: SEEN",
        "",
        ("Natural requirements from `data/requirements_natural.csv`. The template set was "
         "designed after these results, so they are no longer independent. The prompts were "
         "tuned on the 8 dev rows only."),
        "",
    ]
    lines += _table(["Metric", "mock", "ollama"], _ru_split_rows(report, "test", v1))
    lines += ["", "Per requirement, v1 test split:", ""]
    lines += _per_req_understanding(report, "test", v1)
    for split in ("dev", "all"):
        lines += ["", f"### Requirement understanding — natural v1 {split} split"
                  + (" (dev: the rows the prompts were tuned on)" if split == "dev" else ""), ""]
        lines += _table(["Metric", "mock", "ollama"], _ru_split_rows(report, split, v1))
    lines += ["", "Per requirement, v1 dev split:", ""]
    lines += _per_req_understanding(report, "dev", v1)
    lines.append("")
    lines += _breakdown_tables(report)
    return lines


def _side_bugs(report: dict[str, Any]) -> list[str]:
    def det(key: str, which: str) -> Callable[[dict[str, Any]], str]:
        def fn(blk: dict[str, Any]) -> str:
            d = blk[key][which]
            return _frac(d["detected"], d["bugs"], d["rate"])
        return fn

    def supp(name: str) -> Callable[[dict[str, Any]], str]:
        def fn(blk: dict[str, Any]) -> str:
            x = blk["heldout_v2_bug_detection"].get("supplementary", {}).get(name)
            if not isinstance(x, dict):
                return str(x)
            return f"{_frac(x['detected'], x['bugs'], x['rate'])} ({x['tests']} tests)"
        return fn

    done = _completed(report)

    def per_bug_table(key: str) -> list[str]:
        per = {m: {b["bug_id"]: b for b in report["modes"][m][key]["generated"]["per_bug"]}
               for m in done}
        gold_by = {b["bug_id"]: b for b in report["modes"][done[0]][key]["gold"]["per_bug"]}
        rows = []
        for bug_id, b in per[done[0]].items():
            cells = []
            for m in MODES:
                x = per.get(m, {}).get(bug_id)
                cells.append("not run" if x is None else
                             ("yes" if x["detected"] else "**no**")
                             + f" ({len(x['detecting_tests'])} tests)")
            rows.append([f"`{bug_id}`", b["category"], *cells,
                         "yes" if gold_by.get(bug_id, {}).get("detected") else "**no**"])
        return _table(["Bug", "Category", "mock generated", "ollama generated", "gold"], rows)

    lines = _side_v3_bugs(report) + [
        "",
        "### Held-out v2 bug detection (15 bugs) — SEEN: generated suite, gold, union",
        "",
        ("\"Generated suite\" = tests generated from the 15 seed requirements (the Part C "
         "headline definition). These 15 bugs were fresh in Part C and are SEEN now. The last "
         "rows are supplementary and use other test sets."),
        "",
    ]
    lines += _table(["Suite", "mock", "ollama"], [
        ["Generated (Part C headline definition)",
         *_cells(report, det("heldout_v2_bug_detection", "generated"))],
        ["Gold (LLM-independent)", *_cells(report, det("heldout_v2_bug_detection", "gold"))],
        ["Union generated ∪ gold", *_cells(report, det("heldout_v2_bug_detection", "union"))],
        ["Generated tests (seed requirements)",
         *_cells(report, lambda b: str(b["generated_tests"]["count"]))],
        ["Invalid generated tests (fail on clean simulator)",
         *_cells(report, lambda b: str(len(b["heldout_v2_bug_detection"]["generated"]["invalid_tests"])))],
        ["Supplementary: union of ALL generated tests (seed + natural v1 + natural v2)",
         *_cells(report, supp("all_generated"))],
        ["Supplementary: tests generated from natural v2 alone",
         *_cells(report, supp("natural_v2_generated"))],
    ])
    lines += ["", "Per held-out v2 bug (generated suite):", ""]
    lines += per_bug_table("heldout_v2_bug_detection")
    lines += ["", "### Held-out v1 bug detection (12 bugs) — SEEN (templates designed against these misses)", ""]
    lines += _table(["Suite", "mock", "ollama"], [
        ["**Generated**", *_cells(report, det("heldout_bug_detection", "generated"))],
        ["Gold (LLM-independent)", *_cells(report, det("heldout_bug_detection", "gold"))],
        ["Union generated ∪ gold", *_cells(report, det("heldout_bug_detection", "union"))],
        ["Generated tests (seed requirements)",
         *_cells(report, lambda b: str(b["generated_tests"]["count"]))],
        ["Invalid generated tests (fail on clean simulator)",
         *_cells(report, lambda b: str(len(b["heldout_bug_detection"]["generated"]["invalid_tests"])))],
    ])
    lines += ["", "Per held-out v1 bug (generated suite):", ""]
    lines += per_bug_table("heldout_bug_detection")
    lines += ["", "### In-sample bug detection (26 bugs — in-sample, templates tuned on these)", ""]
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
    for key in ("pipeline_natural", "pipeline_natural_v2", "pipeline_natural_v3"):
        rows.update({r["requirement_id"]: r for r in blk.get(key, {}).get("per_requirement", [])})
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
        return int(blk["pipeline"].get(key, 0)) + sum(
            int(blk.get(k, {}).get(key, 0)) for k in ("pipeline_natural", "pipeline_natural_v2", "pipeline_natural_v3"))

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
        ("Per requirement (15 seed + 20 natural v1 + 16 natural v2 + 16 natural v3). *rejected* = planner choices refused (unknown "
         "template/option, outside the shortlist, or failed validation); *retries* = re-plan "
         "rounds (plan attempts − 1); *dropped* = instantiated tests that failed validation."),
        "",
    ]
    lines += _table(["Req", "Split",
                     "mock tests", "mock rejected", "mock retries", "mock plan attempts",
                     "mock dropped",
                     "ollama tests", "ollama rejected", "ollama retries", "ollama plan attempts",
                     "ollama dropped"], rows)
    lines += ["", "LLM call counters (all 67 requirements):", ""]
    lines += _table(["Counter", "mock", "ollama"], [
        [label, *_cells(report, lambda b, k=key: str(tot(b, k)))]
        for label, key in (("LLM calls", "llm_calls"), ("Explain LLM calls", "explain_llm_calls"),
                           ("JSON/schema failures", "llm_json_failures"),
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
        [f"{scope.replace('_', ' ')} (n={n})",
         *_cells(report, lat(scope, "mean")), *_cells(report, lat(scope, "p95")),
         *_cells(report, lat(scope, "max"))]
        for scope, n in (("seed", report["requirements"]),
                         ("natural", report.get("natural_requirements", 0)),
                         ("all", report["requirements"] + report.get("natural_requirements", 0)),
                         ("natural_v2", report.get("natural_requirements_v2", 0)),
                         ("natural_v3", report.get("natural_requirements_v3", 0)),
                         ("all_with_v2", report["requirements"]
                          + report.get("natural_requirements", 0)
                          + report.get("natural_requirements_v2", 0)),
                         ("all_with_v3", report["requirements"]
                          + report.get("natural_requirements", 0)
                          + report.get("natural_requirements_v2", 0)
                          + report.get("natural_requirements_v3", 0)))
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

    def noise_prov(blk: dict[str, Any]) -> str:
        extra = blk["provenance"].get("noise_extra_runs", [])
        if not extra:
            return "none (no extra runs)"
        done_n = sum(e["provenance"]["passed"] for e in extra)
        all_n = sum(e["provenance"]["checked"] for e in extra)
        ok = all(e["provenance"]["ok"] for e in extra)
        return f"{done_n}/{all_n} passed over {len(extra)} run(s)" + ("" if ok else " — **FAILED**")

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
        ["Byte provenance — natural v1 requirement tests", *_cells(report, prov("natural"))],
        ["Byte provenance — natural v2 requirement tests", *_cells(report, prov("natural_v2"))],
        ["Byte provenance — natural v3 requirement tests", *_cells(report, prov("natural_v3"))],
        ["Byte provenance — extra noise-check runs (natural v3)", *_cells(report, noise_prov)],
        ["**Byte provenance — all generated tests, all runs**", *_cells(report, prov("total"))],
    ]
    lines += _table(["Metric", "mock", "ollama"], rows)
    done = _completed(report)
    if done:
        lines += ["", f"_Byte provenance: {report['modes'][done[0]]['provenance']['seed']['definition']}_"]
    for m in done:
        p = report["modes"][m]["provenance"]
        fails = provenance_failures(p)
        if fails:
            lines += ["", f"**Byte-provenance failures — `{m}`:**", ""]
            lines += [f"- `{f['test_id']}` ({f['template_id']}): {_esc('; '.join(f['problems']))}"
                      for f in fails]
    lines.append("")
    return lines


def _yn(x: bool | None) -> str:
    return "n/a" if x is None else ("yes" if x else "**no**")


def _v3_det_row(blk: dict[str, Any], key: str) -> str:
    v3 = blk.get("heldout_v3_bug_detection", {})
    x = v3.get(key)
    if not isinstance(x, dict):
        return str(x if x is not None else v3.get("status", "n/a"))
    return _frac(x["detected"], x["bugs"], x["rate"])


def _side_v3_bugs(report: dict[str, Any]) -> list[str]:
    done = _completed(report)
    lines = [
        "### Held-out v3 bug detection (15 FRESH bugs) — FRESH HEADLINE: full output",
        "",
        (f"{HELDOUT_V3_NOTE} The rows below split the headline into its parts. \"Full output\" is "
         "the per-bug union of (a) and (b)."),
        "",
    ]
    lines += _table(["Suite", "mock", "ollama"], [
        ["**(c) Full output = (a) ∪ (b) — headline**",
         *_cells(report, lambda b: f"**{_v3_det_row(b, 'full_output')}**")],
        ["(a) Requirement-driven (seed requirements; Part C 'generated' suite)",
         *_cells(report, lambda b: _v3_det_row(b, "requirement_driven"))],
        ["(b) Conformance sweep alone (LLM-independent)",
         *_cells(report, lambda b: _v3_det_row(b, "conformance"))],
        ["(d) Gold (LLM-independent)", *_cells(report, lambda b: _v3_det_row(b, "gold"))],
        ["Suite sizes (tests): requirement-driven / sweep / full output",
         *_cells(report, lambda b: " / ".join(
             str(b["heldout_v3_bug_detection"]["suite_sizes"].get(k)) for k in
             ("requirement_driven", "conformance", "full_output"))
             if "suite_sizes" in b["heldout_v3_bug_detection"] else "n/a")],
        ["Supplementary: union of ALL generated tests (seed + natural v1 + v2 + v3)",
         *_cells(report, lambda b: _supp_txt(b, "all_generated"))],
        ["Supplementary: tests generated from natural v3 alone",
         *_cells(report, lambda b: _supp_txt(b, "natural_v3_generated"))],
    ])
    if not done:
        return lines
    ref = report["modes"][done[0]]["heldout_v3_bug_detection"]
    if "per_bug" not in ref:
        return lines + ["", f"Not run: {ref.get('status')}.", ""]
    by_mode = {m: {b["bug_id"]: b for b in report["modes"][m]["heldout_v3_bug_detection"]["per_bug"]}
               for m in done}
    rows = []
    for b in ref["per_bug"]:
        bid = b["bug_id"]
        row: list[Any] = [f"`{bid}`", b["category"]]
        for m in MODES:
            x = by_mode.get(m, {}).get(bid)
            row += (["not run"] * 3 if x is None else
                    [_yn(x["requirement_driven"]), _yn(x["conformance"]), _yn(x["full_output"])])
        row.append(_yn(b["gold"]))
        rows.append(row)
    lines += ["", "Per held-out v3 bug (which suite detected it):", ""]
    lines += _table(["Bug", "Category", "mock (a) req-driven", "mock (b) sweep", "mock (c) full",
                     "ollama (a) req-driven", "ollama (b) sweep", "ollama (c) full", "gold"], rows)
    lines.append("")
    return lines


def _supp_txt(blk: dict[str, Any], name: str) -> str:
    x = blk.get("heldout_v3_bug_detection", {}).get("supplementary", {}).get(name)
    if not isinstance(x, dict):
        return str(x if x is not None else "n/a")
    return f"{_frac(x['detected'], x['bugs'], x['rate'])} ({x['tests']} tests)"


def _heldout_v3(blk: dict[str, Any], mode: str) -> list[str]:
    held = blk["heldout_v3_bug_detection"]
    lines = [f"## Held-out v3 bug detection (15 FRESH bugs) — FRESH HEADLINE — mode={mode}", ""]
    if "per_bug" not in held:
        return lines + [f"Not run: {held.get('status')}.", ""]
    lines += [f"Scope: {held['scope']}. Catalog: `{held['catalog']}`.", "", HELDOUT_V3_NOTE, ""]
    rows = []
    for b in held["per_bug"]:
        tc = b["trigger_counts"]
        headline_hit = (b["full_output"] if b["full_output"] is not None
                        else b["requirement_driven"])
        rows.append([
            f"`{b['bug_id']}`", b["category"],
            _yn(b["requirement_driven"]), b["requirement_driven_detecting_tests"],
            _yn(b["conformance"]), b["conformance_detecting_tests"]
            if b["conformance_detecting_tests"] is not None else "n/a",
            _yn(b["full_output"]), _yn(b["gold"]), _yn(b["all_generated"]), _yn(b["natural_v3"]),
            ", ".join(f"{k}={v}" for k, v in tc.items()),
            "-" if headline_hit else _esc(b["reason_if_missed"] or "-"),
        ])
    lines += _table(
        ["Bug", "Category", "(a) req-driven", "tests", "(b) sweep", "tests", "(c) full output",
         "gold", "all generated (suppl.)", "natural v3 (suppl.)",
         "tests applying the trigger, per suite", "reason if missed by the headline suite"], rows)
    gen, gold, ful = held["requirement_driven"], held["gold"], held["full_output"]
    conf = held["conformance"]
    lines += [
        "",
        (f"Totals: (a) requirement-driven {_frac(gen['detected'], gen['bugs'], gen['rate'])}, "
         f"(b) sweep alone "
         f"{_frac(conf['detected'], conf['bugs'], conf['rate']) if isinstance(conf, dict) else conf}"
         f", (c) full output "
         f"{_frac(ful['detected'], held['bugs'], round(ful['detected'] / held['bugs'], 4)) if isinstance(ful, dict) else ful}"
         f", gold {_frac(gold['detected'], gold['bugs'], gold['rate'])}. Invalid tests (fail on "
         f"the clean simulator): requirement-driven {gen['invalid_tests']}, gold "
         f"{gold['invalid_tests']}."),
        "",
        "### Trigger coverage: how many bugs' stimuli each suite applies (coverage report only)",
        "",
    ]
    lines += _table(["Suite", "bugs whose stimulus is applied", "total stimulus applications"], [
        [name, f"{v['bugs_with_stimulus']}/{v['bugs']}", v["stimulus_applications"]]
        for name, v in held["trigger_summary"].items()])
    lines += ["", f"### Missed v3 bugs — {held['headline_suite']} (the headline suite, mode={mode})",
              ""]
    lines += [f"- `{x['bug_id']}`: {x['reason']}" for x in held["missed_by_headline"]] or ["- none"]
    for name in ("requirement_driven", "conformance", "gold"):
        block = held["analysis"].get(name)
        if block is None:
            continue
        lines += ["", f"### Missed v3 bugs — {name.replace('_', '-')} suite", ""]
        lines += [f"- `{x['bug_id']}`: {x['reason']}" for x in block["missed"]] or ["- none"]
    for name, title in (("all_generated", "all generated tests (supplementary)"),
                        ("natural_v3_generated", "natural-v3 tests alone (supplementary)")):
        block = held["analysis"].get(name)
        if block is None:
            continue
        lines += ["", f"### Missed v3 bugs — {title}", ""]
        lines += [f"- `{x['bug_id']}`: {x['reason']}" for x in block["missed"]] or ["- none"]
    lines += [
        "",
        ("_Reasons come from `uds_assistant/eval/heldout_v3.py`: one predicate per bug, written "
         "only from the bug descriptions in `data/bugs/heldout_v3_catalog.yaml` and "
         "`docs/behaviour_contract.md` before any v3 result existed. \"no X test ...\" means no "
         "test in that suite applies the stimulus; \"N X test(s) ..., but none of their expected "
         "responses differs\" means the stimulus is present but the oracle-derived expectations "
         "do not distinguish the bug. Reporting only — nothing was changed in response._"),
        "",
    ]
    return lines


def _breakdown_tables(report: dict[str, Any]) -> list[str]:
    """Parsed FP / FN by kind and rejected choices by reason, for every set and mode."""
    sets = (
        ("natural v3 (FRESH, test3)", "requirement_understanding_v3", "test3"),
        ("natural v2 (SEEN, test2)", "requirement_understanding_v2", "test2"),
        ("natural v1 test split (SEEN)", "requirement_understanding", "test"),
        ("natural v1 dev split (tuned on)", "requirement_understanding", "dev"),
    )
    lines = ["### Parsed false positives and false negatives by kind (every set, every mode)",
             "",
             ("Kind = service / did / routine / dtc (no label or prediction names a DTC, so that "
              "row is zero). tp = label items of the kind minus the missed ones."), ""]
    for title, key, split in sets:
        def kind_cells(blk: dict[str, Any], key: str = key, split: str = split) -> dict[str, Any] | None:
            ru = blk.get(key, {})
            if "splits" not in ru or split not in ru["splits"]:
                return None
            return ru["splits"][split].get("by_kind", {}).get("parsed")

        tables = {m: kind_cells(report["modes"][m]) if m in _completed(report) else None
                  for m in MODES}
        kinds = list(next((t for t in tables.values() if t), {}))
        rows = []
        for kind in kinds:
            row: list[Any] = [kind]
            for m in MODES:
                t = tables[m]
                row += ["not run"] * 3 if t is None else [t[kind]["tp"], t[kind]["fp"], t[kind]["fn"]]
            rows.append(row)
        lines += [f"**{title}**", ""]
        lines += _table(["Kind", "mock tp", "mock FP", "mock FN", "ollama tp", "ollama FP",
                         "ollama FN"], rows)
        lines.append("")
    lines += ["### Rejected planner choices by reason (every set, every mode)", ""]
    pipes = (("15 seed requirements", "pipeline", None),
             ("natural v1 (20 requirements, SEEN)", "pipeline_natural", None),
             ("natural v2 (16, SEEN)", "pipeline_natural_v2", None),
             ("natural v3 (16, FRESH)", "pipeline_natural_v3", None))
    rows = []
    for title, key, _ in pipes:
        for reason, label in REJECTION_LABELS.items():
            row = [title if reason == REJECTION_REASONS[0] else "", label.split(" (")[0]]
            for m in MODES:
                blk = report["modes"].get(m, {})
                pipe = blk.get(key, {}) if blk.get("status") == "completed" else {}
                row.append(pipe["rejected_by_reason"][reason]
                           if "rejected_by_reason" in pipe else "not run")
            rows.append(row)
        row = ["", "**total**"]
        for m in MODES:
            blk = report["modes"].get(m, {})
            pipe = blk.get(key, {}) if blk.get("status") == "completed" else {}
            row.append(f"**{pipe['rejected']}**" if "rejected" in pipe else "not run")
        rows.append(row)
    lines += _table(["Set", "Reason", "mock", "ollama"], rows)
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


def _missed_lines(ana: dict[str, Any], suite: str) -> list[str]:
    block = ana.get(suite)
    if block is None:
        return ["- not run"]
    return [f"- `{m['bug_id']}`: {m['reason']}" for m in block["missed"]] or ["- none"]


def _heldout(blk: dict[str, Any], mode: str) -> list[str]:
    held = blk["heldout_bug_detection"]
    gen, gold, union = held["generated"], held["gold"], held["union"]
    ana = held["analysis"]
    gold_by = {b["bug_id"]: b for b in gold["per_bug"]}
    lines = [
        (f"## Held-out bug detection (12 v1 bugs — SEEN: templates designed against these "
         f"misses) — mode={mode}"),
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
        f"### Missed held-out v1 bugs — generated suite (mode={mode})",
        "",
    ]
    lines += _missed_lines(ana, "generated")
    lines += ["", "### Missed held-out v1 bugs — gold suite", ""]
    lines += _missed_lines(ana, "gold")
    lines += [
        "",
        ("_Reasons come from a static trigger analysis (`uds_assistant/eval/heldout.py`): for "
         "each held-out bug, a predicate written from its catalog description checks whether a "
         "test applies the stimulus the bug needs. Reporting only — nothing in templates, gold "
         "tests, mock LLM or planner was changed in response._"),
        "",
    ]
    return lines


def _heldout_v2(blk: dict[str, Any], mode: str) -> list[str]:
    held = blk["heldout_v2_bug_detection"]
    gen, gold, union = held["generated"], held["gold"], held["union"]
    ana = held["analysis"]
    supp = held.get("supplementary", {})
    gold_by = {b["bug_id"]: b for b in gold["per_bug"]}

    def supp_by(name: str) -> dict[str, Any]:
        x = supp.get(name)
        return {b["bug_id"]: b for b in x["per_bug"]} if isinstance(x, dict) else {}

    all_by, nat_by = supp_by("all_generated"), supp_by("natural_v2_generated")

    def yn(by: dict[str, Any], bug_id: str) -> str:
        return "not run" if bug_id not in by else ("yes" if by[bug_id]["detected"] else "**no**")

    lines = [
        f"## Held-out v2 bug detection (15 bugs, SEEN) — mode={mode}",
        "",
        f"Scope: {held['scope']}. Catalog: `{held['catalog']}`.",
        "",
        ("Generated suite = the tests from the 15 seed requirements (the Part C headline "
         "definition). The two supplementary columns use all generated tests (seed + natural v1 "
         "+ natural v2) and the natural-v2 tests alone."),
        "",
    ]
    rows = []
    for b in gen["per_bug"]:
        g = gold_by.get(b["bug_id"], {})
        bid = b["bug_id"]
        rows.append([
            f"`{bid}`", b["category"],
            "yes" if b["detected"] else "**no**",
            _tests_list(b["detecting_tests"], 2),
            ana["generated"]["trigger_counts"].get(bid, "n/a"),
            "yes" if g.get("detected") else "**no**",
            ana["gold"]["trigger_counts"].get(bid, "n/a"),
            yn(all_by, bid), ana.get("all_generated", {}).get("trigger_counts", {}).get(bid, "n/a"),
            yn(nat_by, bid),
            ana.get("natural_v2_generated", {}).get("trigger_counts", {}).get(bid, "n/a"),
        ])
    lines += _table(
        ["Bug", "Category", "Generated (seed reqs)", "Generated detecting tests",
         "Gen. tests applying trigger", "Gold", "Gold tests applying trigger",
         "All generated (suppl.)", "trigger", "Natural-v2 tests (suppl.)", "trigger"], rows)
    lines += [
        "",
        (f"Totals: generated {_frac(gen['detected'], gen['bugs'], gen['rate'])}, gold "
         f"{_frac(gold['detected'], gold['bugs'], gold['rate'])}, union "
         f"{_frac(union['detected'], union['bugs'], union['rate'])}. Invalid tests (fail on "
         f"the clean simulator): generated {len(gen['invalid_tests'])}, gold "
         f"{len(gold['invalid_tests'])}."),
    ]
    for name, label in (("all_generated", "All generated tests (seed + natural v1 + natural v2)"),
                        ("natural_v2_generated", "Tests generated from natural v2 alone")):
        x = supp.get(name)
        if isinstance(x, dict):
            lines.append(f"- Supplementary — {label}: {x['tests']} tests, "
                         f"{_frac(x['detected'], x['bugs'], x['rate'])} detected "
                         f"({x['invalid_tests']} invalid tests).")
        else:
            lines.append(f"- Supplementary — {label}: {x}")
    lines += ["", f"### Missed held-out v2 bugs — generated suite (mode={mode})", ""]
    lines += _missed_lines(ana, "generated")
    lines += ["", "### Missed held-out v2 bugs — gold suite", ""]
    lines += _missed_lines(ana, "gold")
    lines += ["", "### Missed held-out v2 bugs — all generated tests (supplementary)", ""]
    lines += _missed_lines(ana, "all_generated")
    lines += ["", "### Missed held-out v2 bugs — natural-v2 tests alone (supplementary)", ""]
    lines += _missed_lines(ana, "natural_v2_generated")
    lines += [
        "",
        ("_Reasons come from `uds_assistant/eval/heldout_v2.py`: one predicate per bug, written "
         "only from the bug descriptions in `data/bugs/heldout_v2_catalog.yaml` and "
         "`docs/behaviour_contract.md` before any v2 result existed. \"no test X\" means no test "
         "in that suite applies the stimulus; \"N test(s) X, but none of their expected "
         "responses differs\" means the stimulus is present but the oracle-derived expectations "
         "do not distinguish the bug. Reporting only — nothing was changed in response._"),
        "",
    ]
    return lines


def _understanding(report: dict[str, Any], blk: dict[str, Any], mode: str,
                   key: str = "requirement_understanding") -> list[str]:
    ru = blk.get(key, {})
    is_v2, is_v3 = key.endswith("_v2"), key.endswith("_v3")
    title = ("Requirement understanding, natural v3 (split test3, FRESH HEADLINE)" if is_v3
             else "Requirement understanding, natural v2 (split test2, SEEN)" if is_v2
             else "Requirement understanding (natural requirements) — natural v1: test split SEEN, "
                  "dev tuned on")
    lines = [f"## {title} — mode={mode}", ""]
    if "splits" not in ru:
        return [*lines, "Not run in this invocation.", ""]
    n_rows = report.get("natural_requirements_v3" if is_v3 else
                        "natural_requirements_v2" if is_v2 else "natural_requirements", 0)
    lines += [
        (f"Source: `{ru['source']}` ({n_rows} labelled rows). "
         f"Each requirement was run through the agent pipeline (`mode={mode}`, "
         f"{report['retriever']}). "
         + ("**The test3 split is the main number (fresh, nothing tuned on it).**" if is_v3 else
            "**The test2 split is SEEN (fresh in Part C).**" if is_v2 else
            "**The test split is the v1 number, but it is SEEN; dev is what the prompts were "
            "tuned on.**")),
        "",
    ]
    rows = []
    for split, a in ru["splits"].items():
        tp, te = a["targets_parsed"], a["targets_exercised"]
        cat, pre = a["categories"], a["preconditions"]
        rows.append([
            f"**{split}**" if split in ("test", "test2", "test3") else split, a["requirements"],
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
    set_name = "natural v3" if is_v3 else "natural v2" if is_v2 else "natural v1"
    lines += ["", f"### Per requirement ({set_name}, mode={mode})", ""]
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
        (f"## Secondary: in-sample bug detection (26 bugs — in-sample, templates tuned on these) "
         f"— mode={mode}"),
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
    lines += _heldout_v3(blk, mode)
    lines += _understanding(report, blk, mode, "requirement_understanding_v3")
    lines += _heldout_v2(blk, mode)
    lines += _understanding(report, blk, mode, "requirement_understanding_v2")
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
    section = fr.get("section", "Part D freeze")
    lines = [f"## Freeze verification ({section}: templates / sweep / prompts / agent / gold)", ""]
    lines += [(f"Recorded hashes are parsed from {fr.get('source', 'PROGRESS.md')}; current = "
               "`git rev-parse HEAD:<path>` when this report ran."), ""]
    if fr.get("error"):
        lines += [f"**ERROR: {fr['error']}**", ""]
    rows = [[f"`{p}`", f"`{v['expected']}`", f"`{v['head']}`",
             "match" if v["matches"] else "**MISMATCH**", v["worktree_clean"]]
            for p, v in fr["paths"].items()]
    c = fr.get("commit")
    if c:
        anc = c["recorded_is_ancestor_of_head"]
        rows.insert(0, ["freeze commit", f"`{c['recorded']}`", f"`{c['head']}` (HEAD)",
                        "ancestor of HEAD" if anc else "**NOT an ancestor of HEAD**", "-"])
    lines += _table(["Path", f"recorded ({fr.get('section', 'Part C freeze')})", "current",
                     "result", "worktree clean"], rows)
    lines += ["", f"All recorded freeze hashes match and are clean: **{fr['all_ok']}**.", ""]
    return lines


def _part_d(report: dict[str, Any]) -> list[str]:
    """Part D rows (report version 4): requirement-driven vs conformance sweep vs full output."""
    conf = report.get("conformance")
    if not conf:
        return []
    lines = ["## Part D — conformance sweep and full-output bug detection", ""]
    if conf.get("status") != "completed":
        return lines + [f"Not run: {conf.get('reason', conf.get('status'))}.", ""]
    lines += [
        ("_Part D rows. The existing headline above keeps its Part C meaning (requirement-driven "
         "suite). (a) = requirement-driven tests from the 15 seed requirements (the Part C "
         "'generated' suite); (b) = the requirement-independent conformance sweep alone; (c) = "
         "the system's full output, (a) ∪ (b). The conformance sweep is generated from the spec "
         "alone, uses no LLM and is identical in every mode; only (a), and therefore (c), "
         "depend on the mode._"),
        "",
    ]
    modes = _completed(report)
    header = ["Bug set"] + [f"{m}: (a) / (b) / (c) / gold" for m in modes]
    rows = []
    for key, info in report.get("part_d_catalogs", {}).items():
        cells = [f"{key}: {info['label']}"]
        for m in modes:
            r = report["modes"][m].get("part_d_detection", {}).get(key)
            if not isinstance(r, dict):
                cells.append("not run")
                continue
            a, b, c = r["requirement_driven"], r["conformance"], r["full_output"]
            g = r.get("gold")
            cells.append(f"{a['detected']}/{a['bugs']} / {b['detected']}/{b['bugs']} / "
                         f"**{c['detected']}/{c['bugs']}**"
                         + (f" / {g['detected']}/{g['bugs']}" if g else ""))
        rows.append(cells)
    lines += _table(header, rows)
    lines.append("")
    for m in modes:
        pdd = report["modes"][m].get("part_d_detection", {})
        for key, r in pdd.items():
            if not isinstance(r, dict):
                continue
            missed = r["full_output"]["undetected"]
            lines.append(f"- {m} / {key}: missed by the full output: "
                         f"{', '.join(f'`{x}`' for x in missed) or 'none'}; only the sweep: "
                         f"{len(r['full_output']['only_conformance'])}, only requirement-driven: "
                         f"{len(r['full_output']['only_requirement_driven'])}.")
    prov = conf["provenance"]
    rt = conf["bug_matrix_runtime_s"]
    st = conf["stats"]
    lines += [
        "",
        (f"- **Conformance sweep:** {conf['tests']} tests ({conf['steps']} steps), template "
         f"`{conf['template_id']}` (not offered to the planner); {st['setups']} setups x "
         f"{st['stimuli']} stimuli = {st['candidates']} candidates, cap {st['cap']}."),
        (f"- **Generation time:** {conf['generation_s']} s (selection {st['selection_s']} s, "
         f"instantiation + oracle validation {st['instantiation_s']} s)."),
        f"- **Clean simulator:** {conf['clean_simulator_passed']}/{conf['tests']} pass.",
        (f"- **Byte provenance (conformance):** {prov['passed']}/{prov['checked']} "
         f"{'OK' if prov['ok'] else '**FAILED**'}."),
        ("- **Bug-matrix runtime (conformance sweep):** "
         + ", ".join(f"{k} {v} s" for k, v in rt.items() if k != "total")
         + f"; total {rt['total']} s."),
        "",
        "Selection phases (greedy covering, see metric definitions):",
        "",
    ]
    lines += _table(["Phase", "item kinds", "items", "covered", "tests added"],
                    [[p["phase"], ", ".join(p["kinds"]), p["items"], p["covered"],
                      p["added_tests"]] for p in st["phases"]])
    lines += ["", "Selected tests by stimulus family (service) and by setup dimension:", ""]
    lines += _table(["family", "tests"], [[k, v] for k, v in st["selected_by_family"].items()])
    lines.append("")
    lines += _table(["setup dimension", "tests"],
                    [[k, v] for k, v in st["selected_by_setup_dimension"].items()])
    lines.append("")
    return lines


def _tag(lines: list[str], tag: str | None, only_first: bool = False) -> list[str]:
    """Append ``tag`` to the section headers (``#`` and ``##`` lines) of ``lines``."""
    if not tag:
        return lines
    out: list[str] = []
    done = False
    for line in lines:
        if line.startswith(("# ", "## ")) and not (only_first and done):
            line = f"{line} — {tag}"
            done = True
        out.append(line)
    return out


def _provenance_block(report: dict[str, Any]) -> list[str]:
    """Top-of-report table: every data source with its own date and git hash."""
    prov = report.get("provenance")
    if not prov:
        return []

    def row(name: str, what: str, ref: dict[str, Any] | None) -> list[Any]:
        if not ref:
            return [name, what, "not available", "-", "-"]
        dirty = ref.get("dirty")
        return [name, what, ref.get("timestamp") or "n/a", f"`{ref.get('git_short')}`",
                "yes" if dirty else ("no" if dirty is False else "not recorded")]

    rows = [
        row("Main evaluation", "every section not listed below (bug detection, requirement "
            "understanding, correctness, coverage, noise check, retrieval)", prov.get("main_eval")),
        row("Diagnostic Q&A", "section 'Diagnostic Q&A'", prov.get("qa")),
        row("Tool-side timing", "section 'Tool-side timing'", prov.get("timing")),
    ]
    lines = ["## Run provenance", "",
             ("Each data source below was produced by its own run; every section header states "
              "which one. Numbers are never mixed across runs inside a section. Historical "
              "before/after tables appear only in the final History section."), ""]
    lines += _table(["Data source", "Used for", "Run (UTC)", "Git hash", "Uncommitted changes"], rows)
    hist = prov.get("history", {})
    if hist:
        lines.append("")
        for key, h in hist.items():
            lines.append(f"- History / {key.replace('_', ' ')} (historical): runs "
                         + ", ".join(f"`{x}`" for x in h["run_hashes"])
                         + f" ({', '.join(h['timestamps'])})")
    lines.append("")
    return lines


def _qa_section(report: dict[str, Any]) -> list[str]:
    qa = report.get("qa")
    if not qa:
        return []
    modes = list(qa["modes"])
    lines = [f"## Diagnostic Q&A (blind set `data/qa_eval.csv`) — {run_tag(qa['run'])}", ""]
    first = qa["modes"][modes[0]]
    lines += [(f"{first['n_questions']} questions ({first['n_answerable']} answerable, "
               f"{first['n_unanswerable']} unanswerable). This is its own run, separate from the "
               "main evaluation; per-question rows are in `outputs/qa/qa_eval.md`."), ""]

    def cell(m: str, key: str, n_key: str, den_key: str) -> str:
        r = qa["modes"][m]
        return f"{_pct(r[key])} ({r[n_key]}/{r[den_key]})"

    def prec(m: str) -> str:
        a, b = qa["modes"][m]["citation_precision_counts"]
        return f"{_pct(qa['modes'][m]['citation_precision'])} ({a}/{b})"

    rows = [
        ["answer accuracy (answerable)",
         *[cell(m, "answer_accuracy", "answer_accuracy_n", "n_answerable") for m in modes]],
        ["citation correctness",
         *[cell(m, "citation_correctness", "citation_correctness_n", "n_answerable")
           for m in modes]],
        ["citation precision", *[prec(m) for m in modes]],
        ["correct not-found (unanswerable)",
         *[cell(m, "correct_not_found_rate", "correct_not_found_n", "n_unanswerable")
           for m in modes]],
        ["false not-found (answerable)", *[qa["modes"][m]["false_not_found"] for m in modes]],
        ["LLM fallback events", *[qa["modes"][m]["fallback_events"] for m in modes]],
        ["seconds (all questions)", *[qa["modes"][m]["total_seconds"] for m in modes]],
    ]
    lines += _table(["Metric", *modes], rows)
    lines.append("")
    return lines


def _timing_section(report: dict[str, Any]) -> list[str]:
    tm = report.get("timing")
    if not tm:
        return []
    reqs = tm["requirements"] or []
    lines = [f"## Tool-side timing (generation time per requirement) — {run_tag(tm['run'])}", "",
             (f"{len(reqs)} requirements ({', '.join(reqs)}), {tm['repeats']} repeats each, "
              "in-process wall clock from `scripts/time_generation.py`. This is tool compute time "
              "only; the manual comparison in `docs/TEST_DESIGN_TIME.md` is **pending owner "
              "measurement**. The first mock repeat includes warm-up."), ""]
    modes = list(tm["modes"])
    rows = []
    for rq in reqs:
        cells: list[Any] = [rq]
        for m in modes:
            r = tm["modes"][m]["per_requirement"].get(rq)
            cells.append("n/a" if not r else f"{r['mean_s']} s ({r['min_s']}–{r['max_s']}), "
                         f"{r['tests_generated']} tests")
        rows.append(cells)
    rows.append(["**mean of requirement means**",
                 *[f"{tm['modes'][m]['mean_of_requirement_means_s']} s" for m in modes]])
    lines += _table(["Requirement (mean, min–max over repeats)", *modes], rows)
    lines.append("")
    return lines


def _history_section(report: dict[str, Any]) -> list[str]:
    hist = report.get("history")
    lines = ["## History", ""]
    if not hist:
        return lines + ["_No historical tables found next to this report._", ""]
    lines += [("**Historical, not current results.** These before/after tables compare earlier runs "
               "with the Part C or Part D final reports. They are kept for the record, were "
               "produced by the runs named in each heading, and are not the headline of this "
               "report (see the sections above, each labelled with its own run)."), ""]
    for h in hist.values():
        runs = ", ".join(f"`{x}`" for x in h["run_hashes"]) or "n/a"
        stamps = ", ".join(h["timestamps"]) or "n/a"
        lines += [f"### {h['title']} — **historical** — runs {runs} ({stamps})", "",
                  f"_Source: `{h['source']}`. Headings below are demoted; content is verbatim._", ""]
        body = h["text"].splitlines()
        if body and body[0].startswith("# "):
            body = body[1:]
        lines += [("##" + b) if b.startswith("#") else b for b in body]
        lines.append("")
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    """Return the Markdown report text.

    Order: title and run provenance, the main-run sections (each header carries the main run's
    date and git hash), the Diagnostic Q&A and Tool-side timing sections (own runs), the long
    per-mode details, and last the History section with the historical before/after tables.
    """
    prov = report.get("provenance") or {}
    tag = run_tag(prov["main_eval"]) if prov.get("main_eval") else None
    head = _header(report)
    lines = head[:1] + [""] + _provenance_block(report) + head[1:]
    lines += _tag(_headline(report), tag)
    lines += _tag(_part_d(report), tag)
    lines += _tag(_interpretation(report), tag, only_first=True)
    lines += _tag(_noise_section(report), tag)
    lines += _qa_section(report) + _timing_section(report)
    lines += _tag(_side_by_side(report), tag)
    if "retrieval_comparison" in report:
        lines += _tag(_retrieval_section(report["retrieval_comparison"]), tag)
    lines += _tag(_checks(report), tag)
    lines += _tag(_freeze(report), tag)
    for mode in _completed(report):
        lines += _tag(_mode_details(report, mode), tag)
    shared = ["# Shared", "",
              "### Precondition mapping (how 'established' is derived from test steps)", ""]
    shared += [f"- `{k}`: {v}" for k, v in report.get("precondition_mapping", {}).items()]
    shared.append("")
    shared += _exports(report)
    shared += ["## Runtime", ""]
    shared += _table(["Phase", "seconds"], [[k, v] for k, v in report["runtime_seconds"].items()])
    shared += ["", "## Metric definitions", ""]
    for key, text in report["metric_definitions"].items():
        shared.append(f"- **{key}**: {text}")
    shared.append("")
    lines += _tag(shared, tag)
    lines += _history_section(report)
    return "\n".join(lines)
