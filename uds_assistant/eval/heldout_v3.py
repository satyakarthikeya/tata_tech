"""Static trigger analysis for the 15 held-out v3 bugs (``data/bugs/heldout_v3_catalog.yaml``).

Same idea as :mod:`.heldout_v2`: for each bug a predicate over the static test trace
(:mod:`.trace`) says whether a test applies the stimulus the bug needs to show up AND
observes the response that would differ, plus a short phrase used in the missed-bug reasons
("no test <phrase>" / "N tests <phrase> but none fails").

PROVENANCE: every predicate below was written from the bug descriptions in the v3
catalog and the documented behaviour (``docs/behaviour_contract.md``) ONLY, before any v3
detection result existed (no bug matrix had been run on the v3 catalog and no v3 result had
been looked at), and they do not feed back into test generation. A predicate may only be
edited afterwards to fix a clear bug in the predicate itself; such fixes are logged in
DECISIONS.md. The predicates are necessary, not sufficient: a bug whose stimulus is applied
but whose expected responses do not differ is reported with that reason.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from uds_assistant.eval.heldout import Trigger, heldout_analysis
from uds_assistant.eval.heldout_v2 import _default_session, _level_of
from uds_assistant.eval.trace import SendEvent, TestTrace, request_did_ids
from uds_assistant.rules.state import dtc_code_to_int
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.model import TestCase

CLEAR_ALL_GROUP = 0xFFFFFF
LOCKOUT_NRCS = (0x36,)
SPEED_SATURATION_KPH = 255
SPEED_DID = 0x0140
P2_STAR_FRAME_LEN = 6
"""A positive 0x10 response is ``50 ss`` + 2 bytes P2 + 2 bytes P2*."""
SUBFUNCTION_SERVICES = (0x10, 0x11, 0x19, 0x27, 0x31, 0x3E)


def _suppressed(ev: SendEvent) -> bool:
    """Suppress-positive-response bit set on a service that has a subfunction byte."""
    return ev.sid in SUBFUNCTION_SERVICES and len(ev.request) > 1 and bool(ev.request[1] & 0x80)


def _write_value(ev: SendEvent) -> int:
    return int.from_bytes(ev.request[3:], "big")


def _supported_subfunctions(spec: EcuSpec, sid: int) -> set[int]:
    """Supported 7-bit subfunctions per the contract's step-4 table (0x31 has no such step)."""
    if sid == 0x10:
        return {s.id for s in spec.sessions}
    if sid == 0x11:
        return set(spec.ecu_reset.supported_subfunctions)
    if sid == 0x19:
        return set(spec.read_dtc_supported_subfunctions)
    if sid == 0x27:
        return ({lvl.seed_subfunction for lvl in spec.security_levels}
                | {lvl.key_subfunction for lvl in spec.security_levels})
    if sid == 0x3E:
        return {0x00}
    return set()


def _dtc_timeline(spec: EcuSpec, tr: TestTrace) -> Iterator[tuple[SendEvent, dict[int, int]]]:
    """Each send event with the tracked DTC statuses BEFORE it (set steps and positive 0x14)."""
    status = {dtc_code_to_int(d.code): d.initial_status for d in spec.dtcs}
    pending = sorted(tr.dtc_sets)
    k = 0
    for ev in tr.sends:
        while k < len(pending) and pending[k][0] < ev.index:
            status[pending[k][1]] = pending[k][2]
            k += 1
        yield ev, dict(status)
        if ev.sid == 0x14 and ev.positive and len(ev.request) == 4:
            group = int.from_bytes(ev.request[1:4], "big")
            if group == CLEAR_ALL_GROUP:
                status = {c: 0 for c in status}
            elif group in status:
                status[group] = 0


def _status_report_visible(ev: SendEvent) -> bool:
    """A positive, un-suppressed 19 02 mm whose response frame is observed."""
    return (ev.sid == 0x19 and ev.subfunction == 0x02 and len(ev.request) == 3
            and ev.positive and not _suppressed(ev))


# ----------------------------------------------------------------------------- predicates


