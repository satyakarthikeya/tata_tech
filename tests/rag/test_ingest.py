"""Tests for corpus building: chunk counts, collections, and identifiers."""

from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.rag.ingest import build_corpus, extract_identifiers, normalize_identifier

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def corpus():
    return build_corpus(REPO_ROOT)


def test_corpus_nonempty(corpus):
    assert len(corpus) > 20


def test_all_four_collections_present(corpus):
    collections = {c.collection for c in corpus}
    assert collections == {"standard", "oem", "ecu", "project"}


def test_ecu_has_one_chunk_per_did_routine_dtc(corpus):
    ecu_chunks = [c for c in corpus if c.collection == "ecu"]
    refs = {c.ref for c in ecu_chunks}
    # From data/bcm_spec.yaml: 14 DIDs, 3 routines, 3 DTCs, 3 sessions, 2 security levels.
    did_refs = [r for r in refs if r.startswith("did:")]
    routine_refs = [r for r in refs if r.startswith("routine:")]
    dtc_refs = [r for r in refs if r.startswith("dtc:")]
    session_refs = [r for r in refs if r.startswith("session:")]
    level_refs = [r for r in refs if r.startswith("security_level:")]
    assert len(did_refs) == 14
    assert len(routine_refs) == 3
    assert len(dtc_refs) == 3
    assert len(session_refs) == 3
    assert len(level_refs) == 2


def test_vin_chunk_mentions_hex_did(corpus):
    vin_chunks = [c for c in corpus if c.collection == "ecu" and c.ref == "did:VIN"]
    assert len(vin_chunks) == 1
    assert "0xF190" in vin_chunks[0].text
    assert "0xF190" in vin_chunks[0].identifiers


def test_standard_collection_has_service_sections(corpus):
    standard_refs = {c.ref for c in corpus if c.collection == "standard"}
    for svc_anchor in ["svc-0x10", "svc-0x22", "svc-0x27", "svc-0x2e", "svc-0x31", "svc-0x3e"]:
        assert svc_anchor in standard_refs


def test_project_collection_has_requirements(corpus):
    project_refs = {c.ref for c in corpus if c.collection == "project"}
    assert "REQ-001" in project_refs
    assert "REQ-010" in project_refs


def test_chunk_fields_well_formed(corpus):
    for chunk in corpus:
        assert chunk.id
        assert chunk.collection in {"standard", "oem", "ecu", "project"}
        assert chunk.source_path
        assert chunk.ref
        assert chunk.text.strip()


def test_chunk_ids_are_unique(corpus):
    ids = [c.id for c in corpus]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0xF190", "0xF190"),
        ("F190", "0xF190"),
        ("f190", "0xF190"),
        ("0x22", "0x22"),
        ("22", "0x22"),
    ],
)
def test_normalize_identifier(raw, expected):
    assert normalize_identifier(raw) == expected


def test_extract_identifiers_dedupes_and_normalizes():
    ids = extract_identifiers("See 0xF190 and 0xf190 again, plus 0x22.")
    assert ids == ["0xF190", "0x22"]
