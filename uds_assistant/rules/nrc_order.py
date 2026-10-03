"""The NRC evaluation order — the single place where negative outcomes are decided.

:func:`evaluate_nrc` is deliberately the *only* function in this module (and in
the rules package) that names an NRC. Every check carries a ``Source:`` comment.
Every check cites "design decision — see DECISIONS.md [tag]" (``[tag]`` is the
bracketed label of the matching DECISIONS.md line) and/or "udsoncan behaviour".
Where the AUTOSAR CP R24-11 Dcm SWS states the same behaviour, the requirement
ID is cited too, with a one-line paraphrase (never SWS text); IDs are checked
against the locally extracted SWS by tests/rules/test_sws_citations.py. Places
where the SWS differs are listed in docs/SWS_DISAGREEMENTS.md, not cited here.
Generic order = PROJECT.md §5.

The function assumes the engine has already applied clock effects (S3 timeout,
expired-lockout clearing) to ``state`` and set ``state.now_ms``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from uds_assistant.protocol.constants import Nrc, ServiceId
from uds_assistant.protocol.security import (
    SecurityLockoutState,
    compute_key,
    is_delay_active,
    record_failed_attempt,
)
from uds_assistant.rules.request import ParsedRequest
from uds_assistant.rules.state import (
    DEFAULT_SESSION_ID,
    EcuState,
    RoutineStatus,
    dtc_code_to_int,
)
from uds_assistant.spec.schema import EcuSpec

#: Minimum total request length (incl. SID) per service, checked at step 3.
_MIN_LENGTH: dict[int, int] = {
    ServiceId.DIAGNOSTIC_SESSION_CONTROL: 2,
    ServiceId.ECU_RESET: 2,
    ServiceId.CLEAR_DIAGNOSTIC_INFORMATION: 4,
    ServiceId.READ_DTC_INFORMATION: 2,
    ServiceId.READ_DATA_BY_IDENTIFIER: 3,
    ServiceId.SECURITY_ACCESS: 2,
    ServiceId.WRITE_DATA_BY_IDENTIFIER: 4,
    ServiceId.ROUTINE_CONTROL: 4,
    ServiceId.TESTER_PRESENT: 2,
}

#: Services whose total length is fixed regardless of subfunction / identifier.
_EXACT_LENGTH: dict[int, int] = {
    ServiceId.DIAGNOSTIC_SESSION_CONTROL: 2,
    ServiceId.ECU_RESET: 2,
    ServiceId.CLEAR_DIAGNOSTIC_INFORMATION: 4,
    ServiceId.TESTER_PRESENT: 2,
}

#: RoutineControl subfunctions: startRoutine, stopRoutine, requestRoutineResults.
ROUTINE_START, ROUTINE_STOP, ROUTINE_RESULTS = 0x01, 0x02, 0x03

#: ReadDTCInformation reportDTCByStatusMask subfunction.
DTC_BY_STATUS_MASK = 0x02

#: ClearDiagnosticInformation "all groups" value.
CLEAR_ALL_DTC_GROUP = 0xFFFFFF


class NrcDecision(BaseModel):
    """Outcome of the NRC evaluation order for one request.

    - ``ignored``: the request is empty; the ECU sends nothing.
    - ``nrc``: final negative response code, or ``None`` for a positive outcome.
    - ``pending_nrc``: an interim NRC (only 0x78) sent before the final response.
    - ``suppress_positive``: the request had the suppress-positive-response bit.
    - ``failed_key_attempt``: a SecurityAccess key was verified and was wrong;
      the engine must record the attempt and consume the pending seed.
    - ``trace``: human-readable evaluation steps, in order.
    """

    sid: int | None = None
    nrc: Nrc | None = None
    pending_nrc: Nrc | None = None
    ignored: bool = False
    suppress_positive: bool = False
    failed_key_attempt: bool = False
    trace: list[str] = Field(default_factory=list)

    @property
    def positive(self) -> bool:
        """True if the outcome is a positive response (possibly suppressed)."""
        return not self.ignored and self.nrc is None


def evaluate_nrc(spec: EcuSpec, state: EcuState, request: ParsedRequest) -> NrcDecision:
    """Run the full NRC evaluation order for ``request`` against ``spec``/``state``.

    Order (generic steps from PROJECT.md §5, then service-specific checks):
    1 service supported (0x11) → 2 service in session (0x7F) → 3 length (0x13)
    → 4 subfunction supported (0x12) → 5 subfunction in session (0x7E)
    → 5b subfunction/identifier-specific length (0x13) → 6 service-specific
    (identifier 0x31, identifier-in-session 0x31, security 0x33, conditions
    0x22, sequence 0x24, value range 0x31, SecurityAccess 0x37/0x24/0x35/0x36,
    NVM failure 0x72) → 7 response length (0x14) → 8 response pending (0x78).
    NRC 0x10 (generalReject) is never produced by this oracle.
    """
    trace: list[str] = []
    raw = request.raw
    sup = request.suppress_positive

    # Step 0 — empty request. Source: design decision — see DECISIONS.md [R-EMPTY]
    if request.sid is None:
        trace.append("Step 0: empty request has no SID; the ECU sends no response.")
        return NrcDecision(ignored=True, trace=trace)
    sid = request.sid

    # Step 1 — service supported (any session lists it) else 0x11.
    # Source: design decision — see DECISIONS.md [R-ORDER] (PROJECT.md §5 step 1)
    # + SWS_Dcm_00197 (an unknown SID is answered with 0x11).
    supported_sids = {s for sess in spec.sessions for s in sess.allowed_services}
    if sid not in supported_sids:
        trace.append(f"Step 1: SID 0x{sid:02X} is not implemented by this ECU -> NRC 0x11.")
        return NrcDecision(sid=sid, nrc=Nrc.SERVICE_NOT_SUPPORTED, trace=trace)
    trace.append(f"Step 1: SID 0x{sid:02X} is supported.")

    # Step 2 — service allowed in the active session else 0x7F.
    # Source: design decision — see DECISIONS.md [R-ORDER] (PROJECT.md §5 step 2)
    # + SWS_Dcm_00211 (SID not enabled for the active session gives 0x7F).
    session = spec.get_session(state.active_session) or spec.get_session(DEFAULT_SESSION_ID)
    assert session is not None
    if sid not in session.allowed_services:
        trace.append(
            f"Step 2: SID 0x{sid:02X} not allowed in session 0x{session.id:02X} "
            f"({session.name}) -> NRC 0x7F."
        )
        return NrcDecision(sid=sid, nrc=Nrc.SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION, trace=trace)
    trace.append(f"Step 2: SID 0x{sid:02X} allowed in session 0x{session.id:02X}.")

    # Step 3 — generic message length / format else 0x13.
    # Source: design decision — see DECISIONS.md [R-LEN] (PROJECT.md §5 step 3)
    # + SWS_Dcm_00696 (shorter than the service minimum gives 0x13) and SWS_Dcm_00272
    # (any length/format error found while parsing the request gives 0x13).
    min_len = _MIN_LENGTH[sid]
    exact_len = _EXACT_LENGTH.get(sid)
    if request.length < min_len or (exact_len is not None and request.length != exact_len):
        trace.append(
            f"Step 3: length {request.length} invalid for SID 0x{sid:02X} "
            f"(min {min_len}{'' if exact_len is None else f', exact {exact_len}'}) -> NRC 0x13."
        )
        return NrcDecision(
            sid=sid, nrc=Nrc.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT, trace=trace
        )
    # Source: design decision — see DECISIONS.md [R-LEN] (DID list must be whole 2-byte ids)
    # + SWS_Dcm_00272 (a malformed request gives 0x13).
    if sid == ServiceId.READ_DATA_BY_IDENTIFIER and (request.length - 1) % 2 != 0:
        trace.append("Step 3: 0x22 DID list is not a whole number of 2-byte DIDs -> NRC 0x13.")
        return NrcDecision(
            sid=sid, nrc=Nrc.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT, trace=trace
        )
    trace.append(f"Step 3: length {request.length} acceptable for SID 0x{sid:02X}.")

    sub = request.subfunction
    level_def = None
    is_seed_request = False
    if sub is not None:
        # Step 4 — subfunction supported else 0x12.
        # Source: design decision — see DECISIONS.md [R-ORDER] (PROJECT.md §5 step 4);
        # bit 7 is stripped only for services with a suppress bit [R-SPRMIB].
        # + SWS_Dcm_00273 (subfunction without a configured sub-service gives 0x12),
        # SWS_Dcm_00307 (0x10: unconfigured session type gives 0x12), SWS_Dcm_00321
        # (0x27: unconfigured access type gives 0x12), SWS_Dcm_00251 (0x3E only
        # supports zeroSubFunction). The SWS defers this check for 0x31 and masks
        # bit 7 for 0x19/0x27 too — see docs/SWS_DISAGREEMENTS.md D2, D6.
        if sid == ServiceId.DIAGNOSTIC_SESSION_CONTROL:
            supported_subs = {s.id for s in spec.sessions}
        elif sid == ServiceId.ECU_RESET:
            supported_subs = set(spec.ecu_reset.supported_subfunctions)
        elif sid == ServiceId.READ_DTC_INFORMATION:
            supported_subs = set(spec.read_dtc_supported_subfunctions)
        elif sid == ServiceId.SECURITY_ACCESS:
            supported_subs = {lvl.seed_subfunction for lvl in spec.security_levels} | {
                lvl.key_subfunction for lvl in spec.security_levels
            }
        elif sid == ServiceId.ROUTINE_CONTROL:
            supported_subs = {ROUTINE_START, ROUTINE_STOP, ROUTINE_RESULTS}
        else:  # TesterPresent: zeroSubFunction only
            supported_subs = {0x00}
        if sub not in supported_subs:
            trace.append(
                f"Step 4: subfunction 0x{sub:02X} not supported by SID 0x{sid:02X} -> NRC 0x12."
            )
            return NrcDecision(sid=sid, nrc=Nrc.SUB_FUNCTION_NOT_SUPPORTED, trace=trace)
        trace.append(f"Step 4: subfunction 0x{sub:02X} supported.")

        # Step 5 — subfunction allowed in the active session else 0x7E.
        # Source: design decision — see DECISIONS.md [R-SUB-SESSION] (PROJECT.md §5 step 5)
        # + SWS_Dcm_00616 (sub-service not enabled for the active session gives 0x7E).
        if sid == ServiceId.SECURITY_ACCESS:
            for lvl in spec.security_levels:
                if sub in (lvl.seed_subfunction, lvl.key_subfunction):
                    level_def = lvl
                    is_seed_request = sub == lvl.seed_subfunction
            assert level_def is not None
            if state.active_session not in level_def.allowed_sessions:
                trace.append(
                    f"Step 5: security level 0x{level_def.level:02X} subfunction 0x{sub:02X} "
                    f"not allowed in session 0x{state.active_session:02X} -> NRC 0x7E."
                )
                return NrcDecision(
                    sid=sid, nrc=Nrc.SUB_FUNCTION_NOT_SUPPORTED_IN_ACTIVE_SESSION, trace=trace
                )
        trace.append(f"Step 5: subfunction 0x{sub:02X} allowed in the active session.")

        # Step 5b — subfunction-specific exact length else 0x13.
        # Source: design decision — see DECISIONS.md [R-LEN]
        # + SWS_Dcm_00272 (wrong length for the parsed request gives 0x13).
        sub_len: int | None = None
        if sid == ServiceId.READ_DTC_INFORMATION and sub == DTC_BY_STATUS_MASK:
            sub_len = 3
        elif sid == ServiceId.SECURITY_ACCESS and level_def is not None:
            sub_len = 2 if is_seed_request else 2 + level_def.seed_length
        if sub_len is not None and request.length != sub_len:
            trace.append(
                f"Step 5b: subfunction 0x{sub:02X} needs total length {sub_len}, "
                f"got {request.length} -> NRC 0x13."
            )
            return NrcDecision(
                sid=sid, nrc=Nrc.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT, trace=trace
            )

    # Step 6 — service-specific checks.
    if sid == ServiceId.CLEAR_DIAGNOSTIC_INFORMATION:
        group = int.from_bytes(raw[1:4], "big")
        known = {dtc_code_to_int(d.code) for d in spec.dtcs}
        # Step 6a — group identifier supported else 0x31.
        # Source: design decision — see DECISIONS.md [R-CLEAR]
        # + SWS_Dcm_01265 (a groupOfDTC the DTC memory cannot select gives 0x31).
        if group != CLEAR_ALL_DTC_GROUP and group not in known:
            trace.append(f"Step 6a: DTC group 0x{group:06X} unknown -> NRC 0x31.")
            return NrcDecision(sid=sid, nrc=Nrc.REQUEST_OUT_OF_RANGE, trace=trace)
        trace.append(f"Step 6a: DTC group 0x{group:06X} accepted.")
        # Step 6f — NVM failure while clearing else 0x72.
        # Source: design decision — see DECISIONS.md [R-0x72]
        # + SWS_Dcm_01060 (a memory error while clearing DTCs gives 0x72).
        if state.environment.nvm_write_fault:
            trace.append("Step 6f: NVM write fault active; clearing DTC memory fails -> NRC 0x72.")
            return NrcDecision(sid=sid, nrc=Nrc.GENERAL_PROGRAMMING_FAILURE, trace=trace)

    elif sid == ServiceId.READ_DTC_INFORMATION:
        mask = raw[2]
        avail = spec.dtc_status_availability_mask
        count = sum(
            1 for d in spec.dtcs if state.dtc_status.get(dtc_code_to_int(d.code), 0) & mask & avail
        )
        response_len = 3 + 4 * count
        # Step 7 — positive response fits the transport else 0x14.
        # Source: design decision — see DECISIONS.md [R-0x14]
        # + SWS_Dcm_01059 (response longer than the response buffer gives 0x14).
        if response_len > spec.max_response_length:
            trace.append(
                f"Step 7: response of {response_len} bytes exceeds "
                f"{spec.max_response_length} -> NRC 0x14."
            )
            return NrcDecision(sid=sid, nrc=Nrc.RESPONSE_TOO_LONG, trace=trace)
        trace.append(f"Step 6: status mask 0x{mask:02X} matches {count} DTC(s).")

    elif sid == ServiceId.READ_DATA_BY_IDENTIFIER:
        dids = [int.from_bytes(raw[i : i + 2], "big") for i in range(1, request.length, 2)]
        response_len = 1
        for did in dids:
            did_def = spec.get_did(did)
            # Step 6a — every DID supported else 0x31 (strict multi-DID rule).
            # Source: design decision — see DECISIONS.md [R-MULTI-DID]
            if did_def is None:
                trace.append(f"Step 6a: DID 0x{did:04X} not supported -> NRC 0x31.")
                return NrcDecision(sid=sid, nrc=Nrc.REQUEST_OUT_OF_RANGE, trace=trace)
            # Step 6b — every DID readable in the active session else 0x31.
            # Source: design decision — see DECISIONS.md [R-MULTI-DID]
            if state.active_session not in did_def.read_sessions:
                trace.append(
                    f"Step 6b: DID 0x{did:04X} not readable in session "
                    f"0x{state.active_session:02X} -> NRC 0x31."
                )
                return NrcDecision(sid=sid, nrc=Nrc.REQUEST_OUT_OF_RANGE, trace=trace)
            response_len += 2 + did_def.length
        trace.append(f"Step 6a/6b: {len(dids)} DID(s) supported and readable.")
        # Step 7 — positive response fits the transport else 0x14.
        # Source: design decision — see DECISIONS.md [R-0x14]
        # + SWS_Dcm_01059 (response longer than the response buffer gives 0x14).
        if response_len > spec.max_response_length:
            trace.append(
                f"Step 7: response of {response_len} bytes exceeds "
                f"{spec.max_response_length} -> NRC 0x14."
            )
            return NrcDecision(sid=sid, nrc=Nrc.RESPONSE_TOO_LONG, trace=trace)

    elif sid == ServiceId.SECURITY_ACCESS:
        assert level_def is not None
        level = level_def.level
        lockout = state.lockouts.get(level)
        # Step 6d — lockout delay still running else continue; 0x37.
        # Source: design decision — see DECISIONS.md [R-SEC-LOCKOUT]
        # + SWS_Dcm_01350 (requestSeed while the level's delay timer runs gives 0x37);
        # applying it to sendKey as well is ours — see docs/SWS_DISAGREEMENTS.md D5.
        if lockout is not None and is_delay_active(lockout, state.now_ms):
            trace.append(
                f"Step 6d: level 0x{level:02X} lockout delay active until "
                f"{lockout.locked_until_ms} ms (now {state.now_ms}) -> NRC 0x37."
            )
            return NrcDecision(sid=sid, nrc=Nrc.REQUIRED_TIME_DELAY_NOT_EXPIRED, trace=trace)
        if is_seed_request:
            trace.append(f"Step 6: seed request for level 0x{level:02X} accepted.")
        else:
            pending = state.pending_seeds.get(level)
            # Step 6e — key requires an outstanding seed for this level else 0x24.
            # Source: udsoncan behaviour (client always sends requestSeed before sendKey)
            # + design decision — see DECISIONS.md [R-SEC-SEQ]
            # + SWS_Dcm_00863 (a key is only compared after a successful seed request
            # for that level; the SWS names 0x24 only in an informative list).
            if pending is None:
                trace.append(f"Step 6e: no seed pending for level 0x{level:02X} -> NRC 0x24.")
                return NrcDecision(sid=sid, nrc=Nrc.REQUEST_SEQUENCE_ERROR, trace=trace)
            key = raw[2:]
            # Step 6g — key verification: 0x35, or 0x36 on the attempt reaching the limit.
            # Source: design decision — see DECISIONS.md [R-SEC-LOCKOUT] (Phase 1 lockout model)
            # + SWS_Dcm_01397 (a failed key increments the level's attempt counter),
            # SWS_Dcm_00660 (counter below the limit gives 0x35), SWS_Dcm_01349 (counter
            # at/above the limit starts the delay timer and gives 0x36).
            if compute_key(pending, level) != key:
                current = lockout if lockout is not None else SecurityLockoutState()
                _, triggered = record_failed_attempt(
                    current, state.now_ms, level_def.max_attempts, level_def.delay_ms
                )
                if triggered:
                    trace.append(
                        f"Step 6g: invalid key; attempt {current.failed_attempts + 1} reaches "
                        f"limit {level_def.max_attempts} -> NRC 0x36, delay "
                        f"{level_def.delay_ms} ms armed."
                    )
                    return NrcDecision(
                        sid=sid,
                        nrc=Nrc.EXCEED_NUMBER_OF_ATTEMPTS,
                        failed_key_attempt=True,
                        trace=trace,
                    )
                trace.append(
                    f"Step 6g: invalid key (attempt {current.failed_attempts + 1} of "
                    f"{level_def.max_attempts}) -> NRC 0x35."
                )
                return NrcDecision(
                    sid=sid, nrc=Nrc.INVALID_KEY, failed_key_attempt=True, trace=trace
                )
            trace.append(f"Step 6g: key valid for level 0x{level:02X}.")

    elif sid == ServiceId.WRITE_DATA_BY_IDENTIFIER:
        did = int.from_bytes(raw[1:3], "big")
        data = raw[3:]
        did_def = spec.get_did(did)
        # Step 6a — DID supported else 0x31.
        # Source: design decision — see DECISIONS.md [R-ORDER] (PROJECT.md §5 step 6)
        # + SWS_Dcm_00467 (0x2E: unsupported DID gives 0x31).
        if did_def is None:
            trace.append(f"Step 6a: DID 0x{did:04X} not supported -> NRC 0x31.")
            return NrcDecision(sid=sid, nrc=Nrc.REQUEST_OUT_OF_RANGE, trace=trace)
        # Step 6a' — DID writable at all else 0x31 (read-only DID).
        # Source: design decision — see DECISIONS.md [R-READONLY]
        # + SWS_Dcm_00468 (0x2E: DID without write access gives 0x31).
        if not did_def.is_writable:
            trace.append(f"Step 6a': DID 0x{did:04X} is read-only -> NRC 0x31.")
            return NrcDecision(sid=sid, nrc=Nrc.REQUEST_OUT_OF_RANGE, trace=trace)
        # Step 6b — DID writable in active session else 0x31.
        # Source: design decision — see DECISIONS.md [R-ORDER] (PROJECT.md §5 step 6)
        # + SWS_Dcm_00469 (0x2E: DID not writable in the active session gives 0x31).
        if state.active_session not in did_def.write_sessions:
            trace.append(
                f"Step 6b: DID 0x{did:04X} not writable in session "
                f"0x{state.active_session:02X} -> NRC 0x31."
            )
            return NrcDecision(sid=sid, nrc=Nrc.REQUEST_OUT_OF_RANGE, trace=trace)
        # Step 6b' — data record length must equal the DID length else 0x13.
        # Source: design decision — see DECISIONS.md [R-LEN]
        # + SWS_Dcm_00473 (fixed-length DID: data length must match the DID size) with
        # SWS_Dcm_00272 (0x13); the SWS lists it after security — SWS_DISAGREEMENTS D3.
        if len(data) != did_def.length:
            trace.append(
                f"Step 6b': DID 0x{did:04X} needs {did_def.length} data byte(s), "
                f"got {len(data)} -> NRC 0x13."
            )
            return NrcDecision(
                sid=sid, nrc=Nrc.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT, trace=trace
            )
        # Step 6c — security level unlocked (exact level match) else 0x33.
        # Source: design decision — see DECISIONS.md [R-SEC-EXACT]
        # + SWS_Dcm_00470 (0x2E: DID not writable at the current security level: 0x33).
        needed = did_def.write_security_level
        if needed is not None and state.unlocked_level != needed:
            trace.append(
                f"Step 6c: DID 0x{did:04X} needs security level 0x{needed:02X} unlocked "
                f"(unlocked: {state.unlocked_level}) -> NRC 0x33."
            )
            return NrcDecision(sid=sid, nrc=Nrc.SECURITY_ACCESS_DENIED, trace=trace)
        # Step 6d — preconditions met else 0x22.
        # Source: design decision — see DECISIONS.md [R-COND]
        # + SWS_Dcm_00822 (0x2E: DID write gated by a mode rule) with SWS_Dcm_00815
        # (a failed mode rule without an explicit NRC gives 0x22).
        for cond in did_def.conditions.requires:
            if not state.environment.is_met(cond):
                trace.append(f"Step 6d: condition '{cond}' not met -> NRC 0x22.")
                return NrcDecision(sid=sid, nrc=Nrc.CONDITIONS_NOT_CORRECT, trace=trace)
        # Step 6e — value range (big-endian unsigned) else 0x31.
        # Source: design decision — see DECISIONS.md [R-RANGE]
        if did_def.value_range is not None:
            value = int.from_bytes(data, "big")
            if not did_def.value_range.min <= value <= did_def.value_range.max:
                trace.append(
                    f"Step 6e: value {value} outside [{did_def.value_range.min}, "
                    f"{did_def.value_range.max}] -> NRC 0x31."
                )
                return NrcDecision(sid=sid, nrc=Nrc.REQUEST_OUT_OF_RANGE, trace=trace)
        # Step 6f — NVM write failure else 0x72.
        # Source: design decision — see DECISIONS.md [R-0x72]
        if state.environment.nvm_write_fault:
            trace.append("Step 6f: NVM write fault active -> NRC 0x72.")
            return NrcDecision(sid=sid, nrc=Nrc.GENERAL_PROGRAMMING_FAILURE, trace=trace)
        trace.append(f"Step 6: write of DID 0x{did:04X} accepted.")

    elif sid == ServiceId.ROUTINE_CONTROL:
        assert sub is not None
        rid = int.from_bytes(raw[2:4], "big")
        routine = spec.get_routine(rid)
        # Step 6a — routine identifier supported else 0x31.
        # Source: design decision — see DECISIONS.md [R-ORDER] (PROJECT.md §5 step 6)
        # + SWS_Dcm_00568 (unsupported routine identifier gives 0x31).
        if routine is None:
            trace.append(f"Step 6a: routine 0x{rid:04X} not supported -> NRC 0x31.")
            return NrcDecision(sid=sid, nrc=Nrc.REQUEST_OUT_OF_RANGE, trace=trace)
        # Step 6b — routine allowed in active session else 0x31.
        # Source: design decision — see DECISIONS.md [R-ORDER] (PROJECT.md §5 step 6)
        # + SWS_Dcm_00570 (routine not executable in the active session gives 0x31).
        if state.active_session not in routine.sessions:
            trace.append(
                f"Step 6b: routine 0x{rid:04X} not allowed in session "
                f"0x{state.active_session:02X} -> NRC 0x31."
            )
            return NrcDecision(sid=sid, nrc=Nrc.REQUEST_OUT_OF_RANGE, trace=trace)
        # Step 6b' — control type supported by this routine else 0x12.
        # Source: design decision — see DECISIONS.md [R-ROUTINE-SUB]
        # + SWS_Dcm_00869 (control type not configured for this routine gives 0x12);
        # the SWS lists it after the security check — see SWS_DISAGREEMENTS D4.
        if sub not in routine.allowed_subfunctions:
            trace.append(
                f"Step 6b': routine 0x{rid:04X} does not support control type 0x{sub:02X} "
                "-> NRC 0x12."
            )
            return NrcDecision(sid=sid, nrc=Nrc.SUB_FUNCTION_NOT_SUPPORTED, trace=trace)
        # Step 6b'' — option record length else 0x13.
        # Source: design decision — see DECISIONS.md [R-LEN]
        # + SWS_Dcm_01140 (0x31: wrong overall request length gives 0x13).
        expected_len = 4 + (routine.option_record_length if sub == ROUTINE_START else 0)
        if request.length != expected_len:
            trace.append(
                f"Step 6b'': routine 0x{rid:04X} control 0x{sub:02X} needs total length "
                f"{expected_len}, got {request.length} -> NRC 0x13."
            )
            return NrcDecision(
                sid=sid, nrc=Nrc.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT, trace=trace
            )
        # Step 6c — security level unlocked (exact match) else 0x33.
        # Source: design decision — see DECISIONS.md [R-SEC-EXACT]
        # + SWS_Dcm_00571 (routine not executable at the current security level: 0x33).
        if routine.security_level is not None and state.unlocked_level != routine.security_level:
            trace.append(
                f"Step 6c: routine 0x{rid:04X} needs security level "
                f"0x{routine.security_level:02X} unlocked -> NRC 0x33."
            )
            return NrcDecision(sid=sid, nrc=Nrc.SECURITY_ACCESS_DENIED, trace=trace)
        # Step 6d — preconditions (checked on start only) else 0x22.
        # Source: design decision — see DECISIONS.md [R-COND]
        # + SWS_Dcm_01169 (startRoutine gated by a mode rule) with SWS_Dcm_00815
        # (a failed mode rule without an explicit NRC gives 0x22).
        if sub == ROUTINE_START:
            for cond in routine.conditions.requires:
                if not state.environment.is_met(cond):
                    trace.append(f"Step 6d: condition '{cond}' not met -> NRC 0x22.")
                    return NrcDecision(sid=sid, nrc=Nrc.CONDITIONS_NOT_CORRECT, trace=trace)
        # Step 6e — sequence: start/stop/results ordering else 0x24.
        # Source: design decision — see DECISIONS.md [R-ROUTINE-SEQ]
        status = state.routine_status.get(rid)
        if sub == ROUTINE_START and status == RoutineStatus.RUNNING:
            trace.append(f"Step 6e: routine 0x{rid:04X} already running -> NRC 0x24.")
            return NrcDecision(sid=sid, nrc=Nrc.REQUEST_SEQUENCE_ERROR, trace=trace)
        if (
            sub == ROUTINE_STOP
            and routine.stop_requires_start
            and status != RoutineStatus.RUNNING
        ):
            trace.append(f"Step 6e: stop but routine 0x{rid:04X} is not running -> NRC 0x24.")
            return NrcDecision(sid=sid, nrc=Nrc.REQUEST_SEQUENCE_ERROR, trace=trace)
        if sub == ROUTINE_RESULTS and routine.results_requires_start and status is None:
            trace.append(
                f"Step 6e: results requested but routine 0x{rid:04X} never started -> NRC 0x24."
            )
            return NrcDecision(sid=sid, nrc=Nrc.REQUEST_SEQUENCE_ERROR, trace=trace)
        trace.append(f"Step 6: routine 0x{rid:04X} control 0x{sub:02X} accepted.")
        # Step 8 — long-running routine start answered with 0x78 first.
        # Source: udsoncan behaviour (client waits up to P2* after 0x78 for the final
        # response) + design decision — see DECISIONS.md [R-0x78]
        # + SWS_Dcm_00024 (send 0x78 when the task needs longer than P2) and
        # SWS_Dcm_00203 (after a pending response the final one is never suppressed).
        if sub == ROUTINE_START and routine.long_running:
            trace.append("Step 8: long-running routine -> interim NRC 0x78, then final positive.")
            return NrcDecision(
                sid=sid,
                pending_nrc=Nrc.REQUEST_CORRECTLY_RECEIVED_RESPONSE_PENDING,
                suppress_positive=sup,
                trace=trace,
            )

    # 0x10, 0x11, 0x3E have no service-specific negative checks in this spec.
    # Source: design decision — see DECISIONS.md [R-NO-0x10]
    # Positive response suppressed on request: SWS_Dcm_00200 (suppress bit set means
    # no positive response). Negatives are always sent [R-SUPPRESS-NEG]:
    # SWS_Dcm_00001 suppresses some NRCs only under functional addressing, which
    # this ECU model does not use.
    trace.append("Result: positive response.")
    return NrcDecision(sid=sid, suppress_positive=sup, trace=trace)