def session_switch_with_pending_seed_then_key(spec: EcuSpec, tr: TestTrace) -> bool:
    """A seed is pending, a positive 0x10 follows, then a key for that level is refused 0x24."""
    pending: set[int] = set()
    switched: set[int] = set()
    for ev in tr.sends:
        if ev.s3_expired or (ev.sid == 0x11 and ev.positive):
            pending.clear()
            switched.clear()
        level, kind = _level_of(spec, ev)
        if ev.sid == 0x10 and ev.positive:
            switched |= pending
        elif level is None:
            continue
        elif kind == "seed" and ev.nrc is None and level not in ev.unlocked:
            pending.add(level)
            switched.discard(level)
        elif kind == "key":
            if level in switched and ev.nrc == 0x24:
                return True
            pending.discard(level)
            switched.discard(level)
    return False


def positive_session_response_observed(spec: EcuSpec, tr: TestTrace) -> bool:
    """A positive 0x10 whose response (with the P2 / P2* timing bytes) is actually checked."""
    return any(
        ev.sid == 0x10 and ev.nrc is None
        and any(f and f[0] == 0x50 and len(f) >= P2_STAR_FRAME_LEN for f in ev.frames)
        for ev in tr.sends
    )


def wrong_key_then_second_key_same_seed(spec: EcuSpec, tr: TestTrace) -> bool:
    """A seed, a wrong key, then another key with no new seed in between (refused 0x24)."""
    after_fail: set[int] = set()
    for ev in tr.sends:
        if ev.s3_expired or (ev.sid in (0x10, 0x11) and ev.positive):
            after_fail.clear()
        level, kind = _level_of(spec, ev)
        if level is None:
            continue
        if kind == "seed" and ev.nrc is None:
            after_fail.discard(level)
        elif kind == "key":
            if level in after_fail and ev.nrc == 0x24:
                return True
            if ev.nrc in (0x35, 0x36):
                after_fail.add(level)
            else:
                after_fail.discard(level)
    return False


def lockout_expired_then_wrong_key(spec: EcuSpec, tr: TestTrace) -> bool:
    """A lockout (0x36), the delay runs out, a fresh seed, then a wrong key still gets 0x36."""
    delay = {lvl.level: lvl.delay_ms for lvl in spec.security_levels}
    locked_at: dict[int, int] = {}  # level -> milliseconds elapsed since the lockout was armed
    expired: set[int] = set()
    seeded: set[int] = set()
    for ev in tr.sends:
        for lv in list(locked_at):
            locked_at[lv] += ev.idle_ms
            if locked_at[lv] >= delay.get(lv, 0):
                expired.add(lv)
        level, kind = _level_of(spec, ev)
        if level is None:
            continue
        if kind == "seed" and ev.nrc is None and level in expired and level not in ev.unlocked:
            seeded.add(level)
        elif kind == "key":
            if level in seeded and level in expired and ev.nrc == 0x36:
                return True
            if ev.nrc in LOCKOUT_NRCS:
                locked_at[level] = 0
                expired.discard(level)
                seeded.discard(level)
            elif ev.nrc is None:
                locked_at.pop(level, None)
                expired.discard(level)
                seeded.discard(level)
    return False


def unsupported_subfunction_with_wrong_length(spec: EcuSpec, tr: TestTrace) -> bool:
    """10 / 11 / 3E with an unsupported subfunction AND a wrong total length (answered 0x13)."""
    for ev in tr.sends:
        if (ev.sid in (0x10, 0x11, 0x3E) and len(ev.request) > 2
                and ev.subfunction not in _supported_subfunctions(spec, ev.sid)
                and ev.nrc == 0x13):
            return True
    return False


def out_of_range_write_while_condition_unmet(spec: EcuSpec, tr: TestTrace) -> bool:
    """An out-of-range write to a conditioned DID whose condition fails (expected 0x22)."""
    for ev in tr.sends:
        if ev.sid != 0x2E or len(ev.request) < 4 or ev.nrc != 0x22:
            continue
        did = spec.get_did(request_did_ids(ev.request)[0])
        if (did is not None and did.value_range is not None and did.conditions.requires
                and len(ev.request) - 3 == did.length
                and not did.value_range.min <= _write_value(ev) <= did.value_range.max):
            return True
    return False


