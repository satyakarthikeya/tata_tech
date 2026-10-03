"""Context-budgeted plan prompt (backends with ``context_tokens``) and the unchanged mock path."""

from __future__ import annotations

import json
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from tests.agent.conftest import SEED_REQUIREMENTS
from uds_assistant.agent import nodes, run_pipeline
from uds_assistant.agent.options import build_catalog, plan_shortlist
from uds_assistant.agent.state import PipelineDeps, PipelineState
from uds_assistant.llm.base import (
    CONTEXT_MARKER,
    ParsedRequirement,
    PlannedTest,
    TestPlan,
    build_prompt,
    estimate_tokens,
)
from uds_assistant.llm.mock import MockLLM
from uds_assistant.llm.prompts import PLAN_INSTRUCTION, SYSTEM_PROMPT
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.templates import TEMPLATES, applicable_params

T = TypeVar("T", bound=BaseModel)
REQ_TEXT = {r["id"]: r["text"] for r in SEED_REQUIREMENTS}


class CapturingMock(MockLLM):
    """MockLLM that records every prompt; optionally advertises a context window."""

    def __init__(self, context_tokens: int | None = None) -> None:
        super().__init__()
        if context_tokens is not None:
            self.context_tokens = context_tokens
        self.prompts: list[str] = []

    def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        self.prompts.append(prompt)
        return super().complete_json(system, prompt, schema)


class ScriptedPlanner:
    """Limited-context backend: fixed parse, then plans whatever ``choose`` returns."""

    name = "scripted"

    def __init__(self, parsed: ParsedRequirement, choose: Any, context_tokens: int = 4096,
                 truncate: bool = False) -> None:
        self.parsed = parsed
        self.choose = choose
        self.context_tokens = context_tokens
        self.truncate = truncate
        self.truncation_events: list[str] = []
        self.prompts: list[str] = []

    def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        self.prompts.append(prompt)
        if self.truncate:
            self.truncation_events.append(
                "prompt likely truncated: prompt_eval_count=2050 num_ctx=4096 "
                "estimated_prompt_tokens=16000")
        if schema is ParsedRequirement:
            return self.parsed  # type: ignore[return-value]
        return TestPlan(tests=self.choose(prompt))  # type: ignore[return-value]

    def complete_text(self, system: str, prompt: str) -> str:
        return ""


