"""Table-driven tests: every NRC path and every positive path of the rules engine.

Each case is ``(id, setup_tokens, request_hex, expected_response_hexes)``. The
setup DSL is documented in :func:`tests.rules.helpers.run_setup`. Expected
bytes are written out literally (not recomputed through the engine).
"""

from __future__ import annotations

import pytest

from tests.rules.helpers import hx, run_setup
from uds_assistant.rules.engine import RulesSession
from uds_assistant.spec.schema import EcuSpec

VIN = "53 59 4E 54 48 45 54 49 43 42 4D 30 30 30 30 30 31"
PART = "42 43 4D 2D 31 32 33 34 35 2D"
TIMING = "00 32 01 F4"  # P2 = 50 ms, P2* = 5000 ms in 10 ms units (500 = 0x01F4)
SEED_L1_C0 = "95 06 77 E8"  # derive_seed(level=1, counter=0, 4)
SEED_L3_C0 = "0B 7C ED 5E"  # derive_seed(level=3, counter=0, 4)
UNLOCK1 = ["ext", "unlock1"]
UNLOCK3 = ["prog", "unlock3"]

Case = tuple[str, list[str], str, list[str]]

GENERIC_CASES: list[Case] = [
    # --- Step 1: service not supported -> 0x11
    ("sid_unsupported_0x85", [], "85 01", ["7F 85 11"]),
    ("sid_unsupported_0x00", [], "00", ["7F 00 11"]),
    ("sid_unsupported_0x23_readmem", [], "23 12 34 56", ["7F 23 11"]),
    ("sid_response_value_0x50", [], "50 01", ["7F 50 11"]),
    # --- Step 2: service not in active session -> 0x7F
    ("0x27_in_default", [], "27 01", ["7F 27 7F"]),
    ("0x2E_in_default", [], "2E 01 00 32", ["7F 2E 7F"]),
    ("0x31_in_default", [], "31 01 02 01", ["7F 31 7F"]),
    ("0x14_in_programming", ["prog"], "14 FF FF FF", ["7F 14 7F"]),
    ("0x19_in_programming", ["prog"], "19 02 FF", ["7F 19 7F"]),
    ("session_check_before_length", [], "27", ["7F 27 7F"]),
    # --- Step 3: generic length -> 0x13
    ("0x10_too_short", [], "10", ["7F 10 13"]),
    ("0x10_too_long", [], "10 03 00", ["7F 10 13"]),
    ("0x11_too_short", [], "11", ["7F 11 13"]),
    ("0x11_too_long", [], "11 01 00", ["7F 11 13"]),
    ("0x14_too_short", [], "14 FF FF", ["7F 14 13"]),
    ("0x14_too_long", [], "14 FF FF FF 00", ["7F 14 13"]),
    ("0x19_no_subfunction", [], "19", ["7F 19 13"]),
    ("0x22_no_did", [], "22", ["7F 22 13"]),
    ("0x22_half_did", [], "22 F1", ["7F 22 13"]),
    ("0x22_odd_did_list", [], "22 F1 90 F1", ["7F 22 13"]),
    ("0x27_no_subfunction", ["ext"], "27", ["7F 27 13"]),
    ("0x2E_no_data", ["ext"], "2E 01 00", ["7F 2E 13"]),
    ("0x31_no_routine_id", ["ext"], "31 01 02", ["7F 31 13"]),
    ("0x3E_too_short", [], "3E", ["7F 3E 13"]),
    ("0x3E_too_long", [], "3E 00 00", ["7F 3E 13"]),
    ("length_before_subfunction", [], "10 05 00", ["7F 10 13"]),
    # --- Step 4: subfunction not supported -> 0x12
    ("0x10_unknown_session", [], "10 05", ["7F 10 12"]),
    ("0x11_unsupported_reset_type", [], "11 02", ["7F 11 12"]),
    ("0x19_unsupported_report_type", [], "19 01 FF", ["7F 19 12"]),
    ("0x19_bit7_is_not_suppress", [], "19 82 FF", ["7F 19 12"]),
    ("0x27_unknown_level", ["ext"], "27 05", ["7F 27 12"]),
    ("0x27_bit7_is_not_suppress", ["ext"], "27 81", ["7F 27 12"]),
    ("0x31_unknown_control_type", ["ext"], "31 04 02 01", ["7F 31 12"]),
    ("0x3E_nonzero_subfunction", [], "3E 01", ["7F 3E 12"]),
    ("suppress_bit_never_hides_nrc_3E", [], "3E 81", ["7F 3E 12"]),
    ("suppress_bit_never_hides_nrc_11", [], "11 82", ["7F 11 12"]),
    # --- Step 5: subfunction not allowed in session -> 0x7E
    ("0x27_level3_seed_in_extended", ["ext"], "27 03", ["7F 27 7E"]),
    ("0x27_level3_key_in_extended", ["ext"], "27 04 00 00 00 00", ["7F 27 7E"]),
    ("0x27_level1_seed_in_programming", ["prog"], "27 01", ["7F 27 7E"]),
    # --- Step 5b: subfunction-specific length -> 0x13
    ("0x19_02_missing_mask", [], "19 02", ["7F 19 13"]),
    ("0x19_02_extra_byte", [], "19 02 FF 00", ["7F 19 13"]),
    ("0x27_seed_with_data", ["ext"], "27 01 00", ["7F 27 13"]),
    ("0x27_key_too_short", ["ext", "27 01"], "27 02 00 00 00", ["7F 27 13"]),
    ("0x27_key_too_long", ["ext", "27 01"], "27 02 00 00 00 00 00", ["7F 27 13"]),
]

