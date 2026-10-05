"""Streamlit demo UI for the UDS diagnostics assistant: four tabs.

Run with::

    streamlit run uds_assistant/ui/streamlit_app.py

Tabs: Ask (cited Q&A) -> Generate & Review (requirement to cited tests, human review in the audit
DB) -> Run & Export (clean simulator or one injected bug, then pytest / CAPL download) ->
Results (the eight evaluation sections from ``outputs/eval_report.json``).

Ollama is required: when it is not reachable the sidebar turns red and the tabs that need the
model say "Start Ollama and pull <model>". The testable logic lives in the sibling modules:
``decode`` (step decoding), ``state`` (review actions), ``bugs`` (bug choices), ``examples``
and ``env`` (probes and paths). The script calls the pipeline, Q&A, runner and store directly
(no network hop to the FastAPI service). Nothing else in ``uds_assistant`` imports this module,
so the package stays importable without streamlit.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from uds_assistant.agent import run_pipeline
from uds_assistant.export import CAPL_BANNER, render_capl, render_pytest
from uds_assistant.llm.factory import START_OLLAMA_HINT, get_llm
from uds_assistant.protocol.describe import decode_responses, decode_step, spaced_hex
from uds_assistant.qa import answer_question
from uds_assistant.qa.lookup import FactLookup
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.runner import run_suite
from uds_assistant.spec.schema import load_spec
from uds_assistant.store.audit import AuditStore
from uds_assistant.ui import env, state
from uds_assistant.ui.bugs import NO_BUG, bug_options
from uds_assistant.ui.examples import ASK_EXAMPLES, requirement_examples

REPO_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_BANNER = "Synthetic ECU spec — human review required before real-hardware use."
NOT_FOUND_TEXT = "Not found in the approved sources."
CONF_COLOR = {"high": "green", "medium": "orange", "low": "red"}
PICK = "(pick an example)"
SCOPES = ("all tests", "approved tests", "selected test")
OLLAMA_MISSING = f"{START_OLLAMA_HINT}."


# ---------------------------------------------------------------------------------- cached backend


@st.cache_resource
def _static() -> dict[str, object]:
    spec = load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")
    corpus = build_corpus(REPO_ROOT)
    return {"spec": spec, "corpus": corpus, "lookup": FactLookup(spec, corpus)}


@st.cache_resource
def _store(path: str) -> AuditStore:
    return AuditStore(path)


@st.cache_resource(show_spinner="Loading the ChromaDB index (BGE embeddings)...")
def _retriever():
    return get_retriever(
        chunks=_static()["corpus"],  # type: ignore[arg-type]
        persist_dir=REPO_ROOT / "outputs" / "chroma",
    )


@st.cache_resource
def _llm():
    return get_llm()


@st.cache_data(ttl=15, show_spinner=False)
def _ollama_status() -> tuple[bool, str]:
    return env.ollama_status()


@st.cache_data(show_spinner=False)
def _read_report(path: str, mtime: float) -> tuple[dict | None, str]:
    """The report JSON keyed on the file's mtime; ``(None, reason)`` when unusable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return (data, "") if isinstance(data, dict) else (None, "report is not a JSON object")


# ---------------------------------------------------------------------------------------- sidebar


def _sidebar() -> dict[str, object]:
    """Ollama status (green / red), the governance banner, and the shared backend objects."""
    sb = st.sidebar
    sb.header("Status")
    ollama_ok, ollama_text = _ollama_status()
    if ollama_ok:
        sb.success(ollama_text)
    else:
        sb.error(ollama_text)
    sb.warning(GOVERNANCE_BANNER)
    db_path = env.audit_db_path()
    sb.caption(f"Audit trail: {db_path.name}")
    return {
        "ollama_ok": ollama_ok,
        "store": _store(str(db_path)),
        **_static(),
    }


def _need_ollama(ctx: dict[str, object]) -> bool:
    """Show the start-Ollama hint and return True when the model is unavailable."""
    if ctx["ollama_ok"]:
        return False
    st.error(OLLAMA_MISSING)
    return True


