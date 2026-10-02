"""Schema-level guarantees of the LLM layer: no byte fields, extras dropped."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from uds_assistant.llm.base import (
    CONTEXT_MARKER,
    LLMClient,
    ParsedRequirement,
    PlannedTest,
    TestPlan,
    build_prompt,
    extract_context,
)
from uds_assistant.llm.client import OllamaClient
from uds_assistant.llm.mock import MockLLM

_BYTE_LIKE = ("hex", "byte", "request", "response", "payload", "data", "step", "param")


def _all_property_names(schema: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for sub in [schema, *schema.get("$defs", {}).values()]:
        names |= set(sub.get("properties", {}))
    return names


@pytest.mark.parametrize("model", [ParsedRequirement, PlannedTest, TestPlan])
def test_llm_schemas_have_no_byte_or_parameter_fields(model: type[BaseModel]) -> None:
    names = _all_property_names(model.model_json_schema())
    offending = [n for n in names if any(word in n.lower() for word in _BYTE_LIKE)]
    assert offending == []


def test_planned_test_fields_are_exactly_template_index_rationale() -> None:
    assert set(PlannedTest.model_fields) == {"template_id", "option_index", "rationale"}


def test_extra_fields_from_llm_are_dropped() -> None:
    plan = TestPlan.model_validate(
        {
            "tests": [
                {
                    "template_id": "read_did_positive",
                    "option_index": 0,
                    "rationale": "x",
                    "request_hex": "2e0100ff",
                    "steps": [{"kind": "send", "request_hex": "1101"}],
                }
            ],
            "raw_bytes": "deadbeef",
        }
    )
    dumped = plan.model_dump()
    assert "raw_bytes" not in dumped
    assert set(dumped["tests"][0]) == {"template_id", "option_index", "rationale"}


def test_negative_option_index_rejected() -> None:
    with pytest.raises(ValidationError):
        PlannedTest(template_id="x", option_index=-1)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0xf190", "0xF190"), ("F190", "0xF190"), ("0x2e", "0x2E"), (" 0x01 ", "0x01")],
)
def test_identifier_normalisation(raw: str, expected: str) -> None:
    assert ParsedRequirement(dids=[raw]).dids == [expected]


@pytest.mark.parametrize("bad", ["read VIN", "0xZZ", "2e 01 00"])
def test_non_hex_identifier_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        ParsedRequirement(services=[bad])


def test_dtc_and_intent_validation() -> None:
    p = ParsedRequirement(dtcs=["b10101", "B10101"], intents=["security", "security"])
    assert p.dtcs == ["B10101"]
    assert p.intents == ["security"]
    with pytest.raises(ValidationError):
        ParsedRequirement(intents=["make_bytes"])
    with pytest.raises(ValidationError):
        ParsedRequirement(dtcs=["B1"])


def test_prompt_context_round_trip() -> None:
    ctx = {"task": "plan", "n": 3, "items": ["a", "b"]}
    prompt = build_prompt("Do things.", ctx)
    assert prompt.startswith("Do things.")
    assert CONTEXT_MARKER in prompt
    assert extract_context(prompt) == ctx


@pytest.mark.parametrize("prompt", ["no marker", f"{CONTEXT_MARKER} not json", f"{CONTEXT_MARKER} [1]"])
def test_extract_context_tolerates_garbage(prompt: str) -> None:
    assert extract_context(prompt) == {}


def test_backends_satisfy_protocol() -> None:
    assert isinstance(MockLLM(), LLMClient)
    assert isinstance(OllamaClient(base_url="http://x"), LLMClient)
