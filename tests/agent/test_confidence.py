"""E3.2: shared confidence rule (one test per signal, combos) and pipeline/API wiring."""

from __future__ import annotations

import pytest

from tests.agent.conftest import SEED_REQUIREMENTS
from uds_assistant.agent import run_pipeline
from uds_assistant.agent.confidence import (
    WEAK_SCORE,
    answer_confidence,
    generated_test_confidence,
)
from uds_assistant.agent.grounding import target_is_written
from uds_assistant.llm.mock import MockLLM
from uds_assistant.qa.confidence import qa_confidence
from uds_assistant.testgen.model import TestCase

STRONG = 30.0


def conf(**kw: object) -> tuple[str, str]:
    base: dict[str, object] = {"top_score": STRONG}
    base.update(kw)
    return generated_test_confidence(**base)  # type: ignore[arg-type]


def test_no_signal_is_high() -> None:
    level, why = conf()
    assert level == "high" and "written in the requirement" in why


def test_inferred_target_downgrades_and_is_named() -> None:
    level, why = conf(inferred=["0x27"])
    assert level == "medium" and "inferred target 0x27 (not in text)" in why


def test_weak_retrieval_downgrades() -> None:
    level, why = conf(top_score=WEAK_SCORE - 0.1)
    assert level == "medium" and "weak retrieval" in why
    assert conf(top_score=WEAK_SCORE)[0] == "high"


def test_no_matching_hit_is_weak() -> None:
    level, why = generated_test_confidence(top_score=None)
    assert level == "medium" and "no matching hit" in why


def test_rejections_downgrade() -> None:
    level, why = conf(rejections=1)
    assert level == "medium" and "1 rejection" in why


def test_retries_downgrade() -> None:
    level, why = conf(retries=2)
    assert level == "medium" and "2 planner retries" in why


def test_rejections_and_retries_are_one_signal() -> None:
    level, why = conf(rejections=3, retries=2)
    assert level == "medium" and "3 rejections" in why and "2 planner retries" in why


def test_grounding_drop_downgrades() -> None:
    level, why = conf(grounding_drops=2)
    assert level == "medium" and "2 grounding drops" in why


def test_fallback_downgrades() -> None:
    level, why = conf(fallbacks=["explain: x: missing in LLM reply; used fallback text"])
    assert level == "medium" and "fallback event" in why


def test_combos_floor_at_low() -> None:
    level, why = conf(inferred=["0x27"], rejections=1)
    assert level == "low"
    assert why.startswith("inferred target 0x27 (not in text); 1 rejection")
    level, why = conf(inferred=["0x27"], rejections=1, grounding_drops=1, fallbacks=["f"])
    assert level == "low" and why.count(";") == 3


def test_deterministic() -> None:
    assert conf(inferred=["0x2E"], retries=1) == conf(inferred=["0x2E"], retries=1)


# ------------------------------------------------------------------------------- Q&A


@pytest.mark.parametrize(
    ("kw", "level"),
    [
        ({"status": "not_found", "deterministic": False}, "low"),
        ({"status": "not_found", "deterministic": True}, "low"),
        ({"status": "answered", "deterministic": True}, "high"),
        ({"status": "answered", "deterministic": True, "fallback_used": True}, "medium"),
        ({"status": "answered", "deterministic": False, "coverage": 1.0}, "medium"),
        ({"status": "answered", "deterministic": False, "coverage": 0.79}, "low"),
        ({"status": "answered", "deterministic": False, "coverage": 1.0, "fallback_used": True}, "low"),
    ],
)
def test_answer_confidence_rules(kw: dict[str, object], level: str) -> None:
    got, why = answer_confidence(**kw)  # type: ignore[arg-type]
    assert got == level and why
    assert qa_confidence(**kw) == (got, why)  # type: ignore[arg-type]


def test_fallback_reason_names_fallback() -> None:
    assert "rejected" in answer_confidence(status="answered", deterministic=True, fallback_used=True)[1]


# ------------------------------------------------------------------ written vs inferred


@pytest.mark.parametrize(
    ("kind", "ident", "name", "text", "written"),
    [
        ("service", "0x27", "SecurityAccess", "Unlock via service 0x27.", True),
        ("service", "0x27", "SecurityAccess", "The tester shall unlock the ECU.", True),
        ("service", "0x27", "SecurityAccess", "Read the VIN.", False),
        ("service", "0x27", "SecurityAccess", "Wait 27 seconds.", False),
        ("did", "0xF190", "vin", "Read DID 0xF190.", True),
        ("did", "0xF190", "vin", "Read the VIN please.", True),
        ("did", "0xF187", "part_number", "Read DID 0xF190.", False),
        ("routine", "0x0201", "led_calibration", "Run the LED calibration.", True),
        ("routine", "0x0201", "led_calibration", "Run the self test.", False),
    ],
)
def test_target_is_written(kind: str, ident: str, name: str, text: str, written: bool) -> None:
    assert target_is_written(kind, ident, name, text) is written


# ----------------------------------------------------------------------------- pipeline


def test_pipeline_mock_tests_carry_confidence(spec, retriever) -> None:
    req = SEED_REQUIREMENTS[0]
    res = run_pipeline(req["text"], req["id"], spec, MockLLM(), retriever)
    assert res.tests
    for t in res.tests:
        assert t.confidence in ("high", "medium", "low") and t.confidence_reason
        targets = res.target_provenance[t.id]
        assert targets and targets[0].kind == "service"
        inferred = [e.id for e in targets if not e.written]
        assert ("inferred target" in t.confidence_reason) == bool(inferred)
        assert all(i in t.confidence_reason for i in inferred)
    assert {t.confidence for t in res.tests} >= {"high"}


def test_pipeline_mock_distribution_has_inferred_mediums(spec, retriever) -> None:
    req = SEED_REQUIREMENTS[0]
    res = run_pipeline(req["text"], req["id"], spec, MockLLM(), retriever)
    assert any(t.confidence == "medium" and "inferred target" in t.confidence_reason
               for t in res.tests)


def test_confidence_fields_optional_for_old_tests() -> None:
    raw = {"id": "x", "title": "t", "category": "positive",
           "steps": [{"kind": "send", "request_hex": "22f190", "expected_responses_hex": ["62f190"]}]}
    t = TestCase.model_validate(raw)
    assert t.confidence is None and t.confidence_reason == ""
