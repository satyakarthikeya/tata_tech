"""Static trigger analysis for the 15 held-out v2 bugs (``data/bugs/heldout_v2_catalog.yaml``).

Same idea as :mod:`.heldout`: for each bug a predicate over the static test trace
(:mod:`.trace`) says whether a test applies the stimulus the bug needs to show up, plus
a short phrase used in the missed-bug reasons ("no test <phrase>" / "N tests <phrase>
but none fails").

PROVENANCE: every predicate below was written from the bug descriptions in the v2
catalog and the documented behaviour (``docs/behaviour_contract.md``) ONLY, before any
v2 detection result existed, and they do not feed back into test generation. A
predicate may only be edited afterwards to fix a clear bug in the predicate itself;
such fixes are logged in the commit / DECISIONS.md.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from uds_assistant.eval.heldout import heldout_analysis
from uds_assistant.eval.trace import (
    SendEvent,
    TestTrace,
    request_did_ids,
    request_routine_id,
)
from uds_assistant.protocol.security import compute_key
from uds_assistant.rules.state import dtc_code_to_int
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.model import TestCase

Trigger = Callable[[EcuSpec, TestTrace], bool]

CLEAR_ALL_GROUP = 0xFFFFFF


def _default_session(spec: EcuSpec) -> int:
    return 0x01 if spec.get_session(0x01) is not None else spec.sessions[0].id


def _level_of(spec: EcuSpec, ev: SendEvent) -> tuple[int | None, str | None]:
    """Security level and kind ("seed" / "key") addressed by a 0x27 event."""
    if ev.sid != 0x27 or ev.subfunction is None:
        return None, None
    for lvl in spec.security_levels:
        if ev.subfunction == lvl.seed_subfunction:
            return lvl.level, "seed"
        if ev.subfunction == lvl.key_subfunction:
            return lvl.level, "key"
    return None, None


def _has_later_send(tr: TestTrace, ev: SendEvent) -> bool:
    return any(e.index > ev.index for e in tr.sends)


# ----------------------------------------------------------------------------- predicates


def session_reentry_while_unlocked(spec: EcuSpec, tr: TestTrace) -> bool:
    """A positive 0x10 to the already-active session while a level is unlocked, then a send."""
    return any(
        ev.sid == 0x10 and ev.positive and ev.subfunction == ev.session and ev.unlocked
        and _has_later_send(tr, ev)
        for ev in tr.sends
    )


def negative_response_then_s3_gap(spec: EcuSpec, tr: TestTrace) -> bool:
    """In a non-default session: an NRC-answered request, then a gap that only exceeds S3
    when counted from the last *positively* answered request.
    """
    default = _default_session(spec)
    acc = 0
    neg_since = False
    for ev in tr.sends:
        sess = spec.get_session(ev.session)
        s3 = sess.timing.s3_ms if sess is not None else 5000
        acc += ev.idle_ms
        if ev.session == default or ev.s3_expired:
            acc, neg_since = 0, False
        elif neg_since and acc > s3:
            return True
        if ev.nrc is not None:
            neg_since = neg_since or ev.session != default
        else:
            acc, neg_since = 0, False
    return False


def lockout_then_s3_then_seed(spec: EcuSpec, tr: TestTrace) -> bool:
    """A lockout (0x36 / 0x37), then an S3 timeout, then a later seed request."""
    locked = expired = False
    for ev in tr.sends:
        if locked and ev.s3_expired:
            expired = True
        _, kind = _level_of(spec, ev)
        if expired and kind == "seed":
            return True
        if ev.sid == 0x27 and ev.nrc in (0x36, 0x37):
            locked = True
            expired = False
    return False


def reset_in_non_default_session(spec: EcuSpec, tr: TestTrace) -> bool:
    """A positive ECUReset sent while a non-default session is active, then another send."""
    default = _default_session(spec)
    return any(
        ev.sid == 0x11 and ev.positive and ev.session != default and _has_later_send(tr, ev)
        for ev in tr.sends
    )


def repeated_seed_request_then_key(spec: EcuSpec, tr: TestTrace) -> bool:
    """Two positive seed requests for one level with no key between, then a key for it."""
    pending: dict[int, int] = {}
    for ev in tr.sends:
        level, kind = _level_of(spec, ev)
        if level is None:
            continue
        if kind == "seed" and ev.nrc is None and level not in ev.unlocked:
            pending[level] = pending.get(level, 0) + 1
        elif kind == "key":
            if pending.get(level, 0) >= 2:
                return True
            pending.pop(level, None)
    return False


def key_right_prefix_wrong_tail(spec: EcuSpec, tr: TestTrace) -> bool:
    """A sendKey whose first two bytes are right but whose tail is wrong."""
    seeds: dict[int, bytes] = {}
    for ev in tr.sends:
        level, kind = _level_of(spec, ev)
        if level is None:
            continue
        if kind == "seed" and ev.nrc is None:
            for frame in ev.frames:
                if len(frame) > 2 and frame[0] == 0x67 and any(frame[2:]):
                    seeds[level] = bytes(frame[2:])
        elif kind == "key":
            seed = seeds.pop(level, None)
            key = ev.request[2:]
            if seed is not None and len(key) >= 2:
                expected = compute_key(seed, level)
                if key != expected and key[:2] == expected[:2]:
                    return True
    return False


def wrong_keys_at_two_levels(spec: EcuSpec, tr: TestTrace) -> bool:
    """Wrong keys at two different levels adding up to at least the attempt limit."""
    fails: dict[int, int] = {}
    for ev in tr.sends:
        level, kind = _level_of(spec, ev)
        if kind == "key" and ev.nrc in (0x35, 0x36) and level is not None:
            fails[level] = fails.get(level, 0) + 1
    limit = min((lv.max_attempts for lv in spec.security_levels), default=3)
    return len(fails) >= 2 and sum(fails.values()) >= limit


def _write_value(ev: SendEvent) -> int:
    return int.from_bytes(ev.request[3:], "big")


def out_of_range_write_while_locked(spec: EcuSpec, tr: TestTrace) -> bool:
    """A correct-length, out-of-range write to a DID in its write session, security not unlocked."""
    for ev in tr.sends:
        if ev.sid != 0x2E or len(ev.request) < 4:
            continue
        did = spec.get_did(request_did_ids(ev.request)[0])
        if (did is not None and did.value_range is not None and did.is_writable
                and ev.session in did.write_sessions
                and len(ev.request) - 3 == did.length
                and did.write_security_level not in ev.unlocked
                and not did.value_range.min <= _write_value(ev) <= did.value_range.max):
            return True
    return False


def clear_unknown_group_with_nvm_fault(spec: EcuSpec, tr: TestTrace) -> bool:
    """0x14 with a group that is neither all-DTCs nor a spec DTC, while the NVM fault is set."""
    known = {dtc_code_to_int(d.code) for d in spec.dtcs} | {CLEAR_ALL_GROUP}
    for ev in tr.sends:
        if (ev.sid == 0x14 and len(ev.request) == 4 and ev.nvm_write_fault
                and int.from_bytes(ev.request[1:4], "big") not in known):
            return True
    return False


def read_dtc_extra_bytes(spec: EcuSpec, tr: TestTrace) -> bool:
    """0x19 sub-function 02 carrying more than one byte after the sub-function."""
    return any(ev.sid == 0x19 and ev.subfunction == 0x02 and len(ev.request) > 3
               for ev in tr.sends)


def routine_start_overlong_option(spec: EcuSpec, tr: TestTrace) -> bool:
    """A 0x31 start of a known routine (in its session) with too many option-record bytes."""
    for ev in tr.sends:
        rid = request_routine_id(ev.request)
        rdef = spec.get_routine(rid) if rid is not None else None
        if (ev.sid == 0x31 and ev.subfunction == 0x01 and rdef is not None
                and ev.session in rdef.sessions
                and len(ev.request) > 4 + rdef.option_record_length):
            return True
    return False


def write_at_range_maximum(spec: EcuSpec, tr: TestTrace) -> bool:
    """An accepted write whose value equals the DID's inclusive maximum."""
    for ev in tr.sends:
        if ev.sid != 0x2E or len(ev.request) < 4 or not ev.positive:
            continue
        did = spec.get_did(request_did_ids(ev.request)[0])
        if (did is not None and did.value_range is not None
                and _write_value(ev) == did.value_range.max):
            return True
    return False


