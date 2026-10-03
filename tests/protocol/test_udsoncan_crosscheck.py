"""Cross-check our SID/NRC constants and encoded bytes against udsoncan."""

from __future__ import annotations

import pytest
import udsoncan
from udsoncan import services

from uds_assistant.protocol import builders
from uds_assistant.protocol.constants import Nrc, ServiceId

_SID_PAIRS = [
    (ServiceId.DIAGNOSTIC_SESSION_CONTROL, services.DiagnosticSessionControl),
    (ServiceId.ECU_RESET, services.ECUReset),
    (ServiceId.CLEAR_DIAGNOSTIC_INFORMATION, services.ClearDiagnosticInformation),
    (ServiceId.READ_DTC_INFORMATION, services.ReadDTCInformation),
    (ServiceId.READ_DATA_BY_IDENTIFIER, services.ReadDataByIdentifier),
    (ServiceId.SECURITY_ACCESS, services.SecurityAccess),
    (ServiceId.WRITE_DATA_BY_IDENTIFIER, services.WriteDataByIdentifier),
    (ServiceId.ROUTINE_CONTROL, services.RoutineControl),
    (ServiceId.TESTER_PRESENT, services.TesterPresent),
]


@pytest.mark.parametrize(("ours", "udsoncan_service"), _SID_PAIRS)
def test_sid_matches_udsoncan(ours: ServiceId, udsoncan_service: object) -> None:
    assert int(ours) == udsoncan_service._sid  # type: ignore[attr-defined]


_NRC_PAIRS = [
    (Nrc.GENERAL_REJECT, "GeneralReject"),
    (Nrc.SERVICE_NOT_SUPPORTED, "ServiceNotSupported"),
    (Nrc.SUB_FUNCTION_NOT_SUPPORTED, "SubFunctionNotSupported"),
    (Nrc.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT, "IncorrectMessageLengthOrInvalidFormat"),
    (Nrc.RESPONSE_TOO_LONG, "ResponseTooLong"),
    (Nrc.CONDITIONS_NOT_CORRECT, "ConditionsNotCorrect"),
    (Nrc.REQUEST_SEQUENCE_ERROR, "RequestSequenceError"),
    (Nrc.REQUEST_OUT_OF_RANGE, "RequestOutOfRange"),
    (Nrc.SECURITY_ACCESS_DENIED, "SecurityAccessDenied"),
    (Nrc.INVALID_KEY, "InvalidKey"),
    (Nrc.EXCEED_NUMBER_OF_ATTEMPTS, "ExceedNumberOfAttempts"),
    (Nrc.REQUIRED_TIME_DELAY_NOT_EXPIRED, "RequiredTimeDelayNotExpired"),
    (
        Nrc.REQUEST_CORRECTLY_RECEIVED_RESPONSE_PENDING,
        "RequestCorrectlyReceived_ResponsePending",
    ),
    (Nrc.GENERAL_PROGRAMMING_FAILURE, "GeneralProgrammingFailure"),
    (Nrc.SUB_FUNCTION_NOT_SUPPORTED_IN_ACTIVE_SESSION, "SubFunctionNotSupportedInActiveSession"),
    (Nrc.SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION, "ServiceNotSupportedInActiveSession"),
]


@pytest.mark.parametrize(("ours", "udsoncan_name"), _NRC_PAIRS)
def test_nrc_matches_udsoncan(ours: Nrc, udsoncan_name: str) -> None:
    assert int(ours) == getattr(udsoncan.Response.Code, udsoncan_name)


def test_session_control_matches_udsoncan() -> None:
    ours = builders.session_control(0x03).to_bytes()
    theirs = services.DiagnosticSessionControl.make_request(session=0x03).get_payload()
    assert ours == theirs


def test_ecu_reset_matches_udsoncan() -> None:
    ours = builders.ecu_reset(0x01).to_bytes()
    theirs = services.ECUReset.make_request(reset_type=0x01).get_payload()
    assert ours == theirs