@pytest.mark.parametrize("req_id", [r["id"] for r in SEED_REQUIREMENTS])
def test_mock_plan_prompt_is_the_legacy_full_catalog_prompt(
    req_id: str, spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    """No context limit -> the plan prompt is exactly the pre-budgeting JSON prompt."""
    llm = CapturingMock()
    run_pipeline(REQ_TEXT[req_id], req_id, spec, llm, retriever, engine="plain")
    plan_prompts = [p for p in llm.prompts if '"task": "plan"' in p]
    assert plan_prompts
    ctx = json.loads(plan_prompts[0].split(CONTEXT_MARKER, 1)[1])
    expected = build_prompt(PLAN_INSTRUCTION, {
        "task": "plan",
        "requirement_id": req_id,
        "requirement_text": REQ_TEXT[req_id],
        "requirement": ctx["requirement"],
        "templates": [t.model_dump() for t in build_catalog(spec)],
        "rejected": [],
        "already_kept": [],
        "feedback": [],
    })
    assert plan_prompts[0] == expected


def test_mock_without_context_attribute_matches_plain_mock(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    for req in SEED_REQUIREMENTS:
        a = run_pipeline(req["text"], req["id"], spec, MockLLM(), retriever, engine="plain")
        b = run_pipeline(req["text"], req["id"], spec, CapturingMock(), retriever, engine="plain")
        assert [t.model_dump() for t in a.tests] == [t.model_dump() for t in b.tests]
        assert a.decisions == b.decisions
        assert not any(d.message.startswith("compact prompt") for d in a.decisions)


@pytest.mark.parametrize("req_id", [r["id"] for r in SEED_REQUIREMENTS])
def test_compact_prompt_fits_budget_and_puts_task_last(
    req_id: str, spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    llm = CapturingMock(context_tokens=4096)
    parsed = run_pipeline(REQ_TEXT[req_id], req_id, spec, MockLLM(), retriever,
                          engine="plain").parsed
    state = PipelineState(requirement_id=req_id, requirement_text=REQ_TEXT[req_id],
                          parsed=parsed)
    deps = PipelineDeps(spec=spec, llm=llm, retriever=retriever)
    catalog = build_catalog(spec)
    prompt, entries = nodes.compact_plan_prompt(state, deps, catalog, set(), 4096)
    assert estimate_tokens(SYSTEM_PROMPT, prompt) <= int(4096 * nodes.PLAN_PROMPT_BUDGET)
    assert CONTEXT_MARKER not in prompt
    assert entries, "shortlist must not be empty for a seed requirement"
    assert prompt.index("OPTIONS") < prompt.index(REQ_TEXT[req_id]) < prompt.index(
        PLAN_INSTRUCTION)
    for e in entries:  # real catalog indices, rendered verbatim
        assert e.option_index < len(applicable_params(spec, e.template_id))
        assert f"option_index {e.option_index}:" in prompt


def test_shortlist_is_deterministic_and_targets_the_parsed_did(spec: EcuSpec) -> None:
    catalog = build_catalog(spec)
    parsed = {"services": ["0x10", "0x27", "0x2E"], "dids": ["0x0100"], "sessions": ["0x03"],
              "security_levels": ["0x01"], "intents": ["write", "security"]}
    a = plan_shortlist(spec, catalog, parsed)
    b = plan_shortlist(spec, catalog, parsed)
    assert a == b
    assert (a[0].template_id, a[0].option_index) == ("write_did_secured_positive", 0)
    did_options = [e for e in a if "DID" in e.detail]
    assert did_options and all("0x0100" in e.detail for e in did_options)


def test_compact_plan_maps_choices_to_real_options_and_rejects_unoffered(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    parsed = ParsedRequirement(services=["0x10", "0x27", "0x2E"], dids=["0x0100"],
                               sessions=["0x03"], security_levels=["0x01"], intents=["write"])

    def choose(prompt: str) -> list[PlannedTest]:
        return [
            PlannedTest(template_id="write_did_secured_positive", option_index=0),
            PlannedTest(template_id="read_did_positive", option_index=0),  # VIN: not offered
        ]

    llm = ScriptedPlanner(parsed, choose)
    result = run_pipeline("Writing DID 0x0100 needs extended session and level 1.", "REQ-X",
                          spec, llm, retriever, engine="plain")
    kept = {t.template_id for t in result.tests}
    assert kept == {"write_did_secured_positive"}
    reference = TEMPLATES["write_did_secured_positive"].instantiate(
        spec, applicable_params(spec, "write_did_secured_positive")[0])
    assert [s.model_dump() for s in result.tests[0].steps] == [
        s.model_dump() for s in reference.steps]
    assert any(r.reason == "option was not in the offered shortlist" for r in result.rejected)
    plan_prompt = next(p for p in llm.prompts if "OPTIONS" in p)
    assert estimate_tokens(SYSTEM_PROMPT, plan_prompt) <= int(4096 * nodes.PLAN_PROMPT_BUDGET)


def test_backend_truncation_events_reach_fallback_events(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    parsed = ParsedRequirement(services=["0x22"], dids=["0xF190"])
    llm = ScriptedPlanner(parsed, lambda p: [], truncate=True)
    result = run_pipeline("Read the VIN.", "REQ-X", spec, llm, retriever, engine="plain")
    msg = ("prompt likely truncated: prompt_eval_count=2050 num_ctx=4096 "
           "estimated_prompt_tokens=16000")
    assert f"parse: {msg}" in result.fallback_events
    assert f"plan: {msg}" in result.fallback_events
