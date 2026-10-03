"""Lenient raw-request view used by the rules engine.

:func:`uds_assistant.protocol.codec.decode_request` is strict (it raises on
unknown SIDs or malformed subfunction bytes). The oracle must answer *any*
byte string, so it works on this lenient view instead and lets the NRC
evaluation order decide what is wrong with the request.
"""

from __future__ import annotations

from pydantic import BaseModel

from uds_assistant.protocol.codec import UdsRequest
from uds_assistant.protocol.constants import (
    SERVICES_WITH_SUBFUNCTION,
    SUPPRESS_POS_RESP_BIT,
)


class ParsedRequest(BaseModel):
    """A raw request plus the fields the NRC order needs, never failing to build.

    ``subfunction`` is the subfunction value with the suppress bit (bit 7)
    stripped, for every service that has a subfunction (0x10, 0x11, 0x19, 0x27,
    0x31, 0x3E). It is ``None`` when the service has no subfunction or the
    request is too short to carry one.

    Source: SWS_Dcm_00201 (the DSD masks the suppress bit out of the request)
    with SWS_Dcm_00204 (only for services configured with subfunctions) and
    SWS_Dcm_01411 (each configured sub-service is accepted with the bit clear
    or set) + design decision — see DECISIONS.md [R-SPRMIB]. This deliberately
    differs from ``protocol.constants.SERVICES_WITH_SUPPRESS_BIT`` (used by the
    strict codec), which still excludes 0x19 and 0x27.
    """

    raw: bytes
    sid: int | None = None
    subfunction: int | None = None
    suppress_positive: bool = False

    @property
    def length(self) -> int:
        """Total request length in bytes, including the SID."""
        return len(self.raw)


def to_raw(request: bytes | bytearray | UdsRequest) -> bytes:
    """Normalise a request given as bytes or :class:`UdsRequest` to raw bytes."""
    if isinstance(request, UdsRequest):
        return request.to_bytes()
    return bytes(request)


def parse_request(request: bytes | bytearray | UdsRequest) -> ParsedRequest:
    """Build a :class:`ParsedRequest` from any byte string (never raises)."""
    raw = to_raw(request)
    if not raw:
        return ParsedRequest(raw=raw)
    sid = raw[0]
    if sid not in SERVICES_WITH_SUBFUNCTION or len(raw) < 2:
        return ParsedRequest(raw=raw, sid=sid)
    sub_byte = raw[1]
    return ParsedRequest(
        raw=raw,
        sid=sid,
        subfunction=sub_byte & ~SUPPRESS_POS_RESP_BIT & 0xFF,
        suppress_positive=bool(sub_byte & SUPPRESS_POS_RESP_BIT),
    )
