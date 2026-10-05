"""Reusable, parameterized test templates.

Every template builds its request steps from :mod:`uds_assistant.protocol.builders`
and computes **every** expected response by stepping the rules engine
(:class:`uds_assistant.rules.engine.RulesSession`) from power-on state — never by
guessing bytes. This is the only place templates may produce bytes; the LLM
(later phases) only ever picks a template id + parameters.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from uds_assistant.protocol.builders import (
    clear_dtc,
    ecu_reset,
    read_did,
    read_dtc_by_status_mask,
    routine_control,
    security_request_seed,
    security_send_key,
    session_control,
    tester_present,
    write_did,
)
from uds_assistant.protocol.codec import UdsRequest
from uds_assistant.protocol.security import compute_key
from uds_assistant.rules.engine import RuleResult, RulesSession
from uds_assistant.rules.state import dtc_code_to_int, with_dtc_status
from uds_assistant.spec.schema import DidDef, EcuSpec
from uds_assistant.testgen import templates_v2 as v2
from uds_assistant.testgen import templates_v3 as v3
from uds_assistant.testgen.criteria import annotate_test
from uds_assistant.testgen.model import (
    AdvanceTimeStep,
    Citation,
    SendStep,
    SetDtcStatusStep,
    SetEnvironmentStep,
    TestCase,
    TestStep,
)

EXTENDED_SESSION = 0x03
PROGRAMMING_SESSION = 0x02
DEFAULT_SESSION = 0x01


class _Builder:
    """Steps a :class:`RulesSession` while recording :class:`TestStep` entries."""

    def __init__(self, spec: EcuSpec) -> None:
        self.spec = spec
        self.rs = RulesSession(spec, now_ms=0)
        self.steps: list[TestStep] = []

    def send(self, req: UdsRequest, description: str = "") -> RuleResult:
        result = self.rs.send(req)
        self.steps.append(
            SendStep(
                request_hex=req.to_bytes().hex(),
                expected_responses_hex=[r.hex() for r in result.responses],
                description=description,
            )
        )
        return result

    def advance(self, ms: int, description: str = "") -> None:
        self.rs.advance(ms)
        self.steps.append(AdvanceTimeStep(ms=ms, description=description))

    def set_environment(
        self,
        *,
        vehicle_speed_kph: int | None = None,
        nvm_write_fault: bool | None = None,
        description: str = "",
    ) -> None:
        self.rs.set_environment(vehicle_speed_kph=vehicle_speed_kph, nvm_write_fault=nvm_write_fault)
        self.steps.append(
            SetEnvironmentStep(
                vehicle_speed_kph=vehicle_speed_kph,
                nvm_write_fault=nvm_write_fault,
                description=description,
            )
        )

    def set_dtc_status(self, code: str, status: int, description: str = "") -> None:
        self.rs.state = with_dtc_status(self.rs.state, dtc_code_to_int(code), status)
        self.steps.append(SetDtcStatusStep(code=code, status=status, description=description))

    def unlock(self, level: int, description_prefix: str = "") -> None:
        """Send requestSeed then sendKey for ``level`` using the computed key."""
        level_def = self.spec.get_security_level(level)
        assert level_def is not None
        self.send(
            security_request_seed(level_def.seed_subfunction),
            f"{description_prefix}Request seed for level {level:#x}.",
        )
        seed = self.rs.state.pending_seeds[level]
        key = compute_key(seed, level)
        self.send(
            security_send_key(level_def.key_subfunction, key),
            f"{description_prefix}Send computed key for level {level:#x}.",
        )

    def goto_session(self, session: int, description: str = "") -> None:
        if session != DEFAULT_SESSION or self.rs.state.active_session != DEFAULT_SESSION:
            self.send(session_control(session), description or f"Switch to session {session:#x}.")


def _out_of_range_value(did: DidDef) -> int | None:
    """Pick a value just outside ``did``'s value_range, or None if none exists."""
    if did.value_range is None:
        return None
    max_representable = 2 ** (8 * did.length) - 1
    if did.value_range.max < max_representable:
        return did.value_range.max + 1
    if did.value_range.min > 0:
        return did.value_range.min - 1
    return None


def _writable_secured_dids(spec: EcuSpec) -> list[DidDef]:
    return [
        d
        for d in spec.dids
        if d.write_sessions and d.write_security_level is not None and not d.conditions.requires
    ]


def _condition_gated_dids(spec: EcuSpec) -> list[DidDef]:
    return [d for d in spec.dids if d.write_sessions and d.conditions.requires]


def _value_bytes(value: int, length: int) -> bytes:
    return value.to_bytes(length, "big")


# --------------------------------------------------------------------- read_did_positive


class ReadDidPositiveParams(BaseModel):
    did: int
    session: int


def _read_did_positive_instantiate(spec: EcuSpec, p: ReadDidPositiveParams) -> TestCase:
    did_def = spec.get_did(p.did)
    assert did_def is not None
    b = _Builder(spec)
    b.goto_session(p.session)
    b.send(read_did(p.did), f"Read DID {p.did:#06x} ({did_def.name}) in session {p.session:#x}.")
    return TestCase(
        id=f"tpl_read_did_positive_{p.did:04x}_{p.session:02x}",
        title=f"Read DID {did_def.name} ({p.did:#06x}) positively in session {p.session:#x}",
        category="positive",
        template_id="read_did_positive",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="bcm_spec.yaml", ref=f"dids.{did_def.name}")],
        explanation=f"DID {p.did:#06x} is readable in session {p.session:#x}; expect 0x62 echo + value.",
        origin="generated",
    )


