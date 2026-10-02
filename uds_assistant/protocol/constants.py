"""UDS protocol constants: service IDs and negative response codes.

Values are cross-checked against ``udsoncan`` in
``tests/protocol/test_udsoncan_crosscheck.py``; they are not copied from the
ISO 14229 text, only the numeric identifiers (which are public protocol
wire values, not prose) and short own-words descriptions are given.
"""

from __future__ import annotations

from enum import IntEnum

POSITIVE_RESPONSE_OFFSET = 0x40
NEGATIVE_RESPONSE_SID = 0x7F
SUPPRESS_POS_RESP_BIT = 0x80


class ServiceId(IntEnum):
    """Service identifiers in scope for this project (MVP subset)."""

    DIAGNOSTIC_SESSION_CONTROL = 0x10
    ECU_RESET = 0x11
    CLEAR_DIAGNOSTIC_INFORMATION = 0x14
    READ_DTC_INFORMATION = 0x19
    READ_DATA_BY_IDENTIFIER = 0x22
    SECURITY_ACCESS = 0x27
    WRITE_DATA_BY_IDENTIFIER = 0x2E
    ROUTINE_CONTROL = 0x31
    TESTER_PRESENT = 0x3E


#: Services whose first request byte after the SID is a subfunction (as
#: opposed to a DID, routine id, etc. with no subfunction concept).
SERVICES_WITH_SUBFUNCTION: frozenset[ServiceId] = frozenset(
    {
        ServiceId.DIAGNOSTIC_SESSION_CONTROL,
        ServiceId.ECU_RESET,
        ServiceId.READ_DTC_INFORMATION,
        ServiceId.SECURITY_ACCESS,
        ServiceId.ROUTINE_CONTROL,
        ServiceId.TESTER_PRESENT,
    }
)

#: Services for which the suppress-positive-response bit (bit 7 of the
#: subfunction byte) is meaningful.
SERVICES_WITH_SUPPRESS_BIT: frozenset[ServiceId] = frozenset(
    {
        ServiceId.DIAGNOSTIC_SESSION_CONTROL,
        ServiceId.ECU_RESET,
        ServiceId.ROUTINE_CONTROL,
        ServiceId.TESTER_PRESENT,
    }
)


class Nrc(IntEnum):
    """Negative response codes in scope for this project.

    Descriptions are written in our own words; they summarise the *meaning*
    of each code for our rules engine, not the ISO 14229 normative text.
    """

    GENERAL_REJECT = 0x10
    """Server rejected the request for an unspecified reason."""

    SERVICE_NOT_SUPPORTED = 0x11
    """The server does not implement this service at all."""

    SUB_FUNCTION_NOT_SUPPORTED = 0x12
    """The service exists but this subfunction value is unknown to it."""

    INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT = 0x13
    """The request's byte length or structure does not match this service."""

    RESPONSE_TOO_LONG = 0x14
    """The positive response would exceed the transport's maximum length."""

    CONDITIONS_NOT_CORRECT = 0x22
    """A required precondition (e.g. vehicle stationary) is not currently met."""

    REQUEST_SEQUENCE_ERROR = 0x24
    """The request arrived out of the required order (e.g. stop before start)."""

    REQUEST_OUT_OF_RANGE = 0x31
    """An identifier, routine id, or parameter value is unknown or out of range."""

    SECURITY_ACCESS_DENIED = 0x33
    """The active session's security level is insufficient for this request."""

    INVALID_KEY = 0x35
    """The key sent in SecurityAccess did not match the expected value."""

    EXCEED_NUMBER_OF_ATTEMPTS = 0x36
    """Too many invalid keys were sent; the server is now enforcing a lockout."""

    REQUIRED_TIME_DELAY_NOT_EXPIRED = 0x37
    """A SecurityAccess attempt was made while the lockout delay is still active."""

    REQUEST_CORRECTLY_RECEIVED_RESPONSE_PENDING = 0x78
    """The server needs more time; a final response will follow later."""

    GENERAL_PROGRAMMING_FAILURE = 0x72
    """An internal non-volatile-memory operation failed."""

    SUB_FUNCTION_NOT_SUPPORTED_IN_ACTIVE_SESSION = 0x7E
    """The subfunction is implemented but disallowed in the current session."""

    SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION = 0x7F
    """The service is implemented but disallowed in the current session."""


NRC_DESCRIPTIONS: dict[Nrc, str] = {
    Nrc.GENERAL_REJECT: "General reject, unspecified reason.",
    Nrc.SERVICE_NOT_SUPPORTED: "Service not supported by this ECU.",
    Nrc.SUB_FUNCTION_NOT_SUPPORTED: "Subfunction not supported by this service.",
    Nrc.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT: "Incorrect length or invalid format.",
    Nrc.RESPONSE_TOO_LONG: "Positive response would be too long for the transport.",
    Nrc.CONDITIONS_NOT_CORRECT: "Preconditions for this request are not currently met.",
    Nrc.REQUEST_SEQUENCE_ERROR: "Request received out of the required sequence.",
    Nrc.REQUEST_OUT_OF_RANGE: "Identifier or parameter value out of range / unknown.",
    Nrc.SECURITY_ACCESS_DENIED: "Insufficient security level for this request.",
    Nrc.INVALID_KEY: "Security key sent does not match the expected value.",
    Nrc.EXCEED_NUMBER_OF_ATTEMPTS: "Too many invalid security key attempts; locked out.",
    Nrc.REQUIRED_TIME_DELAY_NOT_EXPIRED: "Security lockout delay has not yet expired.",
    Nrc.REQUEST_CORRECTLY_RECEIVED_RESPONSE_PENDING: "Request accepted; final response pending.",
    Nrc.GENERAL_PROGRAMMING_FAILURE: "Internal non-volatile memory operation failed.",
    Nrc.SUB_FUNCTION_NOT_SUPPORTED_IN_ACTIVE_SESSION: "Subfunction not allowed in active session.",
    Nrc.SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION: "Service not allowed in active session.",
}
