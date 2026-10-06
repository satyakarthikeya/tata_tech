"""Parsing of the import format: provenance, strictness, per-test and file-level errors."""

from __future__ import annotations

import pytest

from uds_assistant.importer import ImportFormatError, parse_import
from uds_assistant.importer.format import MAX_FILE_BYTES

MINIMAL = """
format_version: 1
suite: s
tests:
  - id: T1
    title: t
    steps:
      - send: "22 F1 86"
        expect: "62 F1 86 01"
"""


def test_regression_fixture_parses_with_provenance(regression_text):
    parsed = parse_import(regression_text, "legacy.yaml")
    assert parsed.suite == "legacy_bcm_regression"
    assert len(parsed.tests) == 14
    assert all(p.test is not None and not p.errors for p in parsed.tests)
    t = parsed.tests[0].test
    assert t.origin == "imported"
    assert t.review_status == "draft"
    assert t.template_id is None
    assert t.provenance.source_file == "legacy.yaml"
    assert t.provenance.source_id == "LEG-001"
    assert t.provenance.source_template == "TPL_READ_DID"
    assert len(t.provenance.source_sha256) == 64
    assert t.steps[0].request_hex == "22f190"  # normalised hex


def test_single_string_expect_becomes_list():
    t = parse_import(MINIMAL).tests[0].test
    assert t.steps[0].expected_responses_hex == ["62f18601"]


def test_category_is_inferred_when_missing(regression_text):
    cats = {p.source_id: p.test.category for p in parse_import(regression_text).tests}
    assert cats["LEG-004"] == "negative"  # last response is a 7F
    assert cats["LEG-001"] == "positive"
    assert cats["LEG-003"] == "session"  # contains 0x10


def test_per_test_errors_do_not_stop_the_file(errors_text):
    parsed = parse_import(errors_text, "e.yaml")
    ok = [p.source_id for p in parsed.tests if p.test is not None]
    assert ok == ["ERR-001", "ERR-002", "ERR-003", "ERR-008"]
    bad = [p.errors for p in parsed.tests if p.test is None]
    assert len(bad) == 4
    text = " ".join(" ".join(e) for e in bad)
    assert "Extra inputs are not permitted" in text
    assert "steps.0" in text  # hex error carries the step index
    assert "at least one send step" in text
    assert "duplicate test id" in text


@pytest.mark.parametrize("doc, needle", [
    ("just text", "mapping"),
    ("format_version: 2\ntests: [{}]", "format_version"),
    ("format_version: 1\ntests: []", "non-empty"),
    ("format_version: 1\nmystery: 1\ntests: [{}]", "unknown top-level"),
    ("format_version: 1\ntests: [", "not valid"),
])
def test_file_level_errors(doc, needle):
    with pytest.raises(ImportFormatError, match=needle):
        parse_import(doc)


def test_size_limit():
    with pytest.raises(ImportFormatError, match="limit"):
        parse_import(b"x" * (MAX_FILE_BYTES + 1))


def test_yaml_is_loaded_safely():
    with pytest.raises(ImportFormatError):
        parse_import("format_version: !!python/object/apply:os.system ['echo hi']\ntests: []")


def test_send_requires_expect_and_one_kind_per_step():
    doc = MINIMAL.replace('        expect: "62 F1 86 01"\n', "")
    assert "needs 'expect'" in " ".join(parse_import(doc).tests[0].errors)
    both = MINIMAL.replace("      - send", "      - wait_ms: 5\n        send")
    assert "exactly one" in " ".join(parse_import(both).tests[0].errors)
