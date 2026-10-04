"""Pydantic state flowing through the agent pipeline, plus its dependencies."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from uds_assistant.llm.base import LLMClient, ParsedRequirement, PlannedTest, TestPlan
from uds_assistant.rag.model import Hit, Retriever
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.model import TestCase

NodeName = Literal["parse", "retrieve", "plan", "instantiate", "validate", "explain"]


class Decision(BaseModel):
    """One logged decision made by a node."""

    node: str
    message: str


class RejectedChoice(BaseModel):
    """A planner choice that was refused (invalid, or failed validation)."""

    template_id: str
    option_index: int
    reason: str
    node: str


class DroppedTest(BaseModel):
    """An instantiated test that failed validation and was not kept."""

    test_id: str
    template_id: str
    option_index: int
    reasons: list[str]


class PlannedInstance(BaseModel):
    """A test together with the planner choice that produced it."""

    choice: PlannedTest
    test: TestCase


class PipelineState(BaseModel):
    """Everything the nodes read and write. Nodes return a new copy."""

    requirement_id: str
    requirement_text: str
    max_retries: int = 2

    parsed: ParsedRequirement | None = None
    notes: list[str] = Field(default_factory=list)
    hits: list[Hit] = Field(default_factory=list)
    plan: TestPlan | None = None
    plan_attempts: int = 0
    accepted: list[PlannedTest] = Field(default_factory=list)
    """Choices accepted by ``plan`` and not yet instantiated."""
    pending: list[PlannedInstance] = Field(default_factory=list)
    """Instantiated tests awaiting validation."""
    validated: list[PlannedInstance] = Field(default_factory=list)
    rejected: list[RejectedChoice] = Field(default_factory=list)
    dropped: list[DroppedTest] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)
    needs_replan: bool = False
    decisions: list[Decision] = Field(default_factory=list)
    node_timings: dict[str, float] = Field(default_factory=dict)
    """Accumulated wall-clock milliseconds per node (re-plan rounds add up)."""
    node_calls: dict[str, int] = Field(default_factory=dict)
    """How many times each node ran."""
    node_llm_calls: dict[str, int] = Field(default_factory=dict)
    """LLM calls (``complete_json``/``complete_text``) made by each node, re-plans summed."""
    fallback_events: list[str] = Field(default_factory=list)
    """Per-call fallbacks: an LLM call failed and the node continued without it."""
    grounding_drops: list[str] = Field(default_factory=list)
    """One line per item removed by parse grounding (same text as the ``Dropped ungrounded`` notes)."""

    def log(self, node: str, message: str) -> None:
        """Append a decision (call only on a node's private copy)."""
        self.decisions.append(Decision(node=node, message=message))


@dataclass
class PipelineDeps:
    """Non-serializable collaborators handed to every node."""

    spec: EcuSpec
    llm: LLMClient
    retriever: Retriever
    store: AuditStore | None = None
    run_id: int | None = None
    catalog_cache: dict[str, object] = field(default_factory=dict)


class TargetEvidence(BaseModel):
    """One service/DID/routine a generated test exercises, and whether the text names it."""

    kind: Literal["service", "did", "routine"]
    id: str
    name: str = ""
    written: bool
    """True if the id or a spec name/lexical pattern for it appears in the requirement text;
    False = only inferred (e.g. a coverage test of a service the requirement never mentions)."""


class PipelineResult(BaseModel):
    """What :func:`uds_assistant.agent.run_pipeline` returns."""

    run_id: int | None
    requirement_id: str
    requirement_text: str
    engine: Literal["langgraph", "plain"]
    llm: str
    parsed: ParsedRequirement | None
    tests: list[TestCase]
    dropped: list[DroppedTest]
    rejected: list[RejectedChoice]
    notes: list[str]
    decisions: list[Decision]
    plan_attempts: int
    node_timings: dict[str, float] = Field(default_factory=dict)
    """Per-node latency in ms (parse/retrieve/plan/instantiate/validate/explain)."""
    node_calls: dict[str, int] = Field(default_factory=dict)
    node_llm_calls: dict[str, int] = Field(default_factory=dict)
    """LLM calls per node (explain = batched calls per requirement, not one per test)."""
    llm_stats: dict[str, float] = Field(default_factory=dict)
    """LLM call counters for this run (calls, http_requests, json_failures, retries, ...)."""
    fallback_events: list[str] = Field(default_factory=list)
    """Per-call LLM failures (a node continued without the reply)."""
    grounding_drops: list[str] = Field(default_factory=list)
    target_provenance: dict[str, list[TargetEvidence]] = Field(default_factory=dict)
    """Per kept test id: its service/DID/routine targets with ``written`` true/false.
    The tests' ``confidence``/``confidence_reason`` are derived from it."""
    status: Literal["completed", "failed"] = "completed"

    @property
    def category_counts(self) -> dict[str, int]:
        """Number of kept tests per category."""
        return dict(Counter(t.category for t in self.tests))