def _read_did_positive_applicable(spec: EcuSpec) -> list[ReadDidPositiveParams]:
    out = []
    for d in spec.dids:
        for s in d.read_sessions:
            out.append(ReadDidPositiveParams(did=d.id, session=s))
    return out


# --------------------------------------------------------------- read_did_wrong_session_or_unknown


class ReadDidWrongParams(BaseModel):
    did: int
    session: int


def _read_did_wrong_instantiate(spec: EcuSpec, p: ReadDidWrongParams) -> TestCase:
    b = _Builder(spec)
    b.goto_session(p.session)
    b.send(read_did(p.did), f"Read DID {p.did:#06x} expecting NRC 0x31 in session {p.session:#x}.")
    return TestCase(
        id=f"tpl_read_did_wrong_{p.did:04x}_{p.session:02x}",
        title=f"Read unknown/unreadable DID {p.did:#06x} in session {p.session:#x}",
        category="negative",
        template_id="read_did_wrong_session_or_unknown",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x22 ReadDataByIdentifier")],
        explanation="Unknown DID or DID not readable in this session -> NRC 0x31.",
        origin="generated",
    )


def _read_did_wrong_applicable(spec: EcuSpec) -> list[ReadDidWrongParams]:
    all_sessions = {s.id for s in spec.sessions}
    out = [ReadDidWrongParams(did=0xDEAD, session=s.id) for s in spec.sessions]
    for d in spec.dids:
        missing = all_sessions - set(d.read_sessions)
        for s in sorted(missing):
            out.append(ReadDidWrongParams(did=d.id, session=s))
    return out


# --------------------------------------------------------------------- write_did_secured_positive


class WriteSecuredParams(BaseModel):
    did: int


def _write_secured_instantiate(spec: EcuSpec, p: WriteSecuredParams) -> TestCase:
    did_def = spec.get_did(p.did)
    assert did_def is not None and did_def.write_security_level is not None
    session = did_def.write_sessions[0]
    level = did_def.write_security_level
    value = did_def.value_range.min if did_def.value_range is not None else 0
    data = _value_bytes(value, did_def.length)
    b = _Builder(spec)
    b.goto_session(session)
    b.unlock(level)
    b.send(write_did(p.did, data), f"Write {value} to DID {p.did:#06x}.")
    b.send(read_did(p.did), "Read back to confirm the write.")
    return TestCase(
        id=f"tpl_write_secured_{p.did:04x}",
        title=f"Write DID {did_def.name} ({p.did:#06x}) after unlocking level {level:#x}",
        category="positive",
        template_id="write_did_secured_positive",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="bcm_spec.yaml", ref=f"dids.{did_def.name}")],
        explanation="Session -> unlock -> write -> read back; expect 0x6E then the written value.",
        origin="generated",
    )


def _write_secured_applicable(spec: EcuSpec) -> list[WriteSecuredParams]:
    return [WriteSecuredParams(did=d.id) for d in _writable_secured_dids(spec)]


# -------------------------------------------------------------------- write_did_without_security


class WriteNoSecParams(BaseModel):
    did: int


def _write_nosec_instantiate(spec: EcuSpec, p: WriteNoSecParams) -> TestCase:
    did_def = spec.get_did(p.did)
    assert did_def is not None
    session = did_def.write_sessions[0]
    value = did_def.value_range.min if did_def.value_range is not None else 0
    data = _value_bytes(value, did_def.length)
    b = _Builder(spec)
    b.goto_session(session)
    b.send(write_did(p.did, data), "Write without unlocking security -> expect NRC 0x33.")
    return TestCase(
        id=f"tpl_write_nosec_{p.did:04x}",
        title=f"Write DID {did_def.name} ({p.did:#06x}) without unlocking security",
        category="negative",
        template_id="write_did_without_security",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x2E WriteDataByIdentifier")],
        explanation="write_security_level set but level not unlocked -> NRC 0x33.",
        origin="generated",
    )


def _write_nosec_applicable(spec: EcuSpec) -> list[WriteNoSecParams]:
    return [WriteNoSecParams(did=d.id) for d in _writable_secured_dids(spec)]


# ---------------------------------------------------------------------- write_did_out_of_range


class WriteOutOfRangeParams(BaseModel):
    did: int


def _write_oor_instantiate(spec: EcuSpec, p: WriteOutOfRangeParams) -> TestCase:
    did_def = spec.get_did(p.did)
    assert did_def is not None and did_def.write_security_level is not None
    value = _out_of_range_value(did_def)
    assert value is not None
    session = did_def.write_sessions[0]
    level = did_def.write_security_level
    b = _Builder(spec)
    b.goto_session(session)
    if did_def.conditions.requires:
        b.set_environment(vehicle_speed_kph=0, description="Ensure required conditions hold.")
    b.unlock(level)
    b.send(
        write_did(p.did, _value_bytes(value, did_def.length)),
        f"Write out-of-range value {value} -> expect NRC 0x31.",
    )
    return TestCase(
        id=f"tpl_write_oor_{p.did:04x}",
        title=f"Write out-of-range value to DID {did_def.name} ({p.did:#06x})",
        category="negative",
        template_id="write_did_out_of_range",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x2E WriteDataByIdentifier")],
        explanation="Value outside value_range (after security/conditions pass) -> NRC 0x31.",
        origin="generated",
    )


