"""Unit tests for the step decoder (no streamlit needed)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from uds_assistant.ui.decode import (
    decode_responses,
    decode_step,
    describe_request,
    describe_response,
    nrc_name,
    service_name,
    spaced_hex,
)


def test_write_without_unlock_example() -> None:
    d = decode_step("2e200101", ["7f2e33"])
    assert d.line == "2E 20 01 01 → 7F 2E 33 (securityAccessDenied)"
    assert d.request_text == "WriteDataByIdentifier DID 0x2001"
    assert d.response_texts == ["negative response to WriteDataByIdentifier: securityAccessDenied"]


def test_positive_session_response() -> None:
    d = decode_step("1003", ["5003003201f4"])
    assert d.line == "10 03 → 50 03 00 32 01 F4 (positive)"
    assert d.request_text == "DiagnosticSessionControl subfunction 0x03"
    assert d.response_texts == ["positive response to DiagnosticSessionControl"]


@pytest.mark.parametrize(
    ("code", "name"),
    [
        (0x11, "serviceNotSupported"),
        (0x13, "incorrectMessageLengthOrInvalidFormat"),
        (0x24, "requestSequenceError"),
        (0x31, "requestOutOfRange"),
        (0x35, "invalidKey"),
        (0x7F, "serviceNotSupportedInActiveSession"),
        (0x99, "unknown NRC 0x99"),
    ],
)
def test_nrc_names(code: int, name: str) -> None:
    assert nrc_name(code) == name


def test_service_names_and_positive_offset() -> None:
    assert service_name(0x27) == "SecurityAccess"
    assert service_name(0x99) == "service 0x99"
    # positive response SID = request SID + 0x40
    assert describe_response("6701950677e8") == "positive response to SecurityAccess"
    assert describe_response("6e0100") == "positive response to WriteDataByIdentifier"


def test_describe_request_forms() -> None:
    assert describe_request("22f190", {0xF190: "vin"}) == "ReadDataByIdentifier DID 0xF190 (vin)"
    assert describe_request("1083") == "DiagnosticSessionControl subfunction 0x03 (suppress positive response)"
    assert describe_request("") == "empty or malformed request"
    assert describe_request("zz") == "empty or malformed request"


def test_multiple_and_empty_responses() -> None:
    assert decode_responses([]) == "(no response)"
    assert decode_responses(["7f2e33", "6e0100"]) == "7F 2E 33 (securityAccessDenied) | 6E 01 00 (positive)"
    assert spaced_hex("2e0100") == "2E 01 00"


def test_decoder_does_not_import_the_rules_engine() -> None:
    src = Path(__file__).resolve().parents[2] / "uds_assistant" / "ui" / "decode.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    mods = [
        n.module or ""
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
    ] + [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any("rules" in m for m in mods)
    assert "uds_assistant.protocol.constants" in mods