SERVICE_CASES: list[Case] = [
    # --- 0x14 ClearDiagnosticInformation
    ("0x14_unknown_group", [], "14 12 34 56", ["7F 14 31"]),
    ("0x14_nvm_fault", ["nvm_fault"], "14 FF FF FF", ["7F 14 72"]),
    ("0x14_unknown_group_before_nvm_fault", ["nvm_fault"], "14 00 00 01", ["7F 14 31"]),
    # --- 0x22 ReadDataByIdentifier
    ("0x22_unknown_did", [], "22 12 34", ["7F 22 31"]),
    ("0x22_multi_one_unknown", [], "22 F1 90 12 34", ["7F 22 31"]),
    ("0x22_did_not_readable_in_default", [], "22 01 50", ["7F 22 31"]),
    ("0x22_response_too_long", [], "22" + " F1 90" * 216, ["7F 22 14"]),
    # --- 0x2E WriteDataByIdentifier
    ("0x2E_unknown_did", ["ext"], "2E 12 34 00", ["7F 2E 31"]),
    ("0x2E_read_only_did", UNLOCK1, "2E F1 90 " + VIN, ["7F 2E 31"]),
    ("0x2E_read_only_did_locked", ["ext"], "2E 01 10 00", ["7F 2E 31"]),
    ("0x2E_not_writable_in_session", UNLOCK3, "2E 01 00 32", ["7F 2E 31"]),
    ("0x2E_wrong_data_length", UNLOCK1, "2E 01 00 10 20", ["7F 2E 13"]),
    ("0x2E_length_checked_before_security", ["ext"], "2E 01 00 10 20", ["7F 2E 13"]),
    ("0x2E_without_security", ["ext"], "2E 01 00 32", ["7F 2E 33"]),
    ("0x2E_coding_variant_level3", UNLOCK3, "2E 01 60 00 02", ["6E 01 60"]),
    ("0x2E_security_before_conditions", ["prog", "speed=30"], "2E 01 50 01", ["7F 2E 33"]),
    ("0x2E_condition_vehicle_moving", [*UNLOCK3, "speed=30"], "2E 01 50 01", ["7F 2E 22"]),
    ("0x2E_condition_before_range", [*UNLOCK3, "speed=30"], "2E 01 50 07", ["7F 2E 22"]),
    ("0x2E_value_above_max", UNLOCK1, "2E 01 00 65", ["7F 2E 31"]),
    ("0x2E_value_below_min", UNLOCK1, "2E 01 30 00", ["7F 2E 31"]),
    ("0x2E_nvm_fault", [*UNLOCK1, "nvm_fault"], "2E 01 00 32", ["7F 2E 72"]),
    ("0x2E_range_before_nvm_fault", [*UNLOCK1, "nvm_fault"], "2E 01 00 FF", ["7F 2E 31"]),
    # --- 0x31 RoutineControl
    ("0x31_unknown_routine", ["ext"], "31 01 12 34", ["7F 31 31"]),
    ("0x31_routine_not_in_session", UNLOCK1, "31 01 02 03", ["7F 31 31"]),
    ("0x31_routine_lacks_stop", UNLOCK3, "31 02 02 03", ["7F 31 12"]),
    ("0x31_missing_option_record", UNLOCK1, "31 01 02 02", ["7F 31 13"]),
    ("0x31_unexpected_option_record", UNLOCK1, "31 01 02 01 FF", ["7F 31 13"]),
    ("0x31_stop_with_extra_byte", UNLOCK1, "31 02 02 01 00", ["7F 31 13"]),
    ("0x31_without_security", ["ext"], "31 01 02 01", ["7F 31 33"]),
    ("0x31_condition_vehicle_moving", [*UNLOCK1, "speed=30"], "31 01 02 02 00", ["7F 31 22"]),
    ("0x31_stop_before_start", UNLOCK1, "31 02 02 01", ["7F 31 24"]),
    ("0x31_results_before_start", UNLOCK1, "31 03 02 01", ["7F 31 24"]),
    ("0x31_start_while_running", [*UNLOCK1, "31 01 02 01"], "31 01 02 01", ["7F 31 24"]),
    ("0x31_stop_twice", [*UNLOCK1, "31 01 02 01", "31 02 02 01"], "31 02 02 01", ["7F 31 24"]),
    (
        "0x31_stop_allowed_while_moving",
        [*UNLOCK1, "31 01 02 02 00", "speed=30"],
        "31 02 02 02",
        ["71 02 02 02 03"],
    ),
    # --- 0x27 SecurityAccess
    ("0x27_key_without_seed", ["ext"], "27 02 00 00 00 00", ["7F 27 24"]),
    ("0x27_invalid_key", ["ext", "27 01"], "27 02 00 00 00 00", ["7F 27 35"]),
    ("0x27_second_invalid_key", ["ext", "badkey1", "27 01"], "27 02 00 00 00 00", ["7F 27 35"]),
    (
        "0x27_third_invalid_key_locks",
        ["ext", "badkey1", "badkey1", "27 01"],
        "27 02 00 00 00 00",
        ["7F 27 36"],
    ),
    ("0x27_seed_during_delay", ["ext", "badkey1", "badkey1", "badkey1"], "27 01", ["7F 27 37"]),
    (
        "0x27_key_during_delay",
        ["ext", "badkey1", "badkey1", "badkey1"],
        "27 02 00 00 00 00",
        ["7F 27 37"],
    ),
    (
        "0x27_seed_one_ms_before_delay_expiry",
        ["ext", "badkey1", "badkey1", "badkey1", "+4000", "3E 80", "+4000", "3E 80", "+1999"],
        "27 01",
        ["7F 27 37"],
    ),
    (
        "0x27_seed_after_delay_expiry",
        ["ext", "badkey1", "badkey1", "badkey1", "+4000", "3E 80", "+4000", "3E 80", "+2000"],
        "27 01",
        ["67 01 6C DD 4E BF"],  # derive_seed(1, counter=3): three seeds issued before
    ),
    (
        "0x27_invalid_key_after_delay_relocks",
        [
            "ext", "badkey1", "badkey1", "badkey1",
            "+4000", "3E 80", "+4000", "3E 80", "+2000", "27 01",
        ],
        "27 02 00 00 00 00",
        ["7F 27 36"],
    ),
    ("0x27_seed_consumed_by_invalid_key", ["ext", "badkey1"], "27 02 9A 06 8F 73", ["7F 27 24"]),
    ("0x27_session_change_clears_seed", ["ext", "27 01", "10 03"], "27 02 9A 06 8F 73",
     ["7F 27 24"]),
]

