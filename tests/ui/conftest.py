"""Shared fixtures for the UI tests: temp audit DB and clean streamlit caches per test."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _ui_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each test gets its own audit DB and fresh st.cache_* state (backend, probes, report)."""
    monkeypatch.setenv("UDS_UI_AUDIT_DB", str(tmp_path / "ui_audit.sqlite"))
    try:
        import streamlit as st
    except ImportError:
        yield
        return
    st.cache_resource.clear()
    st.cache_data.clear()
    yield
    st.cache_resource.clear()
    st.cache_data.clear()
