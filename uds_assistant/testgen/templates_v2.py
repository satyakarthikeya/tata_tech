"""Template set v2 (Phase 7): generic checks a diagnostics test engineer routinely writes.

Kept in a separate module so ``templates.py`` stays readable; the templates are
registered in the same :data:`uds_assistant.testgen.templates.TEMPLATES` registry.
As in v1, every byte comes from the rules engine via ``_Builder`` and every
parameter list is enumerated from the loaded spec (no hardcoded identifiers).
None of these templates (or any generator) reads the bug catalog.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from uds_assistant.protocol.builders import (
    clear_dtc,
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
from uds_assistant.rules.state import dtc_code_to_int
from uds_assistant.spec.schema import DidDef, EcuSpec
from uds_assistant.testgen.model import Citation, TestCase

DEFAULT_SESSION = 0x01
SUPPRESS_BIT_SERVICES = (0x10, 0x11, 0x31, 0x3E)


def _builder(spec: EcuSpec):  # lazy import: templates.py imports this module
    from uds_assistant.testgen.templates import _Builder

    return _Builder(spec)


def _active_session_did(spec: EcuSpec) -> DidDef | None:
    return next((d for d in spec.dids if d.name == "active_diagnostic_session"), None)


def _unused_identifier(used: set[int], preferred: int = 0xDEAD) -> int:
    """A 2-byte identifier the spec does not define (deterministic)."""
    if preferred not in used:
        return preferred
    return next(v for v in range(0xFFFE, 0, -1) if v not in used)


def _writable_secured(spec: EcuSpec) -> list[DidDef]:
    return [
        d
        for d in spec.dids
        if d.write_sessions and d.write_security_level is not None and not d.conditions.requires
    ]


# ------------------------------------------------------------------------- read_multiple_dids


class ReadMultiDidParams(BaseModel):
    dids: list[int] = Field(min_length=2)
    session: int


def read_multi_instantiate(spec: EcuSpec, p: ReadMultiDidParams) -> TestCase:
    """Read two (or more) DIDs in one request."""
    b = _builder(spec)
    b.goto_session(p.session)
    ids = ", ".join(f"{d:#06x}" for d in p.dids)
    b.send(read_did(*p.dids), f"Read DIDs {ids} in one request -> every record, in order.")
    names = " + ".join(
        (did.name if (did := spec.get_did(d)) is not None else f"{d:#06x}") for d in p.dids
    )
    return TestCase(
        id="tpl_read_multi_" + "_".join(f"{d:04x}" for d in p.dids) + f"_{p.session:02x}",
        title=f"Multi-DID read {names} in session {p.session:#x}",
        category="positive",
        template_id="read_multiple_dids",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x22 ReadDataByIdentifier")],
        explanation="Several DIDs in one 0x22 request -> one positive response echoing each record.",
        origin="generated",
    )


def read_multi_applicable(spec: EcuSpec) -> list[ReadMultiDidParams]:
    """Each readable DID paired with the next spec DID readable in the same session."""
    out = []
    for d in spec.dids:
        if not d.read_sessions:
            continue
        session = DEFAULT_SESSION if DEFAULT_SESSION in d.read_sessions else d.read_sessions[0]
        partner = next((o for o in spec.dids if o.id != d.id and session in o.read_sessions), None)
        if partner is not None:
            out.append(ReadMultiDidParams(dids=[d.id, partner.id], session=session))
    return out


# ------------------------------------------------------------------------- write_readonly_did


class WriteReadOnlyParams(BaseModel):
    did: int
    session: int


def write_readonly_instantiate(spec: EcuSpec, p: WriteReadOnlyParams) -> TestCase:
    """Write a read-only DID (expect rejection) and read it back."""
    did_def = spec.get_did(p.did)
    assert did_def is not None
    b = _builder(spec)
    b.goto_session(p.session)
    b.send(
        write_did(p.did, bytes(did_def.length)),
        "Write a read-only DID -> expect NRC 0x31 (identifier not writable).",
    )
    if p.session in did_def.read_sessions:
        b.send(read_did(p.did), "Read back -> value unchanged.")
    return TestCase(
        id=f"tpl_write_readonly_{p.did:04x}",
        title=f"Write to read-only DID {did_def.name} ({p.did:#06x}) is rejected",
        category="negative",
        template_id="write_readonly_did",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x2E WriteDataByIdentifier")],
        explanation="DID has no write sessions -> 0x2E answers NRC 0x31 and the value is unchanged.",
        origin="generated",
    )


def write_readonly_applicable(spec: EcuSpec) -> list[WriteReadOnlyParams]:
    """Every DID without write sessions, in the first session that allows 0x2E."""
    write_session = next((s.id for s in spec.sessions if 0x2E in s.allowed_services), None)
    if write_session is None:
        return []
    return [
        WriteReadOnlyParams(did=d.id, session=write_session)
        for d in spec.dids
        if not d.write_sessions
    ]


# ------------------------------------------------------------- session_change_relocks_security


class SecurityLevelParams(BaseModel):
    level: int


def relock_instantiate(spec: EcuSpec, p: SecurityLevelParams) -> TestCase:
    """Unlock, re-enter the session, and confirm the level is locked again."""
    level_def = spec.get_security_level(p.level)
    assert level_def is not None
    session = level_def.allowed_sessions[0]
    b = _builder(spec)
    b.goto_session(session)
    b.unlock(p.level)
    b.send(session_control(session), "Re-enter the same session -> security must be locked again.")
    probe = next(
        (
            d
            for d in _writable_secured(spec)
            if d.write_security_level == p.level and session in d.write_sessions
        ),
        None,
    )
    if probe is not None:
        value = probe.value_range.min if probe.value_range is not None else 0
        b.send(
            write_did(probe.id, value.to_bytes(probe.length, "big")),
            f"Secured write to {probe.id:#06x} after re-entry -> expect NRC 0x33.",
        )
    b.send(
        security_request_seed(level_def.seed_subfunction),
        "Request seed -> a fresh non-zero seed (level is locked again).",
    )
    return TestCase(
        id=f"tpl_session_relock_{p.level:02x}",
        title=f"Session change re-locks security level {p.level:#x}",
        category="security",
        template_id="session_change_relocks_security",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x27 SecurityAccess")],
        explanation="A positive session change locks security; protected access needs a new unlock.",
        origin="generated",
    )


def security_level_applicable(spec: EcuSpec) -> list[SecurityLevelParams]:
    """Every security level that can be unlocked in some session."""
    return [
        SecurityLevelParams(level=lvl.level) for lvl in spec.security_levels if lvl.allowed_sessions
    ]


# ------------------------------------------------------------------------- seed_replay_rejected


def seed_replay_instantiate(spec: EcuSpec, p: SecurityLevelParams) -> TestCase:
    """Unlock, then replay the same key without requesting a new seed."""
    level_def = spec.get_security_level(p.level)
    assert level_def is not None
    b = _builder(spec)
    b.goto_session(level_def.allowed_sessions[0])
    b.send(security_request_seed(level_def.seed_subfunction), "Request seed.")
    key = compute_key(b.rs.state.pending_seeds[p.level], p.level)
    b.send(security_send_key(level_def.key_subfunction, key), "Send the computed key -> unlocked.")
    b.send(
        security_send_key(level_def.key_subfunction, key),
        "Replay the same key -> expect NRC 0x24 (the seed was consumed).",
    )
    return TestCase(
        id=f"tpl_seed_replay_{p.level:02x}",
        title=f"Replayed SecurityAccess key for level {p.level:#x} is rejected",
        category="security",
        template_id="seed_replay_rejected",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x27 SecurityAccess")],
        explanation="A key is valid for one seed only; sending it again without a new seed -> 0x24.",
        origin="generated",
    )


# ------------------------------------------------------------- dtc_clear_specific_keeps_others


class DtcCodeParams(BaseModel):
    code: str


def dtc_clear_specific_instantiate(spec: EcuSpec, p: DtcCodeParams) -> TestCase:
    """Inject every DTC, clear one, check the rest remain; clear an undefined group."""
    b = _builder(spec)
    for dtc in spec.dtcs:
        b.set_dtc_status(dtc.code, 0x09, f"Inject status 0x09 on DTC {dtc.code}.")
    b.send(read_dtc_by_status_mask(0x09), "Read DTCs with mask 0x09 -> all injected DTCs.")
    b.send(clear_dtc(dtc_code_to_int(p.code).to_bytes(3, "big")), f"Clear only DTC {p.code}.")
    b.send(read_dtc_by_status_mask(0x09), "Read again -> the other DTCs are still reported.")
    known = {dtc_code_to_int(d.code) for d in spec.dtcs} | {0xFFFFFF}
    unknown = next(v for v in range(1, 0xFFFFFF) if v not in known)
    b.send(clear_dtc(unknown.to_bytes(3, "big")), "Clear an undefined DTC group -> NRC 0x31.")
    return TestCase(
        id=f"tpl_dtc_clear_specific_{p.code}",
        title=f"Clearing DTC {p.code} leaves other DTCs; unknown group rejected",
        category="positive",
        template_id="dtc_clear_specific_keeps_others",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x19/0x14 DTC handling")],
        explanation="0x14 with one DTC clears just that DTC; an undefined group -> NRC 0x31.",
        origin="generated",
    )


def dtc_clear_specific_applicable(spec: EcuSpec) -> list[DtcCodeParams]:
    """Every DTC, when the spec defines at least two (otherwise nothing to keep)."""
    if len(spec.dtcs) < 2:
        return []
    return [DtcCodeParams(code=d.code) for d in spec.dtcs]


# ----------------------------------------------------------- negative_response_with_suppress_bit


class SidSessionParams(BaseModel):
    sid: int
    session: int


def negative_suppress_instantiate(spec: EcuSpec, p: SidSessionParams) -> TestCase:
    """Unsupported subfunction with the suppress bit: the NRC must still be sent."""
    from uds_assistant.testgen.templates import _BAD_SUBFUNCTION, _SUBFUNCTION_REQ_BUILDERS

    sub = _BAD_SUBFUNCTION[p.sid](spec)
    base = _SUBFUNCTION_REQ_BUILDERS[p.sid](spec, sub)
    req = UdsRequest.model_validate({**base.model_dump(), "suppress_positive": True})
    b = _builder(spec)
    b.goto_session(p.session)
    b.send(
        req, f"Unsupported subfunction {sub:#x} with the suppress bit set -> the NRC is still sent."
    )
    return TestCase(
        id=f"tpl_negative_suppress_{p.sid:02x}_{p.session:02x}",
        title=f"Negative response not suppressed for service {p.sid:#x} in session {p.session:#x}",
        category="negative",
        template_id="negative_response_with_suppress_bit",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="Suppress bit")],
        explanation="The suppress bit only suppresses positive responses; NRC 0x12 is still sent.",
        origin="generated",
    )


def negative_suppress_applicable(spec: EcuSpec) -> list[SidSessionParams]:
    """Every suppress-bit service allowed in each session."""
    return [
        SidSessionParams(sid=sid, session=session.id)
        for session in spec.sessions
        for sid in SUPPRESS_BIT_SERVICES
        if sid in session.allowed_services
    ]


# ------------------------------------------------------------------------ s3_keepalive_boundary


class SessionParams(BaseModel):
    session: int


def s3_keepalive_instantiate(spec: EcuSpec, p: SessionParams) -> TestCase:
    """Silent for exactly S3, TesterPresent, silent for exactly S3, check the session."""
    session_def = spec.get_session(p.session)
    assert session_def is not None
    s3 = session_def.timing.s3_ms
    b = _builder(spec)
    b.goto_session(p.session)
    b.advance(s3, "Stay silent for exactly S3.")
    b.send(tester_present(suppress_positive=False), "TesterPresent exactly at S3 -> still served.")
    b.advance(s3, "Silent for exactly S3 again (timer restarted by TesterPresent).")
    f186 = _active_session_did(spec)
    if f186 is not None:
        b.send(read_did(f186.id), "Read the active session -> still the non-default session.")
    else:
        b.send(tester_present(suppress_positive=False), "TesterPresent -> still served.")
    return TestCase(
        id=f"tpl_s3_keepalive_{p.session:02x}",
        title=f"TesterPresent keeps session {p.session:#x} alive at the S3 boundary",
        category="timing",
        template_id="s3_keepalive_boundary",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="S3 timeout")],
        explanation="A session only times out when idle strictly longer than S3; requests restart S3.",
        origin="generated",
    )


def s3_keepalive_applicable(spec: EcuSpec) -> list[SessionParams]:
    """Every non-default session where TesterPresent is allowed."""
    return [
        SessionParams(session=s.id)
        for s in spec.sessions
        if s.id != DEFAULT_SESSION and 0x3E in s.allowed_services
    ]


# ------------------------------------------------------------ nrc_priority_session_over_identifier


def nrc_priority_instantiate(spec: EcuSpec, p: SidSessionParams) -> TestCase:
    """Unknown identifier + service not allowed in session: expect the session NRC."""
    b = _builder(spec)
    b.goto_session(p.session)
    if p.sid == 0x31:
        rid = _unused_identifier({r.id for r in spec.routines})
        req = routine_control(0x01, rid)
        what = f"routine {rid:#06x}"
    else:
        did = _unused_identifier({d.id for d in spec.dids})
        req = read_did(did) if p.sid == 0x22 else write_did(did, b"\x00")
        what = f"DID {did:#06x}"
    b.send(
        req,
        f"Unknown {what}, service {p.sid:#x} not allowed in session {p.session:#x} -> "
        "the session check (0x7F) wins over the identifier check (0x31).",
    )
    return TestCase(
        id=f"tpl_nrc_priority_{p.sid:02x}_{p.session:02x}",
        title=f"NRC priority: service {p.sid:#x} + unknown identifier in session {p.session:#x}",
        category="negative",
        template_id="nrc_priority_session_over_identifier",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[
            Citation(source="behaviour_contract", ref="Service allowed in the active session")
        ],
        explanation="NRC order: service-in-session (0x7F) is checked before identifier support.",
        origin="generated",
    )


def nrc_priority_applicable(spec: EcuSpec) -> list[SidSessionParams]:
    """Identifier-based services (0x22/0x2E/0x31) in sessions that do not allow them."""
    supported = {sid for s in spec.sessions for sid in s.allowed_services}
    return [
        SidSessionParams(sid=sid, session=session.id)
        for session in spec.sessions
        for sid in (0x22, 0x2E, 0x31)
        if sid in supported and sid not in session.allowed_services
    ]


# ------------------------------------------------------------------------ routine_start_results


class RoutineParams(BaseModel):
    routine: int


def routine_start_results_instantiate(spec: EcuSpec, p: RoutineParams) -> TestCase:
    """Preconditions -> start (0x78 first for long-running routines) -> results."""
    routine = spec.get_routine(p.routine)
    assert routine is not None
    b = _builder(spec)
    b.goto_session(routine.sessions[0])
    if routine.conditions.requires:
        b.set_environment(vehicle_speed_kph=0, description="Ensure routine preconditions hold.")
    if routine.security_level is not None:
        b.unlock(routine.security_level)
    pending = " -> response pending (0x78) then the final positive" if routine.long_running else ""
    b.send(
        routine_control(0x01, p.routine, bytes(routine.option_record_length)),
        f"Start the routine{pending}.",
    )
    if 0x03 in routine.allowed_subfunctions:
        b.send(routine_control(0x03, p.routine), "Request routine results.")
    return TestCase(
        id=f"tpl_routine_start_results_{p.routine:04x}",
        title=f"Start routine {routine.name} ({p.routine:#06x}) and read its results",
        category="timing" if routine.long_running else "positive",
        template_id="routine_start_results",
        parameters=p.model_dump(),
        steps=b.steps,
        citations=[Citation(source="behaviour_contract", ref="0x31 RoutineControl")],
        explanation="Preconditions -> start (0x78 pending first if long-running) -> results.",
        origin="generated",
    )


def routine_applicable(spec: EcuSpec) -> list[RoutineParams]:
    """Every routine in the spec."""
    return [RoutineParams(routine=r.id) for r in spec.routines]
