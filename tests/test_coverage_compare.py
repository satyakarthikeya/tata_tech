"""Baseline vs generated vs combined coverage, including timing cases."""

from __future__ import annotations

import pytest

from uds_assistant.eval.coverage import coverage_report
from uds_assistant.eval.coverage_compare import (
    ALL_KINDS,
    TIMING_CASES,
    compare_coverage,
    comparison_markdown,
    timing_cases,
)
from uds_assistant.importer import parse_import
from uds_assistant.testgen.conformance import build_conformance_suite
from uds_assistant.testgen.model import TestCase


@pytest.fixture(scope="module")
def sweep(spec) -> list[TestCase]:
    return build_conformance_suite(spec).tests


@pytest.fixture
def imported(regression_text) -> list[TestCase]:
    return [p.test for p in parse_import(regression_text, "r.yaml").tests]


def test_baseline_matches_coverage_report(spec, imported):
    cmp = compare_coverage(imported, [], spec)
    base = coverage_report(imported, spec)
    for kind in ("service", "did", "routine", "nrc", "session", "security_level"):
        touched = sum(1 for r in base["items"][kind] if r["tests"])
        assert cmp["summary"][kind]["imported"] == touched
        assert cmp["summary"][kind]["items"] == len(base["items"][kind])
    assert cmp["summary"]["routine"]["imported"] == 0  # the fixture has no 0x31 test
    assert cmp["newly_covered"]["routine"] == []  # nothing generated to add


def test_combined_closes_gaps_and_never_loses_coverage(spec, imported, sweep):
    cmp = compare_coverage(imported, sweep, spec)
    assert cmp["tests"] == {"imported": 14, "generated": 1200, "combined": 1214}
    for kind in ALL_KINDS:
        s = cmp["summary"][kind]
        assert s["combined"] >= max(s["imported"], s["generated"])
        for r in cmp["rows"][kind]:
            assert r["combined"] == r["imported"] + r["generated"]
    assert len(cmp["newly_covered"]["routine"]) == 3
    assert "0x0201 lighting_self_test" in cmp["newly_covered"]["routine"]
    assert "0x78 requestCorrectlyReceivedResponsePending" in cmp["newly_covered"]["nrc"]
    assert "0x02 programming" in cmp["newly_covered"]["session"]
    assert "0x03 programming" in cmp["newly_covered"]["security_level"]
    # newly covered really means zero imported tests
    for kind in ALL_KINDS:
        zero = {r["item"] for r in cmp["rows"][kind] if r["imported"] == 0}
        assert set(cmp["newly_covered"][kind]) <= zero


def test_ids_cannot_collide_between_imported_and_generated(spec, imported):
    clash = imported[0].model_copy(update={"origin": "generated"})  # same id as the import
    cmp = compare_coverage(imported[:1], [clash], spec)
    assert cmp["tests"]["combined"] == 2
    row = next(r for r in cmp["rows"]["service"] if r["item"].startswith("0x22"))
    assert (row["imported"], row["generated"], row["combined"]) == (1, 1, 2)


def test_timing_cases_in_imported_suite(spec, imported):
    got = timing_cases(imported, spec)
    assert got["p2_response_limit"] == {"LEG-014"}
    assert got["s3_timeout"] == {"LEG-013"}
    assert got["response_pending"] == set() and got["security_delay"] == set()


def test_timing_cases_keepalive_and_security_delay(spec):
    from uds_assistant.importer.format import parse_import as parse

    doc = """
format_version: 1
tests:
  - id: KEEP
    title: wait inside S3
    steps:
      - {send: "10 03", expect: ["50 03 00 32 01 F4"]}
      - {wait_ms: 3000}
      - {send: "22 F1 86", expect: ["62 F1 86 03"]}
  - id: LOCK
    title: lockout then wait then seed
    steps:
      - {send: "10 03", expect: ["50 03 00 32 01 F4"]}
      - {send: "27 01", expect: ["67 01 95 06 77 E8"]}
      - {send: "27 02 DE AD BE EF", expect: ["7F 27 35"]}
      - {send: "27 01", expect: ["67 01 32 A3 14 85"]}
      - {send: "27 02 DE AD BE EF", expect: ["7F 27 35"]}
      - {send: "27 01", expect: ["67 01 CF 40 B1 22"]}
      - {send: "27 02 DE AD BE EF", expect: ["7F 27 36"]}
      - {send: "27 01", expect: ["7F 27 37"]}
  - id: DELAY
    title: lockout, wait out the delay with keep-alives, seed is granted again
    steps:
      - {send: "10 03", expect: ["50 03 00 32 01 F4"]}
      - {send: "27 01", expect: ["67 01 95 06 77 E8"]}
      - {send: "27 02 DE AD BE EF", expect: ["7F 27 35"]}
      - {send: "27 01", expect: ["67 01 32 A3 14 85"]}
      - {send: "27 02 DE AD BE EF", expect: ["7F 27 35"]}
      - {send: "27 01", expect: ["67 01 CF 40 B1 22"]}
      - {send: "27 02 DE AD BE EF", expect: ["7F 27 36"]}
      - {send: "27 01", expect: ["7F 27 37"]}
      - {wait_ms: 4000}
      - {send: "3E 00", expect: ["7E 00"]}
      - {wait_ms: 4000}
      - {send: "3E 00", expect: ["7E 00"]}
      - {wait_ms: 3000}
      - {send: "27 01", expect: ["67 01 6C DD 4E BF"]}
"""
    tests = [p.test for p in parse(doc).tests]
    assert all(t is not None for t in tests)
    got = timing_cases(tests, spec)
    assert got["s3_keepalive"] == {"KEEP", "DELAY"}
    assert got["security_delay"] == {"DELAY"}  # LOCK retries at once, without waiting


def test_markdown_has_all_sections(spec, imported, sweep):
    md = comparison_markdown(compare_coverage(imported, sweep, spec))
    for needle in ("## Summary", "## Newly covered", "## Covered only by imported tests",
                   "## Still uncovered by the combined suite", "### Timing cases",
                   "Routines | 0/3 | 3/3 | 3/3 | 3", "not AI-generated"):
        assert needle in md
    for label in TIMING_CASES.values():
        assert label in md
