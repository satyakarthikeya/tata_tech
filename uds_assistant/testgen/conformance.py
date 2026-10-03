"""Requirement-independent conformance sweep (Part D2): differential testing against the oracle.

Requirement-driven tests only apply the stimuli their templates happen to contain. The
conformance sweep guarantees broad stimulus and observation coverage regardless of which
requirements were written or which templates a planner picked. It is generated
deterministically from the spec alone (no requirement, no LLM, no bug catalog).

A conformance case is

- a **setup**: a sequence of steps from power-on that establishes one state (active session,
  security state, lockout state, pending seed, routine state, environment, DTC statuses,
  written DID values, time since the last request, after a reset / session change);
- one **stimulus**: one request, possibly mutated (trailing byte, truncation, suppress bit,
  unsupported subfunction, range boundaries, wrong keys, ...);
- a fixed set of **probes**: generic observation requests that expose hidden state
  (all DIDs in one read: session / stored values / session-dependent readability; routine
  results: routine state; a seed request per level: security / lockout / seed counter;
  then silence past S3 and the read again: time-dependent state and retention).

Every expected response is computed by the rules engine (via the same ``_Builder`` the
templates use), and every case is re-instantiable from its parameters
``(setup, stimulus, probes)`` alone, so byte provenance holds.

Setup and stimulus catalogs are enumerated from the spec (sessions, security levels, DIDs,
routines, DTCs, ECU-reset types, timing). The full cross product is reduced with a
deterministic greedy covering over oracle-observable items (see :func:`select_cases`).

The conformance template is registered in :data:`CONFORMANCE_TEMPLATES`, deliberately NOT in
:data:`uds_assistant.testgen.templates.TEMPLATES`, so it never appears in the planner's
option catalog.
"""

from __future__ import annotations

import heapq
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

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
from uds_assistant.protocol.constants import (
    NEGATIVE_RESPONSE_SID,
    POSITIVE_RESPONSE_OFFSET,
    SUPPRESS_POS_RESP_BIT,
    ServiceId,
)
from uds_assistant.protocol.security import compute_key
from uds_assistant.rules.engine import RuleResult, evaluate
from uds_assistant.rules.state import DEFAULT_SESSION_ID, EcuState, dtc_code_to_int
from uds_assistant.spec.schema import DidDef, EcuSpec, RoutineDef, SecurityLevelDef
from uds_assistant.testgen.model import Citation, SendStep, TestCase
from uds_assistant.testgen.templates import TEMPLATES, Template, _Builder, validate_test

CONFORMANCE_TEMPLATE_ID = "conformance_case"
"""Template id of every conformance test (not offered to the planner)."""

MAX_SUITE_SIZE = 1200
"""Hard cap on the number of conformance tests."""

PROBE_SET_ID = "state_v1"
"""The one fixed probe set (see :func:`_apply_probes`)."""

SID_SC = int(ServiceId.DIAGNOSTIC_SESSION_CONTROL)
SID_ER = int(ServiceId.ECU_RESET)
SID_CDTC = int(ServiceId.CLEAR_DIAGNOSTIC_INFORMATION)
SID_RDTC = int(ServiceId.READ_DTC_INFORMATION)
SID_RDBI = int(ServiceId.READ_DATA_BY_IDENTIFIER)
SID_SA = int(ServiceId.SECURITY_ACCESS)
SID_WDBI = int(ServiceId.WRITE_DATA_BY_IDENTIFIER)
SID_RC = int(ServiceId.ROUTINE_CONTROL)
SID_TP = int(ServiceId.TESTER_PRESENT)

RC_START, RC_STOP, RC_RESULTS = 1, 2, 3
"""RoutineControl control types defined by the protocol (start / stop / requestResults)."""

TP_ZERO_SUBFUNCTION = 0
"""TesterPresent's only defined subfunction (zeroSubFunction)."""

DTC_ALL_GROUPS = b"\xff\xff\xff"
"""ClearDiagnosticInformation group meaning 'all groups' (protocol constant)."""

# Standard UDS service identifiers (protocol-level, not spec content); the sweep sends the
# first ones the spec does NOT list, to observe the 'service not supported' path.
_STANDARD_SIDS = (0x23, 0x24, 0x28, 0x2A, 0x2C, 0x2F, 0x34, 0x35, 0x36, 0x37, 0x3D, 0x83, 0x84,
                  0x85, 0x86, 0x87)
_UNSUPPORTED_SID_STIMULI = 2

MOVING_SPEED_KPH = 30
"""Any non-zero speed: the vehicle counts as moving (behaviour contract, Environment)."""

FILLER = 0x00
"""Byte used for trailing-byte mutations and zero-filled payloads."""

# Behaviour-contract section headings used as citations.
_SEC = {
    SID_SC: "0x10 DiagnosticSessionControl",
    SID_ER: "0x11 ECUReset",
    SID_CDTC: "0x14 ClearDiagnosticInformation",
    SID_RDTC: "0x19 subfunction 02: ReadDTCInformation by status mask",
    SID_RDBI: "0x22 ReadDataByIdentifier",
    SID_SA: "0x27 SecurityAccess",
    SID_WDBI: "0x2E WriteDataByIdentifier",
    SID_RC: "0x31 RoutineControl",
    SID_TP: "0x3E TesterPresent",
}
SEC_ORDER = "NRC evaluation order (the first failing check wins)"
SEC_SUPPRESS = "Suppress bit"
SEC_SUBFUNCTION = "Subfunction byte"
SEC_BEFORE = "Before evaluating each request"
SEC_POWER_ON = "State at power-on"


# ------------------------------------------------------------------------------ catalog types


@dataclass(frozen=True)
class SetupAction:
    """One setup step. ``kind`` is one of the keys of :data:`_ACTIONS`; ``args`` are ints."""

    kind: str
    args: tuple[int, ...] = ()


@dataclass(frozen=True)
class Setup:
    """A named state reached from power-on by a sequence of actions."""

    id: str
    dimension: str
    description: str
    actions: tuple[SetupAction, ...]


@dataclass(frozen=True)
class Stimulus:
    """One request (possibly mutated) applied after a setup.

    ``build`` returns the request bytes from the builder's current oracle state and history
    (e.g. a key computed from the last seed the ECU actually sent).
    """

    id: str
    sid: int | None
    klass: str
    description: str
    build: Callable[[_ConfBuilder], bytes] = field(compare=False)
    citations: tuple[str, ...] = ()

    @property
    def family(self) -> str:
        """Stimulus family used for the setup x family pairwise covering (the service)."""
        return f"{self.sid:02x}" if self.sid is not None else "other"


# ------------------------------------------------------------------------------- the builder