POSITIVE_CASES: list[Case] = [
    # --- 0x10
    ("0x10_default", [], "10 01", ["50 01 " + TIMING]),
    ("0x10_extended", [], "10 03", ["50 03 " + TIMING]),
    ("0x10_programming", [], "10 02", ["50 02 " + TIMING]),
    ("0x10_suppressed", [], "10 83", []),
    ("0x10_suppressed_still_switches", ["10 83"], "22 F1 86", ["62 F1 86 03"]),
    ("0x10_locks_security", [*UNLOCK1, "10 03"], "2E 01 00 32", ["7F 2E 33"]),
    ("0x10_clears_routines", [*UNLOCK1, "31 01 02 01", "10 03", "unlock1"], "31 03 02 01",
     ["7F 31 24"]),
    # --- 0x11
    ("0x11_hard_reset", [], "11 01", ["51 01"]),
    ("0x11_soft_reset", ["ext"], "11 03", ["51 03"]),
    ("0x11_suppressed", ["ext"], "11 81", []),
    ("0x11_returns_to_default", [*UNLOCK1, "11 01"], "22 F1 86", ["62 F1 86 01"]),
    ("0x11_locks_security", [*UNLOCK1, "11 01", "ext"], "2E 01 00 32", ["7F 2E 33"]),
    # --- 0x14
    ("0x14_clear_all", ["dtc:B10101=09"], "14 FF FF FF", ["54"]),
    ("0x14_clear_one", ["dtc:B10101=09"], "14 B1 01 01", ["54"]),
    ("0x14_clear_all_effect", ["dtc:B10101=09", "dtc:B10310=2F", "14 FF FF FF"], "19 02 FF",
     ["59 02 FF"]),
    ("0x14_clear_one_effect", ["dtc:B10101=09", "dtc:B10310=2F", "14 B1 01 01"], "19 02 FF",
     ["59 02 FF B1 03 10 2F"]),
    # --- 0x19
    ("0x19_no_dtcs", [], "19 02 FF", ["59 02 FF"]),
    ("0x19_one_dtc", ["dtc:B10101=09"], "19 02 FF", ["59 02 FF B1 01 01 09"]),
    ("0x19_mask_filters", ["dtc:B10101=09", "dtc:B10205=01"], "19 02 08",
     ["59 02 FF B1 01 01 09"]),
    ("0x19_all_in_spec_order", ["dtc:B10310=01", "dtc:B10101=01", "dtc:B10205=04"], "19 02 FF",
     ["59 02 FF B1 01 01 01 B1 02 05 04 B1 03 10 01"]),
    ("0x19_zero_mask", ["dtc:B10101=09"], "19 02 00", ["59 02 FF"]),
    # --- 0x22
    ("0x22_vin", [], "22 F1 90", ["62 F1 90 " + VIN]),
    ("0x22_multi_did", [], "22 F1 87 01 00 01 30", ["62 F1 87 " + PART + " 01 00 32 01 30 03"]),
    ("0x22_duplicate_did", [], "22 01 00 01 00", ["62 01 00 32 01 00 32"]),
    ("0x22_active_session_default", [], "22 F1 86", ["62 F1 86 01"]),
    ("0x22_active_session_extended", ["ext"], "22 F1 86", ["62 F1 86 03"]),
    ("0x22_vehicle_speed_live", ["speed=30"], "22 01 40", ["62 01 40 1E"]),
    ("0x22_condition_gated_did_in_extended", ["ext"], "22 01 50", ["62 01 50 00"]),
    ("0x22_coding_variant_2byte", [], "22 01 60", ["62 01 60 00 01"]),
    ("0x22_max_length_fits", [], "22" + " F1 90" * 215, ["62" + (" F1 90 " + VIN) * 215]),
    # --- 0x27
    ("0x27_seed_level1", ["ext"], "27 01", ["67 01 " + SEED_L1_C0]),
    ("0x27_seed_level3", ["prog"], "27 03", ["67 03 " + SEED_L3_C0]),
    ("0x27_seed_counter_advances", ["ext", "27 01"], "27 01", ["67 01 32 A3 14 85"]),
    ("0x27_key_level1", ["ext", "27 01"], "27 02 9A 06 8F 73", ["67 02"]),
    ("0x27_zero_seed_when_unlocked", UNLOCK1, "27 01", ["67 01 00 00 00 00"]),
    ("0x27_key_after_zero_seed", [*UNLOCK1, "27 01"], "27 02 00 00 00 00", ["7F 27 24"]),
    # --- 0x2E
    ("0x2E_write_ok", UNLOCK1, "2E 01 00 64", ["6E 01 00"]),
    ("0x2E_write_readback", [*UNLOCK1, "2E 01 00 64"], "22 01 00", ["62 01 00 64"]),
    ("0x2E_write_range_edge_min", UNLOCK1, "2E 01 30 01", ["6E 01 30"]),
    ("0x2E_write_range_edge_max", UNLOCK1, "2E 01 30 05", ["6E 01 30"]),
    ("0x2E_condition_met_stationary", UNLOCK3, "2E 01 50 01", ["6E 01 50"]),
    ("0x2E_write_2byte", UNLOCK3, "2E 01 60 BE EF", ["6E 01 60"]),
    # --- 0x31
    ("0x31_start", UNLOCK1, "31 01 02 01", ["71 01 02 01 01"]),
    ("0x31_start_with_option", UNLOCK1, "31 01 02 02 07", ["71 01 02 02 01"]),
    ("0x31_stop", [*UNLOCK1, "31 01 02 01"], "31 02 02 01", ["71 02 02 01 03"]),
    ("0x31_results_running", [*UNLOCK1, "31 01 02 01"], "31 03 02 01", ["71 03 02 01 01"]),
    ("0x31_results_stopped", [*UNLOCK1, "31 01 02 01", "31 02 02 01"], "31 03 02 01",
     ["71 03 02 01 03"]),
    ("0x31_restart_after_stop", [*UNLOCK1, "31 01 02 01", "31 02 02 01"], "31 01 02 01",
     ["71 01 02 01 01"]),
    ("0x31_suppressed_start", UNLOCK1, "31 81 02 01", []),
    ("0x31_long_routine_pending", UNLOCK3, "31 01 02 03", ["7F 31 78", "71 01 02 03 02"]),
    ("0x31_long_routine_pending_ignores_suppress", UNLOCK3, "31 81 02 03",
     ["7F 31 78", "71 01 02 03 02"]),
    ("0x31_long_routine_results", [*UNLOCK3, "31 01 02 03"], "31 03 02 03", ["71 03 02 03 02"]),
    ("0x31_long_routine_restart_after_complete", [*UNLOCK3, "31 01 02 03"], "31 01 02 03",
     ["7F 31 78", "71 01 02 03 02"]),
    # --- 0x3E
    ("0x3E_response", [], "3E 00", ["7E 00"]),
    ("0x3E_suppressed", [], "3E 80", []),
    # --- empty request
    ("empty_request_ignored", [], "", []),
]