def _write_oor_applicable(spec: EcuSpec) -> list[WriteOutOfRangeParams]:
    return [
        WriteOutOfRangeParams(did=d.id)
        for d in _writable_secured_dids(spec) + _condition_gated_dids(spec)
        if _out_of_range_value(d) is not None
    ]


# --------------------------------------------------------------------- write_did_invalid_length


class WriteInvalidLengthParams(BaseModel):
    did: int


def _write_badlen_instantiate(spec: EcuSpec, p: WriteInvalidLengthParams) -> TestCase:
    did_def = spec.get_did(p.did)
    assert did_def is not None
    session = did_def.write_sessions[0]
    bad_data = bytes(did_def.length + 1)
    b = _Builder(spec)
    b.goto_session(session)
    b.send(write_did(p.did, bad_data), "Write with one extra data byte -> expect NRC 0x13.")
    return TestCase(
        id=f"tpl_write_badlen_{p.did:04x}",
        title=f"Write wrong-length data to DID {did_def.name} ({p.did:#06x})",
        category="negative",
        template_id="write_did_invalid_length",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x2E WriteDataByIdentifier")],
        explanation="Data length != DID length is checked before security -> NRC 0x13.",
        origin="generated",
    )


def _write_badlen_applicable(spec: EcuSpec) -> list[WriteInvalidLengthParams]:
    return [WriteInvalidLengthParams(did=d.id) for d in spec.dids if d.write_sessions]


# ---------------------------------------------------------------------- service_not_in_session


_SID_BUILDERS: dict[int, Callable[[EcuSpec], UdsRequest]] = {
    0x14: lambda spec: clear_dtc(b"\xff\xff\xff"),
    0x19: lambda spec: read_dtc_by_status_mask(0xFF),
    0x27: lambda spec: security_request_seed(spec.security_levels[0].seed_subfunction),
    0x2E: lambda spec: write_did(
        next(d for d in spec.dids if d.write_sessions).id,
        bytes(next(d for d in spec.dids if d.write_sessions).length),
    ),
    0x31: lambda spec: routine_control(spec.routines[0].allowed_subfunctions[0], spec.routines[0].id),
}


class ServiceNotInSessionParams(BaseModel):
    sid: int
    session: int


def _service_not_in_session_instantiate(spec: EcuSpec, p: ServiceNotInSessionParams) -> TestCase:
    b = _Builder(spec)
    b.goto_session(p.session)
    req = _SID_BUILDERS[p.sid](spec)
    b.send(req, f"Service {p.sid:#x} not allowed in session {p.session:#x} -> expect NRC 0x7F.")
    return TestCase(
        id=f"tpl_service_not_in_session_{p.sid:02x}_{p.session:02x}",
        title=f"Service {p.sid:#x} rejected in session {p.session:#x}",
        category="session",
        template_id="service_not_in_session",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="Service allowed in the active session")],
        explanation="SID is globally supported but not allowed in the active session -> NRC 0x7F.",
        origin="generated",
    )


def _service_not_in_session_applicable(spec: EcuSpec) -> list[ServiceNotInSessionParams]:
    out = []
    for session in spec.sessions:
        for sid in _SID_BUILDERS:
            if sid not in session.allowed_services:
                out.append(ServiceNotInSessionParams(sid=sid, session=session.id))
    return out


# ------------------------------------------------------------------------ unsupported_subfunction

_BAD_SUBFUNCTION: dict[int, Callable[[EcuSpec], int]] = {
    0x10: lambda spec: 0x07,
    0x11: lambda spec: 0x02,
    0x19: lambda spec: 0x01,
    0x27: lambda spec: 0x07,
    0x31: lambda spec: 0x04,
    0x3E: lambda spec: 0x01,
}

_SUBFUNCTION_REQ_BUILDERS: dict[int, Callable[[EcuSpec, int], UdsRequest]] = {
    0x10: lambda spec, sub: session_control(sub),
    0x11: lambda spec, sub: ecu_reset(sub),
    0x19: lambda spec, sub: UdsRequest(sid=0x19, subfunction=sub, data=b"\xff"),
    0x27: lambda spec, sub: UdsRequest(sid=0x27, subfunction=sub),
    0x31: lambda spec, sub: routine_control(sub, spec.routines[0].id),
    0x3E: lambda spec, sub: tester_present(suppress_positive=False) if sub == 0 else UdsRequest(
        sid=0x3E, subfunction=sub
    ),
}


class UnsupportedSubfunctionParams(BaseModel):
    sid: int
    session: int


