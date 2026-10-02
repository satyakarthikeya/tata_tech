"""End-to-end agent pipeline in mock mode: both engines, coverage, audit trail."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.agent.conftest import SEED_REQUIREMENTS
from uds_assistant.agent import PipelineResult, resolve_engine, run_pipeline
from uds_assistant.agent import pipeline as pipeline_mod
from uds_assistant.llm.mock import MockLLM
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.rag.citations import citation_is_valid
from uds_assistant.rag.model import Chunk
from uds_assistant.simulator import SimulatedEcu
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.execute import run_test_on_simulator
from uds_assistant.testgen.templates import TEMPLATES, validate_test

REQ_IDS = [r["id"] for r in SEED_REQUIREMENTS]
REQ_TEXT = {r["id"]: r["text"] for r in SEED_REQUIREMENTS}

_CACHE: dict[tuple[str, str], PipelineResult] = {}


def _run(req_id: str, engine: str, spec: EcuSpec, retriever: Bm25Retriever) -> PipelineResult:
    key = (req_id, engine)
    if key not in _CACHE:
        _CACHE[key] = run_pipeline(
            REQ_TEXT[req_id], req_id, spec, MockLLM(), retriever, engine=engine
        )
    return _CACHE[key]


def test_langgraph_is_available_here() -> None:
    assert pipeline_mod.langgraph_available()
    assert resolve_engine(None) in ("langgraph", "plain")


@pytest.mark.parametrize("req_id", REQ_IDS)
def test_langgraph_and_plain_produce_identical_results(
    req_id: str, spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    lg = _run(req_id, "langgraph", spec, retriever)
    plain = _run(req_id, "plain", spec, retriever)
    assert lg.engine == "langgraph" and plain.engine == "plain"
    assert lg.model_dump(exclude={"engine"}) == plain.model_dump(exclude={"engine"})


@pytest.mark.parametrize("req_id", REQ_IDS)
def test_each_requirement_yields_valid_cited_executable_tests(
    req_id: str, spec: EcuSpec, retriever: Bm25Retriever, corpus: list[Chunk]
) -> None:
    result = _run(req_id, "plain", spec, retriever)
    assert result.status == "completed"
    assert len(result.tests) >= 3, result.decisions
    assert result.dropped == []
    assert len({t.id for t in result.tests}) == len(result.tests)
    for test in result.tests:
        assert test.origin == "generated"
        assert test.review_status == "validated"
        assert test.requirement_ids == [req_id]
        assert test.template_id in TEMPLATES
        assert test.explanation
        assert validate_test(spec, test).ok
        assert test.citations
        for c in test.citations:
            assert citation_is_valid(c, corpus), (test.id, c)
        outcome = run_test_on_simulator(test, lambda: SimulatedEcu(spec))
        assert outcome.passed, (test.id, outcome.first_failure)


def test_tests_cite_their_requirement_row(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    for req_id in REQ_IDS:
        result = _run(req_id, "plain", spec, retriever)
        for test in result.tests:
            assert any(c.ref == req_id for c in test.citations), test.id


def test_secured_writable_did_requirement_is_thorough(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    result = _run("REQ-005", "plain", spec, retriever)
    templates = {t.template_id for t in result.tests}
    assert {
        "write_did_secured_positive",
        "write_did_without_security",
        "write_did_out_of_range",
        "write_did_invalid_length",
        "service_not_in_session",
        "security_invalid_key_lockout",
        "s3_timeout_reverts_session",
    } <= templates
    assert set(result.category_counts) == {"positive", "negative", "session", "security", "timing"}
    # Every DID-specific test targets the requirement's DID.
    for t in result.tests:
        if "did" in t.parameters:
            assert t.parameters["did"] == 0x0100


@pytest.mark.parametrize(
    ("req_id", "must_include"),
    [
        ("REQ-001", {"read_did_positive"}),
        ("REQ-007", {"write_did_out_of_range", "write_did_secured_positive"}),
        ("REQ-009", {"condition_not_met", "security_invalid_key_lockout"}),
        ("REQ-010", {"security_invalid_key_lockout"}),
        ("REQ-011", {"routine_sequence"}),
        ("REQ-012", {"condition_not_met", "routine_sequence"}),
        ("REQ-013", {"unsupported_subfunction"}),
        ("REQ-014", {"dtc_read_clear", "unsupported_subfunction"}),
        ("REQ-015", {"suppress_positive_response", "s3_timeout_reverts_session"}),
    ],
)
def test_requirement_specific_templates(
    req_id: str, must_include: set[str], spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    result = _run(req_id, "plain", spec, retriever)
    assert must_include <= {t.template_id for t in result.tests}


def test_suite_covers_all_categories(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    cats: set[str] = set()
    for req_id in REQ_IDS:
        cats |= set(_run(req_id, "plain", spec, retriever).category_counts)
    assert cats == {"positive", "negative", "session", "security", "timing"}


def test_pipeline_is_deterministic(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    a = run_pipeline(REQ_TEXT["REQ-006"], "REQ-006", spec, MockLLM(), retriever, engine="plain")
    b = run_pipeline(REQ_TEXT["REQ-006"], "REQ-006", spec, MockLLM(), retriever, engine="plain")
    assert a == b


def test_every_node_logs_decisions(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    result = _run("REQ-005", "plain", spec, retriever)
    nodes = {d.node for d in result.decisions}
    assert nodes == {"parse", "retrieve", "plan", "instantiate", "validate", "explain"}


@pytest.mark.parametrize("engine", ["plain", "langgraph"])
def test_audit_store_records_run(
    engine: str, tmp_path: Path, spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    with AuditStore(tmp_path / "audit.db") as store:
        result = run_pipeline(
            REQ_TEXT["REQ-011"], "REQ-011", spec, MockLLM(), retriever, store, engine=engine
        )
        assert result.run_id is not None
        run = store.get_run(result.run_id)
        assert run is not None
        assert run.status == "completed"
        assert (run.requirement_id, run.llm_mode, run.retriever) == (
            "REQ-011", "mock", "Bm25Retriever",
        )
        stored = store.get_tests(result.run_id)
        assert stored == result.tests
        decisions = store.get_decisions(result.run_id)
        assert decisions[0].node == "pipeline" and f"engine={engine}" in decisions[0].message
        assert [(d.node, d.message) for d in decisions[1:]] == [
            (d.node, d.message) for d in result.decisions
        ]


def test_engine_forced_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UDS_AGENT_ENGINE", "plain")
    assert resolve_engine() == "plain"
    monkeypatch.setenv("UDS_AGENT_ENGINE", "langgraph")
    assert resolve_engine() == "langgraph"
    assert resolve_engine("plain") == "plain"


def test_falls_back_to_plain_without_langgraph(
    monkeypatch: pytest.MonkeyPatch, spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    monkeypatch.delenv("UDS_AGENT_ENGINE", raising=False)
    monkeypatch.setattr(pipeline_mod, "langgraph_available", lambda: False)
    assert resolve_engine() == "plain"
    with pytest.warns(UserWarning):
        assert resolve_engine("langgraph") == "plain"
    result = run_pipeline(REQ_TEXT["REQ-001"], "REQ-001", spec, MockLLM(), retriever)
    assert result.engine == "plain"


def test_failed_run_is_marked_in_store(
    tmp_path: Path, spec: EcuSpec, retriever: Bm25Retriever, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("retriever down")

    monkeypatch.setattr(retriever, "search", boom)
    with AuditStore(tmp_path / "a.db") as store:
        with pytest.raises(RuntimeError):
            run_pipeline("x", "REQ-X", spec, MockLLM(), retriever, store, engine="plain")
        assert store.list_runs()[0].status == "failed"
