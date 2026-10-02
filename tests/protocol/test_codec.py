"""Round-trip and format tests for request/response encode/decode."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from uds_assistant.protocol.codec import (
    decode_request,
    decode_response,
    format_hex,
    is_negative,
    negative_response,
    positive_response,
)
from uds_assistant.protocol.constants import SERVICES_WITH_SUBFUNCTION, Nrc, ServiceId


def test_format_hex() -> None:
    assert format_hex(bytes([0x22, 0xF1, 0x90])) == "22 F1 90"
    assert format_hex(b"") == ""


def test_positive_response_no_subfunction() -> None:
    resp = positive_response(ServiceId.READ_DATA_BY_IDENTIFIER, payload=bytes([0xF1, 0x90, 1, 2]))
    assert resp.to_bytes() == bytes([0x62, 0xF1, 0x90, 1, 2])


def test_positive_response_with_subfunction() -> None:
    resp = positive_response(ServiceId.DIAGNOSTIC_SESSION_CONTROL, subfunction=0x03)
    assert resp.to_bytes() == bytes([0x50, 0x03])


def test_negative_response_format() -> None:
    resp = negative_response(ServiceId.READ_DATA_BY_IDENTIFIER, Nrc.REQUEST_OUT_OF_RANGE)
    assert resp.to_bytes() == bytes([0x7F, 0x22, 0x31])
    assert is_negative(resp)
    assert not is_negative(positive_response(ServiceId.READ_DATA_BY_IDENTIFIER))


@given(
    sid=st.sampled_from(list(SERVICES_WITH_SUBFUNCTION)),
    sub=st.integers(min_value=0, max_value=0x7F),
    suppress=st.booleans(),
    data=st.binary(max_size=16),
)
def test_request_roundtrip_with_subfunction(
    sid: ServiceId, sub: int, suppress: bool, data: bytes
) -> None:
    from uds_assistant.protocol.codec import UdsRequest
    from uds_assistant.protocol.constants import SERVICES_WITH_SUPPRESS_BIT

    if suppress and sid not in SERVICES_WITH_SUPPRESS_BIT:
        suppress = False
    req = UdsRequest(sid=sid, subfunction=sub, suppress_positive=suppress, data=data)
    raw = req.to_bytes()
    decoded = decode_request(raw)
    assert decoded == req


@given(
    sid=st.sampled_from([ServiceId.READ_DATA_BY_IDENTIFIER, ServiceId.WRITE_DATA_BY_IDENTIFIER]),
    data=st.binary(max_size=16),
)
def test_request_roundtrip_without_subfunction(sid: ServiceId, data: bytes) -> None:
    from uds_assistant.protocol.codec import UdsRequest

    req = UdsRequest(sid=sid, data=data)
    raw = req.to_bytes()
    decoded = decode_request(raw)
    assert decoded == req


@given(
    sid=st.sampled_from(list(SERVICES_WITH_SUBFUNCTION)),
    sub=st.integers(min_value=0, max_value=0x7F),
    payload=st.binary(max_size=16),
)
def test_positive_response_roundtrip_with_subfunction(
    sid: ServiceId, sub: int, payload: bytes
) -> None:
    resp = positive_response(sid, subfunction=sub, payload=payload)
    decoded = decode_response(resp.to_bytes())
    assert decoded == resp


@given(
    sid=st.sampled_from(list(ServiceId)),
    nrc=st.sampled_from(list(Nrc)),
)
def test_negative_response_roundtrip(sid: ServiceId, nrc: Nrc) -> None:
    resp = negative_response(sid, nrc)
    decoded = decode_response(resp.to_bytes())
    assert decoded == resp


def test_suppress_bit_rejected_for_unsupported_service() -> None:
    import pytest

    from uds_assistant.protocol.codec import UdsRequest

    with pytest.raises(ValueError):
        UdsRequest(sid=ServiceId.READ_DATA_BY_IDENTIFIER, suppress_positive=True)
