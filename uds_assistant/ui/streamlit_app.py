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
from pathlib import Path

import streamlit as st

from uds_assistant.agent import run_pipeline
from uds_assistant.config import get_config
from uds_assistant.export import render_capl, render_pytest
from uds_assistant.llm.factory import get_llm
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.runner import run_suite
from uds_assistant.simulator import load_bug_catalog
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
    return {
        "cfg": cfg,
        "spec": spec,
        "retriever": retriever,
        "llm": llm,
        "store": store,
        "catalog": catalog,
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
    bug_options = {f"{b.id} ({b.title})": b.id for b in catalog.bugs}
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


def _eval_section() -> None:
    st.header("4. Evaluation report (mock mode)")
    path = REPO_ROOT / "outputs" / "eval_report.json"
    if not path.exists():
        st.caption(f"No report yet at {path}. Run `python -m uds_assistant.eval.run_eval`.")
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    block = report["modes"].get(report["actual_mode"], {})
    det = block.get("bug_detection", {})
    col1, col2, col3 = st.columns(3)
    col1.metric("Generated tests", block.get("generated_tests", {}).get("count", "?"))
    gen_det = det.get("generated", {})
    col2.metric(
        "Bug detection (generated)",
        f"{gen_det.get('detected', '?')}/{gen_det.get('bugs', '?')}",
    )
    gold_det = det.get("gold", {})
    col3.metric("Bug detection (gold)", f"{gold_det.get('detected', '?')}/{gold_det.get('bugs', '?')}")
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