def results_request_with_trailing_bytes(spec: EcuSpec, tr: TestTrace) -> bool:
    """31 03 RID with extra bytes after the routine id (expected 0x13)."""
    return any(ev.sid == 0x31 and ev.subfunction == 0x03 and len(ev.request) > 4
               and ev.nrc == 0x13 for ev in tr.sends)


def speed_above_255_then_read(spec: EcuSpec, tr: TestTrace) -> bool:
    """The vehicle speed is above 255 kph and DID 0x0140 is read (answered)."""
    did = spec.get_did(SPEED_DID)
    if did is None:
        return False
    return any(
        ev.sid == 0x22 and ev.nrc is None and ev.vehicle_speed_kph > SPEED_SATURATION_KPH
        and SPEED_DID in request_did_ids(ev.request) and ev.session in did.read_sessions
        for ev in tr.sends
    )


def rejected_write_then_read_back(spec: EcuSpec, tr: TestTrace) -> bool:
    """An out-of-range write refused with 0x31, later a positive read of the same DID."""
    rejected: set[int] = set()
    for ev in tr.sends:
        if ev.sid == 0x2E and len(ev.request) >= 4:
            did = spec.get_did(request_did_ids(ev.request)[0])
            if (did is not None and did.value_range is not None and ev.nrc == 0x31
                    and ev.session in did.write_sessions and len(ev.request) - 3 == did.length
                    and not did.value_range.min <= _write_value(ev) <= did.value_range.max):
                rejected.add(did.id)
        elif ev.sid == 0x22 and ev.nrc is None:
            for did_id in request_did_ids(ev.request):
                did = spec.get_did(did_id)
                if did_id in rejected and did is not None and ev.session in did.read_sessions:
                    return True
    return False


def routine_stop_response_observed(spec: EcuSpec, tr: TestTrace) -> bool:
    """A positive 31 02 RID whose response (ending in the status byte) is observed."""
    return any(ev.sid == 0x31 and ev.subfunction == 0x02 and ev.positive and bool(ev.frames)
               and not _suppressed(ev) for ev in tr.sends)


def clear_one_dtc_next_one_stored_then_read(spec: EcuSpec, tr: TestTrace) -> bool:
    """Clear one DTC while the next DTC in spec order is stored, then read the DTCs back."""
    codes = [dtc_code_to_int(d.code) for d in spec.dtcs]
    armed: set[int] = set()
    for ev, status in _dtc_timeline(spec, tr):
        if ev.sid == 0x14 and ev.positive and len(ev.request) == 4:
            group = int.from_bytes(ev.request[1:4], "big")
            if group in codes and codes.index(group) + 1 < len(codes):
                neighbour = codes[codes.index(group) + 1]
                if status.get(neighbour, 0) != 0:
                    armed.add(neighbour)
        elif _status_report_visible(ev):
            if any(status.get(c, 0) & ev.request[2] for c in armed):
                return True
    return False


def status_with_bits_outside_the_mask(spec: EcuSpec, tr: TestTrace) -> bool:
    """19 02 mm where a listed DTC has status bits that are not in the request mask."""
    avail = spec.dtc_status_availability_mask
    for ev, status in _dtc_timeline(spec, tr):
        if not _status_report_visible(ev):
            continue
        mask = ev.request[2]
        if any(s & mask and (s & avail) & ~mask & 0xFF for s in status.values()):
            return True
    return False


def seed_issued_then_reset_then_seed(spec: EcuSpec, tr: TestTrace) -> bool:
    """A non-zero seed is issued, the ECU is reset, then a seed is requested and observed."""
    issued = 0
    reset_after_seed = False
    for ev in tr.sends:
        level, kind = _level_of(spec, ev)
        if ev.sid == 0x11 and ev.positive and issued:
            reset_after_seed = True
        elif kind == "seed" and ev.nrc is None and level not in ev.unlocked:
            if reset_after_seed and not _suppressed(ev):
                return True
            issued += 1
    return False


