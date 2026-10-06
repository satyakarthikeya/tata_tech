"""The import file format (version 1): a small YAML description of existing UDS tests.

Nothing here computes or guesses a byte: ``send`` and ``expect`` are the author's own hex, which
:mod:`uds_assistant.importer.service` then checks against the deterministic rules engine.
Parsing is per test: a bad test is reported and skipped, the rest of the file still imports.
File-level problems (not YAML, wrong version, too large, no tests) raise :class:`ImportFormatError`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from uds_assistant.testgen.model import (
    AdvanceTimeStep,
    Category,
    Citation,
    ImportProvenance,
    SendStep,
    SetDtcStatusStep,
    SetEnvironmentStep,
    TestCase,
    TestStep,
    hex_to_bytes,
)

FORMAT_VERSION = 1
MAX_FILE_BYTES = 512 * 1024
MAX_TESTS = 500
MAX_STEPS = 100
MAX_FRAME_BYTES = 4095


class ImportFormatError(ValueError):
    """The file as a whole cannot be imported."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _EnvironmentIn(_Strict):
    vehicle_speed_kph: int | None = Field(default=None, ge=0)
    nvm_write_fault: bool | None = None

    @model_validator(mode="after")
    def _something(self) -> _EnvironmentIn:
        if self.vehicle_speed_kph is None and self.nvm_write_fault is None:
            raise ValueError("environment needs vehicle_speed_kph and/or nvm_write_fault")
        return self


class _DtcIn(_Strict):
    code: str
    status: int = Field(ge=0, le=0xFF)


class _StepIn(_Strict):
    """One step: exactly one of ``send`` / ``wait_ms`` / ``environment`` / ``dtc``."""

    send: str | None = None
    expect: list[str] | str | None = None
    max_response_time_ms: int | None = Field(default=None, gt=0)
    wait_ms: int | None = Field(default=None, gt=0)
    environment: _EnvironmentIn | None = None
    dtc: _DtcIn | None = None
    note: str = ""

    @field_validator("expect", mode="before")
    @classmethod
    def _expect_list(cls, v: Any) -> Any:
        return [v] if isinstance(v, str) else v

    @model_validator(mode="after")
    def _one_kind(self) -> _StepIn:
        kinds = [k for k in ("send", "wait_ms", "environment", "dtc") if getattr(self, k) is not None]
        if len(kinds) != 1:
            raise ValueError("a step needs exactly one of: send, wait_ms, environment, dtc")
        if self.send is not None:
            if self.expect is None:
                raise ValueError("a send step needs 'expect' (use [] for 'no response expected')")
        elif self.expect is not None or self.max_response_time_ms is not None:
            raise ValueError("'expect' and 'max_response_time_ms' belong to send steps only")
        return self


class _TestIn(_Strict):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")
    title: str = Field(min_length=1, max_length=200)
    category: Category | None = None
    requirement_ids: list[str] = Field(default_factory=list)
    template: str | None = None
    preconditions: list[str] = Field(default_factory=list)
    pass_criteria: str = ""
    steps: list[_StepIn] = Field(min_length=1, max_length=MAX_STEPS)

    @model_validator(mode="after")
    def _has_send(self) -> _TestIn:
        if not any(s.send is not None for s in self.steps):
            raise ValueError("a test needs at least one send step")
        return self


@dataclass
class ParsedTest:
    """One test of the file: a :class:`TestCase` (imported, draft) or the reasons it failed."""

    source_id: str
    test: TestCase | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class ParsedImport:
    suite: str
    description: str
    source_file: str
    sha256: str
    tests: list[ParsedTest]


def _frames(frames: list[str]) -> list[str]:
    for f in frames:
        n = len(hex_to_bytes(f))
        if n == 0 or n > MAX_FRAME_BYTES:
            raise ValueError(f"response frame length {n} bytes is not 1..{MAX_FRAME_BYTES}")
    return frames


def _step(s: _StepIn) -> TestStep:
    if s.send is not None:
        n = len(hex_to_bytes(s.send))
        if n == 0 or n > MAX_FRAME_BYTES:
            raise ValueError(f"send must be 1..{MAX_FRAME_BYTES} bytes of hex")
        return SendStep(request_hex=s.send, expected_responses_hex=_frames(s.expect or []),
                        description=s.note, max_response_time_ms=s.max_response_time_ms)
    if s.wait_ms is not None:
        return AdvanceTimeStep(ms=s.wait_ms, description=s.note)
    if s.environment is not None:
        return SetEnvironmentStep(vehicle_speed_kph=s.environment.vehicle_speed_kph,
                                  nvm_write_fault=s.environment.nvm_write_fault, description=s.note)
    assert s.dtc is not None
    return SetDtcStatusStep(code=s.dtc.code, status=s.dtc.status, description=s.note)


