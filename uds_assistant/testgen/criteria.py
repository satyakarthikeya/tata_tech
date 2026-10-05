"""Deterministic preconditions and pass criteria for a :class:`TestCase`.

Both are derived by replaying the test's own steps through the rules engine and
reading the spec; no LLM is involved and no test byte is ever changed. The
preconditions describe the ECU state just before the *focus step* (the last send step, or a conformance case's stimulus; the action
under test), so setup steps (session change, unlock, injected DTC, environment)
show up as preconditions. The pass criteria describe what that step and the whole
test must produce.
"""

from __future__ import annotations

from uds_assistant.protocol.constants import ServiceId
from uds_assistant.protocol.describe import decode_responses
from uds_assistant.rules.engine import RulesSession
from uds_assistant.rules.state import EcuState, dtc_code_to_int, with_dtc_status
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.model import (
    SendStep,
    SetDtcStatusStep,
    SetEnvironmentStep,
    TestCase,
)


def _session_label(spec: EcuSpec, session: int) -> str:
    sdef = spec.get_session(session)
    name = sdef.name if sdef else "unknown"
    return f"ECU in {name} session ({session:#04x})"


def _target(spec: EcuSpec, raw: bytes):
    """The DID (WriteDataByIdentifier) or routine (RoutineControl) a request addresses."""
    if raw and raw[0] == ServiceId.WRITE_DATA_BY_IDENTIFIER and len(raw) >= 3:
        return spec.get_did((raw[1] << 8) | raw[2])
    if raw and raw[0] == ServiceId.ROUTINE_CONTROL and len(raw) >= 4:
        return spec.get_routine((raw[2] << 8) | raw[3])
    return None


def _required_level(spec: EcuSpec, raw: bytes) -> int | None:
    target = _target(spec, raw)
    if target is None:
        return None
    return getattr(target, "write_security_level", None) or getattr(target, "security_level", None)


def _focus_index(test: TestCase) -> int | None:
    """The action under test: the ``Stimulus:`` step of a conformance case, else the last send."""
    sends = [i for i, s in enumerate(test.steps) if s.kind == "send"]
    for i in sends:
        if test.steps[i].description.startswith("Stimulus:"):
            return i
    return sends[-1] if sends else None


def _replay(spec: EcuSpec, test: TestCase) -> tuple[EcuState, int, list[SetDtcStatusStep], bytes]:
    """State before the focus step, the clock then, injected DTCs, and its request bytes."""
    last = _focus_index(test)
    rs = RulesSession(spec, now_ms=0)
    injected: list[SetDtcStatusStep] = []
    for i, step in enumerate(test.steps):
        if i == last:
            break
        if isinstance(step, SendStep):
            rs.send(step.request_bytes)
        elif step.kind == "advance_time":
            rs.advance(step.ms)
        elif isinstance(step, SetEnvironmentStep):
            rs.set_environment(
                vehicle_speed_kph=step.vehicle_speed_kph, nvm_write_fault=step.nvm_write_fault
            )
        elif isinstance(step, SetDtcStatusStep):
            rs.state = with_dtc_status(rs.state, dtc_code_to_int(step.code), step.status)
            injected.append(step)
    raw = test.steps[last].request_bytes if last is not None else b""  # type: ignore[union-attr]
    return rs.state, rs.now_ms, injected, raw


def derive_preconditions(spec: EcuSpec, test: TestCase) -> list[str]:
    """Short human-readable ECU state needed before the action under test."""
    if not any(s.kind == "send" for s in test.steps):
        return ["No request is sent by this test."]
    state, now_ms, injected, raw = _replay(spec, test)
    out = [_session_label(spec, state.active_session)]

    need = _required_level(spec, raw)
    if need is not None:
        ok = state.unlocked_level == need
        out.append(f"Security level {need:#04x} {'unlocked' if ok else 'NOT unlocked'}")
    elif state.unlocked_level is not None:
        out.append(f"Security level {state.unlocked_level:#04x} unlocked")
    elif raw and raw[0] == ServiceId.SECURITY_ACCESS:
        out.append("No security level unlocked")
    for level in sorted(state.pending_seeds):
        out.append(f"Seed issued for level {level:#04x} and not yet answered")
    for level, lock in sorted(state.lockouts.items()):
        if lock.locked_until_ms is not None and now_ms < lock.locked_until_ms:
            out.append(
                f"Security level {level:#04x} in lockout delay "
                f"({lock.locked_until_ms - now_ms} ms left)"
            )
        elif lock.failed_attempts:
            out.append(f"{lock.failed_attempts} failed key attempt(s) on level {level:#04x}")
    for rid in sorted(state.routine_status):
        out.append(f"Routine {rid:#06x} already started")
    for dtc in injected:
        out.append(f"DTC {dtc.code} status injected as {dtc.status:#04x}")

    env = state.environment
    target = _target(spec, raw)
    wanted = target.conditions.requires if target is not None else []
    if env.vehicle_speed_kph > 0:
        out.append(f"Vehicle moving at {env.vehicle_speed_kph} km/h (not stationary)")
    elif "vehicle_stationary" in wanted:
        out.append("Vehicle stationary (0 km/h)")
    if env.nvm_write_fault:
        out.append("NVM write fault injected")
    return out


def derive_pass_criteria(spec: EcuSpec, test: TestCase) -> str:
    """One sentence on what the test must observe, from its expected bytes and timing."""
    sends = [s for s in test.steps if isinstance(s, SendStep)]
    focus = _focus_index(test)
    if focus is None:
        return "No request is sent; nothing to observe."
    last = test.steps[focus]
    assert isinstance(last, SendStep)
    state, _, _, _ = _replay(spec, test)
    session = spec.get_session(state.active_session)
    expected = last.expected_responses_hex
    if not expected:
        what = "ECU sends no response (positive response suppressed)"
    else:
        what = f"ECU replies {decode_responses(expected)}".replace(" | ", " then ")
    if last.max_response_time_ms is not None:
        timing = f" within {last.max_response_time_ms} ms (enforced limit)"
    elif session is not None and len(expected) > 1:
        timing = f" within P2* = {session.timing.p2_star_ms} ms"
    elif session is not None and expected:
        timing = f" within P2 = {session.timing.p2_ms} ms"
    else:
        timing = ""
    head = (
        f"All {len(sends)} requests must get exactly the expected bytes. Action under test: "
        if len(sends) > 1
        else ""
    )
    return f"{head}{what}{timing}."


def annotate_test(spec: EcuSpec, test: TestCase, *, overwrite: bool = False) -> TestCase:
    """Return ``test`` with empty ``preconditions`` / ``pass_criteria`` filled in.

    Steps are untouched. Hand-written values (gold YAML) are kept unless ``overwrite``.
    """
    update: dict[str, object] = {}
    if overwrite or not test.preconditions:
        update["preconditions"] = derive_preconditions(spec, test)
    if overwrite or not test.pass_criteria:
        update["pass_criteria"] = derive_pass_criteria(spec, test)
    return test.model_copy(update=update) if update else test


def annotate_tests(spec: EcuSpec, tests: list[TestCase]) -> list[TestCase]:
    """:func:`annotate_test` over a list."""
    return [annotate_test(spec, t) for t in tests]
