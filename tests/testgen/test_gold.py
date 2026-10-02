from __future__ import annotations

from uds_assistant.simulator import IMPLEMENTED_BUG_IDS, SimulatedEcu
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.execute import run_test_on_simulator
from uds_assistant.testgen.model import TestCase
from uds_assistant.testgen.templates import validate_test


def test_gold_count_between_40_and_60(gold_tests: list[TestCase]) -> None:
    assert 40 <= len(gold_tests) <= 60


def test_gold_ids_are_unique(gold_tests: list[TestCase]) -> None:
    ids = [t.id for t in gold_tests]
    assert len(ids) == len(set(ids))


def test_gold_origin_is_gold_and_no_template(gold_tests: list[TestCase]) -> None:
    for t in gold_tests:
        assert t.origin == "gold"
        assert t.template_id is None


def test_gold_covers_all_five_categories(gold_tests: list[TestCase]) -> None:
    categories = {t.category for t in gold_tests}
    assert categories == {"positive", "negative", "session", "security", "timing"}


def test_gold_has_citations(gold_tests: list[TestCase]) -> None:
    for t in gold_tests:
        assert t.citations, f"{t.id} has no citations"


def pytest_generate_tests(metafunc):
    if "gold_test" in metafunc.fixturenames:
        from pathlib import Path

        from uds_assistant.testgen.model import load_tests

        repo_root = Path(__file__).resolve().parents[2]
        tests = load_tests(repo_root / "data" / "gold" / "gold_tests.yaml")
        metafunc.parametrize("gold_test", tests, ids=[t.id for t in tests])


def test_gold_test_passes_on_clean_simulator(gold_test: TestCase, spec: EcuSpec) -> None:
    outcome = run_test_on_simulator(gold_test, lambda: SimulatedEcu(spec))
    assert outcome.passed, f"{gold_test.id}: {outcome.first_failure}"


def test_gold_test_validates_against_oracle(gold_test: TestCase, spec: EcuSpec) -> None:
    report = validate_test(spec, gold_test)
    assert report.ok, f"{gold_test.id}: {report.mismatches}"


def test_gold_set_detects_some_catalog_bugs(gold_tests: list[TestCase], spec: EcuSpec) -> None:
    """Sanity check: the gold set, taken together, must catch *some* real bugs.

    This reports the actual detected count; it never fakes or pads the number.
    """
    detected: set[str] = set()
    for bug_id in sorted(IMPLEMENTED_BUG_IDS):
        for t in gold_tests:
            outcome = run_test_on_simulator(
                t, lambda bug_id=bug_id: SimulatedEcu(spec, bugs=[bug_id])
            )
            if not outcome.passed:
                detected.add(bug_id)
                break
    print(f"Gold set detects {len(detected)}/{len(IMPLEMENTED_BUG_IDS)} catalog bugs: {sorted(detected)}")
    assert len(detected) > 0
