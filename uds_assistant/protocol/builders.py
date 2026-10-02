"""Typed request builders for each in-scope UDS service.

Each function returns a :class:`~uds_assistant.protocol.codec.UdsRequest`;
call ``.to_bytes()`` on the result to get the wire bytes.
"""

from __future__ import annotations

from uds_assistant.protocol.codec import UdsRequest
from uds_assistant.protocol.constants import ServiceId


def session_control(sub: int, suppress_positive: bool = False) -> UdsRequest:
    """Build a DiagnosticSessionControl (0x10) request for session ``sub``."""
    return UdsRequest(
        sid=ServiceId.DIAGNOSTIC_SESSION_CONTROL,
        subfunction=sub,
        suppress_positive=suppress_positive,
    )


def ecu_reset(sub: int, suppress_positive: bool = False) -> UdsRequest:
    """Build an ECUReset (0x11) request for reset type ``sub``."""
    return UdsRequest(
        sid=ServiceId.ECU_RESET, subfunction=sub, suppress_positive=suppress_positive
    )


def clear_dtc(group: bytes) -> UdsRequest:
    """Build a ClearDiagnosticInformation (0x14) request for a 3-byte DTC group mask."""
    if len(group) != 3:
        raise ValueError("DTC group mask must be exactly 3 bytes.")
    return UdsRequest(sid=ServiceId.CLEAR_DIAGNOSTIC_INFORMATION, data=group)


def read_dtc_by_status_mask(mask: int) -> UdsRequest:
    """Build a ReadDTCInformation (0x19) subfunction 0x02 request with a status mask."""
    if not 0 <= mask <= 0xFF:
        raise ValueError("Status mask must fit in one byte.")
    return UdsRequest(
        sid=ServiceId.READ_DTC_INFORMATION, subfunction=0x02, data=bytes([mask])
    )


def read_did(*dids: int) -> UdsRequest:
    """Build a ReadDataByIdentifier (0x22) request for one or more 2-byte DIDs."""
    if not dids:
        raise ValueError("At least one DID is required.")
    data = bytearray()
    for did in dids:
        if not 0 <= did <= 0xFFFF:
            raise ValueError(f"DID {did:#x} does not fit in two bytes.")
        data.extend(did.to_bytes(2, "big"))
    return UdsRequest(sid=ServiceId.READ_DATA_BY_IDENTIFIER, data=bytes(data))


def security_request_seed(level: int) -> UdsRequest:
    """Build a SecurityAccess (0x27) requestSeed request for an odd ``level``."""
    return UdsRequest(sid=ServiceId.SECURITY_ACCESS, subfunction=level)


def security_send_key(level: int, key: bytes) -> UdsRequest:
    """Build a SecurityAccess (0x27) sendKey request for an even ``level``."""
    return UdsRequest(sid=ServiceId.SECURITY_ACCESS, subfunction=level, data=key)


def write_did(did: int, data: bytes) -> UdsRequest:
    """Build a WriteDataByIdentifier (0x2E) request."""
    if not 0 <= did <= 0xFFFF:
        raise ValueError(f"DID {did:#x} does not fit in two bytes.")
    return UdsRequest(
        sid=ServiceId.WRITE_DATA_BY_IDENTIFIER, data=did.to_bytes(2, "big") + data
    )


def routine_control(sub: int, rid: int, option_record: bytes = b"") -> UdsRequest:
    """Build a RoutineControl (0x31) request for routine ``rid`` with subfunction ``sub``."""
    if not 0 <= rid <= 0xFFFF:
        raise ValueError(f"Routine ID {rid:#x} does not fit in two bytes.")
    return UdsRequest(
        sid=ServiceId.ROUTINE_CONTROL,
        subfunction=sub,
        data=rid.to_bytes(2, "big") + option_record,
    )


def tester_present(suppress_positive: bool = True) -> UdsRequest:
    """Build a TesterPresent (0x3E) request (subfunction 0x00, zeroSubFunction)."""
    return UdsRequest(
        sid=ServiceId.TESTER_PRESENT,
        subfunction=0x00,
        suppress_positive=suppress_positive,
    )
