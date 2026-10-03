"""Unit tests for the held-out v2 static trigger predicates (tiny hand-built tests).

Each predicate gets one example that applies the stimulus and one that does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.eval import heldout_v2 as h2
from uds_assistant.eval.heldout import trigger_counts
from uds_assistant.eval.trace import trace_test
from uds_assistant.protocol.security import compute_key
from uds_assistant.simulator import HELDOUT_V2_BUG_IDS
from uds_assistant.spec.schema import EcuSpec, load_spec
from uds_assistant.testgen.model import (
    AdvanceTimeStep,
    SendStep,
    SetEnvironmentStep,
    TestCase,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXT = ("1003", "5003003201f4")
SEED1 = bytes.fromhex("01020304")
SEED3 = bytes.fromhex("0a0b0c0d")


@pytest.fixture(scope="module")
def spec() -> EcuSpec:
    return load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")


def _s(req: str, *resp: str) -> SendStep:
    return SendStep(request_hex=req, expected_responses_hex=list(resp))


def _t(*steps: object) -> TestCase:
    return TestCase(id="t", title="t", category="negative", steps=list(steps))  # type: ignore[arg-type]


def _fires(spec: EcuSpec, pred: h2.Trigger, test: TestCase) -> bool:
    return pred(spec, trace_test(spec, test))


def _unlock1() -> list[SendStep]:
    return [_s(*EXT), _s("2701", "6701" + SEED1.hex()),
            _s("2702" + compute_key(SEED1, 1).hex(), "6702")]


def test_every_v2_bug_has_a_trigger() -> None:
    assert set(h2.HELDOUT_V2_TRIGGERS) == set(HELDOUT_V2_BUG_IDS)
    assert len(h2.HELDOUT_V2_TRIGGERS) == 15


def test_session_reentry(spec: EcuSpec) -> None:
    yes = _t(*_unlock1(), _s(*EXT), _s("2e01 0032".replace(" ", ""), "7f2e33"))
    no = _t(*_unlock1(), _s("1002", "5002003201f4"), _s("22f190", "62f190" + "00" * 17))
    assert _fires(spec, h2.session_reentry_while_unlocked, yes)
    assert not _fires(spec, h2.session_reentry_while_unlocked, no)
    assert not _fires(spec, h2.session_reentry_while_unlocked, _t(_s(*EXT), _s(*EXT)))


def test_negative_response_then_s3_gap(spec: EcuSpec) -> None:
    yes = _t(_s(*EXT), AdvanceTimeStep(ms=3000), _s("2e0100", "7f2e13"),
             AdvanceTimeStep(ms=3000), _s("3e00", "7e00"))
    no_positive_between = _t(_s(*EXT), AdvanceTimeStep(ms=3000), _s("3e00", "7e00"),
                             AdvanceTimeStep(ms=3000), _s("3e00", "7e00"))
    no_gap = _t(_s(*EXT), _s("2e0100", "7f2e13"), AdvanceTimeStep(ms=1000), _s("3e00", "7e00"))
    assert _fires(spec, h2.negative_response_then_s3_gap, yes)
    assert not _fires(spec, h2.negative_response_then_s3_gap, no_positive_between)
    assert not _fires(spec, h2.negative_response_then_s3_gap, no_gap)


def test_lockout_then_s3_then_seed(spec: EcuSpec) -> None:
    lock = [_s(*EXT), _s("2701", "6701" + SEED1.hex()), _s("270200000000", "7f2735"),
            _s("2701", "6701" + SEED1.hex()), _s("270200000000", "7f2735"),
            _s("2701", "6701" + SEED1.hex()), _s("270200000000", "7f2736")]
    yes = _t(*lock, AdvanceTimeStep(ms=6000), _s(*EXT), _s("2701", "7f2737"))
    no_expiry = _t(*lock, _s("2701", "7f2737"))
    no_seed_after = _t(*lock, AdvanceTimeStep(ms=6000), _s(*EXT))
    assert _fires(spec, h2.lockout_then_s3_then_seed, yes)
    assert not _fires(spec, h2.lockout_then_s3_then_seed, no_expiry)
    assert not _fires(spec, h2.lockout_then_s3_then_seed, no_seed_after)


def test_reset_in_non_default_session(spec: EcuSpec) -> None:
    yes = _t(_s(*EXT), _s("1101", "5101"), _s("22f186", "62f18601"))
    assert _fires(spec, h2.reset_in_non_default_session, yes)
    assert not _fires(spec, h2.reset_in_non_default_session,
                      _t(_s("1101", "5101"), _s("22f186", "62f18601")))
    assert not _fires(spec, h2.reset_in_non_default_session, _t(_s(*EXT), _s("1101", "5101")))


def test_repeated_seed_request(spec: EcuSpec) -> None:
    key = compute_key(SEED1, 1).hex()
    yes = _t(_s(*EXT), _s("2701", "6701" + SEED1.hex()), _s("2701", "6701" + SEED1.hex()),
             _s("2702" + key, "6702"))
    once = _t(_s(*EXT), _s("2701", "6701" + SEED1.hex()), _s("2702" + key, "6702"))
    other_level = _t(_s(*EXT), _s("2701", "6701" + SEED1.hex()), _s("2703", "7f277e"),
                     _s("2702" + key, "6702"))
    assert _fires(spec, h2.repeated_seed_request_then_key, yes)
    assert not _fires(spec, h2.repeated_seed_request_then_key, once)
    assert not _fires(spec, h2.repeated_seed_request_then_key, other_level)


def test_key_right_prefix_wrong_tail(spec: EcuSpec) -> None:
    good = compute_key(SEED1, 1)
    tail = good[:2] + bytes([good[2] ^ 0xFF, good[3]])
    yes = _t(_s(*EXT), _s("2701", "6701" + SEED1.hex()), _s("2702" + tail.hex(), "7f2735"))
    all_wrong = _t(_s(*EXT), _s("2701", "6701" + SEED1.hex()),
                   _s("2702" + bytes(a ^ 0xFF for a in good).hex(), "7f2735"))
    correct = _t(*_unlock1())
    assert _fires(spec, h2.key_right_prefix_wrong_tail, yes)
    assert not _fires(spec, h2.key_right_prefix_wrong_tail, all_wrong)
    assert not _fires(spec, h2.key_right_prefix_wrong_tail, correct)


def test_wrong_keys_at_two_levels(spec: EcuSpec) -> None:
    prog = ("1002", "5002003201f4")
    yes = _t(_s(*EXT), _s("2701", "6701" + SEED1.hex()), _s("270200000000", "7f2735"),
             _s("2701", "6701" + SEED1.hex()), _s("270200000000", "7f2735"),
             _s(*prog), _s("2703", "6703" + SEED3.hex()), _s("270400000000", "7f2735"))
    one_level = _t(_s(*EXT), _s("2701", "6701" + SEED1.hex()), _s("270200000000", "7f2735"),
                   _s("2701", "6701" + SEED1.hex()), _s("270200000000", "7f2735"),
                   _s("2701", "6701" + SEED1.hex()), _s("270200000000", "7f2736"))
    too_few = _t(_s(*EXT), _s("2701", "6701" + SEED1.hex()), _s("270200000000", "7f2735"),
                 _s(*prog), _s("2703", "6703" + SEED3.hex()), _s("270400000000", "7f2735"))
    assert _fires(spec, h2.wrong_keys_at_two_levels, yes)
    assert not _fires(spec, h2.wrong_keys_at_two_levels, one_level)
    assert not _fires(spec, h2.wrong_keys_at_two_levels, too_few)


def test_out_of_range_write_while_locked(spec: EcuSpec) -> None:
    yes = _t(_s(*EXT), _s("2e013064", "7f2e33"))  # 0x0130 accepts 1..5 -> 0x64 is out of range
    in_range = _t(_s(*EXT), _s("2e013003", "7f2e33"))
    unlocked = _t(*_unlock1(), _s("2e013064", "7f2e31"))
    wrong_session = _t(_s("2e013064", "7f2e7f"))
    assert _fires(spec, h2.out_of_range_write_while_locked, yes)
    assert not _fires(spec, h2.out_of_range_write_while_locked, in_range)
    assert not _fires(spec, h2.out_of_range_write_while_locked, unlocked)
    assert not _fires(spec, h2.out_of_range_write_while_locked, wrong_session)


def test_clear_unknown_group_with_nvm_fault(spec: EcuSpec) -> None:
    fault = SetEnvironmentStep(nvm_write_fault=True)
    yes = _t(fault, _s("14123456", "7f1431"))
    known_group = _t(fault, _s("14ffffff", "7f1472"))
    known_dtc = _t(fault, _s("14b10101", "7f1472"))
    no_fault = _t(_s("14123456", "7f1431"))
    assert _fires(spec, h2.clear_unknown_group_with_nvm_fault, yes)
    for neg in (known_group, known_dtc, no_fault):
        assert not _fires(spec, h2.clear_unknown_group_with_nvm_fault, neg)


def test_read_dtc_extra_bytes(spec: EcuSpec) -> None:
    assert _fires(spec, h2.read_dtc_extra_bytes, _t(_s("1902ff00", "7f1913")))
    assert _fires(spec, h2.read_dtc_extra_bytes, _t(_s("1982ff00")))
    assert not _fires(spec, h2.read_dtc_extra_bytes, _t(_s("1902ff", "5902ff")))
    assert not _fires(spec, h2.read_dtc_extra_bytes, _t(_s("22f19000")))


def test_routine_overlong_option_record(spec: EcuSpec) -> None:
    assert _fires(spec, h2.routine_start_overlong_option,
                  _t(_s(*EXT), _s("310102010000", "7f3113")))  # 0x0201 takes 0 option bytes
    assert _fires(spec, h2.routine_start_overlong_option,
                  _t(_s(*EXT), _s("3101020200 00".replace(" ", ""), "7f3113")))  # 0x0202 takes 1
    assert not _fires(spec, h2.routine_start_overlong_option,
                      _t(_s(*EXT), _s("31010202" + "00", "7f3133")))
    assert not _fires(spec, h2.routine_start_overlong_option,
                      _t(_s("310102010000", "7f3131")))  # default session: wrong-session NRC first


def test_write_at_range_maximum(spec: EcuSpec) -> None:
    yes = _t(*_unlock1(), _s("2e013005", "6e0130"))
    no_inside = _t(*_unlock1(), _s("2e013003", "6e0130"))
    no_rejected = _t(_s(*EXT), _s("2e013005", "7f2e33"))
    assert _fires(spec, h2.write_at_range_maximum, yes)
    assert not _fires(spec, h2.write_at_range_maximum, no_inside)
    assert not _fires(spec, h2.write_at_range_maximum, no_rejected)


def test_multi_did_read_with_repeat(spec: EcuSpec) -> None:
    assert _fires(spec, h2.multi_did_read_with_repeat, _t(_s("220100 0100".replace(" ", ""))))
    assert not _fires(spec, h2.multi_did_read_with_repeat, _t(_s("22010001 01".replace(" ", ""))))
    assert not _fires(spec, h2.multi_did_read_with_repeat, _t(_s("2212341234", "7f2231")))
    # 0x0150 is readable only in extended: a repeat in the default session is not answered
    assert not _fires(spec, h2.multi_did_read_with_repeat, _t(_s("2201500150", "7f2231")))


def test_routine_start_after_stop(spec: EcuSpec) -> None:
    base = [*_unlock1(), _s("31010201", "71010201" + "01")]
    stop = _s("31020201", "71020201" + "03")
    yes = _t(*base, stop, _s("31010201", "71010201" + "01"))
    never_stopped = _t(*base, _s("31010201", "7f3124"))
    session_between = _t(*base, stop, _s(*EXT), _s("31010201", "7f3133"))
    assert _fires(spec, h2.routine_start_after_stop, yes)
    assert not _fires(spec, h2.routine_start_after_stop, never_stopped)
    assert not _fires(spec, h2.routine_start_after_stop, session_between)


def test_suppressed_seed_then_key(spec: EcuSpec) -> None:
    key = compute_key(SEED1, 1).hex()
    yes = _t(_s(*EXT), _s("2781"), _s("2702" + key, "6702"))
    plain = _t(_s(*EXT), _s("2701", "6701" + SEED1.hex()), _s("2702" + key, "6702"))
    no_key = _t(_s(*EXT), _s("2781"))
    rejected = _t(_s("2781", "7f277f"), _s("2702" + key, "7f277f"))
    assert _fires(spec, h2.suppressed_seed_then_key, yes)
    assert not _fires(spec, h2.suppressed_seed_then_key, plain)
    assert not _fires(spec, h2.suppressed_seed_then_key, no_key)
    assert not _fires(spec, h2.suppressed_seed_then_key, rejected)


def test_trigger_counts_and_analysis_use_the_v2_table(spec: EcuSpec) -> None:
    tests = [_t(_s("1902ff00", "7f1913")), _t(_s("22f190"))]
    counts = trigger_counts(spec, tests, sorted(HELDOUT_V2_BUG_IDS), h2.HELDOUT_V2_TRIGGERS)
    assert counts["read_dtc_trailing_bytes_accepted"] == 1
    assert counts["multi_did_read_dedups_repeats"] == 0
    assert set(counts) == set(HELDOUT_V2_BUG_IDS)
    det = {"per_bug": [{"bug_id": "read_dtc_trailing_bytes_accepted", "detected": False},
                       {"bug_id": "multi_did_read_dedups_repeats", "detected": False}]}
    ana = h2.heldout_v2_analysis(spec, {"generated": tests}, {"generated": det})
    reasons = {m["bug_id"]: m["reason"] for m in ana["generated"]["missed"]}
    assert reasons["multi_did_read_dedups_repeats"].startswith("no generated test")
    assert "1 generated test(s)" in reasons["read_dtc_trailing_bytes_accepted"]
