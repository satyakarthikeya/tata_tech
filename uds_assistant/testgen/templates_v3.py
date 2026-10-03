"""Template set v3 (Part C3): spec-driven behaviour probes for state transitions and edges.

Four generic behaviour classes a diagnostics test engineer checks on any ECU:

- malformed ReadDataByIdentifier lengths (a DID list that is not a whole number of DIDs);
- requesting a seed for a security level that is already unlocked;
- routine state across a session change or an ECU reset;
- written DID values: byte order of the stored value and its retention across an S3
  timeout or an ECU reset.

As in v1/v2, every parameter list is enumerated from the loaded spec (no identifier is
hardcoded) and every expected response comes from the rules engine via ``_Builder``.
Registered in :data:`uds_assistant.testgen.templates.TEMPLATES`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from uds_assistant.protocol.builders import (
    ecu_reset,
    read_did,
    routine_control,
    security_request_seed,
    session_control,
    write_did,
)
from uds_assistant.protocol.codec import UdsRequest
from uds_assistant.spec.schema import DidDef, EcuSpec
from uds_assistant.testgen.model import Citation, TestCase

DEFAULT_SESSION = 0x01
READ_DID_SID = 0x22
ECU_RESET_SID = 0x11

Transition = Literal["session_change", "ecu_reset"]
Retention = Literal["s3_timeout", "ecu_reset"]


def _builder(spec: EcuSpec):  # lazy import: templates.py imports this module
    from uds_assistant.testgen.templates import _Builder

    return _Builder(spec)


def _allows(spec: EcuSpec, session: int, sid: int) -> bool:
    sess = spec.get_session(session)
    return sess is not None and sid in sess.allowed_services


def _read_session(did: DidDef) -> int:
    """Default session if the DID is readable there, else its first read session."""
    return DEFAULT_SESSION if DEFAULT_SESSION in did.read_sessions else did.read_sessions[0]


# ------------------------------------------------------------------------ read_did_invalid_length


class ReadLengthParams(BaseModel):
    did: int
    session: int


def read_length_instantiate(spec: EcuSpec, p: ReadLengthParams) -> TestCase:
    """Behaviour class: ReadDataByIdentifier request-length validation.

    The DID list of a 0x22 request must be a whole, non-empty number of 2-byte identifiers.
    Probes: no identifier at all, an identifier cut to one byte, and a complete identifier
    followed by one dangling byte; each must be rejected as a whole (no partial answer).
    A well-formed read of the same DID afterwards shows the ECU still serves it.
    """
    did_def = spec.get_did(p.did)
    assert did_def is not None
    did_bytes = p.did.to_bytes(2, "big")
    b = _builder(spec)
    b.goto_session(p.session)
    b.send(UdsRequest(sid=READ_DID_SID), "ReadDataByIdentifier without any DID -> length NRC.")
    b.send(
        UdsRequest(sid=READ_DID_SID, data=did_bytes[:1]),
        f"Only the first byte of DID {p.did:#06x} -> length NRC.",
    )
    b.send(
        UdsRequest(sid=READ_DID_SID, data=did_bytes + b"\x00"),
        f"DID {p.did:#06x} plus one dangling byte -> length NRC, no partial answer.",
    )
    b.send(read_did(p.did), "Well-formed read of the same DID -> served normally.")
    return TestCase(
        id=f"tpl_read_badlen_{p.did:04x}_{p.session:02x}",
        title=f"Malformed-length reads of DID {did_def.name} ({p.did:#06x}) are rejected",
        category="negative",
        template_id="read_did_invalid_length",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x22 ReadDataByIdentifier")],
        explanation="A 0x22 DID list that is empty or not a multiple of two bytes -> NRC 0x13.",
        origin="generated",
    )


def read_length_applicable(spec: EcuSpec) -> list[ReadLengthParams]:
    """Every readable DID, in its default-preferred read session (0x22 must be allowed there)."""
    out = []
    for d in spec.dids:
        if not d.read_sessions:
            continue
        session = _read_session(d)
        if _allows(spec, session, READ_DID_SID):
            out.append(ReadLengthParams(did=d.id, session=session))
    return out


# --------------------------------------------------------------------- seed_request_while_unlocked


class UnlockedLevelParams(BaseModel):
    level: int


def seed_while_unlocked_instantiate(spec: EcuSpec, p: UnlockedLevelParams) -> TestCase:
    """Behaviour class: SecurityAccess state once a level is unlocked.

    After a successful unlock, a further seed request for the same level must not start a
    new challenge (the contract answers an all-zero seed) and must not lock the level: a
    protected write at that level is still accepted afterwards.
    """
    level_def = spec.get_security_level(p.level)
    assert level_def is not None
    session = level_def.allowed_sessions[0]
    b = _builder(spec)
    b.goto_session(session)
    b.unlock(p.level)
    b.send(
        security_request_seed(level_def.seed_subfunction),
        "Request a seed again while the level is unlocked -> 'already unlocked' seed.",
    )
    probe = next(
        (
            d for d in spec.dids
            if d.write_security_level == p.level and session in d.write_sessions
            and not d.conditions.requires
        ),
        None,
    )
    if probe is not None:
        value = probe.value_range.min if probe.value_range is not None else 0
        b.send(
            write_did(probe.id, value.to_bytes(probe.length, "big")),
            f"Protected write to {probe.id:#06x} -> still accepted (level stays unlocked).",
        )
    b.send(
        security_request_seed(level_def.seed_subfunction),
        "Request a seed once more -> still the 'already unlocked' answer.",
    )
    return TestCase(
        id=f"tpl_seed_while_unlocked_{p.level:02x}",
        title=f"Seed request while security level {p.level:#x} is already unlocked",
        category="security",
        template_id="seed_request_while_unlocked",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x27 SecurityAccess")],
        explanation="An unlocked level answers a seed request with an all-zero seed and stays unlocked.",
        origin="generated",
    )


def seed_while_unlocked_applicable(spec: EcuSpec) -> list[UnlockedLevelParams]:
    """Every security level that can be unlocked in some session."""
    return [
        UnlockedLevelParams(level=lvl.level) for lvl in spec.security_levels if lvl.allowed_sessions
    ]


# ------------------------------------------------------------------ session_change_resets_routine


class RoutineTransitionParams(BaseModel):
    routine: int
    transition: Transition


def routine_transition_instantiate(spec: EcuSpec, p: RoutineTransitionParams) -> TestCase:
    """Behaviour class: routine status across a session change or an ECU reset.

    Start a routine, then leave its state context (re-enter the session, or reset the ECU
    and return to the session), unlock again if needed, and ask for the routine's results:
    a routine started before the transition must count as never started. A fresh start
    afterwards must be accepted.
    """
    routine = spec.get_routine(p.routine)
    assert routine is not None
    session = routine.sessions[0]
    option = bytes(routine.option_record_length)
    b = _builder(spec)
    b.goto_session(session)
    if routine.conditions.requires:
        b.set_environment(vehicle_speed_kph=0, description="Ensure routine preconditions hold.")
    if routine.security_level is not None:
        b.unlock(routine.security_level)
    b.send(routine_control(0x01, p.routine, option), "Start the routine.")
    if p.transition == "ecu_reset":
        b.send(ecu_reset(spec.ecu_reset.supported_subfunctions[0]), "Reset the ECU.")
        b.goto_session(session, "Return to the routine's session after the reset.")
        what = "the ECU reset"
    else:
        b.send(session_control(session), "Re-enter the session (a positive session change).")
        what = "the session change"
    if routine.security_level is not None:
        b.unlock(routine.security_level, "Unlock again: ")
    b.send(
        routine_control(0x03, p.routine),
        f"Request results -> the start before {what} no longer counts.",
    )
    b.send(routine_control(0x01, p.routine, option), "Start the routine again -> accepted.")
    tag = "reset" if p.transition == "ecu_reset" else "session"
    return TestCase(
        id=f"tpl_routine_after_{tag}_{p.routine:04x}",
        title=f"Routine {routine.name} ({p.routine:#06x}) status is cleared by {what}",
        category="session",
        template_id="session_change_resets_routine",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x31 RoutineControl")],
        explanation=f"Routine status is cleared by {what}; results before a new start -> 0x24.",
        origin="generated",
    )


def routine_transition_applicable(spec: EcuSpec) -> list[RoutineTransitionParams]:
    """Routines that support start + results with results gated on a start: session change
    for each, then ECU reset for each whose session allows ECUReset."""
    eligible = [
        r for r in spec.routines
        if r.sessions and r.results_requires_start
        and {0x01, 0x03} <= set(r.allowed_subfunctions)
    ]
    out = [RoutineTransitionParams(routine=r.id, transition="session_change") for r in eligible]
    if spec.ecu_reset.supported_subfunctions:
        out += [
            RoutineTransitionParams(routine=r.id, transition="ecu_reset")
            for r in eligible
            if _allows(spec, r.sessions[0], ECU_RESET_SID)
        ]
    return out


# ----------------------------------------------------------------------- write_did_value_retained


def retention_value(did: DidDef) -> int:
    """An in-range value that differs from the default and, where possible, has pairwise
    distinct bytes (0x12, 0x1234, 0x123456, ...), so a swapped or reverted value shows."""
    max_repr = 2 ** (8 * did.length) - 1
    lo, hi = (did.value_range.min, did.value_range.max) if did.value_range else (0, max_repr)
    default = int.from_bytes(did.default_value, "big") if did.default_value else None
    pattern = int.from_bytes(bytes((0x12 + 0x22 * i) & 0xFF for i in range(did.length)), "big")
    for cand in (pattern, hi, lo, (lo + hi) // 2):
        if lo <= cand <= hi and cand != default:
            return cand
    return lo


class RetentionParams(BaseModel):
    did: int
    after: Retention


def retention_instantiate(spec: EcuSpec, p: RetentionParams) -> TestCase:
    """Behaviour class: stored DID values (byte order and retention).

    Write a non-default value with distinct bytes, read it back where the write session
    allows reading (byte order of the stored value), then let the session time out (S3) or
    reset the ECU and read it again from a session where the DID is readable: a written
    value must be kept across both.
    """
    did_def = spec.get_did(p.did)
    assert did_def is not None and did_def.write_sessions
    session = did_def.write_sessions[0]
    value = retention_value(did_def)
    data = value.to_bytes(did_def.length, "big")
    b = _builder(spec)
    b.goto_session(session)
    if did_def.conditions.requires:
        b.set_environment(vehicle_speed_kph=0, description="Ensure required conditions hold.")
    if did_def.write_security_level is not None:
        b.unlock(did_def.write_security_level)
    b.send(write_did(p.did, data), f"Write {data.hex(' ').upper()} to DID {p.did:#06x}.")
    if session in did_def.read_sessions:
        b.send(read_did(p.did), "Read back -> the same bytes in the same order.")
    if p.after == "s3_timeout":
        session_def = spec.get_session(session)
        assert session_def is not None
        b.advance(session_def.timing.s3_ms + 1, "Stay silent past S3 (session times out).")
        what = "an S3 timeout"
    else:
        b.send(ecu_reset(spec.ecu_reset.supported_subfunctions[0]), "Reset the ECU.")
        what = "an ECU reset"
    read_session = _read_session(did_def)
    if read_session != DEFAULT_SESSION:
        b.goto_session(read_session, f"Enter session {read_session:#x} where the DID is readable.")
    b.send(read_did(p.did), f"Read again after {what} -> the written value is kept.")
    tag = "s3" if p.after == "s3_timeout" else "reset"
    return TestCase(
        id=f"tpl_write_retained_{tag}_{p.did:04x}",
        title=f"Value written to DID {did_def.name} ({p.did:#06x}) is kept after {what}",
        category="timing" if p.after == "s3_timeout" else "positive",
        template_id="write_did_value_retained",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x2E WriteDataByIdentifier")],
        explanation=f"Stored DID values are big-endian and survive {what}.",
        origin="generated",
    )


def retention_applicable(spec: EcuSpec) -> list[RetentionParams]:
    """Every writable DID that is readable somewhere: S3 variant if its write session is not
    the default one, then ECU-reset variant if that session allows ECUReset."""
    writable = [d for d in spec.dids if d.write_sessions and d.read_sessions]
    out = [
        RetentionParams(did=d.id, after="s3_timeout")
        for d in writable
        if d.write_sessions[0] != DEFAULT_SESSION
    ]
    if spec.ecu_reset.supported_subfunctions:
        out += [
            RetentionParams(did=d.id, after="ecu_reset")
            for d in writable
            if _allows(spec, d.write_sessions[0], ECU_RESET_SID)
        ]
    return out
