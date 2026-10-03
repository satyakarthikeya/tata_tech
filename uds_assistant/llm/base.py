"""LLM interface and the structured schemas the agent asks an LLM to fill.

Design rule (AGENT.md, PROJECT.md §3): **the LLM never produces bytes that
reach a final test.** The schemas below therefore contain *no* byte, hex
payload, request or response fields. An LLM can only:

- name spec identifiers it saw in the requirement (validated against the spec
  afterwards; unknown ones are dropped),
- choose intents from a closed vocabulary,
- choose a registered template id and an *index* into an enumerated list of
  parameter options that the agent computed from the spec,
- write prose (rationale, explanation).

Every schema uses ``extra="ignore"`` so anything else an LLM emits (e.g. a
smuggled ``request_hex``) is silently discarded at parse time.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T", bound=BaseModel)

Intent = Literal[
    "positive",
    "negative",
    "session",
    "security",
    "timing",
    "range",
    "length",
    "sequence",
    "conditions",
    "subfunction",
    "lockout",
    "suppress",
    "dtc",
    "read",
    "write",
    "routine",
]
ALL_INTENTS: tuple[str, ...] = Intent.__args__  # type: ignore[attr-defined]

_HEX_ID_RE = re.compile(r"^0x[0-9A-F]+$")
_DTC_RE = re.compile(r"^[A-Z0-9]{6}$")

CONTEXT_MARKER = "CONTEXT_JSON:"
"""Prompts end with this marker followed by a JSON object holding the structured
context (the requirement, the enumerated options, ...). A real LLM reads it as
part of the prompt; :class:`~uds_assistant.llm.mock.MockLLM` parses it."""


class LLMError(RuntimeError):
    """Raised when an LLM backend cannot produce a valid answer."""


def _norm_hex_id(value: str) -> str:
    v = value.strip()
    if v.lower().startswith("0x"):
        v = v[2:]
    return "0x" + v.upper()


class _Schema(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ParsedRequirement(_Schema):
    """What the LLM understood from a plain-English requirement.

    Identifiers are references to spec entries written as hex strings (e.g.
    ``"0xF190"``); they are *names* of spec objects, not payload bytes, and are
    checked against the loaded spec by the agent's ``parse`` node.
    """

    services: list[str] = Field(default_factory=list, description="UDS service ids, e.g. '0x2E'")
    dids: list[str] = Field(default_factory=list, description="DIDs from the spec, e.g. '0xF190'")
    routines: list[str] = Field(default_factory=list, description="Routine ids, e.g. '0x0201'")
    sessions: list[str] = Field(default_factory=list, description="Session ids, e.g. '0x03'")
    security_levels: list[str] = Field(default_factory=list, description="Levels, e.g. '0x01'")
    dtcs: list[str] = Field(default_factory=list, description="DTC codes, e.g. 'B10101'")
    intents: list[Intent] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    @field_validator("services", "dids", "routines", "sessions", "security_levels")
    @classmethod
    def _hex_ids(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for raw in values:
            norm = _norm_hex_id(str(raw))
            if not _HEX_ID_RE.match(norm):
                raise ValueError(f"not a hex identifier: {raw!r}")
            if norm not in out:
                out.append(norm)
        return out

    @field_validator("dtcs")
    @classmethod
    def _dtc_codes(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for raw in values:
            code = str(raw).strip().upper()
            if not _DTC_RE.match(code):
                raise ValueError(f"not a DTC code: {raw!r}")
            if code not in out:
                out.append(code)
        return out

    @field_validator("intents", mode="before")
    @classmethod
    def _dedupe_intents(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for v in values or []:
            if v not in out:
                out.append(v)
        return out


class PlannedTest(_Schema):
    """One planner choice: a registered template plus an option index.

    ``option_index`` indexes ``testgen.templates.applicable_params(spec,
    template_id)`` — the agent enumerated those options from the spec and
    showed them to the LLM. There is deliberately no way to pass parameters
    or bytes directly.
    """

    template_id: str
    option_index: int = Field(ge=0)
    rationale: str = ""


class TestPlan(_Schema):
    """The planner's output: an ordered list of template choices."""

    __test__ = False  # not a pytest test class despite the name

    tests: list[PlannedTest] = Field(default_factory=list)


