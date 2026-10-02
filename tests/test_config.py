"""Tests for the env-driven runtime Config."""

from __future__ import annotations

import pytest

from uds_assistant.config import get_config


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODE", raising=False)
    monkeypatch.delenv("RETRIEVER", raising=False)
    cfg = get_config()
    assert cfg.llm_mode == "mock"
    assert cfg.retriever == "bm25"


def test_valid_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "ollama")
    monkeypatch.setenv("RETRIEVER", "chroma")
    cfg = get_config()
    assert cfg.llm_mode == "ollama"
    assert cfg.retriever == "chroma"


def test_invalid_value_falls_back_with_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "bogus")
    with pytest.warns(UserWarning):
        cfg = get_config()
    assert cfg.llm_mode == "mock"