def _unsupported_subfunction_instantiate(spec: EcuSpec, p: UnsupportedSubfunctionParams) -> TestCase:
    sub = _BAD_SUBFUNCTION[p.sid](spec)
    req = _SUBFUNCTION_REQ_BUILDERS[p.sid](spec, sub)
    b = _Builder(spec)
    b.goto_session(p.session)
    b.send(req, f"Unsupported subfunction {sub:#x} for service {p.sid:#x} -> expect NRC 0x12.")
    return TestCase(
        id=f"tpl_unsupported_subfunction_{p.sid:02x}_{p.session:02x}",
        title=f"Unsupported subfunction for service {p.sid:#x} in session {p.session:#x}",
        category="negative",
        template_id="unsupported_subfunction",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="Subfunction supported")],
        explanation="Subfunction not in the service's supported set -> NRC 0x12.",
        origin="generated",
    )


def _unsupported_subfunction_applicable(spec: EcuSpec) -> list[UnsupportedSubfunctionParams]:
    out = []
    for session in spec.sessions:
        for sid in _BAD_SUBFUNCTION:
            if sid in session.allowed_services:
                out.append(UnsupportedSubfunctionParams(sid=sid, session=session.id))
    return out


# ------------------------------------------------------------------- security_invalid_key_lockout


class SecurityLockoutParams(BaseModel):
    level: int
    recovery: Literal["delay", "ecu_reset"] = "delay"
    """How the tester tries to leave the lockout: wait for the delay (base variant), or first
    reset the ECU while the delay is still running (the lockout must outlive the reset)."""


def _session_allows(spec: EcuSpec, session: int, sid: int) -> bool:
    sess = spec.get_session(session)
    return sess is not None and sid in sess.allowed_services


def _security_lockout_instantiate(spec: EcuSpec, p: SecurityLockoutParams) -> TestCase:
    """Behaviour class: invalid-key counting, lockout delay and lockout lifetime.

    Wrong keys up to ``max_attempts`` arm the level's delay; seed requests are refused while
    it runs. The ``ecu_reset`` variant resets the ECU during the delay and requests a seed
    again (a reset must not be a way around the delay). Both variants end with delay expiry.
    """
    level_def = spec.get_security_level(p.level)
    assert level_def is not None
    session = level_def.allowed_sessions[0]
    b = _Builder(spec)
    b.goto_session(session)
    for i in range(level_def.max_attempts):
        b.send(
            security_request_seed(level_def.seed_subfunction),
            f"Request seed, attempt {i + 1}.",
        )
        bad_key = bytes((x + 1) % 256 for x in b.rs.state.pending_seeds[p.level])
        b.send(security_send_key(level_def.key_subfunction, bad_key), f"Send wrong key, attempt {i + 1}.")
    b.send(
        security_request_seed(level_def.seed_subfunction),
        "Request seed during lockout -> expect NRC 0x37.",
    )
    reset = p.recovery == "ecu_reset"
    if reset:
        b.send(
            ecu_reset(spec.ecu_reset.supported_subfunctions[0]),
            "Reset the ECU while the lockout delay is still running.",
        )
        b.goto_session(session, "Re-enter the level's session after the reset.")
        b.send(
            security_request_seed(level_def.seed_subfunction),
            "Request seed right after the reset -> the running delay still applies.",
        )
    b.advance(level_def.delay_ms + 1, "Advance past the lockout delay.")
    # The wait also exceeds S3, so the ECU is back in the default session where
    # SecurityAccess is not allowed; re-enter the level's session first so the
    # next request really exercises delay expiry (lockout state survives this).
    b.send(session_control(session), "Re-enter the session (S3 expired during the wait).")
    b.send(
        security_request_seed(level_def.seed_subfunction),
        "Request seed after delay expiry -> seed issued again.",
    )
    return TestCase(
        id=f"tpl_security_lockout_{p.level:02x}" + ("_reset" if reset else ""),
        title=f"SecurityAccess level {p.level:#x} lockout after {level_def.max_attempts} wrong keys"
        + (", delay kept across an ECU reset" if reset else ""),
        category="security",
        template_id="security_invalid_key_lockout",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x27 SecurityAccess")],
        explanation="Wrong keys give 0x35 until max_attempts, then 0x36 and arm a delay (0x37 while active)."
        + (" An ECU reset during the delay does not end it." if reset else ""),
        origin="generated",
    )


def _security_lockout_applicable(spec: EcuSpec) -> list[SecurityLockoutParams]:
    """Every level (delay variant), then every level whose session allows ECUReset (reset variant)."""
    out = [SecurityLockoutParams(level=lvl.level) for lvl in spec.security_levels]
    if spec.ecu_reset.supported_subfunctions:
        out += [
            SecurityLockoutParams(level=lvl.level, recovery="ecu_reset")
            for lvl in spec.security_levels
            if lvl.allowed_sessions and _session_allows(spec, lvl.allowed_sessions[0], 0x11)
        ]
    return out


# --------------------------------------------------------------------- s3_timeout_reverts_session


class S3TimeoutParams(BaseModel):
    session: int


def _s3_timeout_instantiate(spec: EcuSpec, p: S3TimeoutParams) -> TestCase:
    session_def = spec.get_session(p.session)
    assert session_def is not None
    b = _Builder(spec)
    b.goto_session(p.session)
    b.advance(session_def.timing.s3_ms + 1, "Advance past the S3 timer with no requests.")
    f186 = next(d for d in spec.dids if d.name == "active_diagnostic_session")
    b.send(read_did(f186.id), "Read active session DID -> expect it reports default session 0x01.")
    return TestCase(
        id=f"tpl_s3_timeout_{p.session:02x}",
        title=f"S3 timeout drops session {p.session:#x} back to default",
        category="timing",
        template_id="s3_timeout_reverts_session",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="S3 timeout")],
        explanation="Idle longer than s3_ms reverts to default session before the next request is evaluated.",
        origin="generated",
    )


