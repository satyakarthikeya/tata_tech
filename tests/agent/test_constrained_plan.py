"""Plan node with constrained decoding: per-call enum schema, round trip, defence in depth."""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
import pytest
from pydantic import BaseModel

from tests.agent.conftest import SEED_REQUIREMENTS
from uds_assistant.agent import nodes, run_pipeline
from uds_assistant.agent.options import build_catalog
from uds_assistant.agent.state import PipelineDeps, PipelineState
from uds_assistant.llm.base import (
    ChoiceReply,
    ConstrainedPlan,
    ParsedRequirement,
    TestPlan,
    estimate_tokens,
)
from uds_assistant.llm.client import OllamaClient
from uds_assistant.llm.mock import MockLLM
from uds_assistant.llm.prompts import SYSTEM_PROMPT
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.spec.schema import EcuSpec

T = TypeVar("T", bound=BaseModel)
WRITE_TEXT = "Writing DID 0x0100 needs extended session and a level 1 unlock."
PARSED = ParsedRequirement(services=["0x10", "0x27", "0x2E"], dids=["0x0100"],
                           sessions=["0x03"], security_levels=["0x01"], intents=["write"])


class SchemaPlanner:
    """Limited-context fake that supports ``json_schema`` and records what it was given."""

    name = "schema-fake"
    supports_json_schema = True
    context_tokens = 4096

    def __init__(self, choose: Any) -> None:
        self.choose = choose
        self.schemas: list[dict | None] = []
        self.prompts: list[str] = []

    def complete_json(self, system: str, prompt: str, schema: type[T],
                      json_schema: dict | None = None) -> T:
        if schema is ParsedRequirement:
            return PARSED  # type: ignore[return-value]
        self.prompts.append(prompt)
        self.schemas.append(json_schema)
        assert schema is ConstrainedPlan and json_schema is not None
        enum = json_schema["properties"]["tests"]["items"]["properties"]["choice"]["enum"]
        return ConstrainedPlan(  # type: ignore[return-value]
            tests=[ChoiceReply(choice=c) for c in self.choose(enum)]
        )

    def complete_text(self, system: str, prompt: str) -> str:
        return ""


def _plan_state(spec: EcuSpec, retriever: Bm25Retriever, llm: Any) -> PipelineState:
    state = PipelineState(requirement_id="REQ-X", requirement_text=WRITE_TEXT, parsed=PARSED)
    return nodes.plan(state, PipelineDeps(spec=spec, llm=llm, retriever=retriever))


