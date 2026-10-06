"""Validation against the rules engine, review gating, provenance and the audit trail."""

from __future__ import annotations

import pytest

from uds_assistant.importer import import_tests, load_import_result, parse_import
from uds_assistant.runner import run_suite
from uds_assistant.testgen.review_gate import NoApprovedTestsError, select_for_run
from uds_assistant.ui import state as review


def test_regression_fixture_is_fully_accepted(spec, store, regression_text):
    res = import_tests(parse_import(regression_text, "r.yaml"), spec, store)
    assert (res.total, res.accepted, res.oracle_mismatch, res.invalid) == (14, 14, 0, 0)
    tests = store.get_tests(res.run_id)
    assert len(tests) == 14
    for t in tests:
        assert t.origin == "imported"
        assert t.review_status == "validated"  # never auto-approved
        assert t.provenance is not None and t.provenance.source_file == "r.yaml"
        assert t.pass_criteria  # filled deterministically
        assert any(c.source == "import:r.yaml" for c in t.citations)


def test_spec_citations_are_derived_from_what_the_test_touches(spec, store, regression_text):
    res = import_tests(parse_import(regression_text, "r.yaml"), spec, store)
    t = next(t for t in store.get_tests(res.run_id) if t.id == "LEG-009")
    refs = {c.ref for c in t.citations if c.source == "bcm_spec.yaml"}
    assert {"dids.interior_lighting_brightness_pct", "security_levels.extended_diag",
            "sessions.extended"} <= refs


def test_errors_fixture_outcomes(spec, store, errors_text):
    res = import_tests(parse_import(errors_text, "e.yaml"), spec, store)
    assert (res.accepted, res.oracle_mismatch, res.invalid) == (2, 2, 4)
    by = {(o.source_id, o.status) for o in res.outcomes}
    assert ("ERR-002", "oracle_mismatch") in by and ("ERR-003", "oracle_mismatch") in by
    mismatch = next(o for o in res.outcomes if o.source_id == "ERR-003")
    assert "oracle now says" in mismatch.errors[0]
    # mismatching and invalid tests are not stored as runnable tests
    assert [t.id for t in store.get_tests(res.run_id)] == ["ERR-001", "ERR-008"]


def test_hand_written_values_are_kept(spec, store):
    doc = """
format_version: 1
tests:
  - id: K1
    title: keeps text
    preconditions: [my precondition]
    pass_criteria: my criteria
    steps: [{send: "22 F1 86", expect: ["62 F1 86 01"]}]
"""
    res = import_tests(parse_import(doc), spec, store)
    t = store.get_tests(res.run_id)[0]
    assert t.preconditions == ["my precondition"] and t.pass_criteria == "my criteria"


def test_review_gate_blocks_run_until_approved(spec, store, regression_text):
    res = import_tests(parse_import(regression_text, "r.yaml"), spec, store)
    with pytest.raises(NoApprovedTestsError):
        select_for_run(store.get_tests(res.run_id))
    review.approve(store, res.run_id, "LEG-001", "looks right")
    approved = select_for_run(store.get_tests(res.run_id))
    assert [t.id for t in approved] == ["LEG-001"]
    assert approved[0].origin == "imported"
    assert run_suite(approved, spec).passed_count == 1
    assert review.review_log(store, res.run_id, "LEG-001") == [("approved", "looks right")]


def test_audit_trail_records_the_import(spec, store, errors_text):
    res = import_tests(parse_import(errors_text, "e.yaml"), spec, store)
    run = store.get_run(res.run_id)
    assert run.llm_mode == "import" and run.status == "completed"
    assert run.requirement_id == "import:legacy_bcm_with_errors"
    assert res.sha256 in run.requirement_text
    lines = [d.message for d in store.get_decisions(res.run_id, "import")]
    assert len(lines) == res.total
    assert any(m.startswith("ERR-002 | oracle_mismatch") for m in lines)
    assert load_import_result(store, res.run_id) == res


def test_load_import_result_ignores_other_runs(store):
    rid = store.start_run("REQ-1", "text", "ollama", "chroma")
    assert load_import_result(store, rid) is None
    assert load_import_result(store, 999) is None


def test_clean_simulator_agrees_with_accepted_imports(spec, store, regression_text):
    res = import_tests(parse_import(regression_text, "r.yaml"), spec, store)
    suite = run_suite(store.get_tests(res.run_id), spec)
    assert suite.passed_count == suite.total == 14
