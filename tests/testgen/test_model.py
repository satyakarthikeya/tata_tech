from __future__ import annotations

from pathlib import Path

from uds_assistant.testgen.model import (
    AdvanceTimeStep,
    Citation,
    SendStep,
    SetDtcStatusStep,
    SetEnvironmentStep,
    TestCase,
    dump_tests,
    load_tests,
)


def _sample() -> TestCase:
    return TestCase(
        id="t1",
        title="Sample",
        requirement_ids=["REQ-001"],
        category="positive",
        template_id=None,
        parameters={"did": 0xF190},
        preconditions=["ECU powered on"],
        steps=[
            SendStep(request_hex="22 F1 90", expected_responses_hex=["62f190AA"]),
            AdvanceTimeStep(ms=100, description="wait"),
            SetEnvironmentStep(vehicle_speed_kph=10),
            SetDtcStatusStep(code="B10101", status=0x08),
        ],
        citations=[Citation(source="bcm_spec.yaml", ref="dids.VIN")],
        explanation="demo",
        origin="gold",
    )


def test_send_step_normalizes_hex() -> None:
    step = SendStep(request_hex="22 F1 90", expected_responses_hex=["62 F1 90 AA"])
    assert step.request_hex == "22f190"
    assert step.request_bytes == bytes.fromhex("22f190")
    assert step.expected_responses_hex == ["62f190aa"]
    assert step.expected_response_bytes == [bytes.fromhex("62f190aa")]


def test_step_discriminator_round_trip() -> None:
    tc = _sample()
    dumped = tc.model_dump(mode="json")
    restored = TestCase.model_validate(dumped)
    assert [s.kind for s in restored.steps] == ["send", "advance_time", "set_environment", "set_dtc_status"]
    assert restored == tc


def test_yaml_round_trip(tmp_path: Path) -> None:
    tests = [_sample()]
    path = tmp_path / "tests.yaml"
    dump_tests(tests, path)
    loaded = load_tests(path)
    assert loaded == tests


def test_json_round_trip(tmp_path: Path) -> None:
    tests = [_sample()]
    path = tmp_path / "tests.json"
    dump_tests(tests, path)
    loaded = load_tests(path)
    assert loaded == tests


def test_default_review_status_and_origin() -> None:
    tc = TestCase(
        id="t2",
        title="Minimal",
        category="negative",
        steps=[SendStep(request_hex="10 01", expected_responses_hex=[])],
    )
    assert tc.review_status == "draft"
    assert tc.origin == "gold"
    assert tc.template_id is None
