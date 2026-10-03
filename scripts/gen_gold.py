"""One-off script that authors data/gold/gold_tests.yaml.

Request bytes are encoded with the protocol builders (pure wire encoding).
Expected response bytes are written by hand from docs/behaviour_contract.md.
This script is run once; it is not part of the package.
"""

from __future__ import annotations

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
from uds_assistant.protocol.codec import UdsRequest
from uds_assistant.testgen.model import (
    AdvanceTimeStep,
    Citation,
    SendStep,
    SetDtcStatusStep,
    SetEnvironmentStep,
    TestCase,
    dump_tests,
)

VIN = bytes.fromhex("53594e544845544943424d303030303031")
PARTNUM = bytes.fromhex("42434d2d31323334352d")
SERIAL = bytes.fromhex("5345303030303031")


def S(req: UdsRequest, *expected: str, desc: str = "") -> SendStep:
    return SendStep(request_hex=req.to_bytes().hex(), expected_responses_hex=list(expected), description=desc)


def RAW(request_hex: str, *expected: str, desc: str = "") -> SendStep:
    return SendStep(request_hex=request_hex, expected_responses_hex=list(expected), description=desc)


tests: list[TestCase] = []


def add(
    id: str,
    title: str,
    category: str,
    reqs: list[str],
    steps: list,
    citations: list[Citation],
    explanation: str,
) -> None:
    tests.append(
        TestCase(
            id=id,
            title=title,
            requirement_ids=reqs,
            category=category,
            template_id=None,
            steps=steps,
            citations=citations,
            explanation=explanation,
            origin="gold",
        )
    )


BC = "behaviour_contract"
SPEC = "bcm_spec.yaml"