class _ConfBuilder(_Builder):
    """The templates' oracle-stepping builder, plus raw-byte sends for mutated requests."""

    def send_raw(self, raw: bytes, description: str = "") -> RuleResult:
        """Send ``raw`` bytes through the oracle and record the step."""
        result = self.rs.send(bytes(raw))
        self.steps.append(
            SendStep(
                request_hex=bytes(raw).hex(),
                expected_responses_hex=[r.hex() for r in result.responses],
                description=description,
            )
        )
        return result

    def last_seed(self, level: SecurityLevelDef, back: int = 0) -> bytes:
        """A seed the ECU actually sent for ``level`` (as a tester sees it).

        ``back=0`` is the most recent one, ``back=1`` the one before it, and so on. Only
        observed positive responses count (a suppressed seed is invisible to a tester).
        Falls back to an all-zero seed when there is no such observed seed.
        """
        positive = bytes([SID_SA + POSITIVE_RESPONSE_OFFSET, level.seed_subfunction])
        seen = 0
        for res in reversed(self.rs.history):
            req = res.request
            if len(req) != 2 or req[0] != SID_SA or (req[1] & 0x7F) != level.seed_subfunction:
                continue
            for resp in res.responses:
                if resp[:2] == positive and len(resp) == 2 + level.seed_length:
                    if seen == back:
                        return bytes(resp[2:])
                    seen += 1
        return bytes(level.seed_length)

    def hold(self, total_ms: int) -> None:
        """Let ``total_ms`` pass while keeping the session alive (TesterPresent, suppressed).

        Time advances in chunks of the active session's S3 (exactly S3 does not expire),
        with a keep-alive between chunks; the next request follows the last chunk.
        """
        remaining = total_ms
        while remaining > 0:
            session = self.spec.get_session(self.rs.state.active_session)
            chunk = min(remaining, session.timing.s3_ms if session is not None else remaining)
            self.advance(chunk, "Wait (session kept alive).")
            remaining -= chunk
            if remaining > 0:
                self.send(tester_present(suppress_positive=True), "Keep-alive.")


# ----------------------------------------------------------------------------- spec helpers


def _hx(value: int, width: int = 2) -> str:
    return f"{value:0{width}x}"


def _first_missing(used: set[int], start: int = 1) -> int:
    """Smallest 7-bit value >= ``start`` not in ``used`` (an unsupported subfunction)."""
    return next(v for v in range(start, 0x80) if v not in used)


def _unknown_identifier(spec: EcuSpec) -> int:
    """A 16-bit identifier that is neither a DID nor a routine of the spec."""
    used = {d.id for d in spec.dids} | {r.id for r in spec.routines}
    cand = max(used, default=0) + 1
    if cand > 0xFFFF or cand in used:
        cand = next(v for v in range(0x10000) if v not in used)
    return cand


def _dtc_numbers(spec: EcuSpec) -> list[int]:
    return [dtc_code_to_int(d.code) for d in spec.dtcs]


def _dtc_patterns(spec: EcuSpec) -> list[int]:
    """Distinct non-zero status bytes for the DTCs (two mirrored bits per DTC)."""
    return [((1 << (i % 8)) | (0x80 >> (i % 8))) & 0xFF for i in range(len(spec.dtcs))]


def _value_span(did: DidDef) -> tuple[int, int, int]:
    max_repr = (1 << (8 * did.length)) - 1
    lo, hi = (did.value_range.min, did.value_range.max) if did.value_range else (0, max_repr)
    return lo, hi, max_repr


