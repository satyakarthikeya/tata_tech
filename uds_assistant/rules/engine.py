"""Pure rules-engine evaluation: ``(spec, state, request, now_ms) -> RuleResult``.

NRCs are decided only in :mod:`uds_assistant.rules.nrc_order`; this module
applies clock effects before evaluation (S3 timeout, lockout-delay expiry),
builds the positive response payloads, applies state transitions, and
assembles the wire bytes. It never mutates its inputs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from uds_assistant.protocol.codec import UdsRequest, format_hex
from uds_assistant.protocol.constants import (
    NEGATIVE_RESPONSE_SID,
    POSITIVE_RESPONSE_OFFSET,
    Nrc,
    ServiceId,
)
from uds_assistant.protocol.security import (
    SecurityLockoutState,
    clear_expired_lockout,
    derive_seed,
    record_failed_attempt,
    record_successful_unlock,
)
from uds_assistant.rules.nrc_order import (
    CLEAR_ALL_DTC_GROUP,
    ROUTINE_RESULTS,
    ROUTINE_START,
    ROUTINE_STOP,
    NrcDecision,
    evaluate_nrc,
)
from uds_assistant.rules.request import ParsedRequest, parse_request
from uds_assistant.rules.state import (
    DEFAULT_SESSION_ID,
    DYNAMIC_DID_ACTIVE_SESSION,
    DYNAMIC_DID_VEHICLE_SPEED,
    EcuState,
    RoutineStatus,
    dtc_code_to_int,
    initial_state,
    with_environment,
)
from uds_assistant.spec.schema import EcuSpec


class RuleResult(BaseModel):
    """Everything the oracle predicts for one request.

    ``responses`` is the ordered list of wire responses the ECU sends: empty
    when the request is ignored or a positive response is suppressed; two
    entries (``7F SID 78`` then the final positive) for a response-pending
    sequence; otherwise exactly one entry.
    """

    request: bytes
    responses: list[bytes] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    decision: NrcDecision
    next_state: EcuState

    @property
    def final_response(self) -> bytes | None:
        """The last response sent, or ``None`` when nothing is sent."""
        return self.responses[-1] if self.responses else None

    @property
    def nrc(self) -> Nrc | None:
        """The final NRC, or ``None`` for a positive / ignored outcome."""
        return self.decision.nrc


def _reset_volatile(state: EcuState, session: int) -> EcuState:
    """Enter ``session`` and drop session-scoped state (security, seeds, routines)."""
    return state.model_copy(
        update={
            "active_session": session,
            "unlocked_level": None,
            "pending_seeds": {},
            "routine_status": {},
        }
    )


def _apply_clock(spec: EcuSpec, state: EcuState, now_ms: int, trace: list[str]) -> EcuState:
    """Advance the clock: S3 timeout and lockout-delay expiry, before evaluation."""
    st = state.model_copy(update={"now_ms": now_ms})
    session = spec.get_session(st.active_session)
    if (
        st.active_session != DEFAULT_SESSION_ID
        and st.last_request_ms is not None
        and session is not None
        and now_ms - st.last_request_ms > session.timing.s3_ms
    ):
        trace.append(
            f"Clock: S3 expired ({now_ms - st.last_request_ms} ms since last request > "
            f"{session.timing.s3_ms} ms) -> back to default session, security locked, "
            "seeds and routines cleared."
        )
        st = _reset_volatile(st, DEFAULT_SESSION_ID)
    new_lockouts: dict[int, SecurityLockoutState] = {}
    for level, lock in st.lockouts.items():
        cleared = clear_expired_lockout(lock, now_ms)
        if cleared != lock:
            trace.append(f"Clock: level 0x{level:02X} lockout delay expired.")
        new_lockouts[level] = cleared
    return st.model_copy(update={"lockouts": new_lockouts})


def _did_value(spec: EcuSpec, state: EcuState, did: int) -> bytes:
    """Current value of ``did``; a few DIDs are derived live from the state."""
    did_def = spec.get_did(did)
    assert did_def is not None
    if did_def.name == DYNAMIC_DID_ACTIVE_SESSION:
        return bytes([state.active_session]).rjust(did_def.length, b"\x00")
    if did_def.name == DYNAMIC_DID_VEHICLE_SPEED:
        speed = min(state.environment.vehicle_speed_kph, 0xFF)
        return bytes([speed]).rjust(did_def.length, b"\x00")
    return state.did_values.get(did, bytes(did_def.length))


def _positive(
    spec: EcuSpec, state: EcuState, req: ParsedRequest, trace: list[str]
) -> tuple[EcuState, bytes]:
    """Apply the positive-outcome state transition and build the response bytes."""
    raw = req.raw
    sid = raw[0]
    head = bytes([sid + POSITIVE_RESPONSE_OFFSET])
    sub = req.subfunction

    if sid == ServiceId.DIAGNOSTIC_SESSION_CONTROL:
        assert sub is not None
        target = spec.get_session(sub)
        assert target is not None
        p2 = target.timing.p2_ms & 0xFFFF
        p2_star_10ms = (target.timing.p2_star_ms // 10) & 0xFFFF
        trace.append(
            f"Effect: session -> 0x{sub:02X} ({target.name}); security locked, seeds and "
            "routines cleared."
        )
        payload = bytes([sub]) + p2.to_bytes(2, "big") + p2_star_10ms.to_bytes(2, "big")
        return _reset_volatile(state, sub), head + payload

    if sid == ServiceId.ECU_RESET:
        assert sub is not None
        trace.append("Effect: ECU reset -> default session, security locked, routines cleared.")
        return _reset_volatile(state, DEFAULT_SESSION_ID), head + bytes([sub])

    if sid == ServiceId.CLEAR_DIAGNOSTIC_INFORMATION:
        group = int.from_bytes(raw[1:4], "big")
        if group == CLEAR_ALL_DTC_GROUP:
            statuses = {code: 0x00 for code in state.dtc_status}
            trace.append("Effect: all DTC statuses cleared.")
        else:
            statuses = {**state.dtc_status, group: 0x00}
            trace.append(f"Effect: DTC 0x{group:06X} status cleared.")
        return state.model_copy(update={"dtc_status": statuses}), head

    if sid == ServiceId.READ_DTC_INFORMATION:
        assert sub is not None
        mask = raw[2]
        avail = spec.dtc_status_availability_mask
        body = bytearray([sub, avail])
        for dtc in spec.dtcs:
            code = dtc_code_to_int(dtc.code)
            status = state.dtc_status.get(code, 0) & avail
            if status & mask:
                body.extend(code.to_bytes(3, "big"))
                body.append(status)
        return state, head + bytes(body)

    if sid == ServiceId.READ_DATA_BY_IDENTIFIER:
        body = bytearray()
        for i in range(1, len(raw), 2):
            did = int.from_bytes(raw[i : i + 2], "big")
            body.extend(raw[i : i + 2])
            body.extend(_did_value(spec, state, did))
        return state, head + bytes(body)

    if sid == ServiceId.SECURITY_ACCESS:
        assert sub is not None
        level_def = next(
            lvl
            for lvl in spec.security_levels
            if sub in (lvl.seed_subfunction, lvl.key_subfunction)
        )
        level = level_def.level
        if sub == level_def.seed_subfunction:
            if state.unlocked_level == level:
                trace.append(f"Effect: level 0x{level:02X} already unlocked -> all-zero seed.")
                return state, head + bytes([sub]) + bytes(level_def.seed_length)
            seed = derive_seed(level, state.seed_counter, level_def.seed_length)
            trace.append(
                f"Effect: seed {format_hex(seed)} issued for level 0x{level:02X} "
                f"(seed counter {state.seed_counter})."
            )
            new_state = state.model_copy(
                update={
                    "pending_seeds": {**state.pending_seeds, level: seed},
                    "seed_counter": state.seed_counter + 1,
                }
            )
            return new_state, head + bytes([sub]) + seed
        pending = {k: v for k, v in state.pending_seeds.items() if k != level}
        trace.append(f"Effect: level 0x{level:02X} unlocked; attempt counter reset.")
        new_state = state.model_copy(
            update={
                "unlocked_level": level,
                "pending_seeds": pending,
                "lockouts": {**state.lockouts, level: record_successful_unlock()},
            }
        )
        return new_state, head + bytes([sub])

    if sid == ServiceId.WRITE_DATA_BY_IDENTIFIER:
        did = int.from_bytes(raw[1:3], "big")
        trace.append(f"Effect: DID 0x{did:04X} := {format_hex(raw[3:])}.")
        new_state = state.model_copy(update={"did_values": {**state.did_values, did: raw[3:]}})
        return new_state, head + raw[1:3]

    if sid == ServiceId.ROUTINE_CONTROL:
        assert sub is not None
        rid = int.from_bytes(raw[2:4], "big")
        routine = spec.get_routine(rid)
        assert routine is not None
        statuses = dict(state.routine_status)
        if sub == ROUTINE_START:
            status = RoutineStatus.COMPLETED if routine.long_running else RoutineStatus.RUNNING
            statuses[rid] = status
        elif sub == ROUTINE_STOP:
            status = RoutineStatus.STOPPED
            statuses[rid] = status
        else:
            assert sub == ROUTINE_RESULTS
            status = statuses.get(rid, RoutineStatus.NOT_STARTED)
        trace.append(f"Effect: routine 0x{rid:04X} status 0x{int(status):02X} ({status.name}).")
        new_state = state.model_copy(update={"routine_status": statuses})
        return new_state, head + bytes([sub]) + raw[2:4] + bytes([int(status)])

    assert sid == ServiceId.TESTER_PRESENT and sub is not None
    return state, head + bytes([sub])


def _negative_effects(
    spec: EcuSpec, state: EcuState, req: ParsedRequest, decision: NrcDecision, trace: list[str]
) -> EcuState:
    """State changes that accompany a negative outcome (only failed key attempts)."""
    if not decision.failed_key_attempt:
        return state
    sub = req.subfunction
    level_def = next(lvl for lvl in spec.security_levels if lvl.key_subfunction == sub)
    level = level_def.level
    current = state.lockouts.get(level, SecurityLockoutState())
    new_lock, _ = record_failed_attempt(
        current, state.now_ms, level_def.max_attempts, level_def.delay_ms
    )
    trace.append(
        f"Effect: level 0x{level:02X} failed attempts = {new_lock.failed_attempts}; "
        "pending seed consumed."
    )
    return state.model_copy(
        update={
            "lockouts": {**state.lockouts, level: new_lock},
            "pending_seeds": {k: v for k, v in state.pending_seeds.items() if k != level},
        }
    )


def evaluate(
    spec: EcuSpec,
    state: EcuState,
    request: bytes | bytearray | UdsRequest,
    now_ms: int,
) -> RuleResult:
    """Predict the ECU's exact response(s) and next state for ``request`` at ``now_ms``.

    Pure: ``state`` is never mutated. Never raises for any byte string.
    """
    req = parse_request(request)
    trace: list[str] = [f"Request: {format_hex(req.raw) or '<empty>'} at t={now_ms} ms."]
    st = _apply_clock(spec, state, now_ms, trace)
    decision = evaluate_nrc(spec, st, req)
    trace.extend(decision.trace)

    if decision.ignored or decision.sid is None:
        return RuleResult(
            request=req.raw, responses=[], trace=trace, decision=decision, next_state=st
        )

    # Every non-empty request (positive or negative outcome) restarts the S3 timer.
    st = st.model_copy(update={"last_request_ms": now_ms})
    sid = decision.sid

    if decision.nrc is not None:
        st = _negative_effects(spec, st, req, decision, trace)
        neg = bytes([NEGATIVE_RESPONSE_SID, sid, int(decision.nrc)])
        trace.append(f"Response: {format_hex(neg)} (negative responses are never suppressed).")
        return RuleResult(
            request=req.raw, responses=[neg], trace=trace, decision=decision, next_state=st
        )

    st, positive = _positive(spec, st, req, trace)
    responses: list[bytes] = []
    if decision.pending_nrc is not None:
        responses.append(bytes([NEGATIVE_RESPONSE_SID, sid, int(decision.pending_nrc)]))
        responses.append(positive)
        trace.append(
            f"Response: {format_hex(responses[0])} then {format_hex(positive)} "
            "(final response always sent after response-pending, even if suppressed)."
        )
    elif decision.suppress_positive:
        trace.append(f"Response: none (positive {format_hex(positive)} suppressed).")
    else:
        responses.append(positive)
        trace.append(f"Response: {format_hex(positive)}.")
    return RuleResult(
        request=req.raw, responses=responses, trace=trace, decision=decision, next_state=st
    )


def explain(result: RuleResult) -> str:
    """Render a :class:`RuleResult` as a human-readable multi-line explanation."""
    lines = list(result.trace)
    if result.responses:
        lines.append("Expected: " + " | ".join(format_hex(r) for r in result.responses))
    else:
        lines.append("Expected: no response")
    return "\n".join(lines)


class RulesSession:
    """Stateful convenience wrapper that steps an :class:`EcuState` through requests.

    This is the only stateful object in the rules package. It keeps an
    injected clock (``now_ms``) that only moves when told to.
    """

    def __init__(self, spec: EcuSpec, state: EcuState | None = None, now_ms: int = 0) -> None:
        """Start from ``state`` (default: power-on state) at clock ``now_ms``."""
        self.spec = spec
        self.state = state if state is not None else initial_state(spec, now_ms)
        self.now_ms = now_ms
        self.history: list[RuleResult] = []

    def send(
        self, request: bytes | bytearray | UdsRequest | str, now_ms: int | None = None
    ) -> RuleResult:
        """Evaluate ``request`` (bytes, :class:`UdsRequest`, or hex string) and step state."""
        if isinstance(request, str):
            request = bytes.fromhex(request)
        if now_ms is not None:
            self.now_ms = now_ms
        result = evaluate(self.spec, self.state, request, self.now_ms)
        self.state = result.next_state
        self.history.append(result)
        return result

    def advance(self, delta_ms: int) -> None:
        """Move the injected clock forward by ``delta_ms``."""
        self.now_ms += delta_ms

    def set_environment(
        self, *, vehicle_speed_kph: int | None = None, nvm_write_fault: bool | None = None
    ) -> None:
        """Change environmental conditions (vehicle speed, NVM fault injection)."""
        self.state = with_environment(
            self.state, vehicle_speed_kph=vehicle_speed_kph, nvm_write_fault=nvm_write_fault
        )
