"""Part C1: template-id normalisation, identifier grounding, batched explain."""

from __future__ import annotations

from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from uds_assistant.agent import nodes, run_pipeline
from uds_assistant.agent.grounding import ground_identifiers, name_matches_text
from uds_assistant.agent.options import spec_index
from uds_assistant.agent.state import PipelineState
from uds_assistant.llm.base import (
    ExplanationBatch,
    LLMError,
    ParsedRequirement,
    PlannedTest,
    TestExplanation,
    TestPlan,
    extract_context,
)
from uds_assistant.llm.mock import MockLLM
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.spec.schema import EcuSpec

T = TypeVar("T", bound=BaseModel)

VIN_REQ = "The tester shall be able to read the VIN (DID 0xF190) in every session."


class Scripted:
    """Fake LLM: fixed parse/plan; explain behaviour supplied by ``explain_fn``."""

    name = "scripted"

    def __init__(self, parsed: ParsedRequirement, plan: TestPlan, explain_fn: Any = None) -> None:
        self.parsed, self.plan, self.explain_fn = parsed, plan, explain_fn
        self.explain_calls = 0

    def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        if issubclass(schema, ParsedRequirement):
            return self.parsed  # type: ignore[return-value]
        if issubclass(schema, TestPlan):
            return self.plan  # type: ignore[return-value]
        self.explain_calls += 1
        if self.explain_fn is None:
            raise LLMError("no explain script")
        return self.explain_fn(prompt)  # type: ignore[no-any-return]

    def complete_text(self, system: str, prompt: str) -> str:
        raise AssertionError("explain must not make per-test text calls")


def _ids_in(prompt: str) -> list[str]:
    return [str(t["test_id"]) for t in extract_context(prompt)["tests"]]  # type: ignore[attr-defined]


def _explain_all(prompt: str) -> ExplanationBatch:
    return ExplanationBatch(
        explanations=[TestExplanation(test_id=i, explanation="ok") for i in _ids_in(prompt)]
    )


# ------------------------------------------------------------------ template-id normalisation


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("read_did_positive", "read_did_positive"),
        ("read_did_positive (positive)", "read_did_positive"),
        ("  Read_DID_Positive  ", "read_did_positive"),
        ('"read_did_positive"', "read_did_positive"),
        ("'read_did_positive' (positive)", "read_did_positive"),
        ("`READ_DID_POSITIVE`", "read_did_positive"),
        ("read_did", "read_did"),  # never fuzzy-matched
    ],
)
def test_normalise_template_id(raw: str, expected: str) -> None:
    assert nodes.normalise_template_id(raw) == expected