def _s3_timeout_applicable(spec: EcuSpec) -> list[S3TimeoutParams]:
    return [S3TimeoutParams(session=s.id) for s in spec.sessions if s.id != DEFAULT_SESSION]


# -------------------------------------------------------------------------------- routine_sequence


class RoutineSequenceParams(BaseModel):
    routine: int


def _routine_sequence_instantiate(spec: EcuSpec, p: RoutineSequenceParams) -> TestCase:
    routine = spec.get_routine(p.routine)
    assert routine is not None
    session = routine.sessions[0]
    b = _Builder(spec)
    b.goto_session(session)
    if routine.conditions.requires:
        b.set_environment(vehicle_speed_kph=0, description="Ensure routine preconditions hold.")
    if routine.security_level is not None:
        b.unlock(routine.security_level)
    # Start requests carry the spec'd option record (v1 omitted it, so routines with
    # option_record_length > 0 only ever saw NRC 0x13 — found by the eval's request validity).
    option = bytes(routine.option_record_length)
    b.send(routine_control(0x02, p.routine), "Stop before start -> expect NRC 0x24.")
    b.send(routine_control(0x01, p.routine, option), "Start the routine.")
    if not routine.long_running:
        b.send(
            routine_control(0x01, p.routine, option),
            "Start again while running -> expect NRC 0x24.",
        )
        b.send(routine_control(0x02, p.routine), "Stop the routine.")
        b.send(routine_control(0x03, p.routine), "Request results after stop.")
    return TestCase(
        id=f"tpl_routine_sequence_{p.routine:04x}",
        title=f"RoutineControl sequencing for routine {p.routine:#06x}",
        category="negative",
        template_id="routine_sequence",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x31 RoutineControl")],
        explanation="Stop/results before start, and start while running, give NRC 0x24.",
        origin="generated",
    )


def _routine_sequence_applicable(spec: EcuSpec) -> list[RoutineSequenceParams]:
    return [RoutineSequenceParams(routine=r.id) for r in spec.routines]


# -------------------------------------------------------------------------------- condition_not_met


class ConditionNotMetParams(BaseModel):
    kind: str  # "did" or "routine"
    target: int
    security: Literal["unlocked", "locked"] = "unlocked"
    """``unlocked`` (base): only the precondition fails. ``locked``: the precondition fails AND
    the required security level is still locked, which probes the NRC priority of the two."""


def _condition_not_met_instantiate(spec: EcuSpec, p: ConditionNotMetParams) -> TestCase:
    """Behaviour class: environmental preconditions on writes / routine starts and their NRC rank.

    The base variant unlocks and violates only the precondition. The ``locked`` variant
    violates the precondition while the required level is still locked, so the answer shows
    which of the two checks the ECU evaluates first (expected value from the oracle).
    """
    b = _Builder(spec)
    locked = p.security == "locked"
    lock_txt = " and security locked" if locked else ""
    if p.kind == "did":
        did_def = spec.get_did(p.target)
        assert did_def is not None and did_def.write_security_level is not None
        session = did_def.write_sessions[0]
        level = did_def.write_security_level
        value = did_def.value_range.min if did_def.value_range is not None else 0
        b.goto_session(session)
        b.set_environment(vehicle_speed_kph=10, description="Vehicle moving.")
        if not locked:
            b.unlock(level)
        b.send(
            write_did(p.target, _value_bytes(value, did_def.length)),
            "Write while moving and still locked -> the security check ranks first."
            if locked else "Write while vehicle is moving -> expect NRC 0x22.",
        )
        title = f"Write DID {did_def.name} while vehicle is moving{lock_txt}"
    else:
        routine = spec.get_routine(p.target)
        assert routine is not None
        session = routine.sessions[0]
        b.goto_session(session)
        b.set_environment(vehicle_speed_kph=10, description="Vehicle moving.")
        if routine.security_level is not None and not locked:
            b.unlock(routine.security_level)
        b.send(
            routine_control(0x01, p.target, bytes(routine.option_record_length)),
            "Start routine while moving and still locked -> the security check ranks first."
            if locked else "Start routine while vehicle is moving -> expect NRC 0x22.",
        )
        title = f"Start routine {routine.name} while vehicle is moving{lock_txt}"
    return TestCase(
        id=f"tpl_condition_not_met_{p.kind}_{p.target:04x}" + ("_locked" if locked else ""),
        title=title,
        category="negative",
        template_id="condition_not_met",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="conditions.requires")],
        explanation=(
            "Precondition failing while the level is locked -> the security NRC outranks the "
            "condition NRC." if locked else "vehicle_stationary required but speed != 0 -> NRC 0x22."
        ),
        origin="generated",
    )