def multi_did_read_with_repeat(spec: EcuSpec, tr: TestTrace) -> bool:
    """A 0x22 request listing one readable DID more than once."""
    for ev in tr.sends:
        if ev.sid != 0x22:
            continue
        dids = request_did_ids(ev.request)
        for did_id in set(dids):
            did = spec.get_did(did_id)
            if did is not None and dids.count(did_id) >= 2 and ev.session in did.read_sessions:
                return True
    return False


def routine_start_after_stop(spec: EcuSpec, tr: TestTrace) -> bool:
    """A start of a routine that was positively stopped earlier (status stopped still held)."""
    stopped: set[int] = set()
    for ev in tr.sends:
        if ev.s3_expired:
            stopped.clear()
        rid = request_routine_id(ev.request)
        if ev.sid == 0x31 and rid is not None:
            if ev.subfunction == 0x02 and ev.positive:
                stopped.add(rid)
            elif ev.subfunction == 0x01 and rid in stopped:
                return True
        elif ev.sid in (0x10, 0x11) and ev.positive:
            stopped.clear()
    return False


def suppressed_seed_then_key(spec: EcuSpec, tr: TestTrace) -> bool:
    """A suppressed (bit 7) seed request that is accepted, then a key for the same level."""
    pending: set[int] = set()
    for ev in tr.sends:
        level, kind = _level_of(spec, ev)
        if level is None:
            continue
        suppressed = len(ev.request) > 1 and bool(ev.request[1] & 0x80)
        if kind == "seed":
            if suppressed and ev.nrc is None and level not in ev.unlocked:
                pending.add(level)
            else:
                pending.discard(level)
        elif kind == "key":
            if level in pending:
                return True
            pending.discard(level)
    return False