@pytest.mark.parametrize("engine", ["plain", "langgraph"])
def test_plan_accepts_normalised_ids_and_rejects_the_rest(
    engine: str, spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    plan = TestPlan(
        tests=[
            PlannedTest(template_id="read_did_positive (positive)", option_index=0),
            PlannedTest(template_id='  "READ_DID_POSITIVE" ', option_index=1),
            PlannedTest(template_id="read_did", option_index=0),
            PlannedTest(template_id="read_vin_everywhere (positive)", option_index=0),
        ]
    )
    llm = Scripted(
        ParsedRequirement(services=["0x22"], dids=["0xF190"], intents=["read"]),
        plan,
        _explain_all,
    )
    result = run_pipeline(VIN_REQ, "R", spec, llm, retriever, engine=engine, max_retries=0)
    assert [(t.template_id, t.parameters.get("session")) for t in result.tests] == [
        ("read_did_positive", 1),
        ("read_did_positive", 2),
    ]
    rejected = {(r.template_id, r.option_index): r.reason for r in result.rejected}
    assert "unknown template id" in rejected[("read_did", 0)]
    assert "unknown template id" in rejected[("read_vin_everywhere (positive)", 0)]
    assert len(rejected) == 2
    plan_msgs = [d.message for d in result.decisions if d.node == "plan"]
    assert any("'read_did_positive (positive)' -> 'read_did_positive'" in m for m in plan_msgs)
    assert any("READ_DID_POSITIVE" in m and "-> 'read_did_positive'" in m for m in plan_msgs)
    assert sum("Normalised" in n for n in result.notes) == 2


def test_mock_plan_never_normalises(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    result = run_pipeline(VIN_REQ, "R", spec, MockLLM(), retriever, engine="plain")
    assert not any("Normalised" in d.message for d in result.decisions)


# ------------------------------------------------------------------------------- grounding


@pytest.fixture(scope="module")
def index(spec: EcuSpec) -> dict[str, dict[str, str]]:
    return spec_index(spec)


def _ground(
    parsed: dict[str, list[str]],
    text: str,
    index: dict[str, dict[str, str]],
    retriever: Bm25Retriever,
) -> tuple[dict[str, list[str]], list[str]]:
    kept, drops = ground_identifiers(parsed, text, index, retriever)
    return kept, [d.identifier for d in drops]


def test_identifier_absent_from_text_and_evidence_is_dropped(
    index: dict[str, dict[str, str]], retriever: Bm25Retriever
) -> None:
    kept, dropped = _ground(
        {"dids": ["0x0140", "0xF190"], "routines": ["0x0202"], "dtcs": ["B10101"]},
        "The tester shall be able to read the VIN in every session.",
        index,
        retriever,
    )
    assert dropped == ["0x0140", "0x0202", "B10101"]
    assert kept["dids"] == ["0xF190"]  # VIN: name matches the text and its chunk is retrieved
    assert kept["routines"] == [] and kept["dtcs"] == []


@pytest.mark.parametrize("written", ["0xF190", "0xf190", "f190", "F190"])
def test_identifier_written_in_text_is_always_kept(
    index: dict[str, dict[str, str]], retriever: Bm25Retriever, written: str
) -> None:
    kept, dropped = _ground(
        {"dids": ["0xF190"]}, f"Check data item {written} on the bench.", index, retriever
    )
    assert kept["dids"] == ["0xF190"] and dropped == []


def test_short_number_is_not_a_written_identifier(
    index: dict[str, dict[str, str]], retriever: Bm25Retriever
) -> None:
    _, dropped = _ground({"dids": ["0x0100"]}, "Brake after 100 ms.", index, retriever)
    assert dropped == ["0x0100"]


def test_written_dtc_and_routine_kept(
    index: dict[str, dict[str, str]], retriever: Bm25Retriever
) -> None:
    kept, dropped = _ground(
        {"routines": ["0x0201"], "dtcs": ["B10101"]},
        "Report b10101 and run routine 0x201 afterwards.",
        index,
        retriever,
    )
    assert dropped == [] and kept["routines"] == ["0x0201"] and kept["dtcs"] == ["B10101"]


def test_identifier_justified_by_name_and_retrieved_chunk_is_kept(
    index: dict[str, dict[str, str]], retriever: Bm25Retriever
) -> None:
    kept, dropped = _ground(
        {"dids": ["0x0140"], "routines": ["0x0202"]},
        "The vehicle speed shall be readable; door actuator calibration must be started first.",
        index,
        retriever,
    )
    assert dropped == [] and kept["dids"] == ["0x0140"] and kept["routines"] == ["0x0202"]


def test_name_match_ignores_generic_words() -> None:
    assert not name_matches_text("wiper_sensitivity_level", "security level 1 unlock")
    assert name_matches_text("vehicle_speed_kph", "Vehicle speed shall be readable")


@pytest.mark.parametrize("engine", ["plain", "langgraph"])
def test_parse_node_records_grounding_drops(
    engine: str, spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    llm = Scripted(
        ParsedRequirement(services=["0x22"], dids=["0x0140", "0xF190"], intents=["read"]),
        TestPlan(),
        _explain_all,
    )
    result = run_pipeline(
        "The tester shall be able to read the VIN in every session.",
        "R",
        spec,
        llm,
        retriever,
        engine=engine,
    )
    assert result.parsed is not None and result.parsed.dids == ["0xF190"]
    drops = [n for n in result.notes if "ungrounded" in n]
    assert len(drops) == 1 and "0x0140" in drops[0]
    assert any(d.node == "parse" and "ungrounded" in d.message for d in result.decisions)


def test_mock_skips_grounding_and_adds_no_trace(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    assert MockLLM.applies_grounding is False
    result = run_pipeline(VIN_REQ, "R", spec, MockLLM(), retriever, engine="plain")
    assert not any("ungrounded" in d.message for d in result.decisions)


# ---------------------------------------------------------------------------- batched explain

CHOICES = [PlannedTest(template_id="read_did_positive", option_index=i) for i in range(4)]
PARSED = ParsedRequirement(services=["0x22"], dids=["0xF190"], intents=["read"])


def _run(llm: Scripted, spec: EcuSpec, retriever: Bm25Retriever, engine: str = "plain") -> Any:
    return run_pipeline(VIN_REQ, "R", spec, llm, retriever, engine=engine, max_retries=0)


@pytest.mark.parametrize("engine", ["plain", "langgraph"])
def test_explain_one_call_all_ids_present(
    engine: str, spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    llm = Scripted(
        PARSED,
        TestPlan(tests=CHOICES),
        lambda p: ExplanationBatch(
            explanations=[
                TestExplanation(test_id=i, explanation=f"prose for {i}") for i in _ids_in(p)
            ]
        ),
    )
    result = _run(llm, spec, retriever, engine)
    assert len(result.tests) == 4
    assert llm.explain_calls == 1
    assert all(t.explanation == f"prose for {t.id}" for t in result.tests)
    assert all(t.review_status == "validated" for t in result.tests)
    assert result.fallback_events == []


def test_explain_missing_id_falls_back_with_trace(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    def answer(p: str) -> ExplanationBatch:
        ids = _ids_in(p)
        return ExplanationBatch(
            explanations=[TestExplanation(test_id=i, explanation="llm") for i in ids[:-1]]
            + [TestExplanation(test_id="not_a_test", explanation="stray")]
        )

    result = _run(Scripted(PARSED, TestPlan(tests=CHOICES), answer), spec, retriever)
    texts = [t.explanation for t in result.tests]
    assert texts[:-1] == ["llm"] * 3
    last = result.tests[-1]
    assert "read_did_positive" in last.explanation and last.category in last.explanation
    assert any(last.id in e and "missing" in e for e in result.fallback_events)
    assert any(d.node == "explain" and last.id in d.message for d in result.decisions)


def test_explain_batch_failure_falls_back_for_every_test(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    result = _run(Scripted(PARSED, TestPlan(tests=CHOICES), None), spec, retriever)
    assert len(result.tests) == 4
    assert all(t.explanation and t.review_status == "validated" for t in result.tests)
    assert any("batch 1/1" in e for e in result.fallback_events)
    assert sum("missing in LLM reply" in e for e in result.fallback_events) == 4


def test_explain_prose_never_changes_steps(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    evil = "2e0100ffdeadbeef"
    llm = Scripted(
        PARSED,
        TestPlan(tests=CHOICES[:2]),
        lambda p: ExplanationBatch(
            explanations=[TestExplanation(test_id=i, explanation=evil) for i in _ids_in(p)]
        ),
    )
    evil_run = _run(llm, spec, retriever)
    ref = _run(Scripted(PARSED, TestPlan(tests=CHOICES[:2]), None), spec, retriever)
    assert [t.steps for t in evil_run.tests] == [t.steps for t in ref.tests]


def test_explain_batches_split_only_when_over_budget() -> None:
    s = PipelineState(requirement_id="R", requirement_text=VIN_REQ)
    summaries: list[dict[str, object]] = [
        {
            "test_id": f"t{i}",
            "title": "x" * 60,
            "category": "positive",
            "rationale": "r" * 100,
            "steps": "3 steps: " + "s" * 130,
            "citation_refs": ["a#b", "c#d", "e#f"],
        }
        for i in range(30)
    ]
    assert len(nodes.explain_batches(s, summaries, None)) == 1
    assert len(nodes.explain_batches(s, summaries, 100_000)) == 1
    batches = nodes.explain_batches(s, summaries, 4096)
    assert 1 < len(batches) <= 4  # far fewer calls than one per test
    assert [i["test_id"] for b in batches for i in b] == [f"t{i}" for i in range(30)]
    assert len(nodes.explain_batches(s, summaries, 10)) == 30  # at least one test per batch


def test_mock_explain_is_one_call(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    result = run_pipeline(VIN_REQ, "R", spec, MockLLM(), retriever, engine="plain")
    assert result.node_llm_calls["explain"] == 1
    assert result.llm_stats["calls"] == 1 + result.plan_attempts + 1
    assert all(t.explanation for t in result.tests)
