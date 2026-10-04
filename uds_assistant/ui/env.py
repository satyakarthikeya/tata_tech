"""Environment probes and paths for the UI (no streamlit import)."""

from __future__ import annotations

import os
from pathlib import Path

from uds_assistant.llm.client import ollama_base_url, ollama_reachable
from uds_assistant.llm.factory import START_OLLAMA_HINT

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_TIMEOUT_S = 0.8


def ollama_status() -> tuple[bool, str]:
    """``(reachable, text)``; a short-timeout ``GET /api/tags`` against the configured host."""
    base = ollama_base_url()
    if ollama_reachable(base, timeout_s=PROBE_TIMEOUT_S):
        return True, f"Ollama reachable at {base}"
    return False, f"Ollama not reachable at {base}. {START_OLLAMA_HINT}."


def audit_db_path() -> Path:
    """The audit DB of the UI (``UDS_UI_AUDIT_DB`` overrides, used by the tests)."""
    return Path(os.environ.get("UDS_UI_AUDIT_DB") or REPO_ROOT / "outputs" / "ui_audit.sqlite")


def report_path() -> Path:
    """The evaluation report shown on the Results tab (``UDS_EVAL_REPORT`` overrides)."""
    return Path(os.environ.get("UDS_EVAL_REPORT") or REPO_ROOT / "outputs" / "eval_report.json")
