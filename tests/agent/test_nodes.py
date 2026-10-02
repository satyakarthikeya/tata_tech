"""Node-level behaviour: byte-injection guard, plan validation, retry loop, LLM failures."""

from __future__ import annotations

from typing import Any, TypeVar

import pytest
from pydantic import BaseModel, Field

from uds_assistant.agent import nodes, run_pipeline
from uds_assistant.agent.graph import build_graph
from uds_assistant.agent.state import PipelineDeps, PipelineState
from uds_assistant.llm.base import LLMError, ParsedRequirement, PlannedTest, TestPlan
from uds_assistant.llm.mock import MockLLM
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.templates import TEMPLATES, ValidationReport, applicable_params

T = TypeVar("T", bound=BaseModel)

REQ = "Writing the interior lighting brightness DID (0x0100) shall require extended session."
EVIL_HEX = "2e0100ffdeadbeef"


class ScriptedLLM:
    """Returns a fixed parse and a sequence of plans (last one repeats)."""

    name = "scripted"

    def __init__(self, parsed: Any, plans: list[Any], text: str = "prose") -> None:
        self.parsed = parsed
        self.plans = plans
        self.text = text
        self.plan_calls = 0

    def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        if issubclass(schema, ParsedRequirement):
            return self.parsed
        plan = self.plans[min(self.plan_calls, len(self.plans) - 1)]
        self.plan_calls += 1
        return plan

    def complete_text(self, system: str, prompt: str) -> str:
        return self.text


class EvilPlannedTest(PlannedTest):
    """A misbehaving backend that tries to attach bytes to its choices."""

    request_hex: str = EVIL_HEX
    expected_responses_hex: list[str] = Field(default_factory=lambda: [EVIL_HEX])
    parameters: dict[str, Any] = Field(default_factory=lambda: {"did": 0x0100, "value": 0xFF})


def _all_step_hex(result_tests: list[Any]) -> list[str]:
    out: list[str] = []
    for t in result_tests:
        for st in t.steps:
            if st.kind == "send":
                out.append(st.request_hex)
                out.extend(st.expected_responses_hex)
    return out