def _condition_not_met_applicable(spec: EcuSpec) -> list[ConditionNotMetParams]:
    """Every condition-gated DID / routine (unlocked), then those that also need a level (locked)."""
    gated_dids = _condition_gated_dids(spec)
    gated_routines = [r for r in spec.routines if r.conditions.requires]
    out = [ConditionNotMetParams(kind="did", target=d.id) for d in gated_dids]
    out += [ConditionNotMetParams(kind="routine", target=r.id) for r in gated_routines]
    out += [
        ConditionNotMetParams(kind="did", target=d.id, security="locked")
        for d in gated_dids
        if d.write_security_level is not None
    ]
    out += [
        ConditionNotMetParams(kind="routine", target=r.id, security="locked")
        for r in gated_routines
        if r.security_level is not None
    ]
    return out


# ------------------------------------------------------------------------- suppress_positive_response


class SuppressPositiveParams(BaseModel):
    sid: int
    session: int


def _suppress_positive_instantiate(spec: EcuSpec, p: SuppressPositiveParams) -> TestCase:
    b = _Builder(spec)
    b.goto_session(p.session)
    if p.sid == 0x10:
        req = session_control(p.session, suppress_positive=True)
    else:
        req = tester_present(suppress_positive=True)
    b.send(req, "Suppress-positive-response bit set -> expect no response frame.")
    return TestCase(
        id=f"tpl_suppress_positive_{p.sid:02x}_{p.session:02x}",
        title=f"Suppress positive response for service {p.sid:#x} in session {p.session:#x}",
        category="positive",
        template_id="suppress_positive_response",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="Suppress bit")],
        explanation="Positive outcome with suppress bit set -> state changes but no response is sent.",
        origin="generated",
    )


def _suppress_positive_applicable(spec: EcuSpec) -> list[SuppressPositiveParams]:
    out = [SuppressPositiveParams(sid=0x3E, session=s.id) for s in spec.sessions]
    out += [SuppressPositiveParams(sid=0x10, session=s.id) for s in spec.sessions]
    return out


# -------------------------------------------------------------------------------------- dtc_read_clear


class DtcReadClearParams(BaseModel):
    code: str


def _dtc_read_clear_instantiate(spec: EcuSpec, p: DtcReadClearParams) -> TestCase:
    code_int = dtc_code_to_int(p.code)
    b = _Builder(spec)
    b.set_dtc_status(p.code, 0x09, f"Inject status 0x09 on DTC {p.code}.")
    b.send(read_dtc_by_status_mask(0x09), "Read DTCs matching mask 0x09 -> includes the injected DTC.")
    b.send(read_dtc_by_status_mask(0x40), "Read DTCs matching mask 0x40 -> excludes the injected DTC.")
    b.send(clear_dtc(code_int.to_bytes(3, "big")), "Clear just this DTC.")
    b.send(read_dtc_by_status_mask(0x09), "Read again -> the DTC no longer matches.")
    return TestCase(
        id=f"tpl_dtc_read_clear_{p.code}",
        title=f"Read and clear injected DTC {p.code}",
        category="positive",
        template_id="dtc_read_clear",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x19/0x14 DTC handling")],
        explanation="Inject a DTC status, confirm mask filtering, clear it, confirm it is gone.",
        origin="generated",
    )


def _dtc_read_clear_applicable(spec: EcuSpec) -> list[DtcReadClearParams]:
    return [DtcReadClearParams(code=d.code) for d in spec.dtcs]


# --------------------------------------------------------------------------------------- registry


@dataclass
class Template:
    """A reusable parameterized test template."""

    id: str
    description: str
    category: str
    applicable_services: list[int]
    params_model: type[BaseModel]
    instantiate_fn: Callable[[EcuSpec, BaseModel], TestCase]
    applicable_params_fn: Callable[[EcuSpec], list[BaseModel]]
    intended_nrcs: frozenset[int] = frozenset()
    """NRCs this template deliberately provokes (used by the eval's request-validity metric
    to tell an intentional malformed-request probe from an accidental one)."""

    def instantiate(self, spec: EcuSpec, params: BaseModel | dict) -> TestCase:
        """Build a concrete :class:`TestCase` for ``params`` against ``spec``."""
        model = params if isinstance(params, self.params_model) else self.params_model.model_validate(params)
        return annotate_test(spec, self.instantiate_fn(spec, model))


TEMPLATE_SET_VERSION = "v3"
"""Bumped whenever templates are added/changed; recorded in the evaluation report."""

TEMPLATE_SET_NOTES: dict[str, str] = {
    "v1": "14 templates (Phase 4/6).",
    "v2": (
        "v1 + 9 generic templates (multi-DID read, write to read-only DID, session change "
        "re-locks security, key replay, DTC clear specific/unknown group, negative response "
        "with suppress bit, S3 keep-alive boundary, NRC priority session-before-identifier, "
        "routine start+results incl. 0x78) and a fix so routine starts carry the spec'd option "
        "record. Added in Phase 7 AFTER inspecting which catalog bugs v1 missed; the same "
        "author wrote the bug catalog, so v2 detection is an optimistic, non-independent number."
    ),
    "v3": (
        "v2 + 4 generic templates (malformed 0x22 lengths, seed request while unlocked, routine "
        "status across session change / ECU reset, written DID value byte order + retention "
        "across S3 timeout / ECU reset) and new parameter variants of 3 templates (lockout + "
        "ECU reset, precondition failing while locked, routine start with the suppress bit). "
        "Added in Part C3 from the static stimulus analysis of the held-out v1 misses, so v1 "
        "held-out numbers after v3 are 'seen'; only fresh held-out sets measure v3 fairly."
    ),
}