class TestExplanation(_Schema):
    """Prose for one kept test, keyed by the test id the agent showed the LLM."""

    __test__ = False

    test_id: str
    explanation: str = ""


class ExplanationBatch(_Schema):
    """The explainer's output for one batch of tests: ``{explanations: [{test_id, explanation}]}``."""

    explanations: list[TestExplanation] = Field(default_factory=list)


@dataclass
class LLMStats:
    """Counters an LLM backend accumulates; read with :meth:`snapshot`."""

    calls: int = 0
    """Public ``complete_json`` / ``complete_text`` calls."""
    http_requests: int = 0
    """Chat requests actually sent (>= calls; extra ones are re-prompts)."""
    json_failures: int = 0
    """Replies that were not valid JSON or failed schema validation."""
    retries: int = 0
    """Re-sent requests: schema re-prompts plus transport/5xx retries."""
    errors: int = 0
    """Public calls that ended in :class:`LLMError`."""
    latency_ms: float = 0.0
    """Wall-clock time spent inside public calls."""
    truncations: int = 0
    """Chat requests whose prompt was (likely) truncated to fit the context window."""

    def snapshot(self) -> dict[str, float]:
        """A plain-dict copy of the counters."""
        return asdict(self)


def stats_delta(after: dict[str, float], before: dict[str, float]) -> dict[str, float]:
    """Counter differences ``after - before`` (latency rounded to 0.1 ms)."""
    out = {k: after[k] - before.get(k, 0) for k in after}
    out["latency_ms"] = round(out.get("latency_ms", 0.0), 1)
    return out


@runtime_checkable
class LLMClient(Protocol):
    """Interface every LLM backend implements (mock, Ollama, ...)."""

    name: str
    """Short backend label recorded in the audit trail, e.g. ``"mock"``."""

    def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        """Return an instance of ``schema`` answering ``prompt``."""
        ...

    def complete_text(self, system: str, prompt: str) -> str:
        """Return free-text prose answering ``prompt``."""
        ...


CHARS_PER_TOKEN = 3
"""Conservative prompt-size estimate. qwen2.5 tokenizes the hex-heavy JSON context at
about 2.9 chars/token (measured: the 46 kB plan prompt was 16.2k tokens), so 3 is used
rather than the usual 4 for English prose."""


def estimate_tokens(*texts: str) -> int:
    """Rough upper estimate of the token count of ``texts`` (see :data:`CHARS_PER_TOKEN`)."""
    return -(-sum(len(t) for t in texts) // CHARS_PER_TOKEN)


def context_budget(llm: object) -> int | None:
    """The backend's context window in tokens, or None if it has no limit (mock).

    Optional capability: a backend may expose ``context_tokens: int | None``. It is not
    part of the :class:`LLMClient` protocol so existing backends need no change.
    """
    value = getattr(llm, "context_tokens", None)
    return value if isinstance(value, int) and value > 0 else None


def drain_truncation_events(llm: object, start: int) -> list[str]:
    """Truncation messages a backend recorded since index ``start`` (empty if unsupported)."""
    events = getattr(llm, "truncation_events", None)
    return list(events[start:]) if isinstance(events, list) else []


def truncation_mark(llm: object) -> int:
    """Current length of the backend's truncation-event list (0 if unsupported)."""
    events = getattr(llm, "truncation_events", None)
    return len(events) if isinstance(events, list) else 0


def build_prompt(instruction: str, context: dict[str, object]) -> str:
    """Render a prompt as an instruction followed by the JSON context block."""
    return f"{instruction.strip()}\n\n{CONTEXT_MARKER}\n{json.dumps(context, sort_keys=True)}"


def extract_context(prompt: str) -> dict[str, object]:
    """Recover the JSON context block written by :func:`build_prompt`."""
    idx = prompt.rfind(CONTEXT_MARKER)
    if idx < 0:
        return {}
    try:
        data = json.loads(prompt[idx + len(CONTEXT_MARKER) :].strip())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
