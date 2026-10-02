"""Tests for ECU spec loading and cross-reference validation."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from uds_assistant.spec.schema import EcuSpec, _parse_spec_dict, load_spec

SPEC_PATH = Path(__file__).resolve().parents[2] / "data" / "bcm_spec.yaml"


def _raw_spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_bcm_spec_loads() -> None:
    spec = load_spec(SPEC_PATH)
    assert spec.synthetic is True
    assert len(spec.sessions) == 3
    assert 12 <= len(spec.dids) <= 15
    assert len(spec.routines) in (2, 3)
    assert len(spec.dtcs) >= 3
    assert spec.get_did(0xF190) is not None
    assert spec.get_did(0xF190).length == 17


def test_default_session_required() -> None:
    raw = _raw_spec()
    raw["sessions"] = [s for s in raw["sessions"] if s["id"] != 0x01]
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_security_level_unknown_session_rejected() -> None:
    raw = _raw_spec()
    raw["security_levels"][0]["allowed_sessions"] = [0x99]
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_did_unknown_read_session_rejected() -> None:
    raw = _raw_spec()
    raw["dids"][0]["read_sessions"] = [0x99]
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_did_unknown_write_security_level_rejected() -> None:
    raw = _raw_spec()
    raw["dids"][0]["write_security_level"] = 0x77
    raw["dids"][0]["write_sessions"] = [0x03]
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_did_default_value_length_mismatch_rejected() -> None:
    raw = _raw_spec()
    raw["dids"][0]["default_value"] = "00"
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_duplicate_did_ids_rejected() -> None:
    raw = _raw_spec()
    dup = copy.deepcopy(raw["dids"][0])
    raw["dids"].append(dup)
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_routine_unknown_session_rejected() -> None:
    raw = _raw_spec()
    raw["routines"][0]["sessions"] = [0x55]
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_routine_unknown_security_level_rejected() -> None:
    raw = _raw_spec()
    raw["routines"][0]["security_level"] = 0x66
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_session_unknown_service_rejected() -> None:
    raw = _raw_spec()
    raw["sessions"][0]["allowed_services"] = [0x99]
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_security_level_seed_subfunction_must_be_odd() -> None:
    raw = _raw_spec()
    raw["security_levels"][0]["seed_subfunction"] = 0x02
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_security_level_key_subfunction_must_be_even() -> None:
    raw = _raw_spec()
    raw["security_levels"][0]["key_subfunction"] = 0x03
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_value_range_min_must_be_le_max() -> None:
    raw = _raw_spec()
    raw["dids"][4]["value_range"] = {"min": 10, "max": 5}
    with pytest.raises(ValueError):
        _parse_spec_dict(raw)


def test_valid_minimal_spec_parses() -> None:
    minimal = {
        "ecu_name": "Minimal",
        "sessions": [
            {
                "id": 0x01,
                "name": "default",
                "allowed_services": [0x10, 0x22],
                "timing": {"p2_ms": 50, "p2_star_ms": 5000, "s3_ms": 5000},
            }
        ],
        "dids": [
            {
                "id": 0xF190,
                "name": "VIN",
                "length": 2,
                "encoding": "ascii",
                "read_sessions": [0x01],
                "default_value": b"AB",
            }
        ],
        "ecu_reset": {"supported_subfunctions": [0x01]},
    }
    spec = EcuSpec.model_validate(minimal)
    assert spec.get_did(0xF190).default_value == b"AB"
