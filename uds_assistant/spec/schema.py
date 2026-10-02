"""Pydantic schema for an ECU diagnostic spec, plus validated loading from YAML.

The schema models exactly the pieces of an ECU's diagnostic behaviour that the
(later) rules engine needs: sessions with allowed services/timing, security
levels with seed/key parameters, DIDs with per-session read/write rules, a
few routines, a few DTCs, and the ECU-reset subfunctions it accepts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class TimingParams(BaseModel):
    """Session-independent or per-session UDS timing parameters, in milliseconds."""

    p2_ms: int = Field(gt=0)
    p2_star_ms: int = Field(gt=0)
    s3_ms: int = Field(gt=0)


class SessionDef(BaseModel):
    """One diagnostic session (e.g. default, programming, extended)."""

    id: int = Field(ge=0, le=0x7F)
    name: str
    allowed_services: list[int]
    timing: TimingParams


class SecurityLevelDef(BaseModel):
    """One SecurityAccess level: its seed/key subfunction pair and lockout policy."""

    level: int = Field(ge=1, le=0x7F)
    name: str
    seed_subfunction: int = Field(ge=1, le=0x7F)
    key_subfunction: int = Field(ge=1, le=0x7F)
    seed_length: int = Field(gt=0)
    max_attempts: int = Field(gt=0)
    delay_ms: int = Field(ge=0)
    allowed_sessions: list[int]

    @field_validator("seed_subfunction")
    @classmethod
    def _seed_must_be_odd(cls, value: int) -> int:
        if value % 2 == 0:
            raise ValueError("seed_subfunction must be odd (requestSeed convention).")
        return value

    @field_validator("key_subfunction")
    @classmethod
    def _key_must_be_even(cls, value: int) -> int:
        if value % 2 != 0:
            raise ValueError("key_subfunction must be even (sendKey convention).")
        return value


class ValueRange(BaseModel):
    """Inclusive numeric range used to validate a DID's written value."""

    min: int
    max: int

    @model_validator(mode="after")
    def _min_le_max(self) -> ValueRange:
        if self.min > self.max:
            raise ValueError("min must be <= max.")
        return self


class DidConditions(BaseModel):
    """Extra preconditions beyond session/security that gate a DID write."""

    requires: list[str] = Field(default_factory=list)


class DidDef(BaseModel):
    """One Data Identifier (DID): metadata, access rules, and optional constraints."""

    id: int = Field(ge=0, le=0xFFFF)
    name: str
    length: int = Field(gt=0)
    encoding: str
    read_sessions: list[int]
    write_sessions: list[int] = Field(default_factory=list)
    write_security_level: int | None = None
    value_range: ValueRange | None = None
    default_value: bytes = b""
    conditions: DidConditions = Field(default_factory=DidConditions)

    @property
    def is_writable(self) -> bool:
        """True if any session may write this DID."""
        return len(self.write_sessions) > 0


class RoutineDef(BaseModel):
    """One RoutineControl (0x31) routine."""

    id: int = Field(ge=0, le=0xFFFF)
    name: str
    allowed_subfunctions: list[int]
    sessions: list[int]
    security_level: int | None = None
    conditions: DidConditions = Field(default_factory=DidConditions)
    option_record_length: int = Field(ge=0, default=0)
    stop_requires_start: bool = False
    results_requires_start: bool = False
    long_running: bool = False
    """If True, the ECU answers a start request with NRC 0x78 (response pending)
    before the final positive response, and the routine completes synchronously."""


class DtcDef(BaseModel):
    """One Diagnostic Trouble Code entry."""

    code: str
    name: str
    initial_status: int = Field(ge=0, le=0xFF)

    @field_validator("code")
    @classmethod
    def _code_is_3_byte_hex(cls, value: str) -> str:
        cleaned = value.replace("0x", "").replace(" ", "")
        if len(cleaned) != 6:
            raise ValueError(f"DTC code {value!r} must encode exactly 3 bytes (6 hex digits).")
        int(cleaned, 16)  # raises ValueError if not valid hex
        return value


class EcuResetDef(BaseModel):
    """ECUReset (0x11) subfunctions this ECU accepts."""

    supported_subfunctions: list[int]


