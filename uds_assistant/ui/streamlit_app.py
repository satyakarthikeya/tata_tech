"""Streamlit engineering UI for the UDS diagnostics assistant.

Run with::

    streamlit run uds_assistant/ui/streamlit_app.py

Flow: enter a plain-English requirement -> generate cited, validated test
cases -> review them (categories, request/response hex, citations, review
status) -> run them on the ECU simulator, optionally with injected bugs ->
inspect results -> view the mock-mode evaluation report -> export to
pytest/CAPL.

This module calls the pipeline directly (no network hop to the FastAPI
service) and talks to the same :mod:`uds_assistant.store.audit` audit trail.
Nothing else in ``uds_assistant`` imports this module, so the package stays
importable without streamlit installed (see ``uds_assistant/ui/__init__.py``
and ``tests/ui/test_streamlit_app.py``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from uds_assistant.agent import run_pipeline
from uds_assistant.config import get_config
from uds_assistant.export import render_capl, render_pytest
from uds_assistant.llm.factory import get_llm
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.runner import run_suite
from uds_assistant.simulator import HELDOUT_BUG_CATALOG_PATH, HELDOUT_BUG_IDS, load_bug_catalog
from uds_assistant.spec.schema import load_spec
from uds_assistant.store.audit import AuditStore

REPO_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_BANNER = (
    "Generated tests require human review before execution on real hardware. "
    "The ECU spec is synthetic. Audit trail: outputs/ui_audit.sqlite."
)


@st.cache_resource
def _load_backend() -> dict[str, object]:
    cfg = get_config()
    spec = load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")
    corpus = build_corpus(REPO_ROOT)
    retriever = get_retriever(cfg, chunks=corpus)
    llm = get_llm(cfg)
    store = AuditStore(REPO_ROOT / "outputs" / "ui_audit.sqlite")
    catalog = load_bug_catalog()
    try:
        heldout_catalog = load_bug_catalog(HELDOUT_BUG_CATALOG_PATH)
    except (OSError, ValueError):  # held-out catalog missing: in-sample bugs only
        heldout_catalog = None
    return {
        "cfg": cfg,
        "spec": spec,
        "retriever": retriever,
        "llm": llm,
        "store": store,
        "catalog": catalog,
        "heldout_catalog": heldout_catalog,
    }


def _init_state() -> None:
    if "tests" not in st.session_state:
        st.session_state.tests = []
    if "run_id" not in st.session_state:
        st.session_state.run_id = None
    if "requirement_id" not in st.session_state:
        st.session_state.requirement_id = "REQ-UI-001"
    if "run_results" not in st.session_state:
        st.session_state.run_results = None


def _generate_section(backend: dict[str, object]) -> None:
    st.header("1. Generate tests from a requirement")
    requirement_text = st.text_area(
        "Diagnostic requirement (plain English)",
        value="The tester shall be able to read the VIN (DID 0xF190) in any diagnostic session.",
        height=100,
    )
    requirement_id = st.text_input("Requirement id", value=st.session_state.requirement_id)
    if st.button("Generate tests", type="primary"):
        if not requirement_text.strip():
            st.error("Requirement text must not be empty.")
        else:
            with st.spinner("Running parse -> retrieve -> plan -> instantiate -> validate -> explain..."):
                result = run_pipeline(
                    requirement_text,
                    requirement_id,
                    backend["spec"],
                    backend["llm"],
                    backend["retriever"],
                    backend["store"],
                )
            st.session_state.tests = result.tests
            st.session_state.run_id = result.run_id
            st.session_state.requirement_id = requirement_id
            st.session_state.run_results = None
            st.success(
                f"Generated {len(result.tests)} test(s), dropped {len(result.dropped)}. "
                f"run_id={result.run_id}"
            )
            for note in result.notes:
                st.info(note)


def _tests_table(backend: dict[str, object]) -> None:
    st.header("2. Review generated tests")
    st.warning(GOVERNANCE_BANNER)
    tests = st.session_state.tests
    if not tests:
        st.caption("No tests generated yet.")
        return
    rows = [
        {
            "id": t.id,
            "category": t.category,
            "template_id": t.template_id or "(gold)",
            "review_status": t.review_status,
            "steps": len(t.steps),
            "citations": len(t.citations),
        }
        for t in tests
    ]
    st.dataframe(rows, use_container_width=True)

    selected_id = st.selectbox("Inspect test", options=[t.id for t in tests])
    selected = next(t for t in tests if t.id == selected_id)
    st.subheader(selected.title)
    st.write(selected.explanation or "(no explanation)")
    st.markdown("**Steps (hex)**")
    for i, step in enumerate(selected.steps):
        if step.kind == "send":
            st.code(
                f"[{i}] -> {step.request_hex}\n"
                f"[{i}] <- {' | '.join(step.expected_responses_hex) or '(no response)'}",
                language="text",
            )
        else:
            st.code(f"[{i}] {step.kind}: {step.model_dump(exclude={'kind'})}", language="text")
    st.markdown("**Citations**")
    for c in selected.citations:
        st.caption(f"{c.source} / {c.ref}" + (f" -- \"{c.quote}\"" if c.quote else ""))

    if st.session_state.run_id is not None and st.button(
        f"Mark {selected.id} as human_reviewed"
    ):
        backend["store"].set_review_status(st.session_state.run_id, selected.id, "human_reviewed")
        st.session_state.tests = backend["store"].get_tests(st.session_state.run_id)
        st.rerun()


def _run_section(backend: dict[str, object]) -> None:
    st.header("3. Run on the ECU simulator")
    tests = st.session_state.tests
    if not tests:
        st.caption("Generate tests first.")
        return
    catalog = backend["catalog"]
    bug_options = {f"[in-sample] {b.id} ({b.title})": b.id for b in catalog.bugs}
    heldout_catalog = backend.get("heldout_catalog")
    if heldout_catalog is not None:
        for b in heldout_catalog.bugs:
            if b.id in HELDOUT_BUG_IDS:
                bug_options[f"[held-out] {b.id} ({b.title})"] = b.id
    chosen_labels = st.multiselect("Inject bug(s) (optional)", options=list(bug_options))
    chosen_bugs = {bug_options[label] for label in chosen_labels}
    if st.button("Run suite on simulator"):
        with st.spinner("Running..."):
            suite = run_suite(
                tests,
                backend["spec"],
                chosen_bugs,
                store=backend["store"],
                run_id=st.session_state.run_id,
            )
        st.session_state.run_results = suite
    suite = st.session_state.run_results
    if suite is not None:
        st.metric("Passed", f"{suite.passed_count}/{suite.total}")
        st.dataframe(
            [
                {
                    "test_id": r.test_id,
                    "passed": r.passed,
                    "functional_passed": r.functional_passed,
                    "timing_passed": r.timing_passed,
                    "failure": r.failure_detail,
                    "duration_ms": r.duration_ms,
                }
                for r in suite.results
            ],
            use_container_width=True,
        )


def _pct(rate: object) -> str:
    return f"{rate * 100:.1f}%" if isinstance(rate, (int, float)) else "?"


def _frac(block: object) -> str:
    """``hit/all (pct)`` from a detection block, ``n/a`` if keys are missing."""
    if not isinstance(block, dict) or "detected" not in block:
        return "n/a"
    return f"{block['detected']}/{block.get('bugs', '?')} ({_pct(block.get('rate'))})"


def _headline_rows(report: dict, block: dict) -> list[dict[str, str]]:
    """The 7-row headline table, built defensively from whatever the report holds."""
    agree = report.get("simulator_rules_agreement") or {}
    can = report.get("udsoncan_virtual_can") or {}
    held = block.get("heldout_bug_detection") or {}
    und = ((block.get("requirement_understanding") or {}).get("splits") or {}).get("test") or {}
    cov = block.get("coverage") or {}
    cit = block.get("citation_validity") or {}
    cats = cov.get("category_totals") or {}
    if held:
        held_txt = (
            f"generated {_frac(held.get('generated'))} (HEADLINE) | "
            f"gold {_frac(held.get('gold'))} | union {_frac(held.get('union'))}"
        )
    else:
        held_txt = "n/a (report predates the held-out set)"
    if und:
        n = und.get("requirements", "?")
        tp = und.get("targets_parsed", {})
        te = und.get("targets_exercised", {})
        und_txt = (
            f"test split n={n}: parsed exact {tp.get('exact', '?')}/{n} (F1 {tp.get('f1', '?')}), "
            f"exercised exact {te.get('exact', '?')}/{n} (F1 {te.get('f1', '?')})"
        )
    else:
        und_txt = "n/a (report predates the natural-requirements set)"
    agree_txt = (
        f"{agree.get('agreed', 'n/a')}/{agree.get('requests', 'n/a')} ({_pct(agree.get('rate'))})"
        if agree
        else "n/a"
    )
    cit_txt = (
        f"{cit.get('valid', 'n/a')}/{cit.get('citations', 'n/a')} ({_pct(cit.get('rate'))})"
        if cit
        else "n/a"
    )
    gold_txt = (
        f"{report.get('gold_clean_passed', 'n/a')}/{report.get('gold_tests', '?')} "
        f"({_pct(report.get('gold_clean_pass_rate'))})"
    )
    return [
        {"Metric": "1. Simulator <-> rules-engine agreement", "Result": agree_txt},
        {"Metric": "2. Gold tests passing on bug-free simulator", "Result": gold_txt},
        {"Metric": "3. udsoncan virtual-CAN sequence", "Result": str(can.get("status", "n/a")).upper()},
        {"Metric": "4. Held-out bug detection (12 bugs)", "Result": held_txt},
        {"Metric": "5. Requirement understanding (natural requirements)", "Result": und_txt},
        {
            "Metric": "6. Coverage (seed requirements, tests per category)",
            "Result": ", ".join(f"{k} {v}" for k, v in cats.items()) or "n/a",
        },
        {"Metric": "7. Citation validity", "Result": cit_txt},
    ]


def _heldout_section(block: dict) -> None:
    held = block.get("heldout_bug_detection")
    if not held:
        st.caption("Held-out results not in this report (older report).")
        return
    st.subheader("Held-out bug detection (bugs not seen when templates/gold were written)")
    st.caption(held.get("scope", ""))
    gen, gold = held.get("generated", {}), held.get("gold", {})
    analysis = held.get("analysis", {})
    triggers = analysis.get("triggers", {})
    reasons_gen = {m["bug_id"]: m["reason"] for m in analysis.get("generated", {}).get("missed", [])}
    reasons_gold = {m["bug_id"]: m["reason"] for m in analysis.get("gold", {}).get("missed", [])}
    gold_by_id = {b["bug_id"]: b for b in gold.get("per_bug", [])}
    rows = []
    for b in gen.get("per_bug", []):
        g = gold_by_id.get(b["bug_id"], {})
        rows.append(
            {
                "bug": b["bug_id"],
                "category": b.get("category", ""),
                "generated": "yes" if b.get("detected") else "NO",
                "gold": "yes" if g.get("detected") else "NO",
                "trigger needed": triggers.get(b["bug_id"], ""),
                "generated missed because": reasons_gen.get(b["bug_id"], ""),
                "gold missed because": reasons_gold.get(b["bug_id"], ""),
            }
        )
    st.dataframe(rows, use_container_width=True)
    st.caption(
        f"generated {_frac(gen)}, gold {_frac(gold)}, union {_frac(held.get('union'))}. "
        "Reasons come from a static trigger analysis (reporting only)."
    )


def _understanding_section(block: dict) -> None:
    und = block.get("requirement_understanding")
    if not und:
        st.caption("Requirement-understanding results not in this report (older report).")
        return
    st.subheader("Requirement understanding (natural-language requirements)")
    st.caption(f"Source: {und.get('source', '?')}. The TEST split is the main number.")
    split_rows = []
    for name, sp in (und.get("splits") or {}).items():
        tp, te = sp.get("targets_parsed", {}), sp.get("targets_exercised", {})
        cat, pre, fb = sp.get("categories", {}), sp.get("preconditions", {}), sp.get("fallback", {})
        split_rows.append(
            {
                "split": name,
                "n": sp.get("requirements"),
                "parsed exact": f"{tp.get('exact')}/{sp.get('requirements')}",
                "parsed F1": tp.get("f1"),
                "exercised exact": f"{te.get('exact')}/{sp.get('requirements')}",
                "exercised F1": te.get("f1"),
                "category recall (micro)": cat.get("micro_recall"),
                "precondition recall (micro)": pre.get("micro_recall"),
                "fallback / nothing": fb.get("count"),
            }
        )
    st.dataframe(split_rows, use_container_width=True)
    req_rows = []
    for r in und.get("per_requirement", []):
        pa, ex = r.get("parsed", {}), r.get("exercised", {})
        req_rows.append(
            {
                "req": r.get("id"),
                "split": f"{r.get('split')}" + (" (ambiguous)" if r.get("ambiguous") else ""),
                "tests": r.get("tests"),
                "label targets": ", ".join(r.get("label_targets", [])),
                "parsed exact": pa.get("exact"),
                "parsed missed": ", ".join(pa.get("missed", [])),
                "parsed extra": ", ".join(pa.get("extra", [])),
                "exercised exact": ex.get("exact"),
                "exercised missed": ", ".join(ex.get("missed", [])),
                "exercised extra (n)": ex.get("fp"),
                "categories missed": ", ".join(r.get("categories", {}).get("missed", [])),
                "preconditions missed": ", ".join(r.get("preconditions", {}).get("missed", [])),
                "fallback": "; ".join(r.get("fallback_reasons", [])),
            }
        )
    st.dataframe(req_rows, use_container_width=True)


def _eval_section() -> None:
    st.header("4. Evaluation report (mock mode)")
    path = Path(os.environ.get("UDS_EVAL_REPORT") or REPO_ROOT / "outputs" / "eval_report.json")
    if not path.exists():
        st.caption(f"No report yet at {path}. Run `python -m uds_assistant.eval.run_eval`.")
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    block = (report.get("modes") or {}).get(report.get("actual_mode"), {})
    st.subheader("Headline metrics")
    st.table(_headline_rows(report, block))
    st.caption(
        "LLM-dependent rows are for mock mode; ollama numbers are pending Part B. "
        "The oracle self-consistency check is circular and lives in the report appendix."
    )
    det = block.get("bug_detection", {})
    col1, col2, col3 = st.columns(3)
    col1.metric("Generated tests", block.get("generated_tests", {}).get("count", "?"))
    col2.metric(
        "In-sample bugs (generated; templates tuned on these)", _frac(det.get("generated"))
    )
    col3.metric("In-sample bugs (gold)", _frac(det.get("gold")))
    _heldout_section(block)
    _understanding_section(block)
    st.caption(f"Report timestamp: {report.get('timestamp')}; spec is synthetic.")
    with st.expander("Full report JSON"):
        st.json(report)


def _export_section() -> None:
    st.header("5. Export")
    tests = st.session_state.tests
    if not tests:
        st.caption("Generate tests first.")
        return
    pytest_src = render_pytest(tests, filename="generated_tests_test.py")
    capl_src = render_capl(tests)
    col1, col2 = st.columns(2)
    col1.download_button(
        "Download pytest file", pytest_src, file_name="generated_tests_test.py", mime="text/x-python"
    )
    col2.download_button(
        "Download CAPL template (unverified)", capl_src, file_name="generated_tests.can", mime="text/plain"
    )


def main() -> None:
    st.set_page_config(page_title="UDS Diagnostics Assistant", layout="wide")
    st.title("UDS Diagnostics & Automated Test Generation Assistant")
    st.caption(
        "Local, offline-capable. ECU spec is SYNTHETIC. " + GOVERNANCE_BANNER
    )
    backend = _load_backend()
    _init_state()
    _generate_section(backend)
    _tests_table(backend)
    _run_section(backend)
    _eval_section()
    _export_section()


main()