# ------------------------------------------------------------------------------------------- Ask


def _use_ask_example() -> None:
    choice = st.session_state.get("ask_example")
    if choice and choice != PICK:
        st.session_state.ask_q = choice


def _confidence_badge(level: str | None, reason: str) -> None:
    if not level:
        return
    st.markdown(f":{CONF_COLOR.get(level, 'gray')}-badge[confidence: {level}] {reason}")


def _ask_tab(ctx: dict[str, object]) -> None:
    st.subheader("Ask a diagnostic question")
    st.caption("Answers come only from the approved sources (standard, OEM, ECU spec, project).")
    st.selectbox(
        "Example questions", [PICK, *ASK_EXAMPLES], key="ask_example", on_change=_use_ask_example
    )
    question = st.text_input("Question", key="ask_q", placeholder="e.g. What is the length of DID 0xF190?")
    if _need_ollama(ctx):
        return
    if st.button("Ask", type="primary") and question.strip():
        with st.spinner("Searching the approved sources..."):
            st.session_state.ask_resp = answer_question(
                question,
                spec=ctx["spec"],
                chunks=ctx["corpus"],
                retriever=_retriever(),
                llm=_llm(),
                lookup=ctx["lookup"],
            )
    resp = st.session_state.get("ask_resp")
    if resp is None:
        return
    if resp.status == "not_found":
        st.warning(NOT_FOUND_TEXT)
    else:
        st.markdown(resp.answer)
    _confidence_badge(resp.confidence, resp.confidence_reason)
    for ev in resp.fallback_events:
        st.caption(f"LLM phrasing discarded: {ev}")
    if resp.citations:
        with st.expander(f"Citations ({len(resp.citations)})"):
            for c in resp.citations:
                st.markdown(f"**{c.layer}** · `{c.source}`")
                st.markdown(f"> {c.quote}")


# ----------------------------------------------------------------------------- Generate & Review


def _load_example() -> None:
    choice = st.session_state.get("example_choice")
    examples = requirement_examples()
    if choice in examples:
        st.session_state.req_id, st.session_state.req_text = examples[choice]


def _did_names(spec: object) -> dict[int, str]:
    return {int(d.id): d.name for d in getattr(spec, "dids", [])}


def _reload_tests(ctx: dict[str, object]) -> None:
    run_id = st.session_state.get("run_id")
    if run_id is not None:
        st.session_state.tests = ctx["store"].get_tests(run_id)  # type: ignore[attr-defined]


def _review_cb(ctx: dict[str, object], action: str) -> None:
    store, run_id = ctx["store"], st.session_state.get("run_id")
    test_id = st.session_state.get("selected_test")
    if run_id is None or not test_id:
        return
    comment = st.session_state.get("review_comment", "")
    if action == "comment" and not comment.strip():
        st.session_state.flash = ("warning", "Type a comment first.")
        return
    actions = {"approve": state.approve, "reject": state.reject, "comment": state.add_comment}
    actions[action](store, run_id, test_id, comment)
    _reload_tests(ctx)
    past = {"approve": "Approved", "reject": "Rejected", "comment": "Comment saved for"}[action]
    st.session_state.flash = ("success", f"{past} {test_id}. Stored in the audit DB.")


def _chips(prov: list) -> None:
    if not prov:
        st.caption("No target provenance recorded for this test.")
        return
    chips = []
    for t in prov:
        kind = "written" if t.written else "inferred"
        color = "green" if t.written else "orange"
        label = f"{t.kind} {t.id}" + (f" {t.name}" if t.name else "")
        chips.append(f":{color}-badge[{kind}] {label}")
    st.markdown("  ".join(chips))
    st.caption("written = named in the requirement text; inferred = added by the planner.")


def _show_steps(test, did_names: dict[int, str]) -> None:
    for i, step in enumerate(test.steps):
        if step.kind == "send":
            d = decode_step(step.request_hex, step.expected_responses_hex, did_names)
            st.code(f"[{i}] {d.line}", language="text")
            st.caption(f"{d.request_text}; expects: {'; '.join(d.response_texts) or 'no response'}")
        else:
            st.code(f"[{i}] {step.kind}: {step.model_dump(exclude={'kind'})}", language="text")


