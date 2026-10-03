"""Why a held-out bug was missed: does any test even apply the stimulus that triggers it?

For reporting only. Each held-out bug (``data/bugs/heldout_catalog.yaml``) gets a
*trigger* written from its catalog description: a predicate over the static test
trace (:mod:`.trace`) saying whether a test applies the stimulus the bug needs to
show up, plus a short phrase. For a missed bug the report states either "no test
<phrase>" (the suite never exercises it) or "N tests <phrase> but none fails"
(stimulus present, the expected responses did not distinguish the faulty
behaviour). The triggers were written after the held-out results were seen and
never feed back into test generation, templates or gold tests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from uds_assistant.eval.trace import TestTrace, request_did_ids, request_routine_id, trace_test
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.model import TestCase

Trigger = Callable[[EcuSpec, TestTrace], bool]


def _routine_start_then_session_then_results(spec: EcuSpec, tr: TestTrace) -> bool:
    started: set[int] = set()
    changed: set[int] = set()
    for ev in tr.sends:
        rid = request_routine_id(ev.request)
        if ev.sid == 0x31 and ev.subfunction == 0x01 and ev.positive and rid is not None:
            started.add(rid)
            changed.discard(rid)
        elif ev.sid == 0x10 and ev.positive:
            changed |= started
        elif ev.sid == 0x31 and ev.subfunction == 0x03 and rid in changed:
            return True
    return False


def _seed_after_unlock(spec: EcuSpec, tr: TestTrace) -> bool:
    seed_subs = {lvl.level: lvl.seed_subfunction for lvl in spec.security_levels}
    return any(
        ev.sid == 0x27 and ev.subfunction in {seed_subs[lv] for lv in ev.unlocked}
        for ev in tr.sends
    )


def _calibration_start_locked_moving(spec: EcuSpec, tr: TestTrace) -> bool:
    for ev in tr.sends:
        rid = request_routine_id(ev.request)
        rdef = spec.get_routine(rid) if rid is not None else None
        if (ev.sid == 0x31 and ev.subfunction == 0x01 and rdef is not None
                and "vehicle_stationary" in rdef.conditions.requires
                and rdef.security_level is not None
                and rdef.security_level not in ev.unlocked
                and ev.session in rdef.sessions and ev.vehicle_speed_kph > 0):
            return True
    return False


def _odd_did_bytes(spec: EcuSpec, tr: TestTrace) -> bool:
    return any(ev.sid == 0x22 and len(ev.request) >= 4 and len(ev.request) % 2 == 0
               for ev in tr.sends)


def _restricted_read_outside_session(spec: EcuSpec, tr: TestTrace) -> bool:
    for ev in tr.sends:
        if ev.sid != 0x22:
            continue
        for did in request_did_ids(ev.request):
            d = spec.get_did(did)
            if d is not None and ev.session not in d.read_sessions:
                return True
    return False


def _uint16_write_then_read(spec: EcuSpec, tr: TestTrace) -> bool:
    written: set[int] = set()
    for ev in tr.sends:
        dids = request_did_ids(ev.request)
        if ev.sid == 0x2E and ev.positive and dids:
            d = spec.get_did(dids[0])
            if d is not None and d.encoding == "uint16":
                written.add(dids[0])
        elif ev.sid == 0x22 and written & set(dids):
            return True
    return False


def _tester_present_only_keepalive(spec: EcuSpec, tr: TestTrace) -> bool:
    for a, b in zip(tr.sends, tr.sends[1:], strict=False):
        if a.sid == 0x3E and a.session != 0x01 and a.idle_ms > 0 and b.idle_ms > 0:
            return True
    return False


def _reset_after_lockout_then_seed(spec: EcuSpec, tr: TestTrace) -> bool:
    locked = reset = False
    for ev in tr.sends:
        if ev.sid == 0x27 and ev.nrc in (0x36, 0x37) and not reset:
            locked = True
        elif ev.sid == 0x11 and locked and ev.positive:
            reset = True
        elif ev.sid == 0x27 and reset and ev.subfunction is not None and ev.subfunction % 2 == 1:
            return True
    return False


def _write_s3_expire_read(spec: EcuSpec, tr: TestTrace) -> bool:
    written: set[int] = set()
    expired: set[int] = set()
    for ev in tr.sends:
        dids = request_did_ids(ev.request)
        if ev.s3_expired:
            expired |= written
        if ev.sid == 0x2E and ev.positive and dids:
            written.add(dids[0])
            expired.discard(dids[0])
        elif ev.sid == 0x22 and expired & set(dids):
            return True
    return False


def _session_with_suppress_bit(spec: EcuSpec, tr: TestTrace) -> bool:
    return any(ev.sid == 0x10 and len(ev.request) > 1 and ev.request[1] & 0x80
               for ev in tr.sends)


def _routine_suppress_with_response(spec: EcuSpec, tr: TestTrace) -> bool:
    return any(
        ev.sid == 0x31 and len(ev.request) > 1 and ev.request[1] & 0x80
        and any(f[:1] == b"\x71" for f in ev.frames)
        for ev in tr.sends
    )


HELDOUT_TRIGGERS: dict[str, tuple[str, Trigger]] = {
    "routine_state_survives_session_change": (
        "starts a routine, changes session, then asks for that routine's results",
        _routine_start_then_session_then_results),
    "failed_attempts_reset_by_seed_request": (
        "requests a new seed between failed keys up to the attempt limit",
        lambda spec, tr: sum(1 for ev in tr.sends if ev.sid == 0x27 and ev.nrc == 0x35) >= 2),
    "seed_returned_while_unlocked": (
        "requests a seed for a level that is already unlocked", _seed_after_unlock),
    "nrc_order_condition_before_security": (
        "starts a vehicle_stationary-gated routine while moving AND still locked",
        _calibration_start_locked_moving),
    "read_did_odd_length_truncated": (
        "sends 0x22 with an odd number (>= 3) of DID bytes", _odd_did_bytes),
    "read_did_session_restriction_ignored": (
        "reads a DID outside its read_sessions", _restricted_read_outside_session),
    "uint16_did_stored_byte_swapped": (
        "writes a uint16 DID and reads it back", _uint16_write_then_read),
    "s3_not_refreshed_by_tester_present": (
        "keeps a non-default session alive with TesterPresent across idle time",
        _tester_present_only_keepalive),
    "ecu_reset_clears_security_lockout": (
        "resets the ECU after a security lockout and then requests a seed",
        _reset_after_lockout_then_seed),
    "s3_timeout_reverts_written_dids": (
        "writes a DID, lets S3 expire, then reads the DID back", _write_s3_expire_read),
    "session_suppress_bit_not_masked": (
        "sends DiagnosticSessionControl with the suppress bit set", _session_with_suppress_bit),
    "suppress_bit_echoed_in_response": (
        ("sends RoutineControl with the suppress bit where a positive response is still "
         "expected (e.g. after 0x78)"), _routine_suppress_with_response),
}


def trigger_counts(
    spec: EcuSpec, tests: list[TestCase], bug_ids: list[str],
    triggers: dict[str, tuple[str, Trigger]] | None = None,
) -> dict[str, int]:
    """Number of tests applying each bug's trigger stimulus (-1 when no trigger is defined).

    ``triggers`` defaults to the held-out v1 table :data:`HELDOUT_TRIGGERS`.
    """
    table = HELDOUT_TRIGGERS if triggers is None else triggers
    traces = [trace_test(spec, t) for t in tests]
    out: dict[str, int] = {}
    for bug_id in bug_ids:
        entry = table.get(bug_id)
        out[bug_id] = -1 if entry is None else sum(1 for tr in traces if entry[1](spec, tr))
    return out


def miss_reason(
    bug_id: str, suite: str, count: int,
    triggers: dict[str, tuple[str, Trigger]] | None = None,
) -> str:
    """One-line reason a bug was missed by ``suite`` given its trigger count."""
    entry = (HELDOUT_TRIGGERS if triggers is None else triggers).get(bug_id)
    if entry is None or count < 0:
        return "no trigger analysis defined for this bug"
    phrase = entry[0]
    if count == 0:
        return f"no {suite} test {phrase}"
    return (f"{count} {suite} test(s) {phrase}, but none of their expected responses "
            "differs under the bug")


def heldout_analysis(
    spec: EcuSpec, suites: dict[str, list[TestCase]], per_suite_detection: dict[str, Any],
    triggers: dict[str, tuple[str, Trigger]] | None = None,
) -> dict[str, Any]:
    """Trigger counts and miss reasons per suite (``per_suite_detection`` = bug_detection dicts).

    ``triggers`` selects the trigger table (default: held-out v1).
    """
    table = HELDOUT_TRIGGERS if triggers is None else triggers
    out: dict[str, Any] = {"triggers": {k: v[0] for k, v in table.items()}}
    for name, tests in suites.items():
        det = per_suite_detection[name]
        ids = [b["bug_id"] for b in det["per_bug"]]
        counts = trigger_counts(spec, tests, ids, table)
        out[name] = {
            "trigger_counts": counts,
            "missed": [
                {"bug_id": b["bug_id"],
                 "reason": miss_reason(b["bug_id"], name, counts[b["bug_id"]], table)}
                for b in det["per_bug"] if not b["detected"]
            ],
        }
    return out