def stored_dtc_then_s3_timeout_then_read(spec: EcuSpec, tr: TestTrace) -> bool:
    """A DTC status is non-zero, an S3 timeout drops a session, then the DTCs are read."""
    armed: set[int] = set()
    for ev, status in _dtc_timeline(spec, tr):
        if ev.s3_dropped_session:
            armed = {c for c, s in status.items() if s}
        armed = {c for c in armed if status.get(c, 0)}
        if armed and _status_report_visible(ev) and any(status[c] & ev.request[2] for c in armed):
            return True
    return False


def suppressed_keepalive_exceeds_s3(spec: EcuSpec, tr: TestTrace) -> bool:
    """In a non-default session a suppressed request, then an S3 gap that only exceeds S3 when
    counted from the last request that was answered (the next request still finds the session).
    """
    default = _default_session(spec)
    acc = 0
    suppressed_since = False
    for ev in tr.sends:
        sess = spec.get_session(ev.session)
        s3 = sess.timing.s3_ms if sess is not None else 5000
        acc += ev.idle_ms
        if ev.session == default or ev.s3_expired:
            acc, suppressed_since = 0, False
        elif suppressed_since and acc > s3:
            return True
        if ev.positive and not ev.frames and _suppressed(ev) and ev.session != default:
            suppressed_since = True
        else:
            acc, suppressed_since = 0, False
    return False


HELDOUT_V3_TRIGGERS: dict[str, tuple[str, Trigger]] = {
    "session_switch_keeps_pending_seed": (
        ("requests a seed, switches session with a positive 10 xx, then sends a key for that "
         "level (expected 0x24)"), session_switch_with_pending_seed_then_key),
    "session_response_p2_star_in_ms": (
        "checks the timing bytes of a positive 10 xx response",
        positive_session_response_observed),
    "failed_key_keeps_pending_seed": (
        "sends a wrong key and then a second key for the same seed (expected 0x24)",
        wrong_key_then_second_key_same_seed),
    "lockout_expiry_resets_attempt_count": (
        ("reaches a lockout, waits for the delay to run out, requests a seed and sends another "
         "wrong key (expected 0x36)"), lockout_expired_then_wrong_key),
    "nrc_order_subfunction_before_length": (
        ("sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length "
         "(expected 0x13)"), unsupported_subfunction_with_wrong_length),
    "nrc_order_write_range_before_condition": (
        ("writes an out-of-range value to a conditioned DID while the condition fails "
         "(expected 0x22)"), out_of_range_write_while_condition_unmet),
    "routine_results_trailing_bytes_accepted": (
        "sends a requestResults (31 03 RID) with trailing bytes (expected 0x13)",
        results_request_with_trailing_bytes),
    "read_did_speed_not_clamped": (
        "reads DID 0x0140 while the vehicle speed is above 255 kph", speed_above_255_then_read),
    "write_stores_value_before_range_rejection": (
        "has an out-of-range write refused (0x31) and later reads the same DID back",
        rejected_write_then_read_back),
    "routine_stop_reports_completed_status": (
        "checks the response of a positive stopRoutine (31 02 RID)",
        routine_stop_response_observed),
    "dtc_clear_single_clears_neighbour": (
        ("clears one DTC while the next DTC in spec order is stored, then reads the DTCs back "
         "with a mask that shows it"), clear_one_dtc_next_one_stored_then_read),
    "dtc_read_reports_masked_status": (
        ("reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask"),
        status_with_bits_outside_the_mask),
    "ecu_reset_resets_seed_counter": (
        "issues a seed, resets the ECU, and then observes a newly issued seed",
        seed_issued_then_reset_then_seed),
    "s3_timeout_clears_dtc_status": (
        "stores a DTC status, lets an S3 timeout drop a session, then reads the DTCs",
        stored_dtc_then_s3_timeout_then_read),
    "suppressed_request_does_not_restart_s3": (
        ("sends a suppressed request in a non-default session and then waits so that S3 is "
         "exceeded only when counted from the last answered request"),
        suppressed_keepalive_exceeds_s3),
}


def heldout_v3_analysis(
    spec: EcuSpec, suites: dict[str, list[TestCase]], per_suite_detection: dict[str, Any]
) -> dict[str, Any]:
    """Trigger counts and miss reasons per suite for the v3 bugs."""
    return heldout_analysis(spec, suites, per_suite_detection, HELDOUT_V3_TRIGGERS)