def _generate_tab(ctx: dict[str, object]) -> None:
    st.subheader("Generate tests from a requirement")
    examples = requirement_examples()
    st.selectbox(
        "Load example", [PICK, *examples], key="example_choice", on_change=_load_example
    )
    text = st.text_area(
        "Diagnostic requirement (plain English)",
        key="req_text",
        placeholder="Type a diagnostic requirement, or load an example above.",
        height=100,
    )
    st.session_state.setdefault("req_id", "REQ-UI-001")
    rid = st.text_input("Requirement id", key="req_id")
    if _need_ollama(ctx):
        return
    if st.button("Generate tests", type="primary"):
        if not text.strip():
            st.error("Requirement text must not be empty.")
        else:
            with st.spinner("Running parse, retrieve, plan, instantiate, validate, explain..."):
                result = run_pipeline(text, rid, ctx["spec"], _llm(), _retriever(), ctx["store"])
            st.session_state.result = result
            st.session_state.tests = result.tests
            st.session_state.run_id = result.run_id
            st.session_state.run_summary = None
            st.session_state.flash = None
    result = st.session_state.get("result")
    if result is None:
        st.caption("No tests generated yet.")
        return
    st.success(
        f"Generated {len(result.tests)} test(s), dropped {len(result.dropped)}. run_id={result.run_id}"
    )
    for event in result.fallback_events:
        st.warning(f"LLM call failed: {event}")
    for note in result.notes:
        st.info(note)
    tests = st.session_state.tests
    if not tests:
        return
    store, run_id = ctx["store"], st.session_state.get("run_id")
    st.dataframe(
        [
            {
                "id": t.id,
                "category": t.category,
                "confidence": t.confidence or "-",
                "review status": state.review_label(store, run_id, t),
            }
            for t in tests
        ],
        width="stretch",
    )
    selected_id = st.selectbox("Select a test to inspect", [t.id for t in tests], key="selected_test")
    sel = next(t for t in tests if t.id == selected_id)
    st.markdown(f"#### {sel.title}")
    _confidence_badge(sel.confidence, sel.confidence_reason)
    st.markdown("**Preconditions**")
    for pre in sel.preconditions or ["(none recorded)"]:
        st.markdown(f"- {pre}")
    st.markdown("**Pass criteria**")
    st.write(sel.pass_criteria or "(none recorded)")
    st.markdown("**Steps** (hex request → expected response, decoded)")
    _show_steps(sel, _did_names(ctx["spec"]))
    st.markdown("**Targets**")
    _chips(result.target_provenance.get(sel.id, []))
    st.markdown("**Explanation**")
    st.write(sel.explanation or "(no explanation)")
    st.markdown("**Citations**")
    if not sel.citations:
        st.caption("(none)")
    for c in sel.citations:
        st.markdown(f"**{c.source}** · `{c.ref}`" + (f"\n> {c.quote}" if c.quote else ""))
    st.markdown("**Review**")
    st.text_input("Review comment", key="review_comment")
    cols = st.columns(3)
    cols[0].button("Approve", on_click=_review_cb, args=(ctx, "approve"))
    cols[1].button("Reject", on_click=_review_cb, args=(ctx, "reject"))
    cols[2].button("Add comment", on_click=_review_cb, args=(ctx, "comment"))
    flash = st.session_state.get("flash")
    if flash:
        getattr(st, flash[0])(flash[1])
    if run_id is not None:
        for action, comment in state.review_log(store, run_id, sel.id):
            st.caption(f"{action}" + (f": {comment}" if comment else ""))


# ------------------------------------------------------------------------------------ Run tab


def _scope_tests(scope: str) -> list:
    tests = st.session_state.get("tests") or []
    if scope == "selected test":
        return [t for t in tests if t.id == st.session_state.get("selected_test")]
    if scope == "approved tests":
        return state.approved_tests(tests)
    return list(tests)


