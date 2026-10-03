"""Part D robustness fixes: hex-id normalisation in parse, no planner call on an empty shortlist."""

from __future__ import annotations

from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from uds_assistant.agent import nodes
from uds_assistant.agent.state import PipelineDeps, PipelineState
from uds_assistant.llm.base import ParsedRequirement, TestPlan
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.spec.schema import EcuSpec

T = TypeVar("T", bound=BaseModel)
TEXT = "Writing the interior lighting brightness DID 0x0100 needs an unlock."


class FakeParser:
    """Limited-context fake that returns a fixed parse and counts plan calls."""

    name = "fake-parser"
    supports_json_schema = True
    context_tokens = 4096

    def __init__(self, parsed: ParsedRequirement) -> None:
        self.parsed = parsed
        self.plan_calls = 0

    def complete_json(self, system: str, prompt: str, schema: type[T],
                      json_schema: dict | None = None) -> T:
        if schema is ParsedRequirement:
            return self.parsed  # type: ignore[return-value]
        self.plan_calls += 1
        raise AssertionError("the planner must not be called here")

    def complete_text(self, system: str, prompt: str) -> str:
        return ""


def _parse(spec: EcuSpec, retriever: Bm25Retriever, parsed: ParsedRequirement) -> PipelineState:
    llm: Any = FakeParser(parsed)
    state = PipelineState(requirement_id="REQ-X", requirement_text=TEXT)
    return nodes.parse(state, PipelineDeps(spec=spec, llm=llm, retriever=retriever))


@pytest.mark.parametrize("written", ["0x100", "0x0100", "0X100", "0x00100"])
def test_short_or_odd_case_hex_id_is_normalised_to_the_spec_spelling(
    spec: EcuSpec, retriever: Bm25Retriever, written: str
) -> None:
    s = _parse(spec, retriever, ParsedRequirement(services=["0x2E"], dids=[written]))
    assert s.parsed is not None
    assert "0x0100" in s.parsed.dids
    assert written not in s.parsed.dids or written == "0x0100"
    if written != "0x0100":
        assert any("Normalised did identifier" in n for n in s.notes)


def test_lowercase_service_id_is_normalised(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    s = _parse(spec, retriever, ParsedRequirement(services=["0x2e"], dids=["0x0100"]))
    assert s.parsed is not None
    assert "0x2E" not in s.parsed.services or "0x2E" in nodes.spec_index(spec)["services"]
    assert all(v in nodes.spec_index(spec)["services"] for v in s.parsed.services)


def test_unknown_hex_id_is_still_dropped_not_guessed(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    s = _parse(spec, retriever, ParsedRequirement(services=["0x2E"], dids=["0x0999"]))
    assert s.parsed is not None
    assert "0x0999" not in s.parsed.dids
    assert any("Dropped unknown did identifier 0x0999" in n for n in s.notes)


def test_normalisation_never_matches_a_different_id(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    """0x101 is 0x0101, not 0x0100: numeric equality only, no nearest match."""
    s = _parse(spec, retriever, ParsedRequirement(services=["0x2E"], dids=["0x101"]))
    assert s.parsed is not None
    assert "0x0100" not in s.parsed.dids


def test_plan_skips_the_model_when_nothing_is_on_offer(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    """An empty shortlist used to fall back to an unconstrained call that invented choices."""
    llm = FakeParser(ParsedRequirement())
    state = PipelineState(
        requirement_id="REQ-X", requirement_text="Do something unrelated.",
        parsed=ParsedRequirement(),
    )
    out = nodes.plan(state, PipelineDeps(spec=spec, llm=llm, retriever=retriever))  # type: ignore[arg-type]
    assert llm.plan_calls == 0
    assert out.plan == TestPlan()
    assert not out.rejected
    assert any("planner call skipped" in d.message for d in out.decisions)