HELDOUT_V2_TRIGGERS: dict[str, tuple[str, Trigger]] = {
    "session_reentry_keeps_unlock": (
        ("re-enters the active session (positive 10 xx) while a security level is unlocked and "
         "then send another request"), session_reentry_while_unlocked),
    "s3_restart_skipped_on_negative_response": (
        ("answers a request with an NRC in a non-default session and then wait so that S3 is "
         "exceeded only when counted from the last positive request"),
        negative_response_then_s3_gap),
    "s3_timeout_resets_lockout_counters": (
        "reaches a security lockout, lets S3 expire and then requests a seed",
        lockout_then_s3_then_seed),
    "ecu_reset_keeps_session": (
        "sends a positive ECUReset from a non-default session and then another request",
        reset_in_non_default_session),
    "seed_request_keeps_stale_pending_seed": (
        "requests a seed twice for one level before sending a key for it",
        repeated_seed_request_then_key),
    "key_compare_prefix_only": (
        "sends a key with the right first two bytes and a wrong tail", key_right_prefix_wrong_tail),
    "lockout_counter_pooled_across_levels": (
        "sends wrong keys at two different levels that together reach the attempt limit",
        wrong_keys_at_two_levels),
    "nrc_order_range_before_security": (
        ("writes an out-of-range value of correct length to a DID in its write session while "
         "security is locked"), out_of_range_write_while_locked),
    "nrc_order_nvm_fault_before_group_check": (
        "clears an unknown DTC group (0x14) while the NVM write fault is set",
        clear_unknown_group_with_nvm_fault),
    "read_dtc_trailing_bytes_accepted": (
        "sends 19 02 with more than one byte after the sub-function", read_dtc_extra_bytes),
    "routine_option_record_overlong_accepted": (
        "starts a routine (in its session) with an over-long option record",
        routine_start_overlong_option),
    "write_range_upper_bound_exclusive": (
        "writes the DID's maximum in-range value and has it accepted", write_at_range_maximum),
    "multi_did_read_dedups_repeats": (
        "reads one DID several times in a single 0x22 request", multi_did_read_with_repeat),
    "routine_restart_after_stop_blocked": (
        "starts a routine again after stopping it", routine_start_after_stop),
    "suppressed_seed_request_not_stored": (
        "sends a suppressed seed request (27 81 / 27 83) and then a key for that level",
        suppressed_seed_then_key),
}


def heldout_v2_analysis(
    spec: EcuSpec, suites: dict[str, list[TestCase]], per_suite_detection: dict[str, Any]
) -> dict[str, Any]:
    """Trigger counts and miss reasons per suite for the v2 bugs."""
    return heldout_analysis(spec, suites, per_suite_detection, HELDOUT_V2_TRIGGERS)
