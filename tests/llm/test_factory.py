"""get_llm: mock default, Ollama when reachable, warned fallback when not."""

from __future__ import annotations

import warnings

import httpx
import pytest

from uds_assistant.config import Config
from uds_assistant.llm import factory
from uds_assistant.llm.client import OllamaClient
from uds_assistant.llm.factory import get_llm
from uds_assistant.llm.mock import MockLLM


def test_mock_is_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODE", raising=False)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        llm = get_llm()
        assert isinstance(llm, MockLLM)
        assert llm.fallback_events == []


def test_ollama_unreachable_falls_back_with_warning() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.warns(UserWarning, match="falling back"):
        llm = get_llm(Config(llm_mode="ollama"), transport=httpx.MockTransport(down))
    assert isinstance(llm, MockLLM)
    assert len(llm.fallback_events) == 1
    assert llm.fallback_events[0].startswith("LLM_MODE=ollama requested but Ollama is not reachable")
    assert llm.fallback_events[0].endswith("falling back to the deterministic mock LLM.")


def test_ollama_reachable_returns_client() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"models": []}))
    llm = get_llm(Config(llm_mode="ollama"), transport=transport)
    assert isinstance(llm, OllamaClient)


def test_env_selects_ollama_and_probe_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "ollama")
    calls: list[str] = []

    def fake_probe(base_url: str, **kw: object) -> bool:
        calls.append(base_url)
        return False

    monkeypatch.setattr(factory, "ollama_reachable", fake_probe)
    with pytest.warns(UserWarning):
        assert isinstance(get_llm(), MockLLM)
    assert len(calls) == 1
