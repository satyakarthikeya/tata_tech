"""UDS request/response pydantic models and byte-level encode/decode.

Wire format (own-words summary of the public ISO 14229 framing, no normative
text copied):

- Request: ``SID [subfunction-byte] [data...]``. For services with a
  subfunction, bit 7 of that byte is the suppress-positive-response bit.
- Positive response: ``(SID + 0x40) [subfunction-byte] [data...]``.
- Negative response: ``0x7F SID NRC``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from uds_assistant.protocol.constants import (
    NEGATIVE_RESPONSE_SID,
    POSITIVE_RESPONSE_OFFSET,
    SERVICES_WITH_SUBFUNCTION,
    SERVICES_WITH_SUPPRESS_BIT,
    Nrc,
    ServiceId,
)


def format_hex(data: bytes) -> str:
    """Format bytes as upper-case space-separated hex, e.g. ``"22 F1 90"``."""
    return " ".join(f"{b:02X}" for b in data)


class UdsRequest(BaseModel):
    """A decoded UDS request message."""

    sid: ServiceId
    subfunction: int | None = Field(default=None, ge=0, le=0x7F)
    suppress_positive: bool = False
    data: bytes = b""

    @model_validator(mode="after")
    def _check_subfunction_consistency(self) -> UdsRequest:
        """Only services with a subfunction concept may carry one."""
        has_subfunction = self.sid in SERVICES_WITH_SUBFUNCTION
        if self.subfunction is None and has_subfunction:
            raise ValueError(f"Service {self.sid!r} requires a subfunction byte.")
        if self.subfunction is not None and not has_subfunction:
            raise ValueError(f"Service {self.sid!r} does not use a subfunction byte.")
        if self.suppress_positive and self.sid not in SERVICES_WITH_SUPPRESS_BIT:
            raise ValueError(f"Service {self.sid!r} has no suppress-positive-response bit.")
        return self

    def to_bytes(self) -> bytes:
        """Encode this request to its wire byte representation."""
        out = bytearray([int(self.sid)])
        if self.subfunction is not None:
            sub_byte = self.subfunction | (0x80 if self.suppress_positive else 0x00)
            out.append(sub_byte)
        out.extend(self.data)
        return bytes(out)


class UdsResponse(BaseModel):
    """A decoded UDS response message, positive or negative."""

    positive: bool
    sid: ServiceId
    subfunction: int | None = Field(default=None, ge=0, le=0x7F)
    nrc: Nrc | None = None
    payload: bytes = b""

    @model_validator(mode="after")
    def _check_consistency(self) -> UdsResponse:
        """A negative response must carry an NRC and no positive carries one."""
        if self.positive and self.nrc is not None:
            raise ValueError("A positive response cannot carry an NRC.")
        if not self.positive and self.nrc is None:
            raise ValueError("A negative response must carry an NRC.")
        return self

    def to_bytes(self) -> bytes:
        """Encode this response to its wire byte representation."""
        if not self.positive:
            assert self.nrc is not None
            return bytes([NEGATIVE_RESPONSE_SID, int(self.sid), int(self.nrc)])
        out = bytearray([int(self.sid) + POSITIVE_RESPONSE_OFFSET])
        if self.subfunction is not None:
            out.append(self.subfunction)
        out.extend(self.payload)
        return bytes(out)


def decode_request(raw: bytes) -> UdsRequest:
    """Decode raw bytes into a :class:`UdsRequest`."""
    if len(raw) < 1:
        raise ValueError("Empty request.")
    sid = ServiceId(raw[0])
    if sid in SERVICES_WITH_SUBFUNCTION:
        if len(raw) < 2:
            raise ValueError(f"Service {sid!r} requires a subfunction byte.")
        sub_byte = raw[1]
        suppress = bool(sub_byte & 0x80)
        subfunction = sub_byte & 0x7F
        data = bytes(raw[2:])
        return UdsRequest(sid=sid, subfunction=subfunction, suppress_positive=suppress, data=data)
    return UdsRequest(sid=sid, data=bytes(raw[1:]))


def decode_response(raw: bytes) -> UdsResponse:
    """Decode raw bytes into a :class:`UdsResponse`."""
    if len(raw) < 2:
        raise ValueError("Response too short.")
    if raw[0] == NEGATIVE_RESPONSE_SID:
        if len(raw) != 3:
            raise ValueError("Negative response must be exactly 3 bytes: 7F SID NRC.")
        sid = ServiceId(raw[1])
        nrc = Nrc(raw[2])
        return UdsResponse(positive=False, sid=sid, nrc=nrc)
    pos_sid_value = raw[0] - POSITIVE_RESPONSE_OFFSET
    sid = ServiceId(pos_sid_value)
    if sid in SERVICES_WITH_SUBFUNCTION:
        if len(raw) < 2:
            raise ValueError(f"Positive response for {sid!r} requires a subfunction byte.")
        return UdsResponse(positive=True, sid=sid, subfunction=raw[1], payload=bytes(raw[2:]))
    return UdsResponse(positive=True, sid=sid, payload=bytes(raw[1:]))


def positive_response(
    sid: ServiceId, subfunction: int | None = None, payload: bytes = b""
) -> UdsResponse:
    """Build a positive :class:`UdsResponse`."""
    return UdsResponse(positive=True, sid=sid, subfunction=subfunction, payload=payload)


def negative_response(sid: ServiceId, nrc: Nrc) -> UdsResponse:
    """Build a negative :class:`UdsResponse` (``7F SID NRC``)."""
    return UdsResponse(positive=False, sid=sid, nrc=nrc)


def is_negative(response: UdsResponse) -> bool:
    """Return True if ``response`` is a negative response."""
    return not response.positive
