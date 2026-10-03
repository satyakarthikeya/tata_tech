"""Per-service request handlers for the simulated ECU.

Implemented from ``docs/behaviour_contract.md`` only. Each service is a small
handler class that knows its own length rules, its subfunctions and its
service-specific checks; negative outcomes are raised as :class:`Reject`
exceptions and caught by the ECU's dispatcher. Bug hooks are explicit
``ctx.bug(...)`` checks next to the behaviour they corrupt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from uds_assistant.protocol.security import compute_key, derive_seed
from uds_assistant.simulator import bugs as B
from uds_assistant.simulator.memory import (
    DEFAULT_SESSION,
    ROUTINE_COMPLETED,
    ROUTINE_NEVER_STARTED,
    ROUTINE_RUNNING,
    ROUTINE_STOPPED,
    EcuMemory,
    LevelLockout,
    dtc_number,
)
from uds_assistant.spec.schema import DidDef, EcuSpec, RoutineDef, SecurityLevelDef

# NRC byte values (wire values; named locally to keep the simulator self-contained).
NRC_GENERAL_REJECT = 0x10
NRC_SERVICE_NOT_SUPPORTED = 0x11
NRC_SUBFUNCTION_NOT_SUPPORTED = 0x12
NRC_BAD_LENGTH = 0x13
NRC_RESPONSE_TOO_LONG = 0x14
NRC_CONDITIONS = 0x22
NRC_SEQUENCE = 0x24
NRC_OUT_OF_RANGE = 0x31
NRC_SECURITY_DENIED = 0x33
NRC_INVALID_KEY = 0x35
NRC_ATTEMPTS_EXCEEDED = 0x36
NRC_DELAY_ACTIVE = 0x37
NRC_NVM_FAILURE = 0x72
NRC_PENDING = 0x78
NRC_SUBFUNCTION_WRONG_SESSION = 0x7E
NRC_SERVICE_WRONG_SESSION = 0x7F

LIVE_SESSION_DID = 0xF186
LIVE_SPEED_DID = 0x0140


class Reject(Exception):
    """Raised by a handler to answer with a negative response."""

    def __init__(self, nrc: int) -> None:
        super().__init__(f"NRC {nrc:#04x}")
        self.nrc = nrc


@dataclass
class Outcome:
    """A positive outcome: the frames to send and whether suppression may drop them."""

    frames: list[bytes] = field(default_factory=list)
    suppressible: bool = True


class EcuContext(Protocol):
    """What a handler may see of the ECU."""

    spec: EcuSpec
    mem: EcuMemory
    now_ms: int

    def bug(self, bug_id: str) -> bool:
        """True if ``bug_id`` is currently injected."""
        ...


def condition_met(ctx: EcuContext, name: str) -> bool:
    """Evaluate one named precondition; unknown names are never met."""
    if name == "vehicle_stationary":
        return ctx.mem.vehicle_speed_kph == 0
    return False


def conditions_ok(ctx: EcuContext, names: list[str]) -> bool:
    """True if every condition holds (or the condition bug is injected)."""
    if ctx.bug(B.CONDITION_IGNORED):
        return True
    return all(condition_met(ctx, n) for n in names)


class ServiceHandler:
    """Base class: one UDS service."""

    sid: int = 0
    uses_subfunction: bool = False
    suppress_bit: bool = False
    #: Whether the generic "subfunction supported -> 0x12" gate applies (not for 0x31).
    generic_subfunction_gate: bool = True

    def length_ok(self, req: bytes) -> bool:
        """Generic length rule (contract step 3)."""
        return True

    def subfunctions(self, ctx: EcuContext) -> set[int]:
        """Supported subfunction values (contract step 4)."""
        return set()

    def check_subfunction_session(self, ctx: EcuContext, sub: int) -> None:
        """Contract step 5 (0x7E); only SecurityAccess overrides it."""

    def subfunction_length_ok(self, ctx: EcuContext, sub: int, req: bytes) -> bool:
        """Contract step 5b."""
        return True

    def execute(self, ctx: EcuContext, req: bytes, sub: int | None) -> Outcome:
        """Service-specific checks and the positive result."""
        raise NotImplementedError

    def positive_sid(self) -> int:
        """Positive response SID."""
        return (self.sid + 0x40) & 0xFF


class SessionControl(ServiceHandler):
    """0x10 DiagnosticSessionControl."""

    sid = 0x10
    uses_subfunction = True
    suppress_bit = True

    def length_ok(self, req: bytes) -> bool:
        return len(req) == 2

    def subfunctions(self, ctx: EcuContext) -> set[int]:
        return {s.id for s in ctx.spec.sessions}

    def execute(self, ctx: EcuContext, req: bytes, sub: int | None) -> Outcome:
        assert sub is not None
        target = ctx.spec.get_session(sub)
        assert target is not None
        kept_routines = dict(ctx.mem.routine_status)
        kept_seeds = dict(ctx.mem.pending_seeds)
        keep_security = ctx.bug(B.SECURITY_NOT_RESET_ON_SESSION_CHANGE) or (
            ctx.bug(B.SESSION_REENTRY_KEEPS_UNLOCK) and sub == ctx.mem.session
        )
        ctx.mem.drop_volatile(sub, keep_security=keep_security)
        if ctx.bug(B.ROUTINE_STATE_SURVIVES_SESSION_CHANGE):
            ctx.mem.routine_status.update(kept_routines)
        if ctx.bug(B.SESSION_SWITCH_KEEPS_PENDING_SEED):
            ctx.mem.pending_seeds.update(kept_seeds)
        frame = bytes([self.positive_sid(), sub])
        if not ctx.bug(B.SESSION_RESPONSE_MISSING_TIMING):
            p2 = target.timing.p2_ms & 0xFFFF
            star_ms = target.timing.p2_star_ms
            p2_star = (star_ms if ctx.bug(B.SESSION_RESPONSE_P2_STAR_IN_MS) else star_ms // 10)
            p2_star &= 0xFFFF
            frame += p2.to_bytes(2, "big") + p2_star.to_bytes(2, "big")
        return Outcome([frame])


class EcuReset(ServiceHandler):
    """0x11 ECUReset."""

    sid = 0x11
    uses_subfunction = True
    suppress_bit = True

    def length_ok(self, req: bytes) -> bool:
        return len(req) == 2

    def subfunctions(self, ctx: EcuContext) -> set[int]:
        return set(ctx.spec.ecu_reset.supported_subfunctions)

    def execute(self, ctx: EcuContext, req: bytes, sub: int | None) -> Outcome:
        assert sub is not None
        ctx.mem.drop_volatile(
            ctx.mem.session if ctx.bug(B.ECU_RESET_KEEPS_SESSION) else DEFAULT_SESSION
        )
        if ctx.bug(B.ECU_RESET_RESETS_SEED_COUNTER):
            ctx.mem.seed_counter = 0
        if ctx.bug(B.ECU_RESET_CLEARS_SECURITY_LOCKOUT):
            for level in ctx.mem.lockouts:
                ctx.mem.lockouts[level] = LevelLockout()
        return Outcome([bytes([self.positive_sid(), sub])])


class ClearDtc(ServiceHandler):
    """0x14 ClearDiagnosticInformation."""

    sid = 0x14

    def length_ok(self, req: bytes) -> bool:
        return len(req) == 4

    def execute(self, ctx: EcuContext, req: bytes, sub: int | None) -> Outcome:
        group = int.from_bytes(req[1:4], "big")
        statuses = ctx.mem.dtc_status
        if ctx.bug(B.NRC_ORDER_NVM_FAULT_BEFORE_GROUP_CHECK) and ctx.mem.nvm_write_fault:
            raise Reject(NRC_NVM_FAILURE)
        if group == 0xFFFFFF or ctx.bug(B.DTC_CLEAR_IGNORES_GROUP):
            targets = list(statuses)
        elif group in statuses:
            targets = [group]
        else:
            raise Reject(NRC_OUT_OF_RANGE)
        if ctx.mem.nvm_write_fault:
            raise Reject(NRC_NVM_FAILURE)
        if ctx.bug(B.DTC_CLEAR_SINGLE_CLEARS_NEIGHBOUR) and group != 0xFFFFFF:
            order = [dtc_number(d.code) for d in ctx.spec.dtcs]
            index = order.index(targets[0])
            targets = order[index : index + 2]
        if not ctx.bug(B.DTC_CLEAR_NOOP):
            for code in targets:
                statuses[code] = 0x00
        return Outcome([bytes([self.positive_sid()])])


class ReadDtcInfo(ServiceHandler):
    """0x19 ReadDTCInformation (only subfunction 0x02, report by status mask)."""

    sid = 0x19
    uses_subfunction = True
    suppress_bit = True

    def length_ok(self, req: bytes) -> bool:
        return len(req) >= 2

    def subfunctions(self, ctx: EcuContext) -> set[int]:
        return set(ctx.spec.read_dtc_supported_subfunctions)

    def subfunction_length_ok(self, ctx: EcuContext, sub: int, req: bytes) -> bool:
        if sub == 0x02 and ctx.bug(B.READ_DTC_TRAILING_BYTES_ACCEPTED):
            return len(req) >= 3
        return len(req) == 3 if sub == 0x02 else True

    def execute(self, ctx: EcuContext, req: bytes, sub: int | None) -> Outcome:
        mask = req[2]
        avail = ctx.spec.dtc_status_availability_mask
        body = bytearray([self.positive_sid(), 0x02, avail])
        for dtc in ctx.spec.dtcs:
            number = dtc_number(dtc.code)
            status = ctx.mem.dtc_status[number]
            if status & mask or ctx.bug(B.DTC_READ_IGNORES_MASK):
                masked = ctx.bug(B.DTC_READ_REPORTS_MASKED_STATUS)
                body += number.to_bytes(3, "big") + bytes([status & (mask if masked else avail)])
        if len(body) > ctx.spec.max_response_length:
            raise Reject(NRC_RESPONSE_TOO_LONG)
        return Outcome([bytes(body)])


class ReadDataById(ServiceHandler):
    """0x22 ReadDataByIdentifier (one or more DIDs)."""

    sid = 0x22

    def length_ok(self, req: bytes) -> bool:
        return len(req) >= 3 and (len(req) - 1) % 2 == 0

    @staticmethod
    def did_value(ctx: EcuContext, did: DidDef) -> bytes:
        """Current value of ``did`` (two DIDs are computed live)."""
        if did.id == LIVE_SESSION_DID:
            return bytes([ctx.mem.session & 0xFF])
        if did.id == LIVE_SPEED_DID:
            speed = ctx.mem.vehicle_speed_kph
            wrapped = ctx.bug(B.READ_DID_SPEED_NOT_CLAMPED)
            return bytes([speed & 0xFF if wrapped else min(speed, 255)])
        return ctx.mem.did_store[did.id]

    def execute(self, ctx: EcuContext, req: bytes, sub: int | None) -> Outcome:
        requested = [int.from_bytes(req[i : i + 2], "big") for i in range(1, len(req), 2)]
        known: list[DidDef] = []
        defs: list[DidDef] = []
        for did_id in requested:
            did = ctx.spec.get_did(did_id)
            if did is None:
                continue
            known.append(did)
            if ctx.mem.session in did.read_sessions or ctx.bug(
                B.READ_DID_SESSION_RESTRICTION_IGNORED
            ):
                defs.append(did)
        if ctx.bug(B.MULTI_DID_READ_DEDUPS_REPEATS):
            defs = list({d.id: d for d in defs}.values())
        if not known or not defs:
            raise Reject(NRC_OUT_OF_RANGE)
        size = 1 + sum(2 + d.length for d in defs)
        if size > ctx.spec.max_response_length:
            raise Reject(NRC_RESPONSE_TOO_LONG)
        if ctx.bug(B.MULTI_DID_READ_FIRST_ONLY):
            defs = defs[:1]
        body = bytearray([self.positive_sid()])
        for did in defs:
            body += did.id.to_bytes(2, "big") + self.did_value(ctx, did)
        return Outcome([bytes(body)])


class SecurityAccess(ServiceHandler):
    """0x27 SecurityAccess (seed/key per level, lockout)."""

    sid = 0x27
    uses_subfunction = True
    suppress_bit = True

    def length_ok(self, req: bytes) -> bool:
        return len(req) >= 2

    @staticmethod
    def level_for(ctx: EcuContext, sub: int) -> tuple[SecurityLevelDef, bool]:
        """Return (level definition, is_seed_request) for a supported subfunction."""
        for lvl in ctx.spec.security_levels:
            if sub == lvl.seed_subfunction:
                return lvl, True
            if sub == lvl.key_subfunction:
                return lvl, False
        raise Reject(NRC_SUBFUNCTION_NOT_SUPPORTED)  # pragma: no cover - gated earlier

    def subfunctions(self, ctx: EcuContext) -> set[int]:
        subs: set[int] = set()
        for lvl in ctx.spec.security_levels:
            subs.update({lvl.seed_subfunction, lvl.key_subfunction})
        return subs

    def check_subfunction_session(self, ctx: EcuContext, sub: int) -> None:
        lvl, _ = self.level_for(ctx, sub)
        if ctx.mem.session not in lvl.allowed_sessions:
            raise Reject(NRC_SUBFUNCTION_WRONG_SESSION)

    def subfunction_length_ok(self, ctx: EcuContext, sub: int, req: bytes) -> bool:
        lvl, is_seed = self.level_for(ctx, sub)
        return len(req) == (2 if is_seed else 2 + lvl.seed_length)

    def execute(self, ctx: EcuContext, req: bytes, sub: int | None) -> Outcome:
        assert sub is not None
        lvl, is_seed = self.level_for(ctx, sub)
        lock = ctx.mem.lockouts[lvl.level]
        if is_seed:
            delay_active = lock.deadline_ms is not None and (
                ctx.bug(B.LOCKOUT_DELAY_NEVER_EXPIRES) or ctx.now_ms < lock.deadline_ms
            )
            if delay_active and not ctx.bug(B.LOCKOUT_DELAY_IGNORED):
                raise Reject(NRC_DELAY_ACTIVE)
            return self._seed(ctx, lvl, sub, suppressed=bool(req[1] & 0x80))
        return self._key(ctx, lvl, sub, req[2:])

    def _seed(
        self, ctx: EcuContext, lvl: SecurityLevelDef, sub: int, *, suppressed: bool = False
    ) -> Outcome:
        if ctx.mem.unlocked_level == lvl.level and not ctx.bug(B.SEED_RETURNED_WHILE_UNLOCKED):
            return Outcome([bytes([self.positive_sid(), sub]) + bytes(lvl.seed_length)])
        seed = derive_seed(lvl.level, ctx.mem.seed_counter, lvl.seed_length)
        if not ctx.bug(B.STATIC_SEED):
            ctx.mem.seed_counter += 1
        stale_kept = ctx.bug(B.SEED_REQUEST_KEEPS_STALE_PENDING_SEED) and (
            lvl.level in ctx.mem.pending_seeds
        )
        dropped = ctx.bug(B.SUPPRESSED_SEED_REQUEST_NOT_STORED) and suppressed
        if not stale_kept and not dropped:
            ctx.mem.pending_seeds[lvl.level] = seed
        if ctx.bug(B.FAILED_ATTEMPTS_RESET_BY_SEED_REQUEST):
            ctx.mem.lockouts[lvl.level].failures = 0
        return Outcome([bytes([self.positive_sid(), sub]) + seed])

    def _key(self, ctx: EcuContext, lvl: SecurityLevelDef, sub: int, key: bytes) -> Outcome:
        seed = ctx.mem.pending_seeds.get(lvl.level)
        if seed is None:
            raise Reject(NRC_SEQUENCE)
        lock = ctx.mem.lockouts[lvl.level]
        expected = compute_key(seed, lvl.level)
        if ctx.bug(B.KEY_COMPARE_PREFIX_ONLY):
            matches = key[:2] == expected[:2]
        else:
            matches = key == expected
        good = ctx.bug(B.ACCEPTS_ANY_KEY) or matches
        if not good:
            if not ctx.bug(B.FAILED_KEY_KEEPS_PENDING_SEED):
                del ctx.mem.pending_seeds[lvl.level]
            lock.failures += 1
            threshold = lvl.max_attempts + (1 if ctx.bug(B.LOCKOUT_AFTER_EXTRA_ATTEMPT) else 0)
            attempts = lock.failures
            if ctx.bug(B.LOCKOUT_COUNTER_POOLED_ACROSS_LEVELS):
                attempts = sum(item.failures for item in ctx.mem.lockouts.values())
            if attempts >= threshold:
                lock.deadline_ms = ctx.now_ms + lvl.delay_ms
                raise Reject(NRC_ATTEMPTS_EXCEEDED)
            raise Reject(NRC_INVALID_KEY)
        if not ctx.bug(B.SEED_NOT_CONSUMED):
            del ctx.mem.pending_seeds[lvl.level]
        ctx.mem.unlocked_level = lvl.level
        lock.failures = 0
        lock.deadline_ms = None
        return Outcome([bytes([self.positive_sid(), sub])])


class WriteDataById(ServiceHandler):
    """0x2E WriteDataByIdentifier."""

    sid = 0x2E

    def length_ok(self, req: bytes) -> bool:
        return len(req) >= 4

    def execute(self, ctx: EcuContext, req: bytes, sub: int | None) -> Outcome:
        did = ctx.spec.get_did(int.from_bytes(req[1:3], "big"))
        data = req[3:]
        if did is None:
            raise Reject(NRC_OUT_OF_RANGE)
        lax_access = ctx.bug(B.READONLY_DID_WRITABLE) and not did.write_sessions
        if not lax_access:
            if not did.write_sessions:
                raise Reject(NRC_OUT_OF_RANGE)
            if ctx.mem.session not in did.write_sessions:
                raise Reject(NRC_OUT_OF_RANGE)
        if (
            ctx.bug(B.NRC_ORDER_RANGE_BEFORE_SECURITY)
            and did.value_range is not None
            and len(data) == did.length
            and not did.value_range.min <= int.from_bytes(data, "big") <= did.value_range.max
        ):
            raise Reject(NRC_OUT_OF_RANGE)
        security_first = ctx.bug(B.NRC_ORDER_SECURITY_BEFORE_LENGTH)
        if security_first and not lax_access:
            self._security(ctx, did)
        allowed_lengths = {did.length}
        if ctx.bug(B.WRITE_LENGTH_OFF_BY_ONE):
            allowed_lengths.add(did.length + 1)
        if len(data) not in allowed_lengths:
            raise Reject(NRC_BAD_LENGTH)
        if not security_first and not lax_access:
            self._security(ctx, did)
        if (
            ctx.bug(B.NRC_ORDER_WRITE_RANGE_BEFORE_CONDITION)
            and did.value_range is not None
            and not did.value_range.min <= int.from_bytes(data, "big") <= did.value_range.max
        ):
            raise Reject(NRC_OUT_OF_RANGE)
        if not conditions_ok(ctx, did.conditions.requires):
            raise Reject(NRC_CONDITIONS)
        if did.value_range is not None and not ctx.bug(B.WRITE_IGNORES_VALUE_RANGE):
            value = int.from_bytes(data, "big")
            upper_ok = (
                value < did.value_range.max
                if ctx.bug(B.WRITE_RANGE_UPPER_BOUND_EXCLUSIVE)
                else value <= did.value_range.max
            )
            if not (did.value_range.min <= value and upper_ok):
                if ctx.bug(B.WRITE_STORES_VALUE_BEFORE_RANGE_REJECTION):
                    ctx.mem.did_store[did.id] = bytes(data[: did.length])
                raise Reject(NRC_OUT_OF_RANGE)
        if ctx.mem.nvm_write_fault:
            raise Reject(NRC_NVM_FAILURE)
        stored = bytes(data[: did.length])
        if ctx.bug(B.UINT16_DID_STORED_BYTE_SWAPPED) and did.encoding == "uint16":
            stored = stored[::-1]
        ctx.mem.did_store[did.id] = stored
        sid = 0x6F if ctx.bug(B.WRITE_POSITIVE_SID_WRONG) else 0x6E
        return Outcome([bytes([sid]) + did.id.to_bytes(2, "big")])

    @staticmethod
    def _security(ctx: EcuContext, did: DidDef) -> None:
        if ctx.mem.unlocked_level != did.write_security_level:
            raise Reject(NRC_SECURITY_DENIED)


class RoutineControl(ServiceHandler):
    """0x31 RoutineControl (start / stop / requestResults)."""

    sid = 0x31
    uses_subfunction = True
    suppress_bit = True
    generic_subfunction_gate = False

    START, STOP, RESULTS = 0x01, 0x02, 0x03

    def length_ok(self, req: bytes) -> bool:
        return len(req) >= 4

    def execute(self, ctx: EcuContext, req: bytes, sub: int | None) -> Outcome:
        assert sub is not None
        rid = int.from_bytes(req[2:4], "big")
        routine = ctx.spec.get_routine(rid)
        if routine is None or ctx.mem.session not in routine.sessions:
            raise Reject(NRC_OUT_OF_RANGE)
        if sub not in (self.START, self.STOP, self.RESULTS) or (
            sub not in routine.allowed_subfunctions
        ):
            raise Reject(
                NRC_GENERAL_REJECT
                if ctx.bug(B.GENERAL_REJECT_INSTEAD_OF_0X12)
                else NRC_SUBFUNCTION_NOT_SUPPORTED
            )
        expected_len = 4 + routine.option_record_length if sub == self.START else 4
        overlong_ok = (
            ctx.bug(B.ROUTINE_OPTION_RECORD_OVERLONG_ACCEPTED)
            and sub == self.START
            and len(req) > expected_len
        ) or (
            ctx.bug(B.ROUTINE_RESULTS_TRAILING_BYTES_ACCEPTED)
            and sub == self.RESULTS
            and len(req) > expected_len
        )
        if len(req) != expected_len and not overlong_ok:
            raise Reject(NRC_BAD_LENGTH)
        conditions_first = ctx.bug(B.NRC_ORDER_CONDITION_BEFORE_SECURITY) and sub == self.START
        if conditions_first and not conditions_ok(ctx, routine.conditions.requires):
            raise Reject(NRC_CONDITIONS)
        if routine.security_level is not None and ctx.mem.unlocked_level != routine.security_level:
            raise Reject(NRC_SECURITY_DENIED)
        if sub == self.START and not conditions_ok(ctx, routine.conditions.requires):
            raise Reject(NRC_CONDITIONS)
        status = ctx.mem.routine_status.get(rid)
        echo = req[1] if ctx.bug(B.SUPPRESS_BIT_ECHOED_IN_RESPONSE) else sub
        head = bytes([self.positive_sid(), echo]) + rid.to_bytes(2, "big")
        if sub == self.START:
            return self._start(ctx, routine, status, head)
        if sub == self.STOP:
            stop_needs_start = routine.stop_requires_start and not ctx.bug(
                B.ROUTINE_STOP_WITHOUT_START
            )
            if stop_needs_start and status != ROUTINE_RUNNING:
                raise Reject(NRC_SEQUENCE)
            ctx.mem.routine_status[rid] = ROUTINE_STOPPED
            stopped = ctx.bug(B.ROUTINE_STOP_REPORTS_COMPLETED_STATUS)
            shown = ROUTINE_COMPLETED if stopped else ROUTINE_STOPPED
            return Outcome([head + bytes([shown])])
        if status is None and routine.results_requires_start:
            raise Reject(NRC_SEQUENCE)
        reported = ROUTINE_NEVER_STARTED if status is None else status
        return Outcome([head + bytes([reported])])

    def _start(
        self, ctx: EcuContext, routine: RoutineDef, status: int | None, head: bytes
    ) -> Outcome:
        if status == ROUTINE_RUNNING:
            raise Reject(NRC_SEQUENCE)
        if status == ROUTINE_STOPPED and ctx.bug(B.ROUTINE_RESTART_AFTER_STOP_BLOCKED):
            raise Reject(NRC_SEQUENCE)
        if routine.long_running:
            ctx.mem.routine_status[routine.id] = ROUTINE_COMPLETED
            final = head + bytes([ROUTINE_COMPLETED])
            if ctx.bug(B.MISSING_RESPONSE_PENDING):
                return Outcome([final], suppressible=False)
            pending = bytes([0x7F, self.sid, NRC_PENDING])
            return Outcome([pending, final], suppressible=False)
        ctx.mem.routine_status[routine.id] = ROUTINE_RUNNING
        return Outcome([head + bytes([ROUTINE_RUNNING])])


class TesterPresent(ServiceHandler):
    """0x3E TesterPresent."""

    sid = 0x3E
    uses_subfunction = True
    suppress_bit = True

    def length_ok(self, req: bytes) -> bool:
        return len(req) == 2

    def subfunctions(self, ctx: EcuContext) -> set[int]:
        return {0x00}

    def execute(self, ctx: EcuContext, req: bytes, sub: int | None) -> Outcome:
        return Outcome([bytes([self.positive_sid(), 0x00])])


def build_handler_table() -> dict[int, ServiceHandler]:
    """Dispatch table SID -> handler instance."""
    handlers: list[ServiceHandler] = [
        SessionControl(),
        EcuReset(),
        ClearDtc(),
        ReadDtcInfo(),
        ReadDataById(),
        SecurityAccess(),
        WriteDataById(),
        RoutineControl(),
        TesterPresent(),
    ]
    return {h.sid: h for h in handlers}