def _failure_panel(test, result, did_names: dict[int, str]) -> None:
    first = result.outcome.first_failure
    if first is None:
        st.write(result.failure_detail or "failed (timing)")
        return
    step = test.steps[first.index]
    st.markdown(f"**First failing step: {first.index}**")
    st.code(f"request : {spaced_hex(step.request_hex)}", language="text")
    st.code(
        f"expected: {decode_responses(first.expected_responses_hex)}\n"
        f"actual  : {decode_responses(first.actual_responses_hex)}",
        language="text",
    )
    st.caption(decode_step(step.request_hex, first.actual_responses_hex, did_names).request_text)


def _run_tab(ctx: dict[str, object]) -> None:
    st.subheader("Run on the ECU simulator")
    tests = st.session_state.get("tests") or []
    if not tests:
        st.info("Generate tests first on the Generate & Review tab.")
        return
    options = bug_options()
    labels = {o.label: o for o in options}
    choice = st.selectbox("Inject a bug", [NO_BUG, *labels], key="bug_choice")
    if choice in labels:
        st.caption(labels[choice].description)
    scope = st.radio("Run", SCOPES, horizontal=True, key="run_scope")
    if st.button("Run on simulator", type="primary"):
        chosen = _scope_tests(scope)
        if not chosen:
            st.warning(
                "No approved tests yet: approve some on the Generate & Review tab."
                if scope == "approved tests"
                else "No tests to run."
            )
        else:
            bug_id = labels[choice].id if choice in labels else None
            with st.spinner("Running..."):
                clean = run_suite(chosen, ctx["spec"], set())
                suite = run_suite(
                    chosen,
                    ctx["spec"],
                    {bug_id} if bug_id else set(),
                    store=ctx["store"],
                    run_id=st.session_state.get("run_id"),
                )
            st.session_state.run_summary = {
                "bug": bug_id, "scope": scope, "suite": suite, "clean": clean, "tests": chosen,
            }
    summary = st.session_state.get("run_summary")
    if summary is None:
        return
    suite, clean, bug = summary["suite"], summary["clean"], summary["bug"]
    by_id = {t.id: t for t in summary["tests"]}
    clean_ok = {r.test_id for r in clean.results if r.passed}
    failed = [r for r in suite.results if not r.passed]
    if bug is None:
        if not failed:
            st.success("All tests pass on the clean simulator.")
        else:
            st.error(f"{len(failed)} test(s) fail on the clean simulator: " + ", ".join(r.test_id for r in failed))
    else:
        caught = [r for r in failed if r.test_id in clean_ok]
        n = len(caught)
        if n:
            st.success(f"Bug caught by {n} test{'s' if n != 1 else ''}.")
        else:
            st.warning("Bug not caught.")
        invalid = [r for r in failed if r.test_id not in clean_ok]
        if invalid:
            st.caption(f"{len(invalid)} test(s) also fail on the clean simulator and get no credit.")
    st.metric("Passed", f"{suite.passed_count}/{suite.total}")
    st.dataframe(
        [
            {
                "test_id": r.test_id,
                "category": by_id[r.test_id].category if r.test_id in by_id else "",
                "result": "PASS" if r.passed else "FAIL",
                "failure": r.failure_detail,
            }
            for r in suite.results
        ],
        width="stretch",
    )
    for r in failed[:10]:
        with st.expander(f"FAIL {r.test_id}", expanded=r is failed[0]):
            _failure_panel(by_id[r.test_id], r, _did_names(ctx["spec"]))
    if len(failed) > 10:
        st.caption(f"{len(failed) - 10} more failing test(s) not expanded.")


# --------------------------------------------------------------------------------- Export tab