TIMING_CASES: list[Case] = [
    ("s3_not_expired_at_limit", ["t=0", "ext", "t=5000"], "22 F1 86", ["62 F1 86 03"]),
    ("s3_expired_just_after_limit", ["t=0", "ext", "t=5001"], "22 F1 86", ["62 F1 86 01"]),
    ("s3_kept_alive_by_tester_present", ["t=0", "ext", "t=4000", "3E 80", "t=8000"],
     "22 F1 86", ["62 F1 86 03"]),
    ("s3_kept_alive_by_negative_response", ["t=0", "ext", "t=4000", "27 05", "t=8000"],
     "22 F1 86", ["62 F1 86 03"]),
    ("s3_timeout_locks_security", ["t=0", *UNLOCK1, "t=6000"], "2E 01 00 32", ["7F 2E 7F"]),
    ("s3_timeout_then_reenter_still_locked", ["t=0", *UNLOCK1, "t=6000", "ext"],
     "2E 01 00 32", ["7F 2E 33"]),
    ("s3_not_applied_in_default", ["t=0", "t=60000"], "22 F1 86", ["62 F1 86 01"]),
    ("s3_timeout_clears_pending_seed", ["t=0", "ext", "27 01", "t=6000", "ext"],
     "27 02 9A 06 8F 73", ["7F 27 24"]),
    ("lockout_survives_session_change",
     ["ext", "badkey1", "badkey1", "badkey1", "10 01", "ext"], "27 01", ["7F 27 37"]),
]

ALL_CASES = GENERIC_CASES + SERVICE_CASES + POSITIVE_CASES + TIMING_CASES


@pytest.mark.parametrize(
    ("setup", "request_hex", "expected"),
    [pytest.param(s, r, e, id=i) for i, s, r, e in ALL_CASES],
)
def test_rules_table(spec: EcuSpec, setup: list[str], request_hex: str, expected: list[str]) -> None:
    """Run setup, send the request, and compare the exact expected responses."""
    session = RulesSession(spec)
    run_setup(session, setup)
    result = session.send(hx(request_hex))
    got = [r.hex(" ").upper() for r in result.responses]
    want = [hx(e).hex(" ").upper() for e in expected]
    assert got == want, "\n".join(result.trace)


def test_case_ids_unique() -> None:
    """Table ids must be unique so failures are unambiguous."""
    ids = [c[0] for c in ALL_CASES]
    assert len(ids) == len(set(ids))
