"""OllamaClient 4 GB-VRAM request options and call statistics (httpx.MockTransport)."""

from __future__ import annotations

import json

import httpx
import pytest

from uds_assistant.llm.base import LLMError, ParsedRequirement, TestPlan
from uds_assistant.llm.client import OllamaClient, ollama_reachable


def _chat_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


class Recorder:
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


def _client(rec: Recorder, **kw: object) -> OllamaClient:
    return OllamaClient(
        base_url="http://ollama.test:11434",
        transport=httpx.MockTransport(rec),
        sleep=lambda _s: None,
        **kw,  # type: ignore[arg-type]
    )


def test_vram_options_in_every_request_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_KEEP_ALIVE", raising=False)
    rec = Recorder(
        [
            _chat_reply(json.dumps({"dids": ["0xF190"], "intents": ["read"]})),
            _chat_reply(json.dumps({"tests": []})),
            _chat_reply("prose"),
        ]
    )
    client = _client(rec)
    client.complete_json("s", "p", ParsedRequirement)
    client.complete_json("s", "p", TestPlan)
    client.complete_text("s", "p")
    parse_body, plan_body, text_body = rec.bodies()
    for body in (parse_body, plan_body, text_body):
        assert body["options"]["num_ctx"] == 4096
        assert body["options"]["temperature"] == 0
        assert body["keep_alive"] == "10m"
        assert body["stream"] is False
    assert parse_body["format"] == ParsedRequirement.model_json_schema()
    assert plan_body["format"] == TestPlan.model_json_schema()
    assert "format" not in text_body


def test_num_ctx_env_and_argument_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_NUM_CTX", "2048")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "30s")
    rec = Recorder([_chat_reply("a"), _chat_reply("b")])
    _client(rec).complete_text("s", "p")
    assert rec.bodies()[0]["options"]["num_ctx"] == 2048
    assert rec.bodies()[0]["keep_alive"] == "30s"
    _client(rec, num_ctx=8192).complete_text("s", "p")
    assert rec.bodies()[1]["options"]["num_ctx"] == 8192
    monkeypatch.setenv("OLLAMA_NUM_CTX", "garbage")
    assert OllamaClient().num_ctx == 4096


def test_stats_count_calls_json_failures_and_retries() -> None:
    rec = Recorder(
        [
            _chat_reply("not json"),
            _chat_reply(json.dumps({"dids": ["bad!"]})),
            _chat_reply(json.dumps({"dids": ["0xF190"]})),
            httpx.ReadTimeout("slow"),
            _chat_reply("prose"),
        ]
    )
    client = _client(rec, max_retries=2)
    client.complete_json("s", "p", ParsedRequirement)
    client.complete_text("s", "p")
    st = client.stats.snapshot()
    assert st["calls"] == 2
    assert st["json_failures"] == 2
    assert st["retries"] == 3  # two schema re-prompts + one transport retry
    assert st["http_requests"] == 5
    assert st["errors"] == 0
    assert st["latency_ms"] >= 0


def test_stats_count_errors() -> None:
    rec = Recorder([_chat_reply("x")] * 3)
    client = _client(rec, max_retries=2)
    with pytest.raises(LLMError):
        client.complete_json("s", "p", ParsedRequirement)
    assert client.stats.errors == 1
    assert client.stats.json_failures == 3


@pytest.mark.needs_model
def test_real_ollama_parse_returns_valid_parsed_requirement() -> None:
    """One real parse call with the pipeline's own prompt returns a valid object."""
    from uds_assistant.llm.base import ALL_INTENTS, build_prompt
    from uds_assistant.llm.prompts import PARSE_INSTRUCTION, SYSTEM_PROMPT

    assert ollama_reachable(), "Ollama server not reachable"
    client = OllamaClient()
    prompt = build_prompt(
        PARSE_INSTRUCTION,
        {
            "task": "parse",
            "requirement_id": "REQ-001",
            "requirement_text": "The tester shall be able to read the VIN (DID 0xF190) "
            "in any diagnostic session.",
            "spec_index": {
                "dids": {"0xF190": "VIN"},
                "services": {"0x22": "ReadDataByIdentifier"},
            },
            "allowed_intents": list(ALL_INTENTS),
        },
    )
    parsed = client.complete_json(SYSTEM_PROMPT, prompt, ParsedRequirement)
    assert isinstance(parsed, ParsedRequirement)
    assert client.stats.calls == 1
