"""Runner: pass/fail, timing checks, audit recording, and bug-matrix logic."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from uds_assistant.runner import run_bug_matrix, run_suite, run_test
from uds_assistant.runner import suite as suite_mod
from uds_assistant.simulator import IMPLEMENTED_BUG_IDS, load_bug_catalog
from uds_assistant.spec.schema import EcuSpec, load_spec
from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.model import TestCase, load_tests

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def spec() -> EcuSpec:
    return load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")


@pytest.fixture(scope="module")
def gold() -> list[TestCase]:
    return load_tests(REPO_ROOT / "data" / "gold" / "gold_tests.yaml")


def _by_id(tests: list[TestCase], test_id: str) -> TestCase:
    return next(t for t in tests if t.id == test_id)


def _break_expected(test: TestCase) -> TestCase:
    """Copy of ``test`` whose last send step expects a wrong (but well-formed) response."""
    broken = test.model_copy(deep=True)
    broken.id = test.id + "_broken"
    last = [s for s in broken.steps if s.kind == "send"][-1]
    last.expected_responses_hex = ["7f2231"]
    return broken


def test_gold_suite_passes_on_clean_simulator(spec: EcuSpec, gold: list[TestCase]) -> None:
    result = run_suite(gold, spec)
    assert result.total == len(gold)
    assert result.failed_ids == []
    assert result.pass_rate == 1.0
    assert result.bugs == []


def test_step_timings_cover_every_send_step(spec: EcuSpec, gold: list[TestCase]) -> None:
    test = _by_id(gold, "gold_routine_nvm_restore_long_running")
    result = run_test(test, spec)
    send_indices = [i for i, s in enumerate(test.steps) if s.kind == "send"]
    assert [t.step_index for t in result.step_timings] == send_indices
    assert all(t.elapsed_ms >= 0 for t in result.step_timings)
    # The long-running start answers 7F 31 78 first -> checked against P2*, others against P2.
    sources = {t.limit_source for t in result.step_timings}
    assert sources == {"p2", "p2_star"}
    assert result.timing_passed and result.passed


def test_broken_expected_response_fails(spec: EcuSpec, gold: list[TestCase]) -> None:
    broken = _break_expected(_by_id(gold, "gold_read_vin_default"))
    result = run_test(broken, spec)
    assert not result.passed and not result.functional_passed
    assert "step 0" in result.failure_detail


def test_bug_makes_a_test_fail(spec: EcuSpec, gold: list[TestCase]) -> None:
    test = _by_id(gold, "gold_write_readonly_did")
    assert run_suite([test], spec).failed_ids == []
    bugged = run_suite([test], spec, {"readonly_did_writable"})
    assert bugged.failed_ids == [test.id]
    assert bugged.results[0].bug_id == "readonly_did_writable"


class _FakeClock:
    def __init__(self, step_s: float) -> None:
        self._counter = itertools.count()
        self.step_s = step_s

    def __call__(self) -> float:
        return next(self._counter) * self.step_s


def test_explicit_max_response_time_is_enforced(
    spec: EcuSpec, gold: list[TestCase], monkeypatch: pytest.MonkeyPatch
) -> None:
    test = _by_id(gold, "gold_read_vin_default").model_copy(deep=True)
    test.steps[0].max_response_time_ms = 1  # type: ignore[union-attr]
    # Every perf_counter() call advances 60 ms, so each handle() "takes" 60 ms.
    monkeypatch.setattr(suite_mod.time, "perf_counter", _FakeClock(0.060))
    result = run_test(test, spec)
    assert result.functional_passed
    assert not result.timing_passed and not result.passed
    assert result.step_timings[0].limit_source == "max_response_time_ms"
    assert "> 1 ms" in result.failure_detail


def test_p2_overrun_is_a_warning_not_a_failure(
    spec: EcuSpec, gold: list[TestCase], monkeypatch: pytest.MonkeyPatch
) -> None:
    test = _by_id(gold, "gold_read_vin_default")
    monkeypatch.setattr(suite_mod.time, "perf_counter", _FakeClock(0.060))  # 60 ms > P2 50 ms
    result = run_test(test, spec)
    assert result.passed
    assert result.timing_warnings and "p2 50 ms" in result.timing_warnings[0]


def test_results_recorded_in_audit_store(spec: EcuSpec, gold: list[TestCase]) -> None:
    tests = gold[:3]
    with AuditStore(":memory:") as store:
        run_id = store.start_run("EVAL", "runner test", "mock", "none")
        run_suite(tests, spec, None, store, run_id)
        run_suite(tests, spec, {"static_seed"}, store, run_id)
        clean = store.get_results(run_id, bug_id=None, any_bug=False)
        bugged = store.get_results(run_id, bug_id="static_seed", any_bug=False)
    assert [r.test_id for r in clean] == [t.id for t in tests]
    assert len(bugged) == 3 and all(r.bug_id == "static_seed" for r in bugged)
    assert "functional_passed" in clean[0].details


def test_bug_matrix_flags_broken_test_as_invalid_not_detection(
    spec: EcuSpec, gold: list[TestCase]
) -> None:
    good = _by_id(gold, "gold_write_readonly_did")
    broken = _break_expected(_by_id(gold, "gold_read_vin_default"))
    matrix = run_bug_matrix([good, broken], spec, ["readonly_did_writable", "static_seed"])
    assert matrix.valid_test_ids == [good.id]
    assert [t.test_id for t in matrix.invalid_tests] == [broken.id]
    readonly = matrix.get("readonly_did_writable")
    assert readonly is not None and readonly.detected
    assert readonly.detecting_tests == [good.id]
    # The broken test fails under every bug, but that never counts as detection.
    static = matrix.get("static_seed")
    assert static is not None and not static.detected
    assert static.failing_invalid_tests == [broken.id]
    assert matrix.detection_rate == 0.5
    assert matrix.undetected_bug_ids == ["static_seed"]


def test_bug_matrix_only_broken_tests_detects_nothing(spec: EcuSpec, gold: list[TestCase]) -> None:
    broken = _break_expected(_by_id(gold, "gold_write_readonly_did"))
    matrix = run_bug_matrix([broken], spec, ["readonly_did_writable"])
    assert matrix.valid_test_ids == []
    assert matrix.detection_rate == 0.0


def test_bug_matrix_defaults_to_full_catalog(spec: EcuSpec, gold: list[TestCase]) -> None:
    matrix = run_bug_matrix(gold[:2], spec)
    assert matrix.bug_ids == load_bug_catalog().ids
    assert set(matrix.bug_ids) == set(IMPLEMENTED_BUG_IDS)


def test_gold_matrix_detections_come_from_valid_tests(spec: EcuSpec, gold: list[TestCase]) -> None:
    matrix = run_bug_matrix(gold, spec)
    assert matrix.invalid_tests == []
    valid = set(matrix.valid_test_ids)
    for bug in matrix.per_bug:
        assert bug.detected == bool(bug.detecting_tests)
        assert set(bug.detecting_tests) <= valid
    assert "gold_write_readonly_did" in matrix.get("readonly_did_writable").detecting_tests  # type: ignore[union-attr]
