"""OllamaClient truncation detection from ``prompt_eval_count`` (MockTransport, no server)."""

from __future__ import annotations

import json

import httpx

from uds_assistant.llm.base import ParsedRequirement, context_budget
from uds_assistant.llm.client import OllamaClient
from uds_assistant.llm.mock import MockLLM


def _client(prompt_eval_count: int | None, num_ctx: int = 4096) -> OllamaClient:
    def handler(request: httpx.Request) -> httpx.Response:
        payload: dict = {"message": {"role": "assistant", "content": json.dumps({})}}
        if prompt_eval_count is not None:
            payload["prompt_eval_count"] = prompt_eval_count
        return httpx.Response(200, json=payload)

    return OllamaClient(base_url="http://ollama.test", transport=httpx.MockTransport(handler),
                        num_ctx=num_ctx, sleep=lambda _s: None)


def test_context_tokens_capability() -> None:
    assert _client(10).context_tokens == 4096
    assert context_budget(_client(10, num_ctx=2048)) == 2048
    assert context_budget(MockLLM()) is None


def test_small_prompt_is_not_flagged() -> None:
    client = _client(300)
    client.complete_json("sys", "short prompt", ParsedRequirement)
    assert client.stats.truncations == 0
    assert client.truncation_events == []


def test_prompt_eval_count_at_num_ctx_is_flagged() -> None:
    client = _client(4090)
    client.complete_json("sys", "x" * 3000, ParsedRequirement)
    assert client.stats.truncations == 1
    assert client.truncation_events[0].startswith(
        "prompt likely truncated: prompt_eval_count=4090 num_ctx=4096")


def test_ollama_half_context_cut_is_flagged() -> None:
    """A 46 kB prompt evaluated as 2050 tokens is Ollama's silent truncation signature."""
    client = _client(2050)
    client.complete_json("sys", "y" * 46_000, ParsedRequirement)
    assert client.stats.truncations == 1
    assert client.stats.snapshot()["truncations"] == 1
    assert "prompt_eval_count=2050 num_ctx=4096" in client.truncation_events[0]


def test_untruncated_prompt_near_half_context_is_not_flagged() -> None:
    client = _client(2050)
    client.complete_json("sys", "z" * 6000, ParsedRequirement)  # ~2000 est. tokens
    assert client.stats.truncations == 0


def test_estimate_over_num_ctx_is_flagged_without_prompt_eval_count() -> None:
    client = _client(None)
    client.complete_text("sys", "w" * 20_000)
    assert client.stats.truncations == 1
    assert client.truncation_events[0].startswith(
        "prompt likely truncated: prompt_eval_count=n/a num_ctx=4096")
