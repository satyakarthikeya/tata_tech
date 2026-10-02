"""Table-driven tests for request builder byte outputs."""

from __future__ import annotations

import pytest

from uds_assistant.protocol import builders


@pytest.mark.parametrize(
    ("built", "expected"),
    [
        (builders.session_control(0x03), bytes([0x10, 0x03])),
        (builders.session_control(0x03, suppress_positive=True), bytes([0x10, 0x83])),
        (builders.ecu_reset(0x01), bytes([0x11, 0x01])),
        (builders.clear_dtc(bytes([0xFF, 0xFF, 0xFF])), bytes([0x14, 0xFF, 0xFF, 0xFF])),
        (builders.read_dtc_by_status_mask(0x08), bytes([0x19, 0x02, 0x08])),
        (builders.read_did(0xF190), bytes([0x22, 0xF1, 0x90])),
        (builders.read_did(0xF190, 0xF187), bytes([0x22, 0xF1, 0x90, 0xF1, 0x87])),
        (builders.security_request_seed(0x01), bytes([0x27, 0x01])),
        (builders.security_send_key(0x02, bytes([1, 2, 3, 4])), bytes([0x27, 0x02, 1, 2, 3, 4])),
        (builders.write_did(0x0100, bytes([0x32])), bytes([0x2E, 0x01, 0x00, 0x32])),
        (builders.routine_control(0x01, 0x0201), bytes([0x31, 0x01, 0x02, 0x01])),
        (
            builders.routine_control(0x01, 0x0201, option_record=bytes([0xAA])),
            bytes([0x31, 0x01, 0x02, 0x01, 0xAA]),
        ),
        (builders.tester_present(), bytes([0x3E, 0x80])),
        (builders.tester_present(suppress_positive=False), bytes([0x3E, 0x00])),
    ],
)
def test_builder_bytes(built: object, expected: bytes) -> None:
    assert built.to_bytes() == expected  # type: ignore[attr-defined]


def test_clear_dtc_requires_3_bytes() -> None:
    with pytest.raises(ValueError):
        builders.clear_dtc(bytes([0xFF, 0xFF]))


def test_read_did_requires_at_least_one() -> None:
    with pytest.raises(ValueError):
        builders.read_did()


def test_read_did_rejects_oversized_did() -> None:
    with pytest.raises(ValueError):
        builders.read_did(0x1FFFFF)