# 1
add(
    "gold_read_vin_default", "Read VIN in default session", "positive", ["REQ-001"],
    [S(read_did(0xF190), "62f190" + VIN.hex())],
    [Citation(source=SPEC, ref="dids.VIN")], "VIN is readable in every session; default value echoed.",
)
# 2
add(
    "gold_read_vin_extended", "Read VIN in extended session", "positive", ["REQ-001"],
    [S(session_control(0x03), "5003" + "0032" + "01f4"), S(read_did(0xF190), "62f190" + VIN.hex())],
    [Citation(source=SPEC, ref="dids.VIN")], "VIN readable in extended session too.",
)
# 3
add(
    "gold_read_partnum_serial_multi", "Multi-DID read: part number + serial", "positive", ["REQ-002"],
    [S(read_did(0xF187, 0xF18C), "62" + "f187" + PARTNUM.hex() + "f18c" + SERIAL.hex())],
    [Citation(source=BC, ref="0x22 ReadDataByIdentifier")], "Two DIDs in one request, both echoed in order.",
)
# 4
add(
    "gold_read_unknown_did", "Read an unknown DID", "negative", ["REQ-001"],
    [S(read_did(0x9999), "7f2231")],
    [Citation(source=BC, ref="0x22 checks")], "Unknown DID -> NRC 0x31.",
)
# 5
add(
    "gold_session_to_extended", "Session control: default -> extended", "session", ["REQ-003"],
    [S(session_control(0x03), "500300320" "1f4".replace(" ", ""))],
    [Citation(source=BC, ref="0x10 DiagnosticSessionControl")],
    "Positive response carries session byte + P2(50ms)/P2*(5000ms/10=500) timing.",
)
# 6
add(
    "gold_session_back_default", "Session control: extended -> default", "session", ["REQ-003"],
    [S(session_control(0x03), "50030032" + "01f4"), S(session_control(0x01), "50010032" + "01f4")],
    [Citation(source=BC, ref="0x10 DiagnosticSessionControl")], "Can return to default session from extended.",
)
# 7
add(
    "gold_session_programming", "Session control: default -> programming", "session", ["REQ-004"],
    [S(session_control(0x02), "50020032" + "01f4")],
    [Citation(source=BC, ref="0x10 DiagnosticSessionControl")], "Programming session has the same timing record.",
)
# 8
add(
    "gold_session_unsupported_sub", "Session control with unsupported subfunction", "negative", ["REQ-003"],
    [RAW("1005", "7f1012")],
    [Citation(source=BC, ref="Subfunction supported")], "0x10 only supports 01/02/03 -> NRC 0x12 for 0x05.",
)
# 9
add(
    "gold_session_wrong_length", "Session control with extra byte", "negative", ["REQ-003"],
    [RAW("100300", "7f1013")],
    [Citation(source=BC, ref="Generic length")], "0x10 must be exactly 2 bytes -> NRC 0x13.",
)
# 10
add(
    "gold_ecu_reset_hard", "ECU hard reset", "positive", ["REQ-013"],
    [S(ecu_reset(0x01), "5101")],
    [Citation(source=BC, ref="0x11 ECUReset")], "Hard reset (0x01) is supported -> 51 01.",
)
# 11
add(
    "gold_ecu_reset_soft", "ECU soft reset", "positive", ["REQ-013"],
    [S(ecu_reset(0x03), "5103")],
    [Citation(source=BC, ref="0x11 ECUReset")], "Soft reset (0x03) is supported -> 51 03.",
)
# 12
add(
    "gold_ecu_reset_bad_sub", "ECU reset with unsupported subfunction", "negative", ["REQ-013"],
    [S(ecu_reset(0x02), "7f1112")],
    [Citation(source=SPEC, ref="ecu_reset.supported_subfunctions")],
    "Only 0x01/0x03 are supported -> NRC 0x12 for 0x02.",
)
# 13
add(
    "gold_security_not_allowed_default_session", "SecurityAccess not allowed in default session", "session", [],
    [S(security_request_seed(0x01), "7f277f")],
    [Citation(source=SPEC, ref="sessions.default.allowed_services")],
    "0x27 is globally supported but not in default session's allowed_services -> NRC 0x7F.",
)
# 14
add(
    "gold_unsupported_sid", "Completely unsupported service id", "negative", [],
    [RAW("2f01", "7f2f11")],
    [Citation(source=BC, ref="Service supported")], "0x2F is not in any session's allowed_services -> NRC 0x11.",
)
# 15
add(
    "gold_write_without_unlock", "Write secured DID without unlocking", "security", ["REQ-005"],
    [S(session_control(0x03), "50030032" + "01f4"), S(write_did(0x0100, bytes([0x14])), "7f2e33")],
    [Citation(source=BC, ref="0x2E security check")], "write_security_level 0x01 required but not unlocked -> 0x33.",
)
# 16
add(
    "gold_write_secured_positive_lighting", "Unlock level 1, write & read back lighting brightness", "positive",
    ["REQ-005"],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        S(write_did(0x0100, bytes([0x14])), "6e0100"),
        S(read_did(0x0100), "620100" + "14"),
    ],
    [Citation(source=SPEC, ref="dids.interior_lighting_brightness_pct")],
    "Session -> unlock level 1 -> write 20 (0x14) -> read back confirms.",
)
# 17
add(
    "gold_write_secured_positive_ambient_color", "Unlock level 1, write ambient color to max", "positive",
    ["REQ-006"],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        S(write_did(0x0101, bytes([0x0F])), "6e0101"),
        S(read_did(0x0101), "620101" + "0f"),
    ],
    [Citation(source=SPEC, ref="dids.ambient_lighting_color_index")],
    "Value 0x0F is within range [0,15].",
)
# 18
add(
    "gold_write_out_of_range_wiper", "Write wiper sensitivity above max", "negative", ["REQ-007"],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        S(write_did(0x0130, bytes([0x06])), "7f2e31"),
    ],
    [Citation(source=SPEC, ref="dids.wiper_sensitivity_level")], "value_range is [1,5]; 6 is out of range -> 0x31.",
)
# 19
add(
    "gold_write_out_of_range_brightness", "Write brightness above 100", "negative", ["REQ-008"],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        S(write_did(0x0100, bytes([0x65])), "7f2e31"),
    ],
    [Citation(source=SPEC, ref="dids.interior_lighting_brightness_pct")], "101 (0x65) is outside [0,100] -> 0x31.",
)
# 20
add(
    "gold_write_wrong_length", "Write brightness with wrong data length", "negative", ["REQ-005"],
    [S(session_control(0x03), "50030032" + "01f4"), S(write_did(0x0100, bytes([0x00, 0x14])), "7f2e13")],
    [Citation(source=BC, ref="0x2E length check")], "Length check happens before the security check -> 0x13.",
)
# 21
add(
    "gold_write_readonly_did", "Write a read-only DID", "negative", [],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        S(write_did(0x0110, bytes([0x00])), "7f2e31"),
    ],
    [Citation(source=SPEC, ref="dids.driver_door_lock_state")], "Empty write_sessions -> always NRC 0x31.",
)
# 22
add(
    "gold_write_unknown_did", "Write an unknown DID", "negative", [],
    [S(session_control(0x03), "50030032" + "01f4"), S(write_did(0x9999, bytes([0x00])), "7f2e31")],
    [Citation(source=BC, ref="0x2E checks")], "Unknown DID -> NRC 0x31 (in a session where 0x2E is allowed).",
)
# 23
add(
    "gold_security_seed_level1", "Request seed for level 1", "positive", [],
    [S(session_control(0x03), "50030032" + "01f4"), S(security_request_seed(0x01), "6701950677e8")],
    [Citation(source=BC, ref="0x27 seed request")], "First seed for level 1 (counter 0) is deterministic.",
)
# 24
add(
    "gold_security_wrong_key_once", "Send one wrong key", "security", ["REQ-010"],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("00000000")), "7f2735"),
    ],
    [Citation(source=BC, ref="0x27 wrong key")], "Wrong key, attempt 1 of 3 -> NRC 0x35.",
)
# 25
add(
    "gold_security_lockout_after_3", "Lockout after 3 wrong keys, then 0x37", "security", ["REQ-010"],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("00000000")), "7f2735"),
        S(security_request_seed(0x01), "670132a31485"),
        S(security_send_key(0x02, bytes.fromhex("00000000")), "7f2735"),
        S(security_request_seed(0x01), "6701cf40b122"),
        S(security_send_key(0x02, bytes.fromhex("00000000")), "7f2736"),
        S(security_request_seed(0x01), "7f2737"),
    ],
    [Citation(source=BC, ref="0x27 lockout")],
    "3rd wrong key reaches max_attempts -> 0x36 and arms a 10s delay; further seed requests get 0x37.",
)
# 26
add(
    "gold_security_key_without_seed", "Send key with no pending seed", "negative", [],
    [S(session_control(0x03), "50030032" + "01f4"), S(security_send_key(0x02, bytes.fromhex("00000000")), "7f2724")],
    [Citation(source=BC, ref="0x27 key without pending seed")], "No requestSeed first -> NRC 0x24.",
)
# 27
add(
    "gold_security_level3_subfunction_wrong_session", "Level 3 subfunction not allowed in extended session",
    "session", [],
    [S(session_control(0x03), "50030032" + "01f4"), RAW("2703", "7f277e")],
    [Citation(source=SPEC, ref="security_levels.programming.allowed_sessions")],
    "Level 3's seed subfunction (0x03) is only allowed in programming session (0x02) -> 0x7E.",
)
# 28
add(
    "gold_routine_start_without_security", "Start door calibration routine without unlocking", "security", [],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(routine_control(0x01, 0x0202, bytes([0x00])), "7f3133"),
    ],
    [Citation(source=SPEC, ref="routines.door_actuator_calibration")], "security_level 0x01 required -> NRC 0x33.",
)
# 29
add(
    "gold_routine_lighting_full_sequence", "Full lighting self-test routine sequence", "positive", ["REQ-011"],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        S(routine_control(0x01, 0x0201), "71010201" + "01"),
        S(routine_control(0x02, 0x0201), "71020201" + "03"),
        S(routine_control(0x01, 0x0201), "71010201" + "01"),
        S(routine_control(0x03, 0x0201), "71030201" + "01"),
    ],
    [Citation(source=SPEC, ref="routines.lighting_self_test")],
    "start -> stop -> restart (allowed after stopped) -> results reports RUNNING (0x01).",
)
# 30
add(
    "gold_routine_stop_before_start", "Stop lighting routine before it started", "negative", ["REQ-011"],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        S(routine_control(0x02, 0x0201), "7f3124"),
    ],
    [Citation(source=BC, ref="0x31 sequence")], "Stop before start -> NRC 0x24.",
)
# 31
add(
    "gold_routine_results_before_start", "Request lighting routine results before start", "negative", ["REQ-011"],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        S(routine_control(0x03, 0x0201), "7f3124"),
    ],
    [Citation(source=BC, ref="0x31 sequence")], "Results before start -> NRC 0x24.",
)
# 32
add(
    "gold_routine_door_cal_condition_fail", "Start door calibration while vehicle moving", "negative", ["REQ-012"],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        SetEnvironmentStep(vehicle_speed_kph=10, description="Vehicle moving."),
        S(routine_control(0x01, 0x0202, bytes([0x00])), "7f3122"),
    ],
    [Citation(source=SPEC, ref="routines.door_actuator_calibration")], "vehicle_stationary not met -> NRC 0x22.",
)
# 33
add(
    "gold_routine_door_cal_positive", "Start door calibration while stationary", "positive", ["REQ-012"],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        S(routine_control(0x01, 0x0202, bytes([0x00])), "71010202" + "01"),
    ],
    [Citation(source=SPEC, ref="routines.door_actuator_calibration")], "Vehicle stationary by default -> starts fine.",
)
# 34
add(
    "gold_routine_nvm_restore_long_running", "Long-running NVM factory restore start", "timing", [],
    [
        S(session_control(0x02), "50020032" + "01f4"),
        S(security_request_seed(0x03), "67030b7ced5e"),
        S(security_send_key(0x04, bytes.fromhex("20a92dba")), "6704"),
        S(routine_control(0x01, 0x0203), "7f3178", "71010203" + "02"),
    ],
    [Citation(source=BC, ref="Long-running routines")],
    "Start answers with NRC 0x78 responsePending, then completes immediately (status 0x02).",
)
# 35
add(
    "gold_routine_nvm_restore_wrong_session", "NVM restore attempted in default session", "session", [],
    [S(routine_control(0x01, 0x0203), "7f317f")],
    [Citation(source=SPEC, ref="sessions.default.allowed_services")], "0x31 not allowed in default session -> 0x7F.",
)
# 36
add(
    "gold_dtc_read_default", "Read DTCs by status mask at power-on", "positive", ["REQ-014"],
    [S(read_dtc_by_status_mask(0xFF), "590 2ff".replace(" ", ""))],
    [Citation(source=BC, ref="0x19 subfunction 02")], "All DTC statuses start at 0x00 -> no DTC matches any mask.",
)
# 37
add(
    "gold_dtc_read_bad_sub", "ReadDTCInformation with unsupported subfunction", "negative", ["REQ-014"],
    [RAW("1901ff", "7f1912")],
    [Citation(source=SPEC, ref="read_dtc_supported_subfunctions")], "Only 0x02 is supported -> NRC 0x12.",
)
# 38
add(
    "gold_dtc_set_and_read", "Inject a DTC status and read it back with a mask", "positive", [],
    [
        SetDtcStatusStep(code="B10101", status=0x08, description="Confirmed bit set."),
        S(read_dtc_by_status_mask(0x08), "590 2ff".replace(" ", "") + "b1010108"),
    ],
    [Citation(source=BC, ref="0x19 subfunction 02")], "DTC matches mask 0x08 and is reported with status & 0xFF.",
)
# 39
add(
    "gold_dtc_clear_all", "Clear all DTCs", "positive", [],
    [
        SetDtcStatusStep(code="B10101", status=0x08),
        S(read_dtc_by_status_mask(0x08), "5902ff" + "b1010108"),
        S(clear_dtc(bytes.fromhex("ffffff")), "54"),
        S(read_dtc_by_status_mask(0x08), "5902ff"),
    ],
    [Citation(source=BC, ref="0x14 ClearDiagnosticInformation")], "Group 0xFFFFFF clears every DTC status.",
)
# 40
add(
    "gold_dtc_clear_specific", "Clear one specific DTC, others untouched", "positive", [],
    [
        SetDtcStatusStep(code="B10101", status=0x08),
        SetDtcStatusStep(code="B10205", status=0x08),
        S(clear_dtc(bytes.fromhex("b10101")), "54"),
        S(read_dtc_by_status_mask(0x08), "5902ff" + "b1020508"),
    ],
    [Citation(source=BC, ref="0x14 ClearDiagnosticInformation")], "Only the matching DTC number is cleared.",
)
# 41
add(
    "gold_dtc_clear_unknown_group", "Clear with an unknown DTC group", "negative", [],
    [RAW("14123456", "7f1431")],
    [Citation(source=BC, ref="0x14 which DTCs are cleared")], "Group not 0xFFFFFF and not a spec DTC -> NRC 0x31.",
)
# 42
add(
    "gold_dtc_clear_nvm_fault", "Clear DTCs while NVM write fault is active", "negative", [],
    [SetEnvironmentStep(nvm_write_fault=True), S(clear_dtc(bytes.fromhex("ffffff")), "7f1472")],
    [Citation(source=BC, ref="0x14 NVM fault")], "NVM fault flag active -> NRC 0x72, nothing cleared.",
)
# 43
add(
    "gold_write_nvm_fault", "Write a DID while NVM write fault is active", "negative", [],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        SetEnvironmentStep(nvm_write_fault=True),
        S(write_did(0x0100, bytes([0x14])), "7f2e72"),
    ],
    [Citation(source=BC, ref="0x2E NVM fault")], "NVM fault flag active on write -> NRC 0x72.",
)
# 44
add(
    "gold_tester_present", "TesterPresent keeps the S3 timer alive", "positive", ["REQ-015"],
    [S(tester_present(suppress_positive=False), "7e00")],
    [Citation(source=BC, ref="0x3E TesterPresent")], "0x3E 00 -> 0x7E 00.",
)
# 45
add(
    "gold_tester_present_suppressed", "TesterPresent with suppress bit set", "positive", [],
    [S(tester_present(suppress_positive=True))],
    [Citation(source=BC, ref="Suppress bit")], "Positive outcome suppressed -> no response frame sent.",
)
# 46
add(
    "gold_tester_present_bad_sub_not_suppressed", "Negative responses are never suppressed", "negative", [],
    [RAW("3e81", "7f3e12")],
    [Citation(source=BC, ref="Suppress bit")], "3E 81: bad subfunction with suppress bit set still answers 0x7F 3E 12.",
)
# 47
add(
    "gold_s3_timeout_reverts", "S3 timeout reverts session before next request", "timing", [],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        AdvanceTimeStep(ms=5001, description="Idle past s3_ms (5000)."),
        S(read_did(0xF186), "62f18601"),
    ],
    [Citation(source=BC, ref="S3 timeout")], "5001 ms idle > 5000 ms s3_ms -> reverted to default (0x01) before the read.",
)
# 48
add(
    "gold_s3_no_timeout_at_exactly_s3ms", "Exactly s3_ms idle does not expire the session", "timing", [],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        AdvanceTimeStep(ms=5000, description="Idle exactly s3_ms."),
        S(read_did(0xF186), "62f18603"),
    ],
    [Citation(source=BC, ref="S3 timeout")], "Idle strictly greater than s3_ms is required; exactly 5000 ms does not expire.",
)
# 49
add(
    "gold_ecu_reset_suppressed", "Suppressed ECU reset still changes state", "positive", [],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(ecu_reset(0x01, suppress_positive=True)),
        S(read_did(0xF186), "62f18601"),
    ],
    [Citation(source=BC, ref="Suppress bit")], "11 81 suppresses the response but still resets to default session.",
)
# 50
add(
    "gold_multi_did_read_one_bad", "Multi-DID read skips an unknown DID and answers the readable one", "positive",
    ["REQ-002"],
    [RAW("22f19099 99", "62f19053594e544845544943424d303030303031"), ],
    [Citation(source=BC, ref="0x22 checks")], "An unknown DID in a multi-DID request is skipped; the readable DID (VIN F190) is answered. NRC 0x31 only if no requested DID is readable.",
)
# fix request hex above (had stray formatting); rebuild properly below instead.
tests.pop()
add(
    "gold_multi_did_read_one_bad", "Multi-DID read skips an unknown DID and answers the readable one", "positive",
    ["REQ-002"],
    [S(read_did(0xF190, 0x9999), "62f19053594e544845544943424d303030303031")],
    [Citation(source=BC, ref="0x22 checks")], "An unknown DID in a multi-DID request is skipped; the readable DID (VIN F190) is answered. NRC 0x31 only if no requested DID is readable.",
)
# 51
add(
    "gold_duplicate_did_read", "Duplicate DIDs are allowed in one read request", "positive", [],
    [S(read_did(0x0140, 0x0140), "62" + "014000" + "014000")],
    [Citation(source=BC, ref="0x22 checks")], "Duplicate DIDs are allowed; vehicle speed defaults to 0.",
)
# 52
add(
    "gold_security_already_unlocked_seed", "Requesting a new seed while already unlocked", "security", [],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        S(security_request_seed(0x01), "670100000000"),
    ],
    [Citation(source=BC, ref="0x27 seed request, already unlocked")],
    "Already-unlocked level -> all-zero seed and no state change.",
)
# 53
add(
    "gold_read_vehicle_speed_live", "Live vehicle speed DID reflects environment", "positive", [],
    [SetEnvironmentStep(vehicle_speed_kph=42), S(read_did(0x0140), "62" + "0140" + "2a")],
    [Citation(source=BC, ref="0x22 live DIDs")], "DID 0x0140 is read live from the environment (42 = 0x2A).",
)
# 54
add(
    "gold_read_active_session_live", "Live active-session DID reflects the current session", "positive", [],
    [S(session_control(0x02), "50020032" + "01f4"), S(read_did(0xF186), "62f18602")],
    [Citation(source=BC, ref="0x22 live DIDs")], "DID 0xF186 is read live from the current session (0x02).",
)
# 55
add(
    "gold_write_coding_variant", "Unlock level 3 in programming session, write 2-byte coding variant", "positive",
    [],
    [
        S(session_control(0x02), "50020032" + "01f4"),
        S(security_request_seed(0x03), "67030b7ced5e"),
        S(security_send_key(0x04, bytes.fromhex("20a92dba")), "6704"),
        S(write_did(0x0160, bytes.fromhex("0005")), "6e0160"),
        S(read_did(0x0160), "620160" + "0005"),
    ],
    [Citation(source=SPEC, ref="dids.coding_variant_id")], "2-byte DID write/read round trip.",
)
# 56
add(
    "gold_write_factory_reset_flag_positive", "Write factory reset flag while stationary", "positive", ["REQ-009"],
    [
        S(session_control(0x02), "50020032" + "01f4"),
        S(security_request_seed(0x03), "67030b7ced5e"),
        S(security_send_key(0x04, bytes.fromhex("20a92dba")), "6704"),
        S(write_did(0x0150, bytes([0x01])), "6e0150"),
    ],
    [Citation(source=SPEC, ref="dids.factory_reset_flag")],
    "Programming session + level 3 + vehicle stationary (default) -> write succeeds.",
)
# 57
add(
    "gold_write_factory_reset_flag_moving", "Write factory reset flag while moving", "negative", ["REQ-009"],
    [
        S(session_control(0x02), "50020032" + "01f4"),
        S(security_request_seed(0x03), "67030b7ced5e"),
        S(security_send_key(0x04, bytes.fromhex("20a92dba")), "6704"),
        SetEnvironmentStep(vehicle_speed_kph=5),
        S(write_did(0x0150, bytes([0x01])), "7f2e22"),
    ],
    [Citation(source=SPEC, ref="dids.factory_reset_flag")], "vehicle_stationary not met -> NRC 0x22.",
)
# 58
add(
    "gold_security_wrong_level_unlock", "Correct key for the wrong level does not unlock it", "security", [],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("00000001")), "7f2735"),
    ],
    [Citation(source=BC, ref="0x27 key comparison")], "A key not equal to compute_key(seed, level) is rejected.",
)

