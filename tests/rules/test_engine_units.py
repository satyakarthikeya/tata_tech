"""Unit tests for state, seed derivation, engine plumbing, explain, and RulesSession."""

from __future__ import annotations

import pytest

from tests.rules.helpers import unlock
from uds_assistant.protocol import builders
from uds_assistant.protocol.constants import Nrc
from uds_assistant.protocol.security import compute_key, derive_seed
from uds_assistant.rules.engine import RulesSession, evaluate, explain
from uds_assistant.rules.request import parse_request
from uds_assistant.rules.state import (
    EnvironmentConditions,
    RoutineStatus,
    initial_state,
    with_environment,
)
from uds_assistant.spec.schema import EcuSpec


@pytest.mark.parametrize(
    ("level", "counter", "length", "expected"),
    [
        pytest.param(1, 0, 4, "950677e8", id="l1_c0"),
        pytest.param(1, 1, 4, "32a31485", id="l1_c1"),
        pytest.param(3, 0, 4, "0b7ced5e", id="l3_c0"),
        pytest.param(1, 3, 4, "6cdd4ebf", id="l1_c3"),
        pytest.param(1, 256, 2, "9506", id="counter_wraps_mod_256"),
    ],
)
def test_derive_seed_vectors(level: int, counter: int, length: int, expected: str) -> None:
    assert derive_seed(level, counter, length).hex() == expected


def test_derive_seed_never_all_zero() -> None:
    for level in range(1, 0x80):
        for counter in range(256):
            assert any(derive_seed(level, counter, 1))


def test_derive_seed_rejects_bad_args() -> None:
    with pytest.raises(ValueError):
        derive_seed(1, 0, 0)
    with pytest.raises(ValueError):
        derive_seed(1, -1, 4)


def test_initial_state(spec: EcuSpec) -> None:
    s = initial_state(spec, now_ms=123)
    assert s.active_session == 0x01
    assert s.unlocked_level is None
    assert set(s.lockouts) == {0x01, 0x03}
    assert s.pending_seeds == {}
    assert s.seed_counter == 0
    assert s.started_routines == frozenset()
    assert s.dtc_status == {0xB10101: 0, 0xB10205: 0, 0xB10310: 0}
    assert s.did_values[0xF190] == b"SYNTHETICBM000001"
    assert s.environment.vehicle_stationary
    assert s.last_request_ms is None
    assert s.now_ms == 123


def test_environment_conditions() -> None:
    assert EnvironmentConditions().is_met("vehicle_stationary")
    assert not EnvironmentConditions(vehicle_speed_kph=1).is_met("vehicle_stationary")
    assert not EnvironmentConditions().is_met("unknown_condition")


def test_parse_request_lenient() -> None:
    assert parse_request(b"").sid is None
    p = parse_request(bytes([0x3E, 0x80]))
    assert p.subfunction == 0x00 and p.suppress_positive
    p = parse_request(bytes([0x27, 0x81]))
    assert p.subfunction == 0x81 and not p.suppress_positive
    p = parse_request(bytes([0xFF]))
    assert p.sid == 0xFF and p.subfunction is None


def test_accepts_uds_request_objects(spec: EcuSpec) -> None:
    result = evaluate(spec, initial_state(spec), builders.read_did(0xF186), 0)
    assert result.responses == [bytes([0x62, 0xF1, 0x86, 0x01])]
    result = evaluate(spec, initial_state(spec), builders.tester_present(), 0)
    assert result.responses == []


def test_evaluate_returns_new_state_and_sets_timestamps(spec: EcuSpec) -> None:
    s0 = initial_state(spec)
    r = evaluate(spec, s0, bytes([0x10, 0x03]), 42)
    assert r.next_state.active_session == 0x03
    assert r.next_state.last_request_ms == 42
    assert r.next_state.now_ms == 42
    assert s0.active_session == 0x01 and s0.last_request_ms is None


def test_empty_request_does_not_restart_s3(spec: EcuSpec) -> None:
    session = RulesSession(spec)
    session.send("1003", now_ms=0)
    session.send(b"", now_ms=4000)
    assert session.state.last_request_ms == 0
    assert session.send("22F186", now_ms=5001).responses == [bytes.fromhex("62F18601")]


