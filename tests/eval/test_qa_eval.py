"""Fact matching and source-id mapping of the Q&A scorer."""

from __future__ import annotations

import pytest

from uds_assistant.eval.qa_eval import (
    REPO_ROOT,
    fact_present,
    facts_present,
    load_questions,
    map_source_id,
)
from uds_assistant.rag.ingest import build_corpus


@pytest.mark.parametrize(
    ("atom", "answer", "expected"),
    [
        ("session=extended", "Only in the Extended session.", True),
        ("session=default", "Only in the extended session.", False),
        ("security_level=1", "needs security level 0x01 unlocked", True),
        ("security_level=3", "needs security level 0x01 unlocked", False),
        ("security_level=1", "level 1", True),
        ("security_level=1", "Security Level: 0x01 is needed", True),
        ("security_level=none", "No security is required", True),
        ("length=17", "it is 17 bytes long", True),
        ("length=1", "it is 17 bytes long", False),
        ("length=1", "is 1 byte long", True),
        ("access=read", "it is read-only", True),
        ("access=read", "it is readable and writable", False),
        ("access=write", "it is readable and writable", True),
        ("nrc=0x33", "NRC 0x33 is securityAccessDenied", True),
        ("nrc=0x33", "NRC 0x331", False),
        ("nrc_name=requestOutOfRange", "NRC 0x31 REQUESTOUTOFRANGE", True),
        ("value=5000ms", "P2* = 5000 ms", True),
        ("value=5000ms", "P2* = 15000 ms", False),
        ("value=3attempts", "allows 3 attempts before", True),
        ("value=3attempts", "allows 13 attempts", False),
        ("value=10000ms", "lockout delay of 10000ms", True),
        ("term=default session", "falls back to the Default\n session", True),
        ("term=locks security", "locks any unlocked security level", False),
    ],
)
def test_fact_present(atom, answer, expected):
    assert fact_present(answer, atom) is expected


def test_facts_present_reports_missing():
    ok, missing = facts_present("it is 2 bytes", "length=2;session=programming")
    assert not ok and missing == ["session=programming"]


def test_unknown_key_raises():
    with pytest.raises(ValueError):
        fact_present("x", "bogus=1")


def test_source_mapping_covers_every_gold_id():
    chunks = build_corpus(REPO_ROOT)
    for q in load_questions(REPO_ROOT / "data" / "qa_eval.csv"):
        for g in q["gold_source_ids"]:
            assert map_source_id(g, chunks), f"{q['id']}: {g} maps to nothing"
    assert map_source_id("spec:did:0xF190", chunks) == {"ecu:did:VIN"}
    assert map_source_id("notes:nrcs-in-scope", chunks) == {"standard:nrcs"}
    assert "standard:timing" in map_source_id("notes:timing-p2-p2-s3", chunks)