TEMPLATES: dict[str, Template] = {
    "read_did_positive": Template(
        "read_did_positive", "Read a DID in a session where it is allowed.", "positive", [0x22],
        ReadDidPositiveParams, _read_did_positive_instantiate, _read_did_positive_applicable,
    ),
    "read_did_wrong_session_or_unknown": Template(
        "read_did_wrong_session_or_unknown", "Read an unknown DID or a DID not readable in the session.",
        "negative", [0x22], ReadDidWrongParams, _read_did_wrong_instantiate, _read_did_wrong_applicable,
        intended_nrcs=frozenset({0x31}),
    ),
    "write_did_secured_positive": Template(
        "write_did_secured_positive", "Session -> unlock -> write -> read back.", "positive",
        [0x10, 0x27, 0x2E, 0x22], WriteSecuredParams, _write_secured_instantiate, _write_secured_applicable,
    ),
    "write_did_without_security": Template(
        "write_did_without_security", "Write a security-gated DID without unlocking.", "negative",
        [0x2E], WriteNoSecParams, _write_nosec_instantiate, _write_nosec_applicable,
        intended_nrcs=frozenset({0x33}),
    ),
    "write_did_out_of_range": Template(
        "write_did_out_of_range", "Write a value outside the DID's value_range.", "negative",
        [0x2E, 0x27], WriteOutOfRangeParams, _write_oor_instantiate, _write_oor_applicable,
        intended_nrcs=frozenset({0x31}),
    ),
    "write_did_invalid_length": Template(
        "write_did_invalid_length", "Write the wrong number of data bytes.", "negative",
        [0x2E], WriteInvalidLengthParams, _write_badlen_instantiate, _write_badlen_applicable,
        intended_nrcs=frozenset({0x13}),
    ),
    "service_not_in_session": Template(
        "service_not_in_session", "Send a globally-supported service not allowed in this session.",
        "session", list(_SID_BUILDERS), ServiceNotInSessionParams,
        _service_not_in_session_instantiate, _service_not_in_session_applicable,
        intended_nrcs=frozenset({0x7F}),
    ),
    "unsupported_subfunction": Template(
        "unsupported_subfunction", "Send a subfunction value the service does not support.", "negative",
        list(_BAD_SUBFUNCTION), UnsupportedSubfunctionParams,
        _unsupported_subfunction_instantiate, _unsupported_subfunction_applicable,
        intended_nrcs=frozenset({0x12}),
    ),
    "security_invalid_key_lockout": Template(
        "security_invalid_key_lockout", "Exhaust max_attempts, see 0x37, then delay expiry.", "security",
        [0x27], SecurityLockoutParams, _security_lockout_instantiate, _security_lockout_applicable,
        intended_nrcs=frozenset({0x35, 0x36, 0x37}),
    ),
    "s3_timeout_reverts_session": Template(
        "s3_timeout_reverts_session", "Idle past s3_ms and confirm the session reverted.", "timing",
        [0x10, 0x22], S3TimeoutParams, _s3_timeout_instantiate, _s3_timeout_applicable,
    ),
    "routine_sequence": Template(
        "routine_sequence", "Stop/results before start, start while running.", "negative",
        [0x31], RoutineSequenceParams, _routine_sequence_instantiate, _routine_sequence_applicable,
        intended_nrcs=frozenset({0x24}),
    ),
    "condition_not_met": Template(
        "condition_not_met", "Attempt a condition-gated write/routine while the condition fails.",
        "negative", [0x2E, 0x31], ConditionNotMetParams,
        _condition_not_met_instantiate, _condition_not_met_applicable,
        intended_nrcs=frozenset({0x22}),
    ),
    "suppress_positive_response": Template(
        "suppress_positive_response", "Set the suppress bit on a positive-only exchange.", "positive",
        [0x10, 0x3E], SuppressPositiveParams, _suppress_positive_instantiate, _suppress_positive_applicable,
    ),
    "dtc_read_clear": Template(
        "dtc_read_clear", "Inject a DTC status, read with a mask, clear it, confirm.", "positive",
        [0x19, 0x14], DtcReadClearParams, _dtc_read_clear_instantiate, _dtc_read_clear_applicable,
    ),
    # ---- template set v2 (Phase 7; see templates_v2.py and DECISIONS.md [EVAL-TPL-V2]) ----
    "read_multiple_dids": Template(
        "read_multiple_dids", "Read two DIDs in one ReadDataByIdentifier request.", "positive",
        [0x22], v2.ReadMultiDidParams, v2.read_multi_instantiate, v2.read_multi_applicable,
    ),
    "write_readonly_did": Template(
        "write_readonly_did", "Attempt to write a read-only DID, then read it back.", "negative",
        [0x2E, 0x22], v2.WriteReadOnlyParams, v2.write_readonly_instantiate,
        v2.write_readonly_applicable, intended_nrcs=frozenset({0x31}),
    ),
    "session_change_relocks_security": Template(
        "session_change_relocks_security",
        "Unlock, re-enter the session, confirm security is locked again.", "security",
        [0x10, 0x27, 0x2E], v2.SecurityLevelParams, v2.relock_instantiate,
        v2.security_level_applicable, intended_nrcs=frozenset({0x33}),
    ),
    "seed_replay_rejected": Template(
        "seed_replay_rejected", "Unlock, then replay the same key without a new seed.", "security",
        [0x27], v2.SecurityLevelParams, v2.seed_replay_instantiate, v2.security_level_applicable,
        intended_nrcs=frozenset({0x24}),
    ),
    "dtc_clear_specific_keeps_others": Template(
        "dtc_clear_specific_keeps_others",
        "Inject all DTCs, clear one, confirm the others remain; clear an undefined group.",
        "positive", [0x19, 0x14], v2.DtcCodeParams, v2.dtc_clear_specific_instantiate,
        v2.dtc_clear_specific_applicable, intended_nrcs=frozenset({0x31}),
    ),
    "negative_response_with_suppress_bit": Template(
        "negative_response_with_suppress_bit",
        "Unsupported subfunction with the suppress bit set: the NRC must still be sent.",
        "negative", list(v2.SUPPRESS_BIT_SERVICES), v2.SidSessionParams,
        v2.negative_suppress_instantiate, v2.negative_suppress_applicable,
        intended_nrcs=frozenset({0x12}),
    ),
    "s3_keepalive_boundary": Template(
        "s3_keepalive_boundary", "TesterPresent exactly at S3 keeps the session alive.", "timing",
        [0x3E, 0x10, 0x22], v2.SessionParams, v2.s3_keepalive_instantiate,
        v2.s3_keepalive_applicable,
    ),
    "nrc_priority_session_over_identifier": Template(
        "nrc_priority_session_over_identifier",
        "Unknown identifier with a service not allowed in the session: 0x7F before 0x31.",
        "negative", [0x22, 0x2E, 0x31], v2.SidSessionParams, v2.nrc_priority_instantiate,
        v2.nrc_priority_applicable, intended_nrcs=frozenset({0x7F}),
    ),
    "routine_start_results": Template(
        "routine_start_results", "Start a routine (incl. 0x78 response pending), read results.",
        "positive", [0x31, 0x27], v2.RoutineParams, v2.routine_start_results_instantiate,
        v2.routine_applicable,
    ),
    # ---- template set v3 (Part C3; see templates_v3.py) ----
    "read_did_invalid_length": Template(
        "read_did_invalid_length",
        "Read a DID with a malformed DID list (empty, cut, dangling byte), then normally.",
        "negative", [0x22], v3.ReadLengthParams, v3.read_length_instantiate,
        v3.read_length_applicable, intended_nrcs=frozenset({0x13}),
    ),
    "seed_request_while_unlocked": Template(
        "seed_request_while_unlocked",
        "Unlock, request a seed again: zero seed, level stays unlocked.", "security",
        [0x27], v3.UnlockedLevelParams, v3.seed_while_unlocked_instantiate,
        v3.seed_while_unlocked_applicable,
    ),
    "session_change_resets_routine": Template(
        "session_change_resets_routine",
        "Start a routine, change session or reset the ECU, results must say not started.",
        "session", [0x31, 0x10], v3.RoutineTransitionParams,
        v3.routine_transition_instantiate, v3.routine_transition_applicable,
        intended_nrcs=frozenset({0x24}),
    ),
    "write_did_value_retained": Template(
        "write_did_value_retained",
        "Write a distinct-byte value, read back, then S3 timeout or ECU reset and read again.",
        "positive", [0x2E, 0x22], v3.RetentionParams, v3.retention_instantiate,
        v3.retention_applicable,
    ),
}