def _pattern_value(did: DidDef) -> int:
    """An in-range value != default, with distinct bytes where possible."""
    lo, hi, _ = _value_span(did)
    default = int.from_bytes(did.default_value, "big") if did.default_value else None
    pattern = int.from_bytes(bytes((0x12 + 0x22 * i) & 0xFF for i in range(did.length)), "big")
    for cand in (pattern, hi, lo, (lo + hi) // 2):
        if lo <= cand <= hi and cand != default:
            return cand
    return lo


def _level_reachable(spec: EcuSpec, level: int | None, session: int) -> bool:
    if level is None:
        return True
    lvl = spec.get_security_level(level)
    return lvl is not None and session in lvl.allowed_sessions


def _allows(spec: EcuSpec, session: int, sid: int) -> bool:
    sess = spec.get_session(session)
    return sess is not None and sid in sess.allowed_services


def _spec_services(spec: EcuSpec) -> set[int]:
    return {sid for s in spec.sessions for sid in s.allowed_services}


def _max_s3(spec: EcuSpec) -> int:
    return max(s.timing.s3_ms for s in spec.sessions)


# ------------------------------------------------------------------------------- setup actions


def _act_session(b: _ConfBuilder, s: int) -> None:
    b.send(session_control(s), f"Setup: enter session {s:#04x}.")


def _act_unlock(b: _ConfBuilder, level: int) -> None:
    b.unlock(level, "Setup: ")


def _act_seed(b: _ConfBuilder, level: int) -> None:
    lvl = b.spec.get_security_level(level)
    assert lvl is not None
    b.send(security_request_seed(lvl.seed_subfunction), f"Setup: request a seed for level {level:#x}.")


def _act_wrong_key(b: _ConfBuilder, level: int) -> None:
    lvl = b.spec.get_security_level(level)
    assert lvl is not None
    b.send(security_request_seed(lvl.seed_subfunction), f"Setup: request a seed for level {level:#x}.")
    key = bytearray(compute_key(b.last_seed(lvl), level))
    key[-1] ^= 0x01
    b.send(security_send_key(lvl.key_subfunction, bytes(key)), "Setup: send a wrong key.")


def _act_routine(b: _ConfBuilder, sub: int, rid: int) -> None:
    routine = b.spec.get_routine(rid)
    assert routine is not None
    option = bytes(routine.option_record_length) if sub == RC_START else b""
    b.send(routine_control(sub, rid, option), f"Setup: routine {rid:#06x} control type {sub:#x}.")


def _act_env(b: _ConfBuilder, speed: int, nvm: int) -> None:
    b.set_environment(vehicle_speed_kph=speed, nvm_write_fault=bool(nvm),
                      description=f"Setup: vehicle speed {speed} kph, NVM write fault {bool(nvm)}.")


def _act_dtc(b: _ConfBuilder) -> None:
    for dtc, status in zip(b.spec.dtcs, _dtc_patterns(b.spec), strict=True):
        b.set_dtc_status(dtc.code, status, f"Setup: DTC {dtc.code} status {status:#04x}.")


def _act_advance(b: _ConfBuilder, ms: int) -> None:
    b.advance(ms, f"Setup: stay silent for {ms} ms.")


def _act_hold(b: _ConfBuilder, ms: int) -> None:
    b.hold(ms)


def _act_reset(b: _ConfBuilder, sub: int) -> None:
    b.send(ecu_reset(sub), f"Setup: ECU reset type {sub:#x}.")


def _act_write(b: _ConfBuilder, did: int) -> None:
    did_def = b.spec.get_did(did)
    assert did_def is not None
    value = _pattern_value(did_def)
    b.send(write_did(did, value.to_bytes(did_def.length, "big")),
           f"Setup: write {value:#x} to DID {did:#06x}.")


_ACTIONS: dict[str, Callable[..., None]] = {
    "session": _act_session,
    "unlock": _act_unlock,
    "seed": _act_seed,
    "wrong_key": _act_wrong_key,
    "routine": _act_routine,
    "env": _act_env,
    "dtc": _act_dtc,
    "advance": _act_advance,
    "hold": _act_hold,
    "reset": _act_reset,
    "write": _act_write,
}

_TIME_ACTIONS = frozenset({"advance", "hold"})


def _a(kind: str, *args: int) -> SetupAction:
    return SetupAction(kind, tuple(args))


# ------------------------------------------------------------------------------ setup catalog


def setup_catalog(spec: EcuSpec) -> list[Setup]:
    """Every setup, enumerated from the spec in a fixed order."""
    out: list[Setup] = [Setup("pwr", "power_on", "power-on state", ())]
    default = DEFAULT_SESSION_ID
    others = [s for s in spec.sessions if s.id != default]
    reset_sub = spec.ecu_reset.supported_subfunctions[0] if spec.ecu_reset.supported_subfunctions else None

    def enter(s: int) -> tuple[SetupAction, ...]:
        return () if s == default else (_a("session", s),)

    def stag(s: int) -> str:
        return "pwr" if s == default else f"s{_hx(s)}"

    for s in others:
        out.append(Setup(f"s{_hx(s.id)}", "session", f"session {s.id:#04x}", enter(s.id)))
    # Security, lockout and session-transition states, per level and per allowed session.
    for lvl in spec.security_levels:
        lv = _hx(lvl.level)
        for s in lvl.allowed_sessions:
            sess = spec.get_session(s)
            if sess is None:
                continue
            base, tag, where = enter(s), stag(s), f"in session {s:#04x}"
            unl = (*base, _a("unlock", lvl.level))
            wrong = tuple(_a("wrong_key", lvl.level) for _ in range(lvl.max_attempts))
            locked = (*base, *wrong)
            rows = [
                (f"{tag}.u{lv}", "security", f"level {lvl.level:#x} unlocked {where}", unl),
                (f"{tag}.seed{lv}", "security", f"seed pending for level {lvl.level:#x} {where}",
                 (*base, _a("seed", lvl.level))),
                (f"{tag}.seed{lv}x2", "security",
                 f"seed requested twice for level {lvl.level:#x} {where}",
                 (*base, _a("seed", lvl.level), _a("seed", lvl.level))),
            ]
            if lvl.max_attempts > 1:
                rows.append((f"{tag}.fail{lv}x{lvl.max_attempts - 1}", "lockout",
                             f"{lvl.max_attempts - 1} wrong key(s) for level {lvl.level:#x} {where}",
                             (*base, *wrong[:-1])))
            rows += [
                (f"{tag}.lock{lv}", "lockout", f"level {lvl.level:#x} lockout delay armed {where}",
                 locked),
                (f"{tag}.lock{lv}.hold", "timing",
                 f"level {lvl.level:#x} lockout, 1 ms before the delay ends {where}",
                 (*locked, _a("hold", lvl.delay_ms - 1))),
                (f"{tag}.lock{lv}.end", "timing",
                 f"level {lvl.level:#x} lockout, delay just ended {where}",
                 (*locked, _a("hold", lvl.delay_ms))),
            ]
            if reset_sub is not None and _allows(spec, s, SID_ER):
                rows.append((f"{tag}.lock{lv}.reset", "lockout",
                             f"level {lvl.level:#x} lockout armed, then ECU reset and back {where}",
                             (*locked, _a("reset", reset_sub), *enter(s))))
                rows.append((f"{tag}.u{lv}.reset", "reset",
                             f"level {lvl.level:#x} unlocked, then ECU reset and back {where}",
                             (*unl, _a("reset", reset_sub), *enter(s))))
            rows += [
                (f"{tag}.u{lv}.reenter", "session_change",
                 f"level {lvl.level:#x} unlocked, then session {s:#04x} re-entered",
                 (*unl, _a("session", s))),
                (f"{tag}.u{lv}.nearS3", "timing",
                 f"level {lvl.level:#x} unlocked {where}, silent for exactly S3",
                 (*unl, _a("advance", sess.timing.s3_ms))),
                (f"{tag}.u{lv}.s3exp", "timing",
                 f"level {lvl.level:#x} unlocked {where}, silent for S3 + 1 ms",
                 (*unl, _a("advance", sess.timing.s3_ms + 1))),
                (f"{tag}.u{lv}.moving", "environment",
                 f"level {lvl.level:#x} unlocked {where}, vehicle moving",
                 (*unl, _a("env", MOVING_SPEED_KPH, 0))),
                (f"{tag}.u{lv}.nvm", "environment",
                 f"level {lvl.level:#x} unlocked {where}, NVM write fault",
                 (*unl, _a("env", 0, 1))),
            ]
            out += [Setup(i, d, desc, acts) for i, d, desc, acts in rows]
    # One level locked out, then another level's session entered (per-level lockout state).
    for lvl in spec.security_levels:
        if not lvl.allowed_sessions:
            continue
        s0 = lvl.allowed_sessions[0]
        locked = (*enter(s0), *(_a("wrong_key", lvl.level) for _ in range(lvl.max_attempts)))
        for other in spec.security_levels:
            if other.level == lvl.level or not other.allowed_sessions:
                continue
            s1 = other.allowed_sessions[0]
            out.append(Setup(f"{stag(s1)}.after_lock{_hx(lvl.level)}", "lockout",
                             f"level {lvl.level:#x} locked out, then session {s1:#04x} entered "
                             f"(level {other.level:#x} available)",
                             (*locked, *(() if s1 == s0 else (_a("session", s1),)))))
    # Session timing without security.
    for s in others:
        out.append(Setup(f"s{_hx(s.id)}.nearS3", "timing",
                         f"session {s.id:#04x}, silent for exactly S3",
                         (*enter(s.id), _a("advance", s.timing.s3_ms))))
        out.append(Setup(f"s{_hx(s.id)}.s3exp", "timing",
                         f"session {s.id:#04x}, silent for S3 + 1 ms",
                         (*enter(s.id), _a("advance", s.timing.s3_ms + 1))))
    # Environment at power-on.
    out.append(Setup("pwr.moving", "environment", "power-on state, vehicle moving",
                     (_a("env", MOVING_SPEED_KPH, 0),)))
    out.append(Setup("pwr.nvm", "environment", "power-on state, NVM write fault", (_a("env", 0, 1),)))
    # DTC statuses set.
    if spec.dtcs:
        out.append(Setup("pwr.dtc", "dtc", "power-on state, every DTC with a distinct status",
                         (_a("dtc"),)))
        out.append(Setup("pwr.dtc.nvm", "dtc", "every DTC set, NVM write fault",
                         (_a("dtc"), _a("env", 0, 1))))
        for s in others:
            if _allows(spec, s.id, SID_RDTC) or _allows(spec, s.id, SID_CDTC):
                out.append(Setup(f"s{_hx(s.id)}.dtc", "dtc",
                                 f"session {s.id:#04x}, every DTC with a distinct status",
                                 (*enter(s.id), _a("dtc"))))
    # Routine states (started / stopped / completed) per routine.
    for r in spec.routines:
        if not r.sessions:
            continue
        s = r.sessions[0]
        if not _level_reachable(spec, r.security_level, s):
            continue
        base = (*enter(s), *((_a("unlock", r.security_level),) if r.security_level is not None else ()))
        tag = stag(s) + (f".u{_hx(r.security_level)}" if r.security_level is not None else "")
        rid = _hx(r.id, 4)
        if RC_START not in r.allowed_subfunctions:
            continue
        start = (*base, _a("routine", RC_START, r.id))
        state = "completed" if r.long_running else "running"
        out.append(Setup(f"{tag}.r{rid}.start", "routine",
                         f"routine {r.id:#06x} started ({state})", start))
        if not r.long_running and RC_STOP in r.allowed_subfunctions:
            out.append(Setup(f"{tag}.r{rid}.stop", "routine", f"routine {r.id:#06x} stopped",
                             (*start, _a("routine", RC_STOP, r.id))))
    # Written DID values.
    for d in spec.dids:
        if not d.write_sessions:
            continue
        s = d.write_sessions[0]
        if not _level_reachable(spec, d.write_security_level, s):
            continue
        lv = d.write_security_level
        base = (*enter(s), *((_a("unlock", lv),) if lv is not None else ()))
        tag = stag(s) + (f".u{_hx(lv)}" if lv is not None else "")
        out.append(Setup(f"{tag}.w{_hx(d.id, 4)}", "did_value",
                         f"DID {d.id:#06x} written with a non-default value",
                         (*base, _a("write", d.id))))
    return out


# --------------------------------------------------------------------------- stimulus catalog


def _with(raw: bytes, *, extra: int = 0, cut: int = 0) -> bytes:
    """``raw`` plus ``extra`` filler bytes, or minus its last ``cut`` bytes."""
    if cut:
        return raw[:-cut]
    return raw + bytes([FILLER]) * extra


def _spr(raw: bytes) -> bytes:
    """Set the suppress-positive-response bit on the subfunction byte."""
    return bytes([raw[0], raw[1] | SUPPRESS_POS_RESP_BIT]) + raw[2:]


def _const(raw: bytes) -> Callable[[_ConfBuilder], bytes]:
    return lambda _b: raw


def _subfunction_service_stimuli(
    sid: int, valid: list[tuple[str, bytes]], used: set[int], what: str, cite: str,
) -> list[Stimulus]:
    """valid / suppress / +1 byte per valid request; truncated; unsupported subfunction (+spr)."""
    out: list[Stimulus] = []
    for tag, raw in valid:
        out += [
            Stimulus(f"{_hx(sid)}.{tag}", sid, f"{_hx(sid)}/valid", f"{what} {tag}", _const(raw),
                     (cite,)),
            Stimulus(f"{_hx(sid)}.{tag}.spr", sid, f"{_hx(sid)}/suppress",
                     f"{what} {tag} with the suppress bit", _const(_spr(raw)), (cite, SEC_SUPPRESS)),
            Stimulus(f"{_hx(sid)}.{tag}.long", sid, f"{_hx(sid)}/trailing-byte",
                     f"{what} {tag} plus one trailing byte", _const(_with(raw, extra=1)),
                     (cite, SEC_ORDER)),
        ]
    if valid:
        first = valid[0][1]
        out.append(Stimulus(f"{_hx(sid)}.trunc", sid, f"{_hx(sid)}/truncated",
                            f"{what} cut by one byte", _const(first[:-1]), (cite, SEC_ORDER)))
    bad = _first_missing(used)
    bad_raw = bytes([sid, bad]) + valid[0][1][2:] if valid else bytes([sid, bad])
    out += [
        Stimulus(f"{_hx(sid)}.badsub", sid, f"{_hx(sid)}/unsupported-subfunction",
                 f"{what} with unsupported subfunction {bad:#x}", _const(bad_raw),
                 (cite, SEC_ORDER)),
        Stimulus(f"{_hx(sid)}.badsub.spr", sid, f"{_hx(sid)}/unsupported-subfunction-suppress",
                 f"{what} with unsupported subfunction {bad:#x} and the suppress bit",
                 _const(_spr(bad_raw)), (cite, SEC_SUPPRESS)),
    ]
    return out


def _session_stimuli(spec: EcuSpec) -> list[Stimulus]:
    valid = [(f"s{_hx(s.id)}", session_control(s.id).to_bytes()) for s in spec.sessions]
    return _subfunction_service_stimuli(SID_SC, valid, {s.id for s in spec.sessions},
                                        "DiagnosticSessionControl", _SEC[SID_SC])


def _reset_stimuli(spec: EcuSpec) -> list[Stimulus]:
    subs = spec.ecu_reset.supported_subfunctions
    valid = [(f"r{_hx(r)}", ecu_reset(r).to_bytes()) for r in subs]
    return _subfunction_service_stimuli(SID_ER, valid, set(subs), "ECUReset", _SEC[SID_ER])


def _tester_present_stimuli(spec: EcuSpec) -> list[Stimulus]:
    raw = tester_present(suppress_positive=False).to_bytes()
    out = _subfunction_service_stimuli(SID_TP, [("zero", raw)], {TP_ZERO_SUBFUNCTION},
                                       "TesterPresent", _SEC[SID_TP])
    return out


def _read_dtc_stimuli(spec: EcuSpec) -> list[Stimulus]:
    cite = _SEC[SID_RDTC]
    masks = [0x00, 0xFF, *[1 << i for i in range(8)]]
    valid = [(f"m{_hx(m)}", read_dtc_by_status_mask(m).to_bytes()) for m in masks]
    out: list[Stimulus] = []
    for tag, raw in valid:
        out.append(Stimulus(f"{_hx(SID_RDTC)}.{tag}", SID_RDTC, f"{_hx(SID_RDTC)}/valid",
                            f"ReadDTCInformation by status mask {tag}", _const(raw), (cite,)))
    full = read_dtc_by_status_mask(0xFF).to_bytes()
    out += [
        Stimulus(f"{_hx(SID_RDTC)}.mff.spr", SID_RDTC, f"{_hx(SID_RDTC)}/suppress",
                 "ReadDTCInformation mask 0xFF with the suppress bit", _const(_spr(full)),
                 (cite, SEC_SUPPRESS)),
        Stimulus(f"{_hx(SID_RDTC)}.mff.long", SID_RDTC, f"{_hx(SID_RDTC)}/trailing-byte",
                 "ReadDTCInformation mask 0xFF plus one trailing byte", _const(_with(full, extra=1)),
                 (cite, SEC_ORDER)),
        Stimulus(f"{_hx(SID_RDTC)}.nomask", SID_RDTC, f"{_hx(SID_RDTC)}/truncated",
                 "ReadDTCInformation without the mask byte", _const(full[:-1]), (cite, SEC_ORDER)),
        Stimulus(f"{_hx(SID_RDTC)}.nomask.spr", SID_RDTC, f"{_hx(SID_RDTC)}/truncated-suppress",
                 "ReadDTCInformation without the mask byte, suppress bit", _const(_spr(full[:-1])),
                 (cite, SEC_SUPPRESS)),
    ]
    bad = _first_missing(set(spec.read_dtc_supported_subfunctions))
    bad_raw = bytes([SID_RDTC, bad, 0xFF])
    out += [
        Stimulus(f"{_hx(SID_RDTC)}.badsub", SID_RDTC, f"{_hx(SID_RDTC)}/unsupported-subfunction",
                 f"ReadDTCInformation unsupported subfunction {bad:#x}", _const(bad_raw),
                 (cite, SEC_ORDER)),
        Stimulus(f"{_hx(SID_RDTC)}.badsub.spr", SID_RDTC,
                 f"{_hx(SID_RDTC)}/unsupported-subfunction-suppress",
                 f"ReadDTCInformation unsupported subfunction {bad:#x}, suppress bit",
                 _const(_spr(bad_raw)), (cite, SEC_SUPPRESS)),
    ]
    return out


def _clear_dtc_stimuli(spec: EcuSpec) -> list[Stimulus]:
    cite = _SEC[SID_CDTC]
    p = _hx(SID_CDTC)
    numbers = _dtc_numbers(spec)
    out = [Stimulus(f"{p}.all", SID_CDTC, f"{p}/all-groups", "Clear all DTC groups",
                    _const(clear_dtc(DTC_ALL_GROUPS).to_bytes()), (cite,))]
    for code, num in zip((d.code for d in spec.dtcs), numbers, strict=True):
        out.append(Stimulus(f"{p}.dtc{_hx(num, 6)}", SID_CDTC, f"{p}/one-dtc", f"Clear DTC {code}",
                            _const(clear_dtc(num.to_bytes(3, "big")).to_bytes()), (cite,)))
    unknown = next(v for v in range(max(numbers, default=0) + 1, 0x1000000)
                   if v not in numbers and v.to_bytes(3, "big") != DTC_ALL_GROUPS)
    all_raw = clear_dtc(DTC_ALL_GROUPS).to_bytes()
    out += [
        Stimulus(f"{p}.unknown", SID_CDTC, f"{p}/unknown-group",
                 f"Clear an undefined DTC group {unknown:#08x}",
                 _const(clear_dtc(unknown.to_bytes(3, "big")).to_bytes()), (cite,)),
        Stimulus(f"{p}.all.long", SID_CDTC, f"{p}/trailing-byte",
                 "Clear all DTC groups plus one trailing byte", _const(_with(all_raw, extra=1)),
                 (cite, SEC_ORDER)),
        Stimulus(f"{p}.all.short", SID_CDTC, f"{p}/truncated", "Clear DTC with a 2-byte group",
                 _const(all_raw[:-1]), (cite, SEC_ORDER)),
    ]
    return out


def _read_did_stimuli(spec: EcuSpec) -> list[Stimulus]:
    cite = _SEC[SID_RDBI]
    p = _hx(SID_RDBI)
    unknown = _unknown_identifier(spec)
    out: list[Stimulus] = []
    for d in spec.dids:
        tag = _hx(d.id, 4)
        out += [
            Stimulus(f"{p}.{tag}", SID_RDBI, f"{p}/single", f"Read DID {d.id:#06x}",
                     _const(read_did(d.id).to_bytes()), (cite,)),
            Stimulus(f"{p}.{tag}.dup", SID_RDBI, f"{p}/duplicate",
                     f"Read DID {d.id:#06x} twice in one request",
                     _const(read_did(d.id, d.id).to_bytes()), (cite,)),
            Stimulus(f"{p}.unk+{tag}", SID_RDBI, f"{p}/mixed-unknown",
                     f"Read an unknown DID then DID {d.id:#06x}",
                     _const(read_did(unknown, d.id).to_bytes()), (cite,)),
        ]
    out.append(Stimulus(f"{p}.unknown", SID_RDBI, f"{p}/unknown", f"Read unknown DID {unknown:#06x}",
                        _const(read_did(unknown).to_bytes()), (cite,)))
    if spec.dids:
        first = read_did(spec.dids[0].id).to_bytes()
        out += [
            Stimulus(f"{p}.empty", SID_RDBI, f"{p}/truncated", "ReadDataByIdentifier with no DID",
                     _const(first[:1]), (cite, SEC_ORDER)),
            Stimulus(f"{p}.cut", SID_RDBI, f"{p}/truncated", "ReadDataByIdentifier with half a DID",
                     _const(first[:-1]), (cite, SEC_ORDER)),
            Stimulus(f"{p}.dangling", SID_RDBI, f"{p}/trailing-byte",
                     "ReadDataByIdentifier with one dangling byte", _const(_with(first, extra=1)),
                     (cite, SEC_ORDER)),
        ]
        big = max(spec.dids, key=lambda d: (d.length, -spec.dids.index(d)))
        fit = (spec.max_response_length - 1) // (2 + big.length)
        out += [
            Stimulus(f"{p}.{_hx(big.id, 4)}.fit", SID_RDBI, f"{p}/response-length-limit",
                     f"Read DID {big.id:#06x} {fit} times (largest response that fits)",
                     _const(read_did(*([big.id] * fit)).to_bytes()), (cite,)),
            Stimulus(f"{p}.{_hx(big.id, 4)}.overflow", SID_RDBI, f"{p}/response-too-long",
                     f"Read DID {big.id:#06x} {fit + 1} times (response one entry too long)",
                     _const(read_did(*([big.id] * (fit + 1))).to_bytes()), (cite,)),
        ]
    return out


def _write_did_stimuli(spec: EcuSpec) -> list[Stimulus]:
    cite = _SEC[SID_WDBI]
    p = _hx(SID_WDBI)
    out: list[Stimulus] = []
    for d in spec.dids:
        tag = _hx(d.id, 4)
        if not d.write_sessions:
            out.append(Stimulus(f"{p}.{tag}.ro", SID_WDBI, f"{p}/read-only",
                                f"Write read-only DID {d.id:#06x}",
                                _const(write_did(d.id, bytes(d.length)).to_bytes()), (cite,)))
            continue
        lo, hi, max_repr = _value_span(d)
        values: list[tuple[str, str, int]] = [("value", "valid", _pattern_value(d)),
                                              ("min", "boundary", lo), ("max", "boundary", hi)]
        if lo > 0:
            values.append(("min-1", "out-of-range", lo - 1))
        if hi < max_repr:
            values.append(("max+1", "out-of-range", hi + 1))
        for vtag, klass, value in values:
            out.append(Stimulus(f"{p}.{tag}.{vtag}", SID_WDBI, f"{p}/{klass}",
                                f"Write {value:#x} ({vtag}) to DID {d.id:#06x}",
                                _const(write_did(d.id, value.to_bytes(d.length, "big")).to_bytes()),
                                (cite,)))
        good = write_did(d.id, _pattern_value(d).to_bytes(d.length, "big")).to_bytes()
        out += [
            Stimulus(f"{p}.{tag}.short", SID_WDBI, f"{p}/length",
                     f"Write DID {d.id:#06x} with one data byte too few", _const(good[:-1]),
                     (cite, SEC_ORDER)),
            Stimulus(f"{p}.{tag}.long", SID_WDBI, f"{p}/length",
                     f"Write DID {d.id:#06x} with one data byte too many",
                     _const(_with(good, extra=1)), (cite, SEC_ORDER)),
        ]
    unknown = _unknown_identifier(spec)
    out += [
        Stimulus(f"{p}.unknown", SID_WDBI, f"{p}/unknown", f"Write unknown DID {unknown:#06x}",
                 _const(write_did(unknown, bytes(1)).to_bytes()), (cite,)),
        Stimulus(f"{p}.nodata", SID_WDBI, f"{p}/truncated", "Write a DID without any data",
                 _const(write_did(spec.dids[0].id, b"").to_bytes() if spec.dids else
                        bytes([SID_WDBI])), (cite, SEC_ORDER)),
    ]
    return out


def _key_builder(level: SecurityLevelDef, mutate: str, other: SecurityLevelDef | None,
                 suppress: bool = False) -> Callable[[_ConfBuilder], bytes]:
    def build(b: _ConfBuilder) -> bytes:
        seed = b.last_seed(level, back=1 if mutate == "stale" else 0)
        key = bytearray(compute_key(seed, level.level))
        if mutate == "first":
            key[0] ^= 0x01
        elif mutate == "middle":
            key[len(key) // 2] ^= 0x01
        elif mutate == "last":
            key[-1] ^= 0x01
        elif mutate == "other_level" and other is not None:
            key = bytearray(compute_key(seed, other.level))
        elif mutate == "short":
            key = key[:-1]
        elif mutate == "long":
            key = key + bytes([FILLER])
        return security_send_key(level.key_subfunction, bytes(key), suppress).to_bytes()

    return build


def _security_stimuli(spec: EcuSpec) -> list[Stimulus]:
    cite = _SEC[SID_SA]
    p = _hx(SID_SA)
    out: list[Stimulus] = []
    levels = spec.security_levels
    for i, lvl in enumerate(levels):
        lv = _hx(lvl.level)
        other = levels[(i + 1) % len(levels)] if len(levels) > 1 else None
        seed = security_request_seed(lvl.seed_subfunction).to_bytes()
        out += [
            Stimulus(f"{p}.seed{lv}", SID_SA, f"{p}/seed", f"Request seed level {lvl.level:#x}",
                     _const(seed), (cite,)),
            Stimulus(f"{p}.seed{lv}.spr", SID_SA, f"{p}/seed-suppress",
                     f"Request seed level {lvl.level:#x}, suppress bit", _const(_spr(seed)),
                     (cite, SEC_SUPPRESS)),
            Stimulus(f"{p}.seed{lv}.long", SID_SA, f"{p}/trailing-byte",
                     f"Request seed level {lvl.level:#x} plus one trailing byte",
                     _const(_with(seed, extra=1)), (cite, SEC_ORDER)),
            Stimulus(f"{p}.key{lv}", SID_SA, f"{p}/key-correct",
                     f"Send the key for the last seed seen, level {lvl.level:#x}",
                     _key_builder(lvl, "none", other), (cite,)),
            Stimulus(f"{p}.key{lv}.spr", SID_SA, f"{p}/key-suppress",
                     f"Send the key for the last seed seen, level {lvl.level:#x}, suppress bit",
                     _key_builder(lvl, "none", other, suppress=True), (cite, SEC_SUPPRESS)),
            Stimulus(f"{p}.key{lv}.badfirst", SID_SA, f"{p}/key-wrong",
                     f"Key with a wrong first byte, level {lvl.level:#x}",
                     _key_builder(lvl, "first", other), (cite,)),
            Stimulus(f"{p}.key{lv}.badmid", SID_SA, f"{p}/key-wrong",
                     f"Key with a wrong middle byte, level {lvl.level:#x}",
                     _key_builder(lvl, "middle", other), (cite,)),
            Stimulus(f"{p}.key{lv}.badlast", SID_SA, f"{p}/key-wrong",
                     f"Key with a wrong last byte, level {lvl.level:#x}",
                     _key_builder(lvl, "last", other), (cite,)),
            Stimulus(f"{p}.key{lv}.badlast.spr", SID_SA, f"{p}/key-wrong-suppress",
                     f"Key with a wrong last byte, level {lvl.level:#x}, suppress bit",
                     _key_builder(lvl, "last", other, suppress=True), (cite, SEC_SUPPRESS)),
            Stimulus(f"{p}.key{lv}.stale", SID_SA, f"{p}/key-stale",
                     f"Key for the previous (replaced or consumed) seed, level {lvl.level:#x}",
                     _key_builder(lvl, "stale", other), (cite,)),
            Stimulus(f"{p}.key{lv}.short", SID_SA, f"{p}/key-length",
                     f"Key one byte short, level {lvl.level:#x}", _key_builder(lvl, "short", other),
                     (cite, SEC_ORDER)),
            Stimulus(f"{p}.key{lv}.long", SID_SA, f"{p}/key-length",
                     f"Key one byte long, level {lvl.level:#x}", _key_builder(lvl, "long", other),
                     (cite, SEC_ORDER)),
        ]
        if other is not None:
            out.append(Stimulus(f"{p}.key{lv}.otherlevel", SID_SA, f"{p}/key-wrong",
                                f"Key computed with level {other.level:#x}'s algorithm, sent for "
                                f"level {lvl.level:#x}", _key_builder(lvl, "other_level", other),
                                (cite,)))
    used = {s for lvl in levels for s in (lvl.seed_subfunction, lvl.key_subfunction)}
    bad = _first_missing(used)
    out += [
        Stimulus(f"{p}.trunc", SID_SA, f"{p}/truncated", "SecurityAccess without a subfunction",
                 _const(bytes([SID_SA])), (cite, SEC_ORDER)),
        Stimulus(f"{p}.badsub", SID_SA, f"{p}/unsupported-subfunction",
                 f"SecurityAccess unsupported subfunction {bad:#x}", _const(bytes([SID_SA, bad])),
                 (cite, SEC_ORDER)),
        Stimulus(f"{p}.badsub.spr", SID_SA, f"{p}/unsupported-subfunction-suppress",
                 f"SecurityAccess unsupported subfunction {bad:#x}, suppress bit",
                 _const(bytes([SID_SA, bad | SUPPRESS_POS_RESP_BIT])), (cite, SEC_SUPPRESS)),
    ]
    return out


def _routine_stimuli(spec: EcuSpec) -> list[Stimulus]:
    cite = _SEC[SID_RC]
    p = _hx(SID_RC)
    out: list[Stimulus] = []
    known_types = {RC_START, RC_STOP, RC_RESULTS}
    bad_type = _first_missing(known_types)
    names = {RC_START: "start", RC_STOP: "stop", RC_RESULTS: "results"}

    def rc(sub: int, r: RoutineDef | None, rid: int, extra: int = 0, cut: int = 0) -> bytes:
        option = bytes(r.option_record_length) if (r is not None and sub == RC_START) else b""
        raw = routine_control(sub, rid, option).to_bytes()
        return _with(raw, extra=extra, cut=cut)

    for r in spec.routines:
        tag = _hx(r.id, 4)
        for sub in (RC_START, RC_STOP, RC_RESULTS):
            name = names[sub]
            if sub not in r.allowed_subfunctions:
                out.append(Stimulus(f"{p}.{tag}.{name}.na", SID_RC, f"{p}/type-not-for-routine",
                                    f"Routine {r.id:#06x} {name}, not supported by this routine",
                                    _const(rc(sub, r, r.id)), (cite,)))
                continue
            raw = rc(sub, r, r.id)
            out += [
                Stimulus(f"{p}.{tag}.{name}", SID_RC, f"{p}/{name}", f"Routine {r.id:#06x} {name}",
                         _const(raw), (cite,)),
                Stimulus(f"{p}.{tag}.{name}.spr", SID_RC, f"{p}/{name}-suppress",
                         f"Routine {r.id:#06x} {name}, suppress bit", _const(_spr(raw)),
                         (cite, SEC_SUPPRESS)),
                Stimulus(f"{p}.{tag}.{name}.long", SID_RC, f"{p}/length",
                         f"Routine {r.id:#06x} {name} plus one trailing byte",
                         _const(rc(sub, r, r.id, extra=1)), (cite, SEC_ORDER)),
            ]
            if sub == RC_START and r.option_record_length > 0:
                out.append(Stimulus(f"{p}.{tag}.{name}.short", SID_RC, f"{p}/length",
                                    f"Routine {r.id:#06x} start, option record one byte short",
                                    _const(rc(sub, r, r.id, cut=1)), (cite, SEC_ORDER)))
        out.append(Stimulus(f"{p}.{tag}.badtype", SID_RC, f"{p}/unsupported-type",
                            f"Routine {r.id:#06x} unsupported control type {bad_type:#x}",
                            _const(rc(bad_type, None, r.id)), (cite, SEC_ORDER)))
    unknown = _unknown_identifier(spec)
    for sub in (RC_START, RC_STOP, RC_RESULTS, bad_type):
        name = names.get(sub, "badtype")
        out.append(Stimulus(f"{p}.unknown.{name}", SID_RC, f"{p}/unknown-routine",
                            f"Routine {unknown:#06x} (not in the spec) {name}",
                            _const(rc(sub, None, unknown)), (cite, SEC_ORDER)))
    if spec.routines:
        first = rc(RC_START, None, spec.routines[0].id)
        out.append(Stimulus(f"{p}.trunc", SID_RC, f"{p}/truncated",
                            "RoutineControl with half a routine identifier", _const(first[:3]),
                            (cite, SEC_ORDER)))
    return out


def _other_stimuli(spec: EcuSpec) -> list[Stimulus]:
    supported = _spec_services(spec)
    out = [Stimulus("empty", None, "empty", "Empty request (no bytes)", _const(b""), (SEC_BEFORE,))]
    for sid in [s for s in _STANDARD_SIDS if s not in supported][:_UNSUPPORTED_SID_STIMULI]:
        out.append(Stimulus(f"sid{_hx(sid)}", sid, "unsupported-service",
                            f"Service {sid:#04x} that the spec does not list",
                            _const(bytes([sid, 0x01])), (SEC_ORDER,)))
    return out


_SERVICE_STIMULI: dict[int, Callable[[EcuSpec], list[Stimulus]]] = {
    SID_SC: _session_stimuli,
    SID_ER: _reset_stimuli,
    SID_CDTC: _clear_dtc_stimuli,
    SID_RDTC: _read_dtc_stimuli,
    SID_RDBI: _read_did_stimuli,
    SID_SA: _security_stimuli,
    SID_WDBI: _write_did_stimuli,
    SID_RC: _routine_stimuli,
    SID_TP: _tester_present_stimuli,
}


def stimulus_catalog(spec: EcuSpec) -> list[Stimulus]:
    """Every stimulus, enumerated from the spec, for every service the spec lists."""
    out: list[Stimulus] = []
    services = _spec_services(spec)
    for sid, fn in _SERVICE_STIMULI.items():
        if sid in services:
            out += fn(spec)
    out += _other_stimuli(spec)
    ids = [s.id for s in out]
    assert len(ids) == len(set(ids)), "stimulus ids must be unique"
    return out


# ----------------------------------------------------------------------------------- probes


def _apply_probes(b: _ConfBuilder) -> None:
    """The fixed generic probe set ``state_v1`` (observation only; no requirement-specific step).

    1. read every spec DID in one request (session DID, stored values, readability);
    2. requestResults for every routine that supports it (routine state);
    3. a seed request per security level (security state, lockout state, seed counter);
    4. silence past the longest S3, then 5. the all-DID read again (time-dependent state,
       retention across the S3 fall-back);
    6. ReadDTCInformation with an all-bits mask in that default session (fault memory).
    """
    spec = b.spec
    all_dids = [d.id for d in spec.dids]
    if all_dids:
        b.send(read_did(*all_dids), "Probe: read every DID (session, values, readability).")
    for r in spec.routines:
        if RC_RESULTS in r.allowed_subfunctions:
            b.send(routine_control(RC_RESULTS, r.id), f"Probe: routine {r.id:#06x} results (state).")
    for lvl in spec.security_levels:
        b.send(security_request_seed(lvl.seed_subfunction),
               f"Probe: seed request level {lvl.level:#x} (security / lockout state).")
    b.advance(_max_s3(spec) + 1, "Probe: stay silent past S3.")
    if all_dids:
        b.send(read_did(*all_dids), "Probe: read every DID after the S3 fall-back.")
    if spec.dtcs and SID_RDTC in _spec_services(spec):
        b.send(read_dtc_by_status_mask(0xFF), "Probe: report every DTC with any status bit set.")


# ------------------------------------------------------------------------------ the template


class ConformanceParams(BaseModel):
    """Everything needed to re-instantiate one conformance test."""

    setup: str
    stimulus: str
    probes: str = PROBE_SET_ID


@dataclass
class _Catalogs:
    setups: dict[str, Setup]
    stimuli: dict[str, Stimulus]


def _catalogs(spec: EcuSpec) -> _Catalogs:
    return _Catalogs({s.id: s for s in setup_catalog(spec)},
                     {s.id: s for s in stimulus_catalog(spec)})


def _run_setup(b: _ConfBuilder, setup: Setup) -> None:
    for act in setup.actions:
        _ACTIONS[act.kind](b, *act.args)


def _response_class(responses: list[bytes]) -> str:
    """Coarse oracle outcome: none / pos / nrc:XX / pend+pos ..."""
    if not responses:
        return "none"
    parts = []
    for r in responses:
        if len(r) >= 3 and r[0] == NEGATIVE_RESPONSE_SID:
            parts.append(f"nrc:{r[2]:02x}")
        else:
            parts.append("pos")
    return "+".join(parts)


def _category(setup: Setup, stim: Stimulus, responses: list[bytes]) -> str:
    if any(a.kind in _TIME_ACTIONS for a in setup.actions):
        return "timing"
    if stim.sid == SID_SA:
        return "security"
    if stim.sid in (SID_SC, SID_ER):
        return "session"
    if any(len(r) >= 3 and r[0] == NEGATIVE_RESPONSE_SID and r[2] != 0x78 for r in responses):
        return "negative"
    return "positive"


def case_id_for(setup_id: str, stimulus_id: str) -> str:
    """Deterministic test id of the conformance case (setup, stimulus)."""
    raw = f"conf_{setup_id}__{stimulus_id}"
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", raw)


def _instantiate_with(spec: EcuSpec, cats: _Catalogs, p: ConformanceParams) -> TestCase:
    if p.probes != PROBE_SET_ID:
        raise ValueError(f"unknown probe set {p.probes!r}")
    setup = cats.setups[p.setup]
    stim = cats.stimuli[p.stimulus]
    b = _ConfBuilder(spec)
    _run_setup(b, setup)
    raw = stim.build(b)
    result = b.send_raw(raw, f"Stimulus: {stim.description}.")
    _apply_probes(b)
    cites = [Citation(source="behaviour_contract", ref=ref)
             for ref in dict.fromkeys((*stim.citations, SEC_POWER_ON))]
    return TestCase(
        id=case_id_for(setup.id, stim.id),
        title=f"Conformance: {stim.description} [{setup.description}]",
        category=_category(setup, stim, result.responses),  # type: ignore[arg-type]
        template_id=CONFORMANCE_TEMPLATE_ID,
        parameters=p.model_dump(),
        steps=b.steps,
        citations=cites,
        explanation=(
            f"Requirement-independent conformance case: setup '{setup.id}' ({setup.dimension}), "
            f"stimulus '{stim.id}' ({stim.klass}), then the fixed probe set '{p.probes}'. "
            "Every expected response comes from the rules engine."
        ),
        origin="generated",
    )


def conformance_instantiate(spec: EcuSpec, p: ConformanceParams) -> TestCase:
    """Re-build one conformance test from its parameters (used by byte provenance)."""
    return _instantiate_with(spec, _catalogs(spec), p)


# -------------------------------------------------------------------------------- selection


def _abstract_state(spec: EcuSpec, st: EcuState, now: int) -> tuple[Any, ...]:
    """Oracle-observable state abstraction used by the covering items."""
    lock = tuple(sorted((lvl, ls.failed_attempts, ls.locked_until_ms is not None
                         and now < ls.locked_until_ms) for lvl, ls in st.lockouts.items()))
    routines = tuple(sorted((rid, int(s)) for rid, s in st.routine_status.items()))
    return (st.active_session, st.unlocked_level, tuple(sorted(st.pending_seeds)), lock, routines,
            not st.environment.vehicle_stationary, st.environment.nvm_write_fault)


def _time_class(spec: EcuSpec, st: EcuState, now: int) -> str:
    if st.last_request_ms is None:
        return "idle"
    sess = spec.get_session(st.active_session)
    s3 = sess.timing.s3_ms if sess is not None else 0
    gap = now - st.last_request_ms
    return "lt" if gap < s3 else ("eq" if gap == s3 else "gt")


@dataclass
class SelectionResult:
    """The selected cases plus the statistics of the reduction."""

    params: list[ConformanceParams]
    stats: dict[str, Any]


N_PHASES = 4
SELECTION_METHOD = (
    "Deterministic lazy-greedy set cover over oracle-observable items, in priority phases; each "
    "phase adds tests until its items are covered or the cap is reached, ties broken by "
    "catalog order (setup, then stimulus). Phase 1: every (stimulus, response class) the "
    "oracle can produce for it over all setups, and every (setup, service family) pair for "
    "the spec's services. Phase 2: transition tuples (session, unlocked level, active "
    "lockouts, time since last request vs S3, stimulus class, response class) and state "
    "effects (stimulus class, response class, which abstract state components changed and "
    "how). Phase 3: (stimulus, active session, response class). Phase 4: fine transitions "
    "(full abstract pre-state, stimulus class, response class, full abstract post-state)."
)

_STATE_COMPONENTS = ("session","unlocked", "pending_seeds", "lockout", "routines", "moving", "nvm")


def _candidate_items(
    spec: EcuSpec, setup: Setup, b: _ConfBuilder, stim: Stimulus, services: set[int],
) -> list[frozenset[tuple[Any, ...]]]:
    """Covering items per phase observed by the oracle for one (setup, stimulus)."""
    pre = b.rs.state
    now = b.rs.now_ms
    raw = stim.build(b)
    result = evaluate(spec, pre, raw, now)
    resp = _response_class(result.responses)
    pre_abs = _abstract_state(spec, pre, now)
    post_abs = _abstract_state(spec, result.next_state, now)
    delta = tuple((name, a, z) for name, a, z in zip(_STATE_COMPONENTS, pre_abs, post_abs,
                                                      strict=True) if a != z)
    lock_active = tuple(lvl for lvl, _count, active in pre_abs[3] if active)
    phase1 = {("stim_resp", stim.id, resp)}
    if stim.sid in services:
        phase1.add(("pair", setup.id, stim.family))
    phase2 = {
        ("transition", pre.active_session, pre.unlocked_level, lock_active,
         _time_class(spec, pre, now), stim.klass, resp),
        ("effect", stim.klass, resp, delta),
    }
    phase3 = {("stim_session", stim.id, pre.active_session, resp)}
    phase4 = {("fine_transition", pre_abs, stim.klass, resp, post_abs)}
    return [frozenset(phase1), frozenset(phase2), frozenset(phase3), frozenset(phase4)]


def _lazy_greedy(
    items: list[frozenset[tuple[Any, ...]]], covered: set[tuple[Any, ...]], chosen: list[int],
    taken: set[int], cap: int,
) -> None:
    """Deterministic lazy greedy set cover: max new items, ties -> lowest candidate index."""
    heap = [(-len(it - covered), i) for i, it in enumerate(items) if i not in taken]
    heapq.heapify(heap)
    while heap and len(chosen) < cap:
        neg, i = heapq.heappop(heap)
        gain = len(items[i] - covered)
        if gain == 0:
            continue
        if -neg != gain:
            heapq.heappush(heap, (-gain, i))
            continue
        chosen.append(i)
        taken.add(i)
        covered |= items[i]


def select_cases(spec: EcuSpec, cap: int = MAX_SUITE_SIZE) -> SelectionResult:
    """Deterministic reduction of setups x stimuli to at most ``cap`` cases.

    Every (setup, stimulus) candidate is evaluated with the oracle (setup run once, stimulus
    evaluated purely from the setup's end state); see :data:`SELECTION_METHOD` for the
    covering phases.
    """
    cats = _catalogs(spec)
    setups = list(cats.setups.values())
    stimuli = list(cats.stimuli.values())
    services = _spec_services(spec)
    pairs: list[tuple[int, int]] = []
    phases: list[list[frozenset[tuple[Any, ...]]]] = [[] for _ in range(N_PHASES)]
    for si, setup in enumerate(setups):
        b = _ConfBuilder(spec)
        _run_setup(b, setup)
        for ti, stim in enumerate(stimuli):
            items = _candidate_items(spec, setup, b, stim, services)
            pairs.append((si, ti))
            for k in range(N_PHASES):
                phases[k].append(items[k])
    chosen: list[int] = []
    taken: set[int] = set()
    phase_stats: list[dict[str, Any]] = []
    for k in range(N_PHASES):
        covered: set[tuple[Any, ...]] = set().union(*(phases[k][i] for i in chosen))
        before = len(chosen)
        _lazy_greedy(phases[k], covered, chosen, taken, cap)
        universe: set[tuple[Any, ...]] = set().union(*phases[k])
        phase_stats.append({"phase": k + 1, "items": len(universe), "covered": len(covered),
                            "added_tests": len(chosen) - before,
                            "kinds": sorted({x[0] for x in universe})})
    order = sorted(chosen, key=lambda i: pairs[i])
    params = [ConformanceParams(setup=setups[pairs[i][0]].id, stimulus=stimuli[pairs[i][1]].id)
              for i in order]

    stats = {
        "setups": len(setups),
        "stimuli": len(stimuli),
        "candidates": len(pairs),
        "selected": len(params),
        "cap": cap,
        "phases": phase_stats,
        "setup_dimensions": dict(sorted(Counter(s.dimension for s in setups).items())),
        "stimulus_families": dict(sorted(Counter(s.family for s in stimuli).items())),
        "selected_by_family": dict(sorted(Counter(
            stimuli[pairs[i][1]].family for i in chosen).items())),
        "selected_by_setup_dimension": dict(sorted(Counter(
            setups[pairs[i][0]].dimension for i in chosen).items())),
        "method": SELECTION_METHOD,
    }
    return SelectionResult(params=params, stats=stats)


def conformance_applicable(spec: EcuSpec) -> list[ConformanceParams]:
    """The selected parameter list (the conformance suite, in its deterministic order)."""
    return select_cases(spec).params


@dataclass
class ConformanceSuite:
    """The generated suite plus generation statistics."""

    tests: list[TestCase]
    stats: dict[str, Any]


def build_conformance_suite(spec: EcuSpec, cap: int = MAX_SUITE_SIZE) -> ConformanceSuite:
    """Generate the suite and its statistics (selection, timings, family counts)."""
    t0 = time.perf_counter()
    sel = select_cases(spec, cap)
    t1 = time.perf_counter()
    cats = _catalogs(spec)
    tests: list[TestCase] = []
    for p in sel.params:
        test = _instantiate_with(spec, cats, p)
        report = validate_test(spec, test)
        if not report.ok:  # pragma: no cover - the oracle built every byte
            raise AssertionError(f"{test.id}: {report.mismatches}")
        tests.append(test.model_copy(update={"review_status": "validated"}))
    t2 = time.perf_counter()
    stats = {
        **sel.stats,
        "tests": len(tests),
        "steps": sum(len(t.steps) for t in tests),
        "categories": dict(sorted(Counter(t.category for t in tests).items())),
        "selection_s": round(t1 - t0, 3),
        "instantiation_s": round(t2 - t1, 3),
        "generation_s": round(t2 - t0, 3),
        "probe_set": PROBE_SET_ID,
        "template_id": CONFORMANCE_TEMPLATE_ID,
    }
    return ConformanceSuite(tests=tests, stats=stats)


def generate_conformance_suite(spec: EcuSpec) -> list[TestCase]:
    """The requirement-independent conformance suite for ``spec`` (deterministic, capped)."""
    return build_conformance_suite(spec).tests


CONFORMANCE_TEMPLATE = Template(
    CONFORMANCE_TEMPLATE_ID,
    "Requirement-independent conformance case: spec-derived setup, one (mutated) stimulus, "
    "fixed state probes; every expected response from the rules engine.",
    "negative",
    sorted(_SERVICE_STIMULI),
    ConformanceParams,
    conformance_instantiate,  # type: ignore[arg-type]
    conformance_applicable,  # type: ignore[arg-type]
)

CONFORMANCE_TEMPLATES: dict[str, Template] = {CONFORMANCE_TEMPLATE_ID: CONFORMANCE_TEMPLATE}
"""Templates that are NOT offered to the planner (kept out of ``TEMPLATES`` on purpose)."""


def resolve_template(template_id: str | None) -> Template | None:
    """Look a template id up in the planner registry, then in the conformance registry."""
    if template_id is None:
        return None
    return TEMPLATES.get(template_id) or CONFORMANCE_TEMPLATES.get(template_id)
