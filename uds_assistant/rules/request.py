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
    SERVICES_WITH_SUPPRESS_BIT,
    SUPPRESS_POS_RESP_BIT,
)


class ParsedRequest(BaseModel):
    """A raw request plus the fields the NRC order needs, never failing to build.

    ``subfunction`` is the subfunction value with the suppress bit stripped for
    services that define a suppress bit, and the *full* byte for services that
    have a subfunction but no suppress bit (0x19, 0x27). It is ``None`` when
    the service has no subfunction or the request is too short to carry one.
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
    if sid in SERVICES_WITH_SUPPRESS_BIT:
        return ParsedRequest(
            raw=raw,
            sid=sid,
            subfunction=sub_byte & ~SUPPRESS_POS_RESP_BIT & 0xFF,
            suppress_positive=bool(sub_byte & SUPPRESS_POS_RESP_BIT),
        )
    return ParsedRequest(raw=raw, sid=sid, subfunction=sub_byte)
