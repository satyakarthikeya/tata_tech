"""Model-dependent UI check (needs a running Ollama): the 7-minute demo path in ollama mode."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from uds_assistant.ui.examples import NATURAL_TEXT

UI_FILE = str(Path(__file__).resolve().parents[2] / "uds_assistant" / "ui" / "streamlit_app.py")


@pytest.mark.needs_model
def test_demo_path_ollama_natural_requirement_then_v3_bug() -> None:
    at = AppTest.from_file(UI_FILE, default_timeout=300)
    at.run()
    radio = at.radio(key="llm_mode")
    if "ollama" not in radio.options:
        pytest.skip("Ollama not reachable")
    radio.set_value("ollama").run()
    sb = at.selectbox(key="example_choice")
    sb.select(next(o for o in sb.options if o.startswith("REQ-NL-DOOR"))).run()
    assert at.text_area(key="req_text").value == NATURAL_TEXT
    next(b for b in at.button if b.label == "Generate tests").click().run()
    assert not at.exception
    assert any("LLM backend used: ollama" in c.value for c in at.caption)
    assert at.session_state["tests"]
    bug = at.selectbox(key="bug_choice")
    bug.select(next(o for o in bug.options if " session_response_p2_star_in_ms " in o)).run()
    at.radio(key="run_scope").set_value("all tests")
    next(b for b in at.button if b.label == "Run on simulator").click().run()
    assert not at.exception
    assert any(s.value.startswith("Bug caught by") for s in at.success)