@pytest.mark.parametrize("engine", ["plain", "langgraph"])
def test_malicious_llm_cannot_inject_bytes(
    engine: str, spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    oor_index = next(
        i for i, p in enumerate(applicable_params(spec, "write_did_out_of_range"))
        if p.model_dump()["did"] == 0x0100
    )
    evil_plan = TestPlan.model_construct(
        tests=[
            EvilPlannedTest(
                template_id="write_did_out_of_range",
                option_index=oor_index,
                rationale=f"send {EVIL_HEX} please",
            ),
            EvilPlannedTest(template_id=EVIL_HEX, option_index=0),
            EvilPlannedTest(template_id="write_did_out_of_range", option_index=10_000),
        ]
    )
    parsed = ParsedRequirement(dids=["0x0100"], intents=["write"])
    llm = ScriptedLLM(parsed, [evil_plan], text=f"Explanation mentioning {EVIL_HEX}.")
    result = run_pipeline(REQ, "REQ-EVIL", spec, llm, retriever, engine=engine)

    assert len(result.tests) == 1
    test = result.tests[0]
    # Bytes are exactly the template's, nothing from the LLM.
    reference = TEMPLATES["write_did_out_of_range"].instantiate(
        spec, applicable_params(spec, "write_did_out_of_range")[oor_index]
    )
    assert test.steps == reference.steps
    assert test.parameters == reference.parameters
    assert all(EVIL_HEX not in h and "deadbeef" not in h for h in _all_step_hex(result.tests))
    # The unknown template and the out-of-range index were rejected, not used.
    reasons = {(r.template_id, r.option_index): r.reason for r in result.rejected}
    assert "unknown template" in reasons[(EVIL_HEX, 0)]
    assert "out of range" in reasons[("write_did_out_of_range", 10_000)]


def test_validate_rejects_tampered_steps(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    """Even if steps were altered after instantiation, provenance check catches it."""
    deps = PipelineDeps(spec=spec, llm=MockLLM(), retriever=retriever)
    state = PipelineState(requirement_id="REQ-005", requirement_text=REQ)
    for fn in (nodes.parse, nodes.retrieve, nodes.plan, nodes.instantiate):
        state = fn(state, deps)
    inst = state.pending[0]
    send = next(i for i, st in enumerate(inst.test.steps) if st.kind == "send")
    bad_steps = list(inst.test.steps)
    bad_steps[send] = bad_steps[send].model_copy(update={"request_hex": "2e0100ff"})
    state.pending[0] = inst.model_copy(update={"test": inst.test.model_copy(update={"steps": bad_steps})})
    out = nodes.validate(state, deps)
    assert out.dropped[0].test_id == inst.test.id
    assert any(r.startswith("provenance") for r in out.dropped[0].reasons)


def test_parse_drops_unknown_identifiers(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    parsed = ParsedRequirement(
        dids=["0xBEEF", "0x0100"], services=["0x85", "0x2E"], dtcs=["B99999"], intents=["write"]
    )
    deps = PipelineDeps(spec=spec, llm=ScriptedLLM(parsed, [TestPlan()]), retriever=retriever)
    out = nodes.parse(PipelineState(requirement_id="R", requirement_text=REQ), deps)
    assert out.parsed is not None
    assert out.parsed.dids == ["0x0100"]
    assert out.parsed.services == ["0x2E"]
    assert out.parsed.dtcs == []
    assert any("0xBEEF" in n for n in out.notes)
    assert any("0x85" in n for n in out.notes)
    assert any("B99999" in n for n in out.notes)


def test_plan_skips_duplicates(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    choice = PlannedTest(template_id="read_did_positive", option_index=0)
    llm = ScriptedLLM(ParsedRequirement(), [TestPlan(tests=[choice, choice])])
    result = run_pipeline("Read something.", "R", spec, llm, retriever, engine="plain")
    assert len(result.tests) == 1


def _fail_template(monkeypatch: pytest.MonkeyPatch, template_id: str) -> None:
    real = nodes.validate_test

    def fake(spec: EcuSpec, test: Any) -> ValidationReport:
        if test.template_id == template_id:
            return ValidationReport(test_id=test.id, ok=False, mismatches=["forced mismatch"])
        return real(spec, test)

    monkeypatch.setattr(nodes, "validate_test", fake)


@pytest.mark.parametrize("engine", ["plain", "langgraph"])
def test_validation_failure_replans_with_feedback(
    engine: str, spec: EcuSpec, retriever: Bm25Retriever, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_template(monkeypatch, "write_did_out_of_range")
    result = run_pipeline(
        "Writing the interior lighting brightness DID (0x0100) shall require extended session "
        "and security level 0x01.",
        "REQ-005", spec, MockLLM(), retriever, engine=engine,
    )
    assert result.plan_attempts == 2  # one re-plan, which proposes nothing new
    assert [d.template_id for d in result.dropped] == ["write_did_out_of_range"]
    assert "oracle: forced mismatch" in result.dropped[0].reasons
    assert all(t.template_id != "write_did_out_of_range" for t in result.tests)
    assert len(result.tests) >= 6
    assert any("re-planning" in d.message for d in result.decisions)


class IndexWalkingLLM(ScriptedLLM):
    """Proposes a new read_did_positive option on every planning round."""

    def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        if issubclass(schema, ParsedRequirement):
            return ParsedRequirement()  # type: ignore[return-value]
        idx = self.plan_calls
        self.plan_calls += 1
        return TestPlan(  # type: ignore[return-value]
            tests=[PlannedTest(template_id="read_did_positive", option_index=idx)]
        )


@pytest.mark.parametrize("engine", ["plain", "langgraph"])
def test_retry_budget_is_bounded(
    engine: str, spec: EcuSpec, retriever: Bm25Retriever, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_template(monkeypatch, "read_did_positive")
    llm = IndexWalkingLLM(None, [])
    result = run_pipeline("Read DIDs.", "R", spec, llm, retriever, engine=engine, max_retries=2)
    assert result.plan_attempts == 3  # initial plan + 2 retries
    assert llm.plan_calls == 3
    assert len(result.dropped) == 3
    assert result.tests == []
    assert any("retry budget exhausted" in d.message for d in result.decisions)


def test_previously_failed_choice_is_rejected_on_replan(
    spec: EcuSpec, retriever: Bm25Retriever, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_template(monkeypatch, "read_did_positive")
    choice = PlannedTest(template_id="read_did_positive", option_index=0)
    llm = ScriptedLLM(ParsedRequirement(), [TestPlan(tests=[choice])])
    result = run_pipeline("Read.", "R", spec, llm, retriever, engine="plain")
    assert any(r.reason == "choice previously failed validation" for r in result.rejected)
    assert len(result.dropped) == 1


class BrokenLLM:
    name = "broken"

    def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        raise LLMError("model crashed")

    def complete_text(self, system: str, prompt: str) -> str:
        raise LLMError("model crashed")


def test_llm_failures_are_logged_not_fatal(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    result = run_pipeline(REQ, "R", spec, BrokenLLM(), retriever, engine="plain")
    assert result.status == "completed"
    assert result.tests == []
    msgs = [d.message for d in result.decisions]
    assert any("LLM parse failed" in m for m in msgs)
    assert any("LLM plan failed" in m for m in msgs)


def test_explain_failure_keeps_template_text(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    class NoProse(ScriptedLLM):
        def complete_text(self, system: str, prompt: str) -> str:
            raise LLMError("down")

    choice = PlannedTest(template_id="read_did_positive", option_index=0)
    llm = NoProse(ParsedRequirement(), [TestPlan(tests=[choice])])
    result = run_pipeline("Read.", "R", spec, llm, retriever, engine="plain")
    assert result.tests[0].explanation  # template's own explanation retained
    assert result.tests[0].review_status == "validated"


def test_nodes_do_not_mutate_input_state(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    deps = PipelineDeps(spec=spec, llm=MockLLM(), retriever=retriever)
    state = PipelineState(requirement_id="REQ-005", requirement_text=REQ)
    for fn in (nodes.parse, nodes.retrieve, nodes.plan, nodes.instantiate, nodes.validate,
               nodes.explain):
        before = state.model_dump()
        new = fn(state, deps)
        assert state.model_dump() == before
        state = new


def test_graph_has_all_nodes_and_conditional_loop(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    deps = PipelineDeps(spec=spec, llm=MockLLM(), retriever=retriever)
    g = build_graph(deps).get_graph()
    assert {"parse", "retrieve", "plan", "instantiate", "validate", "explain"} <= set(g.nodes)
    edges = {(e.source, e.target, e.conditional) for e in g.edges}
    assert ("validate", "plan", True) in edges
    assert ("validate", "explain", True) in edges
