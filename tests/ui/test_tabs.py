"""Headless AppTest checks of the five tabs (mock LLM, temp audit DB; see conftest.py)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from uds_assistant.store.audit import AuditStore
from uds_assistant.ui import env
from uds_assistant.ui.examples import NATURAL_TEXT, requirement_examples
from uds_assistant.ui.results_cards import build_cards

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_FILE = str(REPO_ROOT / "uds_assistant" / "ui" / "streamlit_app.py")
BANNER = "Synthetic ECU spec. Human review required before any real-hardware execution."
# Verified by running the mock and Ollama pipelines on the natural door-lock requirement: both
# produce tests that catch this fresh v3 bug (see PROGRESS.md "E4").
DEMO_V3_BUG = "session_response_p2_star_in_ms"


def _app() -> AppTest:
    at = AppTest.from_file(UI_FILE, default_timeout=120)
    at.run()
    assert not at.exception
    return at


def _click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception
    return at


def _generate_example(at: AppTest, index: int) -> AppTest:
    sb = at.selectbox(key="example_choice")
    sb.select(sb.options[index]).run()
    return _click(at, "Generate tests")


def _all_text(at: AppTest) -> list[str]:
    out: list[str] = []
    for kind in ("warning", "info", "error", "success", "caption", "markdown", "text"):
        out += [str(getattr(e, "value", "")) for e in getattr(at, kind)]
    return out


# -------------------------------------------------------------------------------- structure


def test_five_tabs_render_and_banner_once() -> None:
    at = _app()
    assert [t.label for t in at.tabs] == [
        "Ask",
        "Generate & Review",
        "Run on Simulator",
        "Export",
        "Results",
    ]
    assert sum(BANNER in t for t in _all_text(at)) == 1
    assert [w.value for w in at.sidebar.warning if BANNER in w.value] == [BANNER]


def test_banner_still_once_after_generate_and_run() -> None:
    at = _generate_example(_app(), 4)
    _click(at, "Run on simulator")
    assert sum(BANNER in t for t in _all_text(at)) == 1
    assert not any("Generated tests require human review" in t for t in _all_text(at))


# ------------------------------------------------------------------------------------ sidebar


def test_ollama_option_disabled_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env, "ollama_status", lambda: (False, "Ollama not reachable at http://x:1"))
    at = _app()
    radio = at.radio(key="llm_mode")
    assert radio.options == ["mock"]
    assert radio.disabled
    assert radio.value == "mock"
    assert any("Ollama option disabled" in w.value and "not reachable" in w.value for w in at.sidebar.warning)


def test_ollama_option_enabled_when_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env, "ollama_status", lambda: (True, "Ollama reachable at http://x:1"))
    at = _app()
    radio = at.radio(key="llm_mode")
    assert radio.options == ["mock", "ollama"]
    assert not radio.disabled
    assert any("Ollama reachable" in s.value for s in at.sidebar.success)


def test_chroma_option_disabled_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env, "chroma_status", lambda embedder="fastembed": (False, "chromadb missing"))
    at = _app()
    radio = at.radio(key="retriever")
    assert radio.options == ["bm25"]
    assert radio.disabled
    assert any("Chroma option disabled: chromadb missing" in w.value for w in at.sidebar.warning)


# ---------------------------------------------------------------------------------------- Ask


def test_ask_answers_did_question_with_citations() -> None:
    at = _app()
    at.text_input(key="ask_q").set_value("What is the length of DID 0xF190?")
    _click(at, "Ask")
    texts = _all_text(at)
    assert any("17 bytes" in t for t in texts)
    assert any("confidence: high" in t for t in texts)
    exp = [e for e in at.expander if e.label.startswith("Citations")]
    assert exp, "citations expander missing"
    assert any("0xF190" in m.value for m in exp[0].markdown)
    assert not any("Not found in the approved sources." == w.value for w in at.warning)


def test_ask_unknown_did_is_not_found_callout() -> None:
    at = _app()
    at.text_input(key="ask_q").set_value("What does DID 0x0999 contain?")
    _click(at, "Ask")
    assert any(w.value == "Not found in the approved sources." for w in at.warning)
    assert any("confidence: low" in m.value for m in at.markdown)


def test_ask_example_dropdown_fills_the_question() -> None:
    at = _app()
    sb = at.selectbox(key="ask_example")
    sb.select(sb.options[1]).run()
    assert at.text_input(key="ask_q").value == sb.options[1]


# ------------------------------------------------------------------------ Generate & Review


def test_requirement_box_starts_empty_with_four_examples() -> None:
    at = _app()
    assert at.text_area(key="req_text").value == ""
    assert at.text_area(key="req_text").placeholder
    ex = requirement_examples()
    assert len(ex) == 4
    texts = [t for _, t in ex.values()]
    seed = (REPO_ROOT / "data" / "requirements_seed.csv").read_text(encoding="utf-8")
    assert all(t in seed for t in texts[:3])
    assert texts[3] == NATURAL_TEXT
    assert "door lock status must only be writable in extended session after security unlock." in NATURAL_TEXT


def test_empty_requirement_is_rejected() -> None:
    at = _click(_app(), "Generate tests")
    assert any("must not be empty" in e.value for e in at.error)


def test_generate_table_select_decoded_steps_and_chips() -> None:
    at = _generate_example(_app(), 4)  # the natural-language door-lock example
    assert at.text_area(key="req_text").value == NATURAL_TEXT
    table = next(d.value for d in at.dataframe if "review status" in d.value.columns)
    assert list(table.columns) == ["id", "category", "confidence", "review status"]
    assert len(table) >= 1
    sb = at.selectbox(key="selected_test")
    sb.select(sb.options[0]).run()
    steps = [c.value for c in at.code if c.value.startswith("[0]")]
    assert steps and "→" in steps[0]
    assert any("(" in s and ")" in s for s in steps)  # decoded tag
    assert any("written-badge" in m.value or "-badge[written]" in m.value or "-badge[inferred]" in m.value
               for m in at.markdown)
    assert any("confidence:" in m.value for m in at.markdown)


def test_approve_reject_comment_are_stored_in_audit_db() -> None:
    at = _generate_example(_app(), 4)
    run_id = at.session_state["run_id"]
    sb = at.selectbox(key="selected_test")
    first, second = sb.options[0], sb.options[1]
    sb.select(first).run()
    at.text_input(key="review_comment").set_value("looks right")
    _click(at, "Approve")
    sb = at.selectbox(key="selected_test")
    sb.select(second).run()
    at.text_input(key="review_comment").set_value("needs rework")
    _click(at, "Reject")
    _click(at, "Add comment")
    store = AuditStore(env.audit_db_path())
    status = {t.id: t.review_status for t in store.get_tests(run_id)}
    assert status[first] == "human_reviewed"
    assert status[second] == "draft"
    msgs = [d.message for d in store.get_decisions(run_id, "review")]
    assert f"{first} | approved | looks right" in msgs
    assert f"{second} | rejected | needs rework" in msgs
    assert f"{second} | comment | needs rework" in msgs
    table = next(d.value for d in at.dataframe if "review status" in d.value.columns)
    by_id = dict(zip(table["id"], table["review status"], strict=True))
    assert by_id[first] == "human_reviewed" and by_id[second] == "rejected"


# ----------------------------------------------------------------------------- Run on Simulator


def test_run_tab_without_tests_is_a_hint() -> None:
    at = _app()
    assert any("Generate tests first" in i.value for i in at.info)


def test_run_clean_all_tests_pass() -> None:
    at = _generate_example(_app(), 4)
    at.radio(key="run_scope").set_value("all tests")
    _click(at, "Run on simulator")
    assert any(s.value == "All tests pass on the clean simulator." for s in at.success)


def test_run_with_v3_bug_reports_caught_and_first_failing_step() -> None:
    at = _generate_example(_app(), 4)
    sb = at.selectbox(key="bug_choice")
    label = next(o for o in sb.options if f" {DEMO_V3_BUG} " in o)
    assert label.startswith("[held-out v3, fresh]")
    sb.select(label).run()
    assert any("P2*" in c.value for c in at.caption)  # the bug description is shown
    at.radio(key="run_scope").set_value("all tests")
    _click(at, "Run on simulator")
    assert any(s.value.startswith("Bug caught by") for s in at.success)
    res = next(d.value for d in at.dataframe if "result" in d.value.columns)
    assert (res["result"] == "FAIL").sum() >= 1
    codes = [c.value for c in at.code]
    assert any(c.startswith("expected:") and "(positive)" in c for c in codes)
    assert any("actual  : " in c for c in codes)
    assert any("First failing step" in m.value for m in at.markdown)


def test_run_bug_not_caught_message() -> None:
    at = _generate_example(_app(), 4)
    sb = at.selectbox(key="bug_choice")
    # a bug about DTC reads: none of the door-lock tests touch it
    label = next(o for o in sb.options if " dtc_read_reports_masked_status " in o)
    sb.select(label).run()
    at.radio(key="run_scope").set_value("all tests")
    _click(at, "Run on simulator")
    assert any(w.value == "Bug not caught." for w in at.warning)


def test_run_scopes_selected_and_approved() -> None:
    at = _generate_example(_app(), 4)
    at.radio(key="run_scope").set_value("approved tests")
    _click(at, "Run on simulator")
    assert any("No approved tests yet" in w.value for w in at.warning)
    _click(at, "Approve")
    at.radio(key="run_scope").set_value("approved tests")
    _click(at, "Run on simulator")
    assert next(m.value for m in at.metric if m.label == "Passed") == "1/1"
    at.radio(key="run_scope").set_value("selected test")
    _click(at, "Run on simulator")
    assert next(m.value for m in at.metric if m.label == "Passed") == "1/1"


# ------------------------------------------------------------------------------------ Export


def test_export_buttons_and_capl_label() -> None:
    at = _app()
    assert any("Generate tests first" in i.value for i in at.info)
    at = _generate_example(at, 4)
    labels = [b.proto.label for b in at.get("download_button")]
    assert "Download pytest file" in labels
    assert any("CAPL" in lab and "unverified — never run in CANoe" in lab for lab in labels)


# ----------------------------------------------------------------------------------- Results


def test_results_tab_shows_six_cards_with_run_and_git() -> None:
    at = _app()
    titles = [m.value for m in at.markdown if m.value.startswith("**") and m.value[2:3].isdigit()]
    assert len(titles) == 6, titles
    runs = [c.value for c in at.caption if c.value.startswith("run ") and "· git " in c.value]
    assert len(runs) == 6
    assert all("n/a" not in r for r in runs), runs
    assert len(at.expander) >= 7
    labels = [e.label for e in at.expander]
    assert any(lab.startswith("History") for lab in labels)
    assert any("Noise" in lab for lab in labels)


def test_cards_content_matches_report() -> None:
    report = json.loads((REPO_ROOT / "outputs" / "eval_report.json").read_text(encoding="utf-8"))
    cards = build_cards(report)
    assert len(cards) == 6 and all(c.available for c in cards)
    bugs = dict(cards[1].lines)
    assert bugs["mock"] == "10/15 (66.7%)"
    assert dict(cards[2].lines)["ollama"] == "0.609"


def test_results_degrades_without_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("UDS_EVAL_REPORT", str(tmp_path / "nope.json"))
    at = _app()
    assert any("No evaluation report" in i.value for i in at.info)


def test_results_degrades_with_malformed_and_minimal_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("UDS_EVAL_REPORT", str(bad))
    at = _app()
    assert any("could not be read" in i.value for i in at.info)
    minimal = tmp_path / "min.json"
    minimal.write_text(json.dumps({"report_version": 5, "modes": {}}), encoding="utf-8")
    monkeypatch.setenv("UDS_EVAL_REPORT", str(minimal))
    at = _app()
    assert not at.exception
    assert sum("Not in this report" in i.value for i in at.info) >= 6


def test_report_cache_follows_file_mtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    base = {"report_version": 5, "modes": {}, "headline_cards": []}
    p.write_text(json.dumps({**base, "timestamp": "FIRST"}), encoding="utf-8")
    monkeypatch.setenv("UDS_EVAL_REPORT", str(p))
    at = _app()
    assert any("FIRST" in c.value for c in at.caption)
    p.write_text(json.dumps({**base, "timestamp": "SECOND"}), encoding="utf-8")
    os.utime(p, (time.time() + 5, time.time() + 5))
    at.run()
    assert any("SECOND" in c.value for c in at.caption)