def test_full_lockout_cycle_state(spec: EcuSpec) -> None:
    session = RulesSession(spec)
    session.send("1003")
    codes = []
    for _ in range(3):
        session.send("2701")
        codes.append(session.send("270200000000").nrc)
    assert codes == [Nrc.INVALID_KEY, Nrc.INVALID_KEY, Nrc.EXCEED_NUMBER_OF_ATTEMPTS]
    lock = session.state.lockouts[0x01]
    assert lock.failed_attempts == 3 and lock.locked_until_ms == 10_000
    assert session.state.pending_seeds == {}
    # Delay expires exactly at locked_until_ms; a correct key then clears the counter.
    session.send("3E80", now_ms=4000)
    session.send("3E80", now_ms=8000)
    seed = session.send("2701", now_ms=10_000).responses[0][2:]
    assert session.send(bytes([0x27, 0x02]) + compute_key(seed, 1)).responses == [b"\x67\x02"]
    assert session.state.lockouts[0x01].failed_attempts == 0
    assert session.state.unlocked_level == 0x01


def test_failed_attempts_reset_only_by_success(spec: EcuSpec) -> None:
    session = RulesSession(spec)
    session.send("1003")
    session.send("2701")
    session.send("270200000000")
    session.send("1003")
    assert session.state.lockouts[0x01].failed_attempts == 1
    session.send("1101")
    assert session.state.lockouts[0x01].failed_attempts == 1
    session.send("1003")
    unlock(session, 1)
    assert session.state.lockouts[0x01].failed_attempts == 0


def test_routine_status_tracking(spec: EcuSpec) -> None:
    session = RulesSession(spec)
    session.send("1003")
    unlock(session, 1)
    session.send("31010201")
    assert session.state.routine_status == {0x0201: RoutineStatus.RUNNING}
    assert session.state.running_routines == frozenset({0x0201})
    session.send("31020201")
    assert session.state.routine_status == {0x0201: RoutineStatus.STOPPED}
    assert session.state.started_routines == frozenset({0x0201})


def test_pending_sequence_decision_fields(spec: EcuSpec) -> None:
    session = RulesSession(spec)
    session.send("1002")
    unlock(session, 3)
    r = session.send("31010203")
    assert r.decision.pending_nrc == Nrc.REQUEST_CORRECTLY_RECEIVED_RESPONSE_PENDING
    assert r.nrc is None
    assert r.final_response == bytes.fromhex("7101020302")


def test_nvm_fault_does_not_change_did(spec: EcuSpec) -> None:
    session = RulesSession(spec)
    session.send("1003")
    unlock(session, 1)
    session.set_environment(nvm_write_fault=True)
    assert session.send("2E010064").nrc == Nrc.GENERAL_PROGRAMMING_FAILURE
    session.set_environment(nvm_write_fault=False)
    assert session.send("220100").responses == [bytes.fromhex("62010032")]


def test_with_environment_is_pure(spec: EcuSpec) -> None:
    s0 = initial_state(spec)
    s1 = with_environment(s0, vehicle_speed_kph=50)
    assert s0.environment.vehicle_speed_kph == 0
    assert s1.environment.vehicle_speed_kph == 50


def test_explain_contains_trace_and_expected(spec: EcuSpec) -> None:
    r = evaluate(spec, initial_state(spec), bytes([0x27, 0x01]), 0)
    text = explain(r)
    assert "Step 2" in text and "NRC 0x7F" in text
    assert text.endswith("Expected: 7F 27 7F")
    r = evaluate(spec, initial_state(spec), bytes([0x3E, 0x80]), 0)
    assert explain(r).endswith("Expected: no response")


def test_trace_lists_steps_in_order(spec: EcuSpec) -> None:
    r = evaluate(spec, initial_state(spec), bytes([0x22, 0xF1, 0x90]), 0)
    steps = [t.split(":")[0] for t in r.trace if t.startswith("Step")]
    assert steps[:3] == ["Step 1", "Step 2", "Step 3"]


def test_session_send_accepts_hex_and_clock(spec: EcuSpec) -> None:
    session = RulesSession(spec, now_ms=100)
    session.advance(50)
    r = session.send("3E00")
    assert r.next_state.now_ms == 150
    assert len(session.history) == 1
