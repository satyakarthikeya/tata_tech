"""Environment probes and paths for the UI (no streamlit import)."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

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


LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
REMOTE_OLLAMA_WARNING = (
    "OLLAMA_HOST is not localhost: requirements, questions and retrieved text would LEAVE THIS "
    "MACHINE. Use a local Ollama for any confidential data."
)


def ollama_is_local(base_url: str | None = None) -> bool:
    """True when the configured Ollama host is this machine (``localhost`` / loopback)."""
    host = urlparse(base_url or ollama_base_url()).hostname or ""
    return host.lower() in LOCAL_HOSTS


def audit_db_path() -> Path:
    """The audit DB of the UI (``UDS_UI_AUDIT_DB`` overrides, used by the tests)."""
    return Path(os.environ.get("UDS_UI_AUDIT_DB") or REPO_ROOT / "outputs" / "ui_audit.sqlite")


def report_path() -> Path:
    """The evaluation report shown on the Results tab (``UDS_EVAL_REPORT`` overrides)."""
    return Path(os.environ.get("UDS_EVAL_REPORT") or REPO_ROOT / "outputs" / "eval_report.json")