class EcuSpec(BaseModel):
    """Top-level synthetic ECU diagnostic spec."""

    ecu_name: str
    synthetic: bool = True
    sessions: list[SessionDef]
    security_levels: list[SecurityLevelDef] = Field(default_factory=list)
    dids: list[DidDef]
    routines: list[RoutineDef] = Field(default_factory=list)
    dtcs: list[DtcDef] = Field(default_factory=list)
    dtc_status_availability_mask: int = Field(ge=0, le=0xFF, default=0xFF)
    ecu_reset: EcuResetDef
    read_dtc_supported_subfunctions: list[int] = Field(default_factory=lambda: [0x02])
    max_response_length: int = Field(gt=0, default=4095)
    """Largest positive response (bytes, incl. SID) the transport can carry; larger -> 0x14."""

    @model_validator(mode="after")
    def _cross_reference_checks(self) -> EcuSpec:
        """Validate every cross-reference between sections of the spec."""
        session_ids = {s.id for s in self.sessions}
        security_levels = {lvl.level for lvl in self.security_levels}

        if not self.sessions:
            raise ValueError("At least one session must be defined.")
        if 0x01 not in session_ids:
            raise ValueError("Default session (0x01) must be defined.")

        for level in self.security_levels:
            unknown = set(level.allowed_sessions) - session_ids
            if unknown:
                raise ValueError(
                    f"Security level {level.level:#x} references unknown sessions {unknown}."
                )

        for did in self.dids:
            unknown_read = set(did.read_sessions) - session_ids
            if unknown_read:
                raise ValueError(f"DID {did.id:#x} read_sessions references unknown {unknown_read}.")
            unknown_write = set(did.write_sessions) - session_ids
            if unknown_write:
                raise ValueError(
                    f"DID {did.id:#x} write_sessions references unknown {unknown_write}."
                )
            if did.write_security_level is not None and did.write_security_level not in security_levels:
                raise ValueError(
                    f"DID {did.id:#x} write_security_level "
                    f"{did.write_security_level:#x} is not a defined security level."
                )
            if did.default_value and len(did.default_value) != did.length:
                raise ValueError(
                    f"DID {did.id:#x} default_value length {len(did.default_value)} "
                    f"!= declared length {did.length}."
                )

        did_ids = [d.id for d in self.dids]
        if len(did_ids) != len(set(did_ids)):
            raise ValueError("Duplicate DID ids defined.")

        for routine in self.routines:
            unknown_sessions = set(routine.sessions) - session_ids
            if unknown_sessions:
                raise ValueError(
                    f"Routine {routine.id:#x} references unknown sessions {unknown_sessions}."
                )
            if routine.security_level is not None and routine.security_level not in security_levels:
                raise ValueError(
                    f"Routine {routine.id:#x} security_level "
                    f"{routine.security_level:#x} is not a defined security level."
                )

        for session in self.sessions:
            from uds_assistant.protocol.constants import ServiceId

            valid_sids = {int(s) for s in ServiceId}
            unknown_services = set(session.allowed_services) - valid_sids
            if unknown_services:
                raise ValueError(
                    f"Session {session.id:#x} allowed_services has unknown SIDs "
                    f"{[hex(s) for s in unknown_services]}."
                )

        return self

    def get_session(self, session_id: int) -> SessionDef | None:
        """Look up a session definition by id."""
        return next((s for s in self.sessions if s.id == session_id), None)

    def get_security_level(self, level: int) -> SecurityLevelDef | None:
        """Look up a security level definition by its level value."""
        return next((lvl for lvl in self.security_levels if lvl.level == level), None)

    def get_did(self, did_id: int) -> DidDef | None:
        """Look up a DID definition by id."""
        return next((d for d in self.dids if d.id == did_id), None)

    def get_routine(self, routine_id: int) -> RoutineDef | None:
        """Look up a routine definition by id."""
        return next((r for r in self.routines if r.id == routine_id), None)


def load_spec(path: str | Path) -> EcuSpec:
    """Load and validate an :class:`EcuSpec` from a YAML file."""
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return _parse_spec_dict(raw)


def _parse_spec_dict(raw: dict[str, Any]) -> EcuSpec:
    """Convert hex-string byte fields (e.g. default_value) before pydantic validation."""
    data = dict(raw)
    for did in data.get("dids", []):
        default = did.get("default_value")
        if isinstance(default, str):
            did["default_value"] = bytes.fromhex(default.replace("0x", "").replace(" ", ""))
    return EcuSpec.model_validate(data)
