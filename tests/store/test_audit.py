"""AuditStore: SQLite audit trail of runs, tests, decisions and results."""

from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.model import SendStep
from uds_assistant.testgen.model import TestCase as UdsTestCase


def _test(test_id: str = "t1") -> UdsTestCase:
    return UdsTestCase(
        id=test_id,
        title="Read VIN",
        requirement_ids=["REQ-001"],
        category="positive",
        template_id="read_did_positive",
        steps=[SendStep(request_hex="22f190", expected_responses_hex=["62f190"])],
        origin="generated",
    )


@pytest.fixture
def store(tmp_path: Path) -> AuditStore:
    s = AuditStore(tmp_path / "sub" / "audit.db")
    yield s
    s.close()


def test_run_lifecycle(store: AuditStore) -> None:
    run_id = store.start_run("REQ-001", "Read the VIN.", "mock", "Bm25Retriever")
    run = store.get_run(run_id)
    assert run is not None
    assert (run.requirement_id, run.llm_mode, run.retriever, run.status) == (
        "REQ-001", "mock", "Bm25Retriever", "running",
    )
    assert run.finished_at is None
    store.finish_run(run_id, "completed")
    run = store.get_run(run_id)
    assert run is not None and run.status == "completed" and run.finished_at is not None
    assert store.get_run(999) is None


def test_list_runs_filter(store: AuditStore) -> None:
    a = store.start_run("REQ-001", "a", "mock", "bm25")
    b = store.start_run("REQ-002", "b", "ollama", "bm25")
    c = store.start_run("REQ-001", "c", "mock", "bm25")
    assert [r.id for r in store.list_runs()] == [a, b, c]
    assert [r.id for r in store.list_runs("REQ-001")] == [a, c]


def test_tests_round_trip_and_review_status(store: AuditStore) -> None:
    run_id = store.start_run("REQ-001", "x", "mock", "bm25")
    store.record_test(run_id, _test("t1"))
    store.record_test(run_id, _test("t2"))
    got = store.get_tests(run_id)
    assert [t.id for t in got] == ["t1", "t2"]
    assert got[0] == _test("t1")

    store.set_review_status(run_id, "t2", "human_reviewed")
    assert store.get_tests(run_id)[1].review_status == "human_reviewed"
    with pytest.raises(KeyError):
        store.set_review_status(run_id, "missing", "validated")


def test_decisions_in_order_and_by_node(store: AuditStore) -> None:
    run_id = store.start_run("REQ-001", "x", "mock", "bm25")
    other = store.start_run("REQ-002", "y", "mock", "bm25")
    store.record_decision(run_id, "parse", "p1")
    store.record_decision(run_id, "plan", "q1")
    store.record_decision(other, "plan", "other")
    store.record_decision(run_id, "plan", "q2")
    assert [d.message for d in store.get_decisions(run_id)] == ["p1", "q1", "q2"]
    assert [d.message for d in store.get_decisions(run_id, node="plan")] == ["q1", "q2"]


def test_results_with_bug_filter(store: AuditStore) -> None:
    run_id = store.start_run("REQ-001", "x", "mock", "bm25")
    store.record_result(run_id, "t1", True, {"steps": 1})
    store.record_result(run_id, "t1", False, {"first_failure": 0}, bug_id="static_seed")
    store.record_result(run_id, "t2", True, None, bug_id="static_seed")
    all_rows = store.get_results(run_id)
    assert [(r.test_id, r.passed, r.bug_id) for r in all_rows] == [
        ("t1", True, None), ("t1", False, "static_seed"), ("t2", True, "static_seed"),
    ]
    assert all_rows[1].details == {"first_failure": 0}
    clean = store.get_results(run_id, bug_id=None, any_bug=False)
    assert [r.test_id for r in clean] == ["t1"]
    bug = store.get_results(run_id, bug_id="static_seed", any_bug=False)
    assert len(bug) == 2


def test_persists_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "a.db"
    with AuditStore(path) as s:
        run_id = s.start_run("REQ-001", "x", "mock", "bm25")
        s.record_test(run_id, _test())
        s.record_decision(run_id, "parse", "hello")
    with AuditStore(path) as s:
        assert s.get_tests(run_id)[0].id == "t1"
        assert s.get_decisions(run_id)[0].message == "hello"


def test_in_memory_store() -> None:
    with AuditStore(":memory:") as s:
        run_id = s.start_run("R", "x", "mock", "bm25")
        assert s.get_run(run_id) is not None