def test_enum_is_exactly_the_offered_shortlist(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    llm = SchemaPlanner(lambda enum: enum[:2])
    s = _plan_state(spec, retriever, llm)
    schema = llm.schemas[0]
    assert schema is not None
    enum = schema["properties"]["tests"]["items"]["properties"]["choice"]["enum"]
    prompt = llm.prompts[0]
    assert enum and len(enum) == len(set(enum))
    for entry in enum:
        tid, idx = entry.rsplit("#", 1)
        assert f"template_id {tid} (" in prompt and f"option_index {idx}:" in prompt
    offered_lines = [ln for ln in prompt.splitlines() if ln.startswith("  option_index ")]
    assert len(offered_lines) == len(enum)
    assert [f"{c.template_id}#{c.option_index}" for c in s.accepted] == enum[:2]
    assert s.rejected == []
    assert any("constrained decoding" in d.message for d in s.decisions)


def test_prompt_mentions_the_choice_format_and_fits_budget(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    for req in SEED_REQUIREMENTS:
        parsed = run_pipeline(req["text"], req["id"], spec, MockLLM(), retriever,
                              engine="plain").parsed
        state = PipelineState(requirement_id=req["id"], requirement_text=req["text"],
                              parsed=parsed)
        deps = PipelineDeps(spec=spec, llm=SchemaPlanner(lambda e: []), retriever=retriever)
        prompt, entries = nodes.compact_plan_prompt(
            state, deps, build_catalog(spec), set(), 4096, constrained=True)
        assert "<template_id>#<option_index>" in prompt
        assert entries
        assert estimate_tokens(SYSTEM_PROMPT, prompt) <= int(4096 * nodes.PLAN_PROMPT_BUDGET)


def test_non_schema_backend_keeps_the_old_path(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    class Old:
        name = "old"
        context_tokens = 4096

        def __init__(self) -> None:
            self.calls: list[type] = []

        def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
            self.calls.append(schema)
            return TestPlan() if schema is TestPlan else PARSED  # type: ignore[return-value]

        def complete_text(self, system: str, prompt: str) -> str:
            return ""

    llm = Old()
    _plan_state(spec, retriever, llm)
    assert llm.calls == [TestPlan]


def test_mock_path_is_unchanged(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    assert not hasattr(MockLLM(), "supports_json_schema")
    s = _plan_state(spec, retriever, MockLLM())
    assert not any("constrained" in d.message for d in s.decisions)


def test_defence_in_depth_still_rejects_out_of_enum_choices(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    llm = SchemaPlanner(lambda enum: [enum[0], "no_such_template#0", "read_did_positive#0",
                                      "garbage", enum[0]])
    s = _plan_state(spec, retriever, llm)
    assert len(s.accepted) == 1
    reasons = {(r.template_id, r.option_index): r.reason for r in s.rejected}
    assert reasons[("no_such_template", 0)].startswith("unknown template id")
    assert reasons[("garbage", 0)].startswith("unknown template id")
    assert ("read_did_positive", 0) in reasons  # not offered for this requirement
    assert any("duplicate" in d.message for d in s.decisions)


def test_out_of_range_index_is_rejected(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    llm = SchemaPlanner(lambda enum: [enum[0].split("#")[0] + "#999"])
    s = _plan_state(spec, retriever, llm)
    assert s.accepted == [] and "out of range" in s.rejected[0].reason


def test_normalisation_still_applies_to_constrained_choices(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    def choose(enum: list[str]) -> list[str]:
        tid, idx = enum[0].rsplit("#", 1)
        return [f"{tid.upper()} (positive)#{idx}"]

    s = _plan_state(spec, retriever, SchemaPlanner(choose))
    assert len(s.accepted) == 1
    assert any(n.startswith("Normalised planner template_id") for n in s.notes)


def test_empty_shortlist_does_not_call_the_model(
    spec: EcuSpec, retriever: Bm25Retriever, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Part D: with nothing on offer there is nothing to choose, and an unconstrained call
    only invited invented template names (13 rejections on the seed smoke run), so the
    planner call is skipped."""
    monkeypatch.setattr(nodes, "plan_shortlist", lambda *a, **k: [])
    calls: list[type] = []

    class Fake(SchemaPlanner):
        def complete_json(self, system, prompt, schema, json_schema=None):  # type: ignore[no-untyped-def]
            calls.append(schema)
            return TestPlan()

    s = _plan_state(spec, retriever, Fake(lambda e: []))
    assert calls == []
    assert s.plan == TestPlan()
    assert not s.rejected


def test_end_to_end_with_ollama_client_over_mock_transport(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    """Real OllamaClient: parse request keeps the model schema, plan request carries the enum."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        fmt = body["format"]
        if "choice" in json.dumps(fmt):
            enum = fmt["properties"]["tests"]["items"]["properties"]["choice"]["enum"]
            content = json.dumps({"tests": [{"choice": enum[0], "rationale": "r"}]})
        elif "services" in fmt.get("properties", {}):
            content = json.dumps({
                "services": ["0x2E"], "dids": ["0x0100"], "intents": ["write"],
                "evidence": {"service:0x2E": "Writing DID"}})
        else:
            content = json.dumps({"explanations": []})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    llm = OllamaClient(base_url="http://x:1", transport=httpx.MockTransport(handler),
                       sleep=lambda s: None)
    res = run_pipeline(WRITE_TEXT, "REQ-X", spec, llm, retriever, engine="plain")
    assert res.parsed is not None and res.parsed.services == ["0x2E"]
    assert res.parsed.evidence == {"service:0x2E": "Writing DID"}
    plan_bodies = [b for b in bodies if "choice" in json.dumps(b["format"])]
    assert plan_bodies, "the plan request must carry the enum schema"
    assert "enum" in json.dumps(plan_bodies[0]["format"])
    assert res.tests, "the enum choice must round-trip to an instantiated test"
    assert res.rejected == []
