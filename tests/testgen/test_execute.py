from __future__ import annotations

from uds_assistant.simulator import SimulatedEcu
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.execute import run_test_on_simulator
from uds_assistant.testgen.model import SendStep, TestCase


def test_run_passes_on_clean_simulator(spec: EcuSpec) -> None:
    tc = TestCase(
        id="exec1",
        title="tester present",
        category="positive",
        steps=[SendStep(request_hex="3e00", expected_responses_hex=["7e00"])],
    )
    outcome = run_test_on_simulator(tc, lambda: SimulatedEcu(spec))
    assert outcome.passed
    assert outcome.first_failure is None
    assert outcome.step_outcomes[0].actual_responses_hex == ["7e00"]


def test_run_detects_mismatch(spec: EcuSpec) -> None:
    tc = TestCase(
        id="exec2",
        title="wrong expectation",
        category="positive",
        steps=[SendStep(request_hex="3e00", expected_responses_hex=["ffffff"])],
    )
    outcome = run_test_on_simulator(tc, lambda: SimulatedEcu(spec))
    assert not outcome.passed
    assert outcome.first_failure is not None
    assert outcome.first_failure.index == 0


def test_run_handles_all_step_kinds(spec: EcuSpec) -> None:
    from uds_assistant.testgen.model import AdvanceTimeStep, SetDtcStatusStep, SetEnvironmentStep

    tc = TestCase(
        id="exec3",
        title="full step kinds",
        category="positive",
        steps=[
            SetEnvironmentStep(vehicle_speed_kph=5),
            SetDtcStatusStep(code="B10101", status=0x08),
            AdvanceTimeStep(ms=10),
            SendStep(request_hex="22 01 40", expected_responses_hex=["62014005"]),
        ],
    )
    outcome = run_test_on_simulator(tc, lambda: SimulatedEcu(spec))
    assert outcome.passed
    assert [o.kind for o in outcome.step_outcomes] == [
        "set_environment",
        "set_dtc_status",
        "advance_time",
        "send",
    ]
