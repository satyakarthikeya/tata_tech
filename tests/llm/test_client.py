"""OllamaClient, driven entirely through ``httpx.MockTransport`` (no server, no model)."""

from __future__ import annotations

import json
import os

import httpx
import pytest

from uds_assistant.llm.base import LLMError, ParsedRequirement, TestPlan
from uds_assistant.llm.client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    OllamaClient,
    ollama_base_url,
    ollama_reachable,
)


def _chat_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


class Recorder:
    """Serves queued responses (or exceptions) and records request bodies."""

    def __init__(self, replies: list[httpx.Response | Exception]) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


def _client(rec: Recorder, **kw: object) -> tuple[OllamaClient, list[float]]:
    sleeps: list[float] = []
    client = OllamaClient(
        base_url="http://ollama.test:11434",
        transport=httpx.MockTransport(rec),
        sleep=sleeps.append,
        **kw,  # type: ignore[arg-type]
    )
    return client, sleeps


def test_request_body_and_response_parsing() -> None:
    rec = Recorder([_chat_reply(json.dumps({"tests": [
        {"template_id": "read_did_positive", "option_index": 2, "rationale": "r"}
    ]}))])
    client, _ = _client(rec, model="m:1")
    plan = client.complete_json("SYS", "PROMPT", TestPlan)
    assert plan.tests[0].template_id == "read_did_positive"
    assert plan.tests[0].option_index == 2

    req = rec.requests[0]
    assert req.method == "POST"
    assert str(req.url) == "http://ollama.test:11434/api/chat"
    body = rec.bodies()[0]
    assert body["model"] == "m:1"
    assert body["stream"] is False
    assert body["options"]["temperature"] == 0
    assert body["format"] == TestPlan.model_json_schema()
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "PROMPT"},
    ]


def test_extra_byte_fields_in_reply_are_discarded() -> None:
    rec = Recorder([_chat_reply(json.dumps({"tests": [
        {"template_id": "t", "option_index": 0, "request_hex": "2e0100ff"}
    ]}))])
    client, _ = _client(rec)
    plan = client.complete_json("s", "p", TestPlan)
    assert "request_hex" not in plan.tests[0].model_dump()


def test_retry_on_invalid_json_reprompts_with_error() -> None:
    good = json.dumps({"dids": ["0xF190"], "intents": ["read"]})
    rec = Recorder([_chat_reply("not json {"), _chat_reply(good)])
    client, sleeps = _client(rec)
    parsed = client.complete_json("s", "p", ParsedRequirement)
    assert parsed.dids == ["0xF190"]
    second = rec.bodies()[1]["messages"]
    assert second[2] == {"role": "assistant", "content": "not json {"}
    assert second[3]["role"] == "user" and "not valid JSON" in second[3]["content"]
    assert sleeps == []  # schema retries are immediate; backoff is for transport errors


def test_retry_on_schema_violation() -> None:
    rec = Recorder([
        _chat_reply(json.dumps({"dids": ["not-hex!"]})),
        _chat_reply(json.dumps({"dids": ["0x0100"]})),
    ])
    client, _ = _client(rec)
    assert client.complete_json("s", "p", ParsedRequirement).dids == ["0x0100"]
    assert "not a hex identifier" in rec.bodies()[1]["messages"][3]["content"]


def test_error_after_max_invalid_replies() -> None:
    rec = Recorder([_chat_reply("nope")] * 3)
    client, _ = _client(rec, max_retries=2)
    with pytest.raises(LLMError, match="valid ParsedRequirement"):
        client.complete_json("s", "p", ParsedRequirement)
    assert len(rec.requests) == 3


def test_timeout_is_retried_with_backoff_then_succeeds() -> None:
    rec = Recorder([
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("refused"),
        _chat_reply("hello"),
    ])
    client, sleeps = _client(rec, max_retries=2, backoff_s=0.5)
    assert client.complete_text("s", "p") == "hello"
    assert sleeps == [0.5, 1.0]
    assert "format" not in rec.bodies()[2]


def test_transport_error_after_max_retries() -> None:
    rec = Recorder([httpx.ConnectTimeout("t")] * 3)
    client, sleeps = _client(rec, max_retries=2)
    with pytest.raises(LLMError, match="unreachable after 3"):
        client.complete_text("s", "p")
    assert len(sleeps) == 2


def test_server_error_retried_client_error_not() -> None:
    rec = Recorder([httpx.Response(503, text="busy"), _chat_reply("ok")])
    client, _ = _client(rec)
    assert client.complete_text("s", "p") == "ok"

    rec2 = Recorder([httpx.Response(404, text="model not found")])
    client2, _ = _client(rec2)
    with pytest.raises(LLMError, match="404"):
        client2.complete_text("s", "p")
    assert len(rec2.requests) == 1


def test_missing_message_content_is_an_error() -> None:
    rec = Recorder([httpx.Response(200, json={"done": True})])
    client, _ = _client(rec)
    with pytest.raises(LLMError, match="no message content"):
        client.complete_text("s", "p")


def test_timeout_configured_on_client() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions.get("timeout", {}))
        return _chat_reply("x")

    client = OllamaClient(base_url="http://h", timeout_s=7.5, transport=httpx.MockTransport(handler))
    client.complete_text("s", "p")
    assert seen[0]["read"] == 7.5


def test_defaults_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    assert ollama_base_url() == DEFAULT_BASE_URL
    assert OllamaClient().model == DEFAULT_MODEL == "qwen2.5:3b-instruct-q4_K_M"
    monkeypatch.setenv("OLLAMA_HOST", "gpu-box:1234")
    assert ollama_base_url() == "http://gpu-box:1234"
    monkeypatch.setenv("OLLAMA_MODEL", "other:7b")
    assert OllamaClient().model == "other:7b"


def test_reachability_probe() -> None:
    def up(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": []})

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert ollama_reachable("http://h", transport=httpx.MockTransport(up))
    assert not ollama_reachable("http://h", transport=httpx.MockTransport(down))
    assert not ollama_reachable(
        "http://h", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )


@pytest.mark.needs_model
def test_real_ollama_smoke() -> None:
    """Hits a real local Ollama server; skipped unless RUN_MODEL_TESTS=1."""
    base = os.environ.get("OLLAMA_HOST") or DEFAULT_BASE_URL
    assert ollama_reachable(base), "Ollama server not reachable"
    client = OllamaClient()
    parsed = client.complete_json(
        "Extract identifiers as JSON.",
        "Requirement: read the VIN (DID 0xF190) in any session.",
        ParsedRequirement,
    )
    assert isinstance(parsed, ParsedRequirement)
