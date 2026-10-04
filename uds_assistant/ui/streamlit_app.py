"""Streamlit demo UI for the UDS diagnostics assistant: five tabs.

Run with::

    streamlit run uds_assistant/ui/streamlit_app.py

Tabs: Ask (cited Q&A) -> Generate & Review (requirement to cited tests, human review in the audit
DB) -> Run on Simulator (clean or with one injected bug) -> Export (pytest, CAPL) -> Results
(headline cards from ``outputs/eval_report.json``).

This script only wires the tabs. The testable logic lives in the sibling modules: ``decode``
(step decoding), ``state`` (review actions), ``bugs`` (bug choices), ``examples``,
``results_cards`` / ``results_detail`` (Results tab) and ``env`` (probes and paths). It calls the
pipeline, Q&A, runner and store directly (no network hop to the FastAPI service). Nothing else in
``uds_assistant`` imports this module, so the package stays importable without streamlit.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import streamlit as st

from uds_assistant.agent import run_pipeline
from uds_assistant.config import Config, get_config
from uds_assistant.export import CAPL_BANNER, render_capl, render_pytest
from uds_assistant.llm.factory import get_llm
from uds_assistant.qa import answer_question
from uds_assistant.qa.lookup import FactLookup
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.runner import run_suite
from uds_assistant.spec.schema import load_spec
from uds_assistant.store.audit import AuditStore
from uds_assistant.ui import env, state
from uds_assistant.ui.bugs import NO_BUG, bug_options
from uds_assistant.ui.decode import decode_responses, decode_step, spaced_hex
from uds_assistant.ui.examples import ASK_EXAMPLES, requirement_examples
from uds_assistant.ui.results_cards import build_cards
from uds_assistant.ui.results_detail import render_details

REPO_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_BANNER = (
    "Synthetic ECU spec. Human review required before any real-hardware execution."
)
NOT_FOUND_TEXT = "Not found in the approved sources."
CONF_COLOR = {"high": "green", "medium": "orange", "low": "red"}
PICK = "(pick an example)"
SCOPES = ("selected test", "approved tests", "all tests")


# ---------------------------------------------------------------------------------- cached backend


@st.cache_resource
def _static() -> dict[str, object]:
    spec = load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")
    corpus = build_corpus(REPO_ROOT)
    return {"spec": spec, "corpus": corpus, "lookup": FactLookup(spec, corpus)}


@st.cache_resource
def _store(path: str) -> AuditStore:
    return AuditStore(path)


@st.cache_resource
def _retriever(name: str) -> tuple[object, list[str]]:
    """The retriever plus any fallback warnings (e.g. Chroma could not start)."""
    cfg = get_config()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        r = get_retriever(
            Config(llm_mode="mock", retriever=name, embedder=cfg.embedder),  # type: ignore[arg-type]
            chunks=_static()["corpus"],  # type: ignore[arg-type]
        )
    return r, [str(w.message) for w in caught]


@st.cache_resource
def _llm(mode: str, reachable: bool):
    cfg = get_config()
    return get_llm(Config(llm_mode=mode, retriever=cfg.retriever, embedder=cfg.embedder))  # type: ignore[arg-type]


@st.cache_data(ttl=15, show_spinner=False)
def _ollama_status() -> tuple[bool, str]:
    return env.ollama_status()


@st.cache_data(ttl=60, show_spinner=False)
def _chroma_status(embedder: str) -> tuple[bool, str]:
    return env.chroma_status(embedder)


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
    """Mode and retriever selectors. An unavailable option is removed and the widget disabled.

    ``st.radio`` cannot disable a single option, so when a backend is unavailable the radio keeps
    only the working option, is itself disabled, and a warning gives the reason.
    """
    cfg = get_config()
    sb = st.sidebar
    sb.header("Settings")
    ollama_ok, ollama_text = _ollama_status()
    modes = ["mock", "ollama"] if ollama_ok else ["mock"]
    mode = sb.radio(
        "LLM mode",
        modes,
        index=modes.index(cfg.llm_mode) if cfg.llm_mode in modes else 0,
        key="llm_mode",
        disabled=not ollama_ok,
        help="mock = deterministic keyword stand-in; ollama = local Qwen2.5-3B.",
    )
    if ollama_ok:
        sb.success(ollama_text)
    else:
        sb.warning(f"Ollama option disabled: {ollama_text}. Start Ollama to enable it.")
    chroma_ok, chroma_text = _chroma_status(cfg.embedder)
    rets = ["bm25", "chroma"] if chroma_ok else ["bm25"]
    retr = sb.radio(
        "Retriever",
        rets,
        index=rets.index(cfg.retriever) if cfg.retriever in rets else 0,
        key="retriever",
        disabled=not chroma_ok,
    )
    if not chroma_ok:
        sb.warning(f"Chroma option disabled: {chroma_text}.")
    sb.warning(GOVERNANCE_BANNER)
    db_path = env.audit_db_path()
    sb.caption(f"Audit trail: {db_path.name}")
    retriever, notes = _retriever(retr)
    for n in notes:
        sb.warning(n)
    return {
        "mode": mode,
        "llm": _llm(mode, ollama_ok),
        "retriever": retriever,
        "store": _store(str(db_path)),
        **_static(),
    }


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
    if st.button("Ask", type="primary") and question.strip():
        with st.spinner("Searching the approved sources..."):
            st.session_state.ask_resp = answer_question(
                question,
                spec=ctx["spec"],
                chunks=ctx["corpus"],
                retriever=ctx["retriever"],
                llm=ctx["llm"],
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
    st.caption(f"Answer phrased by: {resp.llm_mode}")
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
    if st.button("Generate tests", type="primary"):
        if not text.strip():
            st.error("Requirement text must not be empty.")
        else:
            with st.spinner(f"Running parse, retrieve, plan, instantiate, validate, explain ({ctx['mode']})..."):
                result = run_pipeline(
                    text, rid, ctx["spec"], ctx["llm"], ctx["retriever"], ctx["store"]
                )
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
    st.caption(f"LLM backend used: {result.llm}; engine: {result.engine}.")
    for event in result.fallback_events:
        st.warning(f"Fallback: {event}")
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
    st.subheader("Run tests on the ECU simulator")
    tests = st.session_state.get("tests") or []
    if not tests:
        st.info("Generate tests first (Generate & Review tab).")
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
        st.info("Generate tests first (Generate & Review tab).")
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
    cards = build_cards(report)
    for row in (cards[:3], cards[3:]):
        cols = st.columns(3)
        for col, card in zip(cols, row, strict=False):
            with col.container(border=True):
                st.markdown(f"**{card.title}**")
                if not card.available:
                    st.info(card.caption)
                    continue
                for label, value in card.lines:
                    st.markdown(f"{label}: **{value}**")
                st.caption(card.caption)
                st.caption(f"run {card.run_date} · git {card.git_short}")
    try:
        render_details(report)
    except Exception as exc:  # noqa: BLE001 - a malformed section must not blank the tab
        st.info(f"Some detail sections could not be rendered ({type(exc).__name__}: {exc}).")


# ------------------------------------------------------------------------------------------ main


def main() -> None:
    st.set_page_config(page_title="UDS Diagnostics Assistant", layout="wide")
    st.title("UDS Diagnostics & Automated Test Generation Assistant")
    ctx = _sidebar()
    tabs = st.tabs(["Ask", "Generate & Review", "Run on Simulator", "Export", "Results"])
    with tabs[0]:
        _ask_tab(ctx)
    with tabs[1]:
        _generate_tab(ctx)
    with tabs[2]:
        _run_tab(ctx)
    with tabs[3]:
        _export_tab()
    with tabs[4]:
        _results_tab()


main()