def applicable_params(spec: EcuSpec, template_id: str) -> list[BaseModel]:
    """Enumerate sensible parameter combinations for ``template_id`` against ``spec``."""
    return TEMPLATES[template_id].applicable_params_fn(spec)


class ValidationReport(BaseModel):
    """Result of re-running a test's steps through the rules engine oracle."""

    test_id: str
    ok: bool
    mismatches: list[str] = Field(default_factory=list)


def validate_test(spec: EcuSpec, test: TestCase) -> ValidationReport:
    """Re-run ``test``'s steps through the rules engine and compare expected responses."""
    rs = RulesSession(spec, now_ms=0)
    mismatches: list[str] = []
    for i, step in enumerate(test.steps):
        if step.kind == "send":
            result = rs.send(step.request_bytes)
            actual = [r.hex() for r in result.responses]
            if actual != step.expected_responses_hex:
                mismatches.append(
                    f"step {i}: request {step.request_hex} expected {step.expected_responses_hex} "
                    f"but oracle now says {actual}"
                )
        elif step.kind == "advance_time":
            rs.advance(step.ms)
        elif step.kind == "set_environment":
            rs.set_environment(
                vehicle_speed_kph=step.vehicle_speed_kph, nvm_write_fault=step.nvm_write_fault
            )
        elif step.kind == "set_dtc_status":
            rs.state = with_dtc_status(rs.state, dtc_code_to_int(step.code), step.status)
    return ValidationReport(test_id=test.id, ok=not mismatches, mismatches=mismatches)
