"""Pydantic schema for multi-step UDS test cases, plus YAML/JSON load/dump.

A :class:`TestCase` is a sequence of :class:`TestStep` entries. Steps carry
only concrete bytes (hex strings); those bytes must always be produced by a
:mod:`uds_assistant.testgen.templates` instantiation or by a human author
reading :mod:`docs.behaviour_contract`, never by an LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


def hex_to_bytes(value: str) -> bytes:
    """Parse a hex string (spaces/``0x`` allowed) into bytes."""
    cleaned = value.replace("0x", "").replace("0X", "").replace(" ", "").replace("_", "")
    if cleaned == "":
        return b""
    return bytes.fromhex(cleaned)


def bytes_to_hex(data: bytes) -> str:
    """Render bytes as a compact lower-case hex string, e.g. ``"22f190"``."""
    return data.hex()


def _normalize_hex(value: str) -> str:
    """Round-trip a hex string through :func:`hex_to_bytes`/:func:`bytes_to_hex`."""
    return bytes_to_hex(hex_to_bytes(value))


class Citation(BaseModel):
    """A pointer to the source material backing a test case or a claim in it."""

    source: str
    """Which document: e.g. ``"bcm_spec.yaml"``, ``"behaviour_contract"``, ``"requirements_seed.csv"``."""
    ref: str
    """A locator within that source: section heading, DID/service name, requirement id."""
    quote: str | None = None


class SendStep(BaseModel):
    """Send a request and expect one of a set of acceptable response frames."""

    kind: Literal["send"] = "send"
    request_hex: str
    expected_responses_hex: list[str]
    description: str = ""
    max_response_time_ms: int | None = Field(default=None, gt=0)

    @field_validator("request_hex")
    @classmethod
    def _norm_request(cls, value: str) -> str:
        return _normalize_hex(value)

    @field_validator("expected_responses_hex")
    @classmethod
    def _norm_responses(cls, value: list[str]) -> list[str]:
        return [_normalize_hex(v) for v in value]

    @property
    def request_bytes(self) -> bytes:
        return hex_to_bytes(self.request_hex)

    @property
    def expected_response_bytes(self) -> list[bytes]:
        return [hex_to_bytes(v) for v in self.expected_responses_hex]


class AdvanceTimeStep(BaseModel):
    """Move the injected clock forward before the next step."""

    kind: Literal["advance_time"] = "advance_time"
    ms: int = Field(gt=0)
    description: str = ""


class SetEnvironmentStep(BaseModel):
    """Change environmental conditions (vehicle speed, NVM write fault)."""

    kind: Literal["set_environment"] = "set_environment"
    vehicle_speed_kph: int | None = Field(default=None, ge=0)
    nvm_write_fault: bool | None = None
    description: str = ""


class SetDtcStatusStep(BaseModel):
    """Inject a DTC status byte directly (bypassing protocol), for setup."""

    kind: Literal["set_dtc_status"] = "set_dtc_status"
    code: str
    """DTC code, e.g. ``"B10101"``, or a 6-hex-digit number."""
    status: int = Field(ge=0, le=0xFF)
    description: str = ""


TestStep = Annotated[
    SendStep | AdvanceTimeStep | SetEnvironmentStep | SetDtcStatusStep,
    Field(discriminator="kind"),
]


Category = Literal["positive", "negative", "session", "security", "timing"]
ReviewStatus = Literal["draft", "validated", "human_reviewed"]
Origin = Literal["gold", "generated"]


class TestCase(BaseModel):
    """One multi-step UDS test case."""

    id: str
    title: str
    requirement_ids: list[str] = Field(default_factory=list)
    category: Category
    template_id: str | None = None
    """None for hand-authored gold tests; a template id in :mod:`.templates` otherwise."""
    parameters: dict[str, object] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    steps: list[TestStep]
    citations: list[Citation] = Field(default_factory=list)
    review_status: ReviewStatus = "draft"
    explanation: str = ""
    origin: Origin = "gold"


def _to_plain(obj: object) -> object:
    """Recursively convert pydantic models to plain dict/list for YAML/JSON dumping."""
    if isinstance(obj, BaseModel):
        return _to_plain(obj.model_dump(mode="json"))
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return obj


def load_tests(path: str | Path) -> list[TestCase]:
    """Load a list of :class:`TestCase` from a YAML or JSON file."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    raw = json.loads(text) if p.suffix == ".json" else yaml.safe_load(text)
    if raw is None:
        return []
    return [TestCase.model_validate(item) for item in raw]


def dump_tests(tests: list[TestCase], path: str | Path) -> None:
    """Dump a list of :class:`TestCase` to a YAML or JSON file."""
    p = Path(path)
    plain = [_to_plain(t) for t in tests]
    if p.suffix == ".json":
        p.write_text(json.dumps(plain, indent=2), encoding="utf-8")
    else:
        p.write_text(yaml.safe_dump(plain, sort_keys=False, allow_unicode=True), encoding="utf-8")