def test_tester_present_matches_udsoncan() -> None:
    ours = builders.tester_present(suppress_positive=False).to_bytes()
    theirs = services.TesterPresent.make_request().get_payload()
    assert ours == theirs


def test_clear_dtc_matches_udsoncan() -> None:
    ours = builders.clear_dtc(bytes([0xFF, 0xFF, 0xFF])).to_bytes()
    theirs = services.ClearDiagnosticInformation.make_request(
        group=0xFFFFFF, standard_version=2006
    ).get_payload()
    assert ours == theirs


def test_read_dtc_by_status_mask_matches_udsoncan() -> None:
    ours = builders.read_dtc_by_status_mask(0x08).to_bytes()
    theirs = services.ReadDTCInformation.make_request(
        subfunction=0x02, status_mask=0x08
    ).get_payload()
    assert ours == theirs


def test_suppress_on_read_dtc_and_security_matches_udsoncan() -> None:
    def theirs(request: object) -> bytes:
        request.suppress_positive_response = True  # type: ignore[attr-defined]
        return request.get_payload()  # type: ignore[attr-defined]

    assert builders.read_dtc_by_status_mask(0x08, suppress_positive=True).to_bytes() == theirs(
        services.ReadDTCInformation.make_request(subfunction=0x02, status_mask=0x08)
    )
    assert builders.security_request_seed(0x01, suppress_positive=True).to_bytes() == theirs(
        services.SecurityAccess.make_request(level=0x01, mode=services.SecurityAccess.Mode.RequestSeed)
    )
    key = bytes([1, 2, 3, 4])
    assert builders.security_send_key(0x02, key, suppress_positive=True).to_bytes() == theirs(
        services.SecurityAccess.make_request(
            level=0x02, mode=services.SecurityAccess.Mode.SendKey, data=key
        )
    )


def test_read_did_matches_udsoncan() -> None:
    ours = builders.read_did(0xF190).to_bytes()
    theirs = services.ReadDataByIdentifier.make_request(didlist=0xF190, didconfig=None).get_payload()
    assert ours == theirs


def test_read_did_multiple_matches_udsoncan() -> None:
    ours = builders.read_did(0xF190, 0xF187).to_bytes()
    theirs = services.ReadDataByIdentifier.make_request(
        didlist=[0xF190, 0xF187], didconfig=None
    ).get_payload()
    assert ours == theirs


def test_write_did_matches_udsoncan() -> None:
    ours = builders.write_did(0x0100, bytes([0x32])).to_bytes()
    theirs = services.WriteDataByIdentifier.make_request(
        did=0x0100, value=0x32, didconfig={0x0100: "B"}
    ).get_payload()
    assert ours == theirs


def test_security_access_seed_matches_udsoncan() -> None:
    ours = builders.security_request_seed(0x01).to_bytes()
    theirs = services.SecurityAccess.make_request(
        level=0x01, mode=services.SecurityAccess.Mode.RequestSeed
    ).get_payload()
    assert ours == theirs


def test_security_access_send_key_matches_udsoncan() -> None:
    key = bytes([0xAA, 0xBB, 0xCC, 0xDD])
    ours = builders.security_send_key(0x02, key).to_bytes()
    theirs = services.SecurityAccess.make_request(
        level=0x02, mode=services.SecurityAccess.Mode.SendKey, data=key
    ).get_payload()
    assert ours == theirs


def test_routine_control_matches_udsoncan() -> None:
    ours = builders.routine_control(0x01, 0x0201).to_bytes()
    theirs = services.RoutineControl.make_request(routine_id=0x0201, control_type=0x01).get_payload()
    assert ours == theirs


def test_routine_control_with_option_record_matches_udsoncan() -> None:
    ours = builders.routine_control(0x01, 0x0201, option_record=bytes([0xAA])).to_bytes()
    theirs = services.RoutineControl.make_request(
        routine_id=0x0201, control_type=0x01, data=bytes([0xAA])
    ).get_payload()
    assert ours == theirs
