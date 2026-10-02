"""Hypothesis properties of the rules engine over arbitrary inputs."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.rules.helpers import bcm_spec, unlock
from uds_assistant.protocol.constants import Nrc
from uds_assistant.rules.engine import RulesSession, evaluate
from uds_assistant.rules.state import EcuState, initial_state, with_environment

SPEC = bcm_spec()
ALLOWED_NRCS = {int(n) for n in Nrc}
IN_SCOPE_SIDS = [0x10, 0x11, 0x14, 0x19, 0x22, 0x27, 0x2E, 0x31, 0x3E]


def _unlocked_extended() -> EcuState:
    session = RulesSession(SPEC)
    session.send("1003")
    unlock(session, 1)
    session.send("31010201")
    return session.state


def _programming_locked_out_faulty() -> EcuState:
    session = RulesSession(SPEC)
    session.send("1002")
    unlock(session, 3)
    for _ in range(3):
        session.send("2703")
        session.send("270400000000")
    return with_environment(session.state, vehicle_speed_kph=40, nvm_write_fault=True)


STATES = [initial_state(SPEC), _unlocked_extended(), _programming_locked_out_faulty()]

# Bias generation towards in-scope SIDs so deep paths are exercised.
REQUESTS = st.one_of(
    st.binary(max_size=40),
    st.tuples(st.sampled_from(IN_SCOPE_SIDS), st.binary(max_size=24)).map(
        lambda t: bytes([t[0]]) + t[1]
    ),
)


@settings(max_examples=600, deadline=None)
@given(raw=REQUESTS, state_idx=st.integers(0, len(STATES) - 1), dt=st.integers(0, 20_000))
def test_engine_never_raises_and_responses_well_formed(raw: bytes, state_idx: int, dt: int) -> None:
    """Any bytes -> only well-formed positive (SID+0x40) or 7F SID NRC responses."""
    state = STATES[state_idx]
    result = evaluate(SPEC, state, raw, state.now_ms + dt)
    if not raw:
        assert result.responses == []
        return
    sid = raw[0]
    assert len(result.responses) <= 2
    for i, resp in enumerate(result.responses):
        if resp[0] == 0x7F:
            assert len(resp) == 3
            assert resp[1] == sid
            assert resp[2] in ALLOWED_NRCS
            if len(result.responses) == 2 and i == 0:
                assert resp[2] == 0x78
            else:
                assert resp[2] not in (0x78, 0x10)
        else:
            assert resp[0] == sid + 0x40
            assert sid in IN_SCOPE_SIDS
        assert len(resp) <= SPEC.max_response_length
    if result.nrc is not None:
        assert result.responses == [bytes([0x7F, sid, int(result.nrc)])]


@settings(max_examples=300, deadline=None)
@given(raw=REQUESTS, state_idx=st.integers(0, len(STATES) - 1), dt=st.integers(0, 20_000))
def test_input_state_not_mutated(raw: bytes, state_idx: int, dt: int) -> None:
    """``evaluate`` never mutates the state it is given."""
    state = STATES[state_idx]
    before = state.model_dump()
    evaluate(SPEC, state, raw, state.now_ms + dt)
    assert state.model_dump() == before


@settings(max_examples=300, deadline=None)
@given(raw=REQUESTS, state_idx=st.integers(0, len(STATES) - 1), dt=st.integers(0, 20_000))
def test_evaluate_is_deterministic(raw: bytes, state_idx: int, dt: int) -> None:
    """Same inputs, same outputs."""
    state = STATES[state_idx]
    a = evaluate(SPEC, state, raw, state.now_ms + dt)
    b = evaluate(SPEC, state, raw, state.now_ms + dt)
    assert a.responses == b.responses
    assert a.next_state == b.next_state


@settings(max_examples=200, deadline=None)
@given(seq=st.lists(REQUESTS, min_size=1, max_size=15), step=st.integers(0, 3000))
def test_random_sequences_keep_invariants(seq: list[bytes], step: int) -> None:
    """Security only unlocked in a session that allows that level; default session is clean."""
    session = RulesSession(SPEC)
    for raw in seq:
        session.advance(step)
        session.send(raw)
        s = session.state
        assert SPEC.get_session(s.active_session) is not None
        if s.unlocked_level is not None:
            lvl = SPEC.get_security_level(s.unlocked_level)
            assert lvl is not None and s.active_session in lvl.allowed_sessions
        if s.active_session == 0x01:
            assert s.unlocked_level is None
            assert s.routine_status == {}
            assert s.pending_seeds == {}
