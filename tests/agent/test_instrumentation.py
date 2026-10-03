"""Per-node timings, LLM call stats and fallback events (mock LLM, both engines)."""

from __future__ import annotations

import pytest

from tests.agent.conftest import SEED_REQUIREMENTS
from uds_assistant.agent import run_pipeline
from uds_assistant.llm.base import LLMError
from uds_assistant.llm.mock import MockLLM
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.spec.schema import EcuSpec

REQ_TEXT = {r["id"]: r["text"] for r in SEED_REQUIREMENTS}
NODE_NAMES = {"parse", "retrieve", "plan", "instantiate", "validate", "explain"}


@pytest.mark.parametrize("engine", ["plain", "langgraph"])
def test_node_timings_and_llm_stats_recorded(
    engine: str, spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    result = run_pipeline(REQ_TEXT["REQ-001"], "REQ-001", spec, MockLLM(), retriever, engine=engine)
    assert set(result.node_timings) == NODE_NAMES
    assert all(ms >= 0 for ms in result.node_timings.values())
    assert set(result.node_calls) == NODE_NAMES
    assert result.node_calls["plan"] == result.plan_attempts
    # parse + one plan call per attempt + one explain call per kept test
    assert result.llm_stats["calls"] == 1 + result.plan_attempts + len(result.tests)
    assert result.llm_stats["json_failures"] == 0
    assert result.llm_stats["retries"] == 0
    assert result.fallback_events == []


def test_llm_stats_are_per_run_deltas(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    llm = MockLLM()
    a = run_pipeline(REQ_TEXT["REQ-001"], "REQ-001", spec, llm, retriever, engine="plain")
    b = run_pipeline(REQ_TEXT["REQ-001"], "REQ-001", spec, llm, retriever, engine="plain")
    assert a.llm_stats["calls"] == b.llm_stats["calls"]
    assert llm.stats.calls == a.llm_stats["calls"] + b.llm_stats["calls"]


class _FailingLLM(MockLLM):
    name = "failing"

    def complete_json(self, system, prompt, schema):  # type: ignore[no-untyped-def]
        raise LLMError("boom")

    def complete_text(self, system, prompt):  # type: ignore[no-untyped-def]
        raise LLMError("boom")


@pytest.mark.parametrize("engine", ["plain", "langgraph"])
def test_per_call_llm_failures_are_recorded_as_fallback_events(
    engine: str, spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    llm = _FailingLLM(fallback_events=["get_llm fell back (test)"])
    result = run_pipeline(REQ_TEXT["REQ-001"], "REQ-001", spec, llm, retriever, engine=engine)
    assert result.fallback_events[0] == "get_llm fell back (test)"
    assert any(e.startswith("parse: LLM call failed (boom)") for e in result.fallback_events)
    assert any(e.startswith("plan: LLM call failed (boom)") for e in result.fallback_events)
    assert result.tests == []


@pytest.mark.needs_model
def test_real_ollama_pipeline_completes_on_one_seed_requirement(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    """Ollama mode end to end on REQ-001; the outcome may be few tests, but never a crash."""
    from uds_assistant.llm.client import OllamaClient, ollama_reachable

    assert ollama_reachable(), "Ollama server not reachable"
    llm = OllamaClient()
    result = run_pipeline(REQ_TEXT["REQ-001"], "REQ-001", spec, llm, retriever, engine="plain")
    assert result.status == "completed"
    assert result.llm == "ollama"
    assert result.llm_stats["calls"] >= 2
    assert set(result.node_timings) == NODE_NAMES
    for test in result.tests:  # core invariant: every kept test came from a template
        assert test.origin == "generated"
