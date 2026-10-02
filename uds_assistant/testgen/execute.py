"""Execute a :class:`TestCase` against a (simulated) ECU and compare outcomes.

Kept intentionally simple: a single pass over the steps, with an injected
clock (starting at 0, advanced only by :class:`AdvanceTimeStep`). Phase 7's
runner builds a batch/report layer on top of :func:`run_test_on_simulator`.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from uds_assistant.simulator import SimulatedEcu
from uds_assistant.testgen.model import TestCase

EcuFactory = Callable[[], SimulatedEcu]


class StepOutcome(BaseModel):
    """Result of executing one step."""

    index: int
    kind: str
    passed: bool
    detail: str = ""
    actual_responses_hex: list[str] = Field(default_factory=list)
    expected_responses_hex: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0


class TestOutcome(BaseModel):
    """Result of executing an entire :class:`TestCase`."""

    test_id: str
    passed: bool
    step_outcomes: list[StepOutcome] = Field(default_factory=list)

    @property
    def first_failure(self) -> StepOutcome | None:
        return next((s for s in self.step_outcomes if not s.passed), None)


def run_test_on_simulator(test: TestCase, ecu_factory: EcuFactory) -> TestOutcome:
    """Run every step of ``test`` against a fresh ECU from ``ecu_factory``.

    Comparison is exact-bytes on the ordered list of response frames per send
    step. A test passes when every step passes.
    """
    ecu = ecu_factory()
    now_ms = 0
    outcomes: list[StepOutcome] = []
    for i, step in enumerate(test.steps):
        if step.kind == "send":
            start = now_ms
            actual = ecu.handle(step.request_bytes, now_ms=now_ms)
            actual_hex = [a.hex() for a in actual]
            passed = actual_hex == step.expected_responses_hex
            outcomes.append(
                StepOutcome(
                    index=i,
                    kind="send",
                    passed=passed,
                    detail="" if passed else f"expected {step.expected_responses_hex}, got {actual_hex}",
                    actual_responses_hex=actual_hex,
                    expected_responses_hex=step.expected_responses_hex,
                    elapsed_ms=now_ms - start,
                )
            )
        elif step.kind == "advance_time":
            now_ms += step.ms
            outcomes.append(StepOutcome(index=i, kind="advance_time", passed=True))
        elif step.kind == "set_environment":
            ecu.set_environment(
                vehicle_speed_kph=step.vehicle_speed_kph, nvm_write_fault=step.nvm_write_fault
            )
            outcomes.append(StepOutcome(index=i, kind="set_environment", passed=True))
        elif step.kind == "set_dtc_status":
            ecu.set_dtc_status(step.code, step.status)
            outcomes.append(StepOutcome(index=i, kind="set_dtc_status", passed=True))
        else:  # pragma: no cover - exhaustive over the TestStep union
            raise ValueError(f"Unknown step kind {step.kind!r}.")
    return TestOutcome(
        test_id=test.id,
        passed=all(o.passed for o in outcomes),
        step_outcomes=outcomes,
    )