def infer_category(steps: list[TestStep]) -> Category:
    """Deterministic category when the file gives none (documented in IMPORT_FORMAT.md)."""
    sends = [s for s in steps if s.kind == "send"]
    if any(s.kind == "advance_time" for s in steps) or any(s.max_response_time_ms for s in sends):
        return "timing"
    sids = {s.request_bytes[0] for s in sends if s.request_bytes}
    if 0x27 in sids:
        return "security"
    if sids & {0x10, 0x11}:
        return "session"
    last = sends[-1].expected_response_bytes
    return "negative" if last and last[-1][:1] == b"\x7f" else "positive"


def _fmt_error(exc: ValidationError) -> list[str]:
    out = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e["loc"])
        out.append(f"{loc}: {e['msg']}" if loc else e["msg"])
    return out


def parse_import(content: str | bytes, filename: str = "upload.yaml") -> ParsedImport:
    """Parse an import file into draft :class:`TestCase` objects with provenance.

    Raises :class:`ImportFormatError` for file-level problems; per-test problems are returned in
    ``ParsedImport.tests[i].errors``.
    """
    raw = content.encode("utf-8") if isinstance(content, str) else content
    if len(raw) > MAX_FILE_BYTES:
        raise ImportFormatError(f"file is {len(raw)} bytes; the limit is {MAX_FILE_BYTES}")
    try:
        doc = yaml.safe_load(raw.decode("utf-8-sig"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ImportFormatError(f"not valid UTF-8 YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise ImportFormatError("the file must be a YAML mapping with format_version and tests")
    unknown = set(doc) - {"format_version", "suite", "description", "tests"}
    if unknown:
        raise ImportFormatError(f"unknown top-level key(s): {sorted(unknown)}")
    if doc.get("format_version") != FORMAT_VERSION:
        raise ImportFormatError(
            f"format_version must be {FORMAT_VERSION} (got {doc.get('format_version')!r})")
    items = doc.get("tests")
    if not isinstance(items, list) or not items:
        raise ImportFormatError("'tests' must be a non-empty list")
    if len(items) > MAX_TESTS:
        raise ImportFormatError(f"{len(items)} tests; the limit is {MAX_TESTS}")
    suite = str(doc.get("suite") or filename.rsplit(".", 1)[0])[:80]
    sha = hashlib.sha256(raw).hexdigest()

    parsed: list[ParsedTest] = []
    seen: set[str] = set()
    for n, item in enumerate(items):
        sid = str(item.get("id", f"#{n + 1}")) if isinstance(item, dict) else f"#{n + 1}"
        pt = ParsedTest(source_id=sid)
        parsed.append(pt)
        try:
            t_in = _TestIn.model_validate(item)
            if t_in.id in seen:
                raise ValueError(f"duplicate test id {t_in.id!r} in this file")
            seen.add(t_in.id)
            steps: list[TestStep] = []
            for i, s_in in enumerate(t_in.steps):
                try:
                    steps.append(_step(s_in))
                except ValueError as exc:
                    raise ValueError(f"steps.{i}: {exc}") from exc
            pt.test = TestCase(
                id=t_in.id, title=t_in.title, requirement_ids=t_in.requirement_ids,
                category=t_in.category or infer_category(steps), template_id=None,
                preconditions=t_in.preconditions, pass_criteria=t_in.pass_criteria, steps=steps,
                citations=[Citation(source=f"import:{filename}", ref=t_in.id)],
                review_status="draft", origin="imported",
                explanation=f"Imported from {filename} (suite {suite}); not AI-generated.",
                provenance=ImportProvenance(suite=suite, source_file=filename, source_sha256=sha,
                                            source_id=t_in.id, source_template=t_in.template))
        except ValidationError as exc:
            pt.errors = _fmt_error(exc)
        except ValueError as exc:
            pt.errors = [str(exc)]
    return ParsedImport(suite=suite, description=str(doc.get("description") or ""),
                        source_file=filename, sha256=sha, tests=parsed)