# 59
add(
    "gold_write_unknown_did_default_session", "Unknown DID write in a session where 0x2E isn't allowed",
    "session", [],
    [RAW("2e999900", "7f2e7f")],
    [Citation(source=BC, ref="Service allowed in the active session")],
    "The service-in-session check (step 2) wins over the DID lookup (step 6): default session doesn't "
    "allow 0x2E at all, so this is 0x7F, not 0x31, even for an unknown DID.",
)
# 60
add(
    "gold_security_relocked_on_session_reentry", "Security is re-locked by any positive 0x10, even same session",
    "security", [],
    [
        S(session_control(0x03), "50030032" + "01f4"),
        S(security_request_seed(0x01), "6701950677e8"),
        S(security_send_key(0x02, bytes.fromhex("9a068f73")), "6702"),
        S(write_did(0x0100, bytes([0x14])), "6e0100"),
        S(session_control(0x03), "50030032" + "01f4"),
        S(write_did(0x0100, bytes([0x14])), "7f2e33"),
    ],
    [Citation(source=BC, ref="0x10 effects")],
    "Re-entering the same session still locks security; the write after re-entry needs unlocking again -> 0x33.",
)

print(f"Authored {len(tests)} gold tests.")
dump_tests(tests, "data/gold/gold_tests.yaml")
