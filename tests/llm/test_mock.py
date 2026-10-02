"""MockLLM: deterministic rule-based parsing, planning and explanation."""

from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.agent.options import build_catalog, spec_index
from uds_assistant.llm.base import LLMError, ParsedRequirement, TestPlan, build_prompt
from uds_assistant.llm.mock import MockLLM
from uds_assistant.spec.schema import EcuSpec, load_spec

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def spec() -> EcuSpec:
    return load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")


def _parse(spec: EcuSpec, text: str) -> ParsedRequirement:
    prompt = build_prompt(
        "parse", {"task": "parse", "requirement_text": text, "spec_index": spec_index(spec)}
    )
    return MockLLM().complete_json("sys", prompt, ParsedRequirement)


# (text, expected subset per field, expected intents subset)
PARSE_TABLE = [
    (
        "The tester shall be able to read the VIN (DID 0xF190) in any diagnostic session.",
        {"dids": ["0xF190"], "services": ["0x22"]},
        {"positive", "read", "session"},
    ),
    (
        ("Writing the interior lighting brightness DID (0x0100) shall require extended session "
        "and security level 0x01."),
        {"dids": ["0x0100"], "security_levels": ["0x01"], "services": ["0x27", "0x2E"]},
        {"security", "write", "negative"},
    ),
    (
        ("The wiper sensitivity level (DID 0x0130) shall only accept values between 1 and 5 "
        "inclusive."),
        {"dids": ["0x0130"], "services": ["0x2E"]},
        {"range", "write"},
    ),
    (
        ("The lighting self-test routine (0x0201) shall not accept a stop or requestResults "
        "subfunction before start has been sent."),
        {"routines": ["0x0201"], "services": ["0x31"]},
        {"sequence", "routine", "negative"},
    ),
    (
        "ECUReset shall support hard reset (0x01) and soft reset (0x03) subfunctions only.",
        {"services": ["0x11"], "sessions": [], "security_levels": []},
        {"subfunction", "negative"},
    ),
    (
        "ReadDTCInformation shall support subfunction 0x02 (reportDTCByStatusMask) only.",
        {"services": ["0x19"], "sessions": []},
        {"subfunction"},
    ),
    (
        ("SecurityAccess level 0x01 shall lock out further attempts for 10 seconds after 3 "
        "consecutive invalid keys."),
        {"security_levels": ["0x01"], "services": ["0x27"]},
        {"security", "lockout", "timing"},
    ),
    (
        ("The tester shall be able to switch the BCM into extended diagnostic session (0x03) and "
        "back to default session (0x01)."),
        {"sessions": ["0x03", "0x01"], "services": ["0x10"]},
        {"session"},
    ),
    (
        "Clear DTC B10205 after reading it.",
        {"dtcs": ["B10205"]},
        {"dtc"},
    ),
]


@pytest.mark.parametrize(("text", "fields", "intents"), PARSE_TABLE)
def test_parse_table(spec: EcuSpec, text: str, fields: dict[str, list[str]], intents: set[str]) -> None:
    parsed = _parse(spec, text)
    for field_name, expected in fields.items():
        actual = getattr(parsed, field_name)
        if expected:
            assert actual == expected, (field_name, actual)
        else:
            assert actual == [], (field_name, actual)
    assert intents <= set(parsed.intents)


def test_parse_by_name_without_hex(spec: EcuSpec) -> None:
    parsed = _parse(spec, "Writing the wiper sensitivity level shall need security.")
    assert parsed.dids == ["0x0130"]


def test_read_dtc_information_is_not_read_data_by_identifier(spec: EcuSpec) -> None:
    parsed = _parse(spec, "ReadDTCInformation shall work.")
    assert "0x22" not in parsed.services


def test_parse_reports_unknown_identifiers_for_agent_to_drop(spec: EcuSpec) -> None:
    parsed = _parse(spec, "Read DID 0xBEEF in session 0x05.")
    assert parsed.dids == ["0xBEEF"]
    assert parsed.sessions == ["0x05"]


def test_parse_is_deterministic(spec: EcuSpec) -> None:
    text = PARSE_TABLE[1][0]
    assert _parse(spec, text) == _parse(spec, text)


def _plan(spec: EcuSpec, parsed: ParsedRequirement, rejected: list[dict] | None = None) -> TestPlan:
    ctx = {
        "task": "plan",
        "requirement": parsed.model_dump(),
        "templates": [t.model_dump() for t in build_catalog(spec)],
        "rejected": rejected or [],
    }
    return MockLLM().complete_json("sys", build_prompt("plan", ctx), TestPlan)


def test_plan_for_secured_writable_did_is_thorough(spec: EcuSpec) -> None:
    parsed = _parse(spec, PARSE_TABLE[1][0])
    chosen = {t.template_id for t in _plan(spec, parsed).tests}
    assert {
        "write_did_secured_positive",
        "write_did_without_security",
        "write_did_out_of_range",
        "write_did_invalid_length",
        "service_not_in_session",
        "security_invalid_key_lockout",
        "s3_timeout_reverts_session",
    } <= chosen


def test_plan_only_uses_offered_indices(spec: EcuSpec) -> None:
    catalog = {t.template_id: len(t.options) for t in build_catalog(spec)}
    for text, _, _ in PARSE_TABLE:
        for choice in _plan(spec, _parse(spec, text)).tests:
            assert choice.template_id in catalog
            assert 0 <= choice.option_index < catalog[choice.template_id]
            assert choice.rationale


def test_plan_respects_rejected_choices(spec: EcuSpec) -> None:
    parsed = _parse(spec, PARSE_TABLE[1][0])
    first = _plan(spec, parsed).tests[0]
    again = _plan(
        spec,
        parsed,
        rejected=[{"template_id": first.template_id, "option_index": first.option_index}],
    )
    assert (first.template_id, first.option_index) not in {
        (t.template_id, t.option_index) for t in again.tests
    }


def test_plan_empty_requirement_gives_empty_plan(spec: EcuSpec) -> None:
    assert _plan(spec, ParsedRequirement()).tests == []


def test_plan_is_deterministic(spec: EcuSpec) -> None:
    parsed = _parse(spec, PARSE_TABLE[3][0])
    assert _plan(spec, parsed) == _plan(spec, parsed)


def test_explain_is_templated_prose() -> None:
    ctx = {
        "task": "explain",
        "test": {
            "title": "Write DID X",
            "category": "negative",
            "requirement_id": "REQ-9",
            "template_description": "Write a security-gated DID without unlocking.",
            "rationale": "Because.",
            "step_descriptions": ["a", "b"],
            "citation_refs": ["data/bcm_spec.yaml#did:x"],
        },
    }
    text = MockLLM().complete_text("sys", build_prompt("explain", ctx))
    assert "REQ-9" in text and "negative" in text and "2 step(s)" in text
    assert "data/bcm_spec.yaml#did:x" in text
    assert text == MockLLM().complete_text("sys", build_prompt("explain", ctx))


def test_unknown_schema_raises() -> None:
    from pydantic import BaseModel

    class Other(BaseModel):
        x: int = 0

    with pytest.raises(LLMError):
        MockLLM().complete_json("sys", "prompt", Other)
