"""Per-call JSON schema (enum of offered choices) through OllamaClient + httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from uds_assistant.llm.base import (
    ConstrainedPlan,
    LLMError,
    ParsedRequirement,
    constrained_plan_schema,
)
from uds_assistant.llm.client import OllamaClient

OFFERED = [("read_did_positive", 0), ("read_did_positive", 3), ("write_did_negative", 1)]


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


class Rec:
    def __init__(self, contents: list[str]) -> None:
        self.contents = list(contents)
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return _reply(self.contents.pop(0))


def _client(rec: Rec) -> OllamaClient:
    return OllamaClient(base_url="http://x:1", transport=httpx.MockTransport(rec),
                        sleep=lambda s: None)


def test_schema_enum_lists_exactly_the_offered_pairs() -> None:
    schema = constrained_plan_schema(OFFERED)
    item = schema["properties"]["tests"]["items"]  # type: ignore[index]
    assert item["properties"]["choice"]["enum"] == [
        "read_did_positive#0", "read_did_positive#3", "write_did_negative#1"]
    assert item["required"] == ["choice", "rationale"]
    assert schema["properties"]["tests"]["maxItems"] > 0  # type: ignore[index]


def test_custom_schema_is_sent_as_the_format_and_reply_round_trips() -> None:
    rec = Rec([json.dumps({"tests": [
        {"choice": "write_did_negative#1", "rationale": "bad value"},
        {"choice": "read_did_positive#3", "rationale": "read"},
    ]})])
    schema = constrained_plan_schema(OFFERED)
    plan = _client(rec).complete_json("S", "P", ConstrainedPlan, json_schema=schema).to_test_plan()
    assert rec.bodies[0]["format"] == schema
    assert rec.bodies[0]["format"]["properties"]["tests"]["items"]["properties"]["choice"][
        "enum"] == [f"{t}#{i}" for t, i in OFFERED]
    assert [(t.template_id, t.option_index, t.rationale) for t in plan.tests] == [
        ("write_did_negative", 1, "bad value"), ("read_did_positive", 3, "read")]


def test_without_json_schema_the_models_own_schema_is_used() -> None:
    rec = Rec([json.dumps({"tests": []})])
    _client(rec).complete_json("S", "P", ConstrainedPlan)
    assert rec.bodies[0]["format"] == ConstrainedPlan.model_json_schema()
    rec = Rec([json.dumps({"services": ["0x22"]})])
    _client(rec).complete_json("S", "P", ParsedRequirement)
    assert rec.bodies[0]["format"] == ParsedRequirement.model_json_schema()


def test_custom_schema_survives_the_schema_reprompt() -> None:
    rec = Rec(["not json", json.dumps({"tests": [{"choice": "read_did_positive#0"}]})])
    schema = constrained_plan_schema(OFFERED)
    out = _client(rec).complete_json("S", "P", ConstrainedPlan, json_schema=schema)
    assert len(out.tests) == 1
    assert [b["format"] for b in rec.bodies] == [schema, schema]


def test_client_advertises_schema_support_and_complete_text_has_no_format() -> None:
    assert OllamaClient.supports_json_schema is True
    rec = Rec(["hello"])
    _client(rec).complete_text("S", "P")
    assert "format" not in rec.bodies[0]


def test_exhausted_retries_raise_llm_error() -> None:
    rec = Rec(["x", "y", "z"])
    with pytest.raises(LLMError):
        _client(rec).complete_json("S", "P", ConstrainedPlan,
                                   json_schema=constrained_plan_schema(OFFERED))


@pytest.mark.parametrize(
    "choice,expected",
    [
        ("a_b#2", ("a_b", 2)),
        ("  a_b#12 ", ("a_b", 12)),
        ("weird#name#4", ("weird#name", 4)),
        ("a_b", ("a_b", 0)),
        ("a_b#x", ("a_b#x", 0)),
        ("#3", ("#3", 0)),
    ],
)
def test_to_test_plan_parses_back_deterministically(choice: str, expected: tuple[str, int]) -> None:
    plan = ConstrainedPlan.model_validate({"tests": [{"choice": choice}]}).to_test_plan()
    assert (plan.tests[0].template_id, plan.tests[0].option_index) == expected


def test_constrained_models_have_no_byte_like_fields() -> None:
    names = set(ConstrainedPlan.model_json_schema()["$defs"]["ChoiceReply"]["properties"])
    assert names == {"choice", "rationale"}