def _export_tab() -> None:
    st.subheader("Export")
    tests = st.session_state.get("tests") or []
    if not tests:
        st.info("Generate tests first on the Generate & Review tab.")
        return
    approved_only = st.checkbox("Approved tests only", key="export_approved")
    chosen = state.approved_tests(tests) if approved_only else tests
    if not chosen:
        st.warning("No approved tests to export.")
        return
    st.caption(f"{len(chosen)} test(s) in the export.")
    col1, col2 = st.columns(2)
    col1.download_button(
        "Download pytest file",
        render_pytest(chosen, filename="generated_tests_test.py"),
        file_name="generated_tests_test.py",
        mime="text/x-python",
    )
    col2.download_button(
        "Download CAPL template (unverified — never run in CANoe)",
        render_capl(chosen),
        file_name="generated_tests.can",
        mime="text/plain",
    )
    st.caption(CAPL_BANNER)


# -------------------------------------------------------------------------------- Results tab


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _card(col, title: str, value: str, caption: str) -> None:
    with col.container(border=True):
        st.caption(title)
        st.markdown(f"### {value}")
        st.caption(caption)


def _results_tab() -> None:
    st.subheader("Evaluation results")
    path = env.report_path()
    if not path.exists():
        st.info(f"No evaluation report at {path}. Create one with `python -m uds_assistant.eval.run_eval`.")
        return
    report, why = _read_report(str(path), path.stat().st_mtime)
    if report is None:
        st.info(f"The report at {path} could not be read ({why}).")
        return
    st.caption(f"Run {report['timestamp']} · git {report['git']} · model {report['llm']['model']}")
    g, cov, ru, dd = (
        report["generation_accuracy"], report["coverage"], report["reuse"],
        report["defect_detection"],
    )
    un, qa, td, c = report["understanding"], report["qa"], report["test_design_time"], report["correctness"]
    totals = cov["category_totals"]
    cols = st.columns(4)
    _card(cols[0], "Generation accuracy", _pct(g["valid_request_rate"]),
          f"valid requests; {_pct(g['clean_pass_rate'])} of {g['tests']} tests pass on the clean simulator")
    _card(cols[1], "Coverage", f"{cov['requirements_with_tests']}/{cov['requirements']} requirements",
          ", ".join(f"{k} {v}" for k, v in totals.items()))
    _card(cols[2], "Reuse rate", _pct(ru["rate"]),
          f"{ru['from_templates']}/{ru['tests']} tests built from approved templates")
    _card(cols[3], "Defect detection", f"{dd['caught']}/{dd['bugs']} bugs",
          "blind v3 set, generated tests + conformance sweep")
    cols = st.columns(4)
    _card(cols[0], "Requirement understanding", _pct(un["target_f1"]),
          f"target F1; category recall {_pct(un['category_recall'])}, "
          f"precondition recall {_pct(un['precondition_recall'])}")
    _card(cols[1], "Q&A accuracy", _pct(qa["answer_accuracy"]),
          f"citations correct {_pct(qa['citation_correctness'])}; "
          f"correct not-found {qa['correct_not_found_n']}/{qa['n_unanswerable']}")
    _card(cols[2], "Tool time per requirement", f"{td['tool_seconds_per_requirement_mean']} s",
          f"mean over {td['requirements_timed']} requirements; manual time: owner to fill")
    ag = c["simulator_rules_agreement"]
    _card(cols[3], "Correctness checks",
          f"{c['gold_clean']['passed']}/{c['gold_clean']['total']} gold pass",
          f"simulator = rules engine on {ag.get('agreed')}/{ag.get('requests')} requests; "
          f"udsoncan virtual CAN: {c['udsoncan_virtual_can']['status']}")
    if dd["missed"]:
        st.caption("Missed blind-set bugs: " + ", ".join(x["bug_id"] for x in dd["missed"]))


# ------------------------------------------------------------------------------------------ main


def main() -> None:
    st.set_page_config(page_title="UDS Diagnostics Assistant", layout="wide")
    st.title("UDS Diagnostics & Automated Test Generation Assistant")
    ctx = _sidebar()
    tabs = st.tabs(["Ask", "Generate & Review", "Run & Export", "Results"])
    with tabs[0]:
        _ask_tab(ctx)
    with tabs[1]:
        _generate_tab(ctx)
    with tabs[2]:
        _run_tab(ctx)
        st.divider()
        _export_tab()
    with tabs[3]:
        _results_tab()


main()
