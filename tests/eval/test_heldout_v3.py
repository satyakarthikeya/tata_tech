"""Unit tests for the held-out v3 static trigger predicates (tiny hand-built tests).

Each predicate gets one example that applies the stimulus and at least one that does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.eval import heldout_v3 as h3
from uds_assistant.eval.heldout import trigger_counts
from uds_assistant.eval.trace import trace_test
from uds_assistant.simulator import HELDOUT_V3_BUG_IDS
from uds_assistant.spec.schema import EcuSpec, load_spec
from uds_assistant.testgen.model import (
    AdvanceTimeStep,
    SendStep,
    SetDtcStatusStep,
    SetEnvironmentStep,
    TestCase,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXT = ("1003", "5003003201f4")
PROG = ("1002", "5002003201f4")
SEED1 = "01020304"
SEED3 = "0a0b0c0d"
WRONG = "00000000"


@pytest.fixture(scope="module")
def spec() -> EcuSpec:
    return load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")


def _s(req: str, *resp: str) -> SendStep:
    return SendStep(request_hex=req, expected_responses_hex=list(resp))


def _t(*steps: object) -> TestCase:
    return TestCase(id="t", title="t", category="negative", steps=list(steps))  # type: ignore[arg-type]


def _fires(spec: EcuSpec, pred: h3.Trigger, test: TestCase) -> bool:
    return pred(spec, trace_test(spec, test))


def _unlock3() -> list[SendStep]:
    return [_s(*PROG), _s("2703", "6703" + SEED3), _s("2704" + SEED3, "6704")]


def test_every_v3_bug_has_a_trigger() -> None:
    assert set(h3.HELDOUT_V3_TRIGGERS) == set(HELDOUT_V3_BUG_IDS)
    assert len(h3.HELDOUT_V3_TRIGGERS) == 15
    assert all(phrase for phrase, _fn in h3.HELDOUT_V3_TRIGGERS.values())


def test_session_switch_keeps_pending_seed(spec: EcuSpec) -> None:
    pred = h3.session_switch_with_pending_seed_then_key
    yes = _t(_s(*EXT), _s("2701", "6701" + SEED1), _s(*EXT), _s("2702" + WRONG, "7f2724"))
    no_no_switch = _t(_s(*EXT), _s("2701", "6701" + SEED1), _s("2702" + WRONG, "7f2735"))
    no_seed_after_switch = _t(_s(*EXT), _s("2701", "6701" + SEED1), _s(*EXT),
                              _s("2701", "6701" + SEED1), _s("2702" + WRONG, "7f2735"))
    no_nothing_pending = _t(_s(*EXT), _s(*EXT), _s("2702" + WRONG, "7f2724"))
    assert _fires(spec, pred, yes)
    assert not _fires(spec, pred, no_no_switch)
    assert not _fires(spec, pred, no_seed_after_switch)
    assert not _fires(spec, pred, no_nothing_pending)


def test_session_response_observed(spec: EcuSpec) -> None:
    pred = h3.positive_session_response_observed
    assert _fires(spec, pred, _t(_s(*EXT)))
    assert not _fires(spec, pred, _t(_s("1083")))  # suppressed: no frame is checked
    assert not _fires(spec, pred, _t(_s("1005", "7f1012")))


def test_failed_key_keeps_pending_seed(spec: EcuSpec) -> None:
    pred = h3.wrong_key_then_second_key_same_seed
    yes = _t(_s(*EXT), _s("2701", "6701" + SEED1), _s("2702" + WRONG, "7f2735"),
             _s("2702" + WRONG, "7f2724"))
    fresh_seed = _t(_s(*EXT), _s("2701", "6701" + SEED1), _s("2702" + WRONG, "7f2735"),
                    _s("2701", "6701" + SEED1), _s("2702" + WRONG, "7f2735"))
    session_between = _t(_s(*EXT), _s("2701", "6701" + SEED1), _s("2702" + WRONG, "7f2735"),
                         _s(*EXT), _s("2702" + WRONG, "7f2724"))
    assert _fires(spec, pred, yes)
    assert not _fires(spec, pred, fresh_seed)
    assert not _fires(spec, pred, session_between)


def _lockout_steps() -> list[object]:
    out: list[object] = [_s(*EXT)]
    for nrc in ("35", "35", "36"):
        out += [_s("2701", "6701" + SEED1), _s("2702" + WRONG, "7f27" + nrc)]
    return out


def test_lockout_expiry_resets_attempt_count(spec: EcuSpec) -> None:
    pred = h3.lockout_expired_then_wrong_key
    yes = _t(*_lockout_steps(), AdvanceTimeStep(ms=10000), _s(*EXT), _s("2701", "6701" + SEED1),
             _s("2702" + WRONG, "7f2736"))
    too_early = _t(*_lockout_steps(), AdvanceTimeStep(ms=4000), _s("2701", "7f2737"),
                   _s("2702" + WRONG, "7f2724"))
    no_wrong_key = _t(*_lockout_steps(), AdvanceTimeStep(ms=10000), _s(*EXT),
                      _s("2701", "6701" + SEED1), _s("2702", "6702"))
    assert _fires(spec, pred, yes)
    assert not _fires(spec, pred, too_early)
    assert not _fires(spec, pred, no_wrong_key)


def test_subfunction_before_length(spec: EcuSpec) -> None:
    pred = h3.unsupported_subfunction_with_wrong_length
    assert _fires(spec, pred, _t(_s("100500", "7f1013")))
    assert _fires(spec, pred, _t(_s("3e0100", "7f3e13")))
    assert not _fires(spec, pred, _t(_s("1005", "7f1012")))  # length is fine
    assert not _fires(spec, pred, _t(_s("100100", "7f1013")))  # subfunction is supported
    assert not _fires(spec, pred, _t(_s("19ff00", "7f1913")))  # no generic length rule here


def test_write_range_before_condition(spec: EcuSpec) -> None:
    pred = h3.out_of_range_write_while_condition_unmet
    moving = SetEnvironmentStep(vehicle_speed_kph=10)
    yes = _t(*_unlock3(), moving, _s("2e015005", "7f2e22"))
    answered_range = _t(*_unlock3(), _s("2e015005", "7f2e31"))
    in_range = _t(*_unlock3(), moving, _s("2e015001", "7f2e22"))
    unconditioned = _t(_s(*EXT), _s("2e016000", "7f2e13"))
    assert _fires(spec, pred, yes)
    assert not _fires(spec, pred, answered_range)
    assert not _fires(spec, pred, in_range)
    assert not _fires(spec, pred, unconditioned)


def test_results_with_trailing_bytes(spec: EcuSpec) -> None:
    pred = h3.results_request_with_trailing_bytes
    assert _fires(spec, pred, _t(_s("310302010000", "7f3113")))
    assert not _fires(spec, pred, _t(_s("31030201", "7f3124")))
    assert not _fires(spec, pred, _t(_s("310102010000", "7f3113")))  # a start request


def test_speed_above_255_read(spec: EcuSpec) -> None:
    pred = h3.speed_above_255_then_read
    read = _s("220140", "620140ff")
    assert _fires(spec, pred, _t(SetEnvironmentStep(vehicle_speed_kph=300), read))
    assert not _fires(spec, pred, _t(SetEnvironmentStep(vehicle_speed_kph=255), read))
    assert not _fires(spec, pred, _t(read))
    assert not _fires(spec, pred, _t(SetEnvironmentStep(vehicle_speed_kph=300),
                                     _s("22f190", "62f190" + "00" * 17)))


def test_rejected_write_then_read_back(spec: EcuSpec) -> None:
    pred = h3.rejected_write_then_read_back
    yes = _t(*_unlock3(), _s("2e015005", "7f2e31"), _s(*EXT), _s("220150", "62015000"))
    accepted = _t(*_unlock3(), _s("2e015001", "6e0150"), _s(*EXT), _s("220150", "62015001"))
    never_read = _t(*_unlock3(), _s("2e015005", "7f2e31"))
    other_did = _t(*_unlock3(), _s("2e015005", "7f2e31"), _s(*EXT),
                   _s("22f190", "62f190" + "00" * 17))
    assert _fires(spec, pred, yes)
    assert not _fires(spec, pred, accepted)
    assert not _fires(spec, pred, never_read)
    assert not _fires(spec, pred, other_did)


def test_routine_stop_response_observed(spec: EcuSpec) -> None:
    pred = h3.routine_stop_response_observed
    assert _fires(spec, pred, _t(_s("31020201", "71020201" + "03")))
    assert not _fires(spec, pred, _t(_s("31020201", "7f3124")))
    assert not _fires(spec, pred, _t(_s("31820201")))  # suppressed
    assert not _fires(spec, pred, _t(_s("31010201", "71010201" + "01")))


def test_clear_one_dtc_clears_the_next(spec: EcuSpec) -> None:
    pred = h3.clear_one_dtc_next_one_stored_then_read
    stored_next = SetDtcStatusStep(code="B10205", status=0x09)
    read = _s("1902ff", "5902ff" + "b10205" + "09")
    yes = _t(stored_next, _s("14b10101", "54"), read)
    next_empty = _t(SetDtcStatusStep(code="B10101", status=0x09), _s("14b10101", "54"),
                    _s("1902ff", "5902ff"))
    no_read_back = _t(stored_next, _s("14b10101", "54"))
    last_dtc = _t(SetDtcStatusStep(code="B10310", status=0x09), _s("14b10310", "54"), read)
    clear_all = _t(stored_next, _s("14ffffff", "54"), _s("1902ff", "5902ff"))
    assert _fires(spec, pred, yes)
    assert not _fires(spec, pred, next_empty)
    assert not _fires(spec, pred, no_read_back)
    assert not _fires(spec, pred, last_dtc)
    assert not _fires(spec, pred, clear_all)


def test_dtc_status_masked(spec: EcuSpec) -> None:
    pred = h3.status_with_bits_outside_the_mask
    stored = SetDtcStatusStep(code="B10101", status=0x09)
    yes = _t(stored, _s("190201", "590201b1010109"))
    full_mask = _t(stored, _s("1902ff", "5902ffb1010109"))
    bits_inside = _t(SetDtcStatusStep(code="B10101", status=0x01),
                     _s("190201", "590201b1010101"))
    suppressed = _t(stored, _s("198201"))
    assert _fires(spec, pred, yes)
    assert not _fires(spec, pred, full_mask)
    assert not _fires(spec, pred, bits_inside)
    assert not _fires(spec, pred, suppressed)


def test_reset_then_seed(spec: EcuSpec) -> None:
    pred = h3.seed_issued_then_reset_then_seed
    yes = _t(_s(*EXT), _s("2701", "6701" + SEED1), _s("1101", "5101"), _s(*EXT),
             _s("2701", "6701" + SEED1))
    no_seed_before = _t(_s("1101", "5101"), _s(*EXT), _s("2701", "6701" + SEED1))
    suppressed_after = _t(_s(*EXT), _s("2701", "6701" + SEED1), _s("1101", "5101"), _s(*EXT),
                          _s("2781"))
    no_seed_after = _t(_s(*EXT), _s("2701", "6701" + SEED1), _s("1101", "5101"))
    assert _fires(spec, pred, yes)
    assert not _fires(spec, pred, no_seed_before)
    assert not _fires(spec, pred, suppressed_after)
    assert not _fires(spec, pred, no_seed_after)


def test_stored_dtc_then_s3_timeout_then_read(spec: EcuSpec) -> None:
    pred = h3.stored_dtc_then_s3_timeout_then_read
    stored = SetDtcStatusStep(code="B10101", status=0x09)
    read = _s("1902ff", "5902ffb1010109")
    yes = _t(_s(*EXT), stored, AdvanceTimeStep(ms=6000), read)
    no_timeout = _t(_s(*EXT), stored, AdvanceTimeStep(ms=1000), read)
    default_session_wait = _t(stored, AdvanceTimeStep(ms=60000), read)
    nothing_stored = _t(_s(*EXT), AdvanceTimeStep(ms=6000), _s("1902ff", "5902ff"))
    assert _fires(spec, pred, yes)
    assert not _fires(spec, pred, no_timeout)
    assert not _fires(spec, pred, default_session_wait)
    assert not _fires(spec, pred, nothing_stored)


def test_suppressed_keepalive_exceeds_s3(spec: EcuSpec) -> None:
    pred = h3.suppressed_keepalive_exceeds_s3
    probe = _s("22f186", "62f18603")
    yes = _t(_s(*EXT), AdvanceTimeStep(ms=3000), _s("3e80"), AdvanceTimeStep(ms=3000), probe)
    answered = _t(_s(*EXT), AdvanceTimeStep(ms=3000), _s("3e00", "7e00"),
                  AdvanceTimeStep(ms=3000), probe)
    short_gap = _t(_s(*EXT), AdvanceTimeStep(ms=1000), _s("3e80"), AdvanceTimeStep(ms=1000),
                   probe)
    default_session = _t(AdvanceTimeStep(ms=3000), _s("3e80"), AdvanceTimeStep(ms=3000),
                         _s("22f186", "62f18601"))
    assert _fires(spec, pred, yes)
    assert not _fires(spec, pred, answered)
    assert not _fires(spec, pred, short_gap)
    assert not _fires(spec, pred, default_session)


def test_trigger_counts_and_analysis_use_the_v3_table(spec: EcuSpec) -> None:
    stored = SetDtcStatusStep(code="B10101", status=0x09)
    suite = [_t(_s(*EXT)), _t(stored, _s("190201", "590201b1010101"))]
    ids = sorted(HELDOUT_V3_BUG_IDS)
    counts = trigger_counts(spec, suite, ids, h3.HELDOUT_V3_TRIGGERS)
    assert set(counts) == set(ids) and min(counts.values()) >= 0
    assert counts["session_response_p2_star_in_ms"] == 1
    assert counts["read_did_speed_not_clamped"] == 0
    det = {"s": {"per_bug": [{"bug_id": b, "detected": False} for b in ids]}}
    ana = h3.heldout_v3_analysis(spec, {"s": suite}, det)
    reasons = {m["bug_id"]: m["reason"] for m in ana["s"]["missed"]}
    assert reasons["read_did_speed_not_clamped"].startswith("no s test ")
    assert reasons["session_response_p2_star_in_ms"].startswith("1 s test(s) ")
    assert all("no trigger analysis" not in r for r in reasons.values())


def test_trace_records_dtc_sets_and_real_s3_drops(spec: EcuSpec) -> None:
    test = _t(_s(*EXT), SetDtcStatusStep(code="B10101", status=0x09),
              AdvanceTimeStep(ms=6000), _s("1902ff", "5902ff"),
              AdvanceTimeStep(ms=60000), _s("1902ff", "5902ff"))
    tr = trace_test(spec, test)
    assert tr.dtc_sets == [(1, 0xB10101, 0x09)]
    # the first idle gap drops the extended session; the second one is in the default session
    assert [ev.s3_dropped_session for ev in tr.sends] == [False, True, False]
    assert [ev.s3_expired for ev in tr.sends] == [False, True, True]
