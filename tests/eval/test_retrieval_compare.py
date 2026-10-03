"""Retrieval comparison: scoring on hand examples (no model) plus a needs_model end-to-end run."""

from __future__ import annotations

import pytest

from uds_assistant.eval.retrieval_compare import (
    first_relevant_rank,
    relevant_chunk_ids,
    render_section,
    run_retrieval_comparison,
    score_ranks,
)
from uds_assistant.rag.model import Chunk


def test_first_relevant_rank_basic_and_miss():
    assert first_relevant_rank(["a", "b", "c"], {"b"}) == 2
    assert first_relevant_rank(["a", "b", "c"], {"c", "b"}) == 2
    assert first_relevant_rank(["a", "b", "c"], {"z"}) == 0


def test_first_relevant_rank_respects_limit():
    ranked = [f"x{i}" for i in range(12)]
    assert first_relevant_rank(ranked, {"x10"}) == 0
    assert first_relevant_rank(ranked, {"x9"}) == 10


def test_score_ranks_hand_example():
    # ranks: 1, 3, 0 (miss), 2  ->  hit@1 1/4, hit@3 3/4, MRR (1 + 1/3 + 0 + 1/2)/4
    s = score_ranks([1, 3, 0, 2])
    assert s["queries"] == 4
    assert s["hit_at_1"] == 0.25
    assert s["hit_at_3"] == 0.75
    assert s["mrr"] == pytest.approx((1 + 1 / 3 + 0.5) / 4, abs=1e-4)


def test_score_ranks_empty():
    assert score_ranks([])["mrr"] is None


def _chunks() -> list[Chunk]:
    return [
        Chunk(id="ecu_spec:did:VIN", collection="ecu_spec", source_path="s", ref="did:VIN",
              text="t", identifiers=["0x22", "0xF190"]),
        Chunk(id="ecu_spec:did:W", collection="ecu_spec", source_path="s", ref="did:W",
              text="t", identifiers=["0x22", "0x0130"]),
        Chunk(id="standard:svc-0x27", collection="standard", source_path="s", ref="svc-0x27",
              text="t", identifiers=["0x27"]),
    ]


def test_relevance_prefers_did_targets_then_services_then_excludes():
    corpus = _chunks()
    assert relevant_chunk_ids(
        {"target_services": "0x22", "target_dids": "0xf190", "target_routines": ""}, corpus
    ) == {"ecu_spec:did:VIN"}
    assert relevant_chunk_ids(
        {"target_services": "0x27", "target_dids": "", "target_routines": ""}, corpus
    ) == {"standard:svc-0x27"}
    assert relevant_chunk_ids(
        {"target_services": "", "target_dids": "", "target_routines": ""}, corpus
    ) == set()


def test_render_section_not_run():
    text = "\n".join(render_section({"status": "not run", "reason": "because"}))
    assert "Not run: because" in text


@pytest.mark.needs_model
def test_full_comparison_runs_both_backends(tmp_path):
    cmp = run_retrieval_comparison(persist_dir=tmp_path / "chroma")
    assert cmp["excluded"] == ["NAT-020"]
    assert cmp["queries_scored"] == 19
    for name in ("bm25", "chroma"):
        assert cmp["backends"][name]["status"] == "completed", cmp["backends"][name]
        for split in ("dev", "test", "all"):
            s = cmp["backends"][name]["splits"][split]
            assert 0 <= s["hit_at_1"] <= s["hit_at_3"] <= 1
            assert 0 <= s["mrr"] <= 1
            assert s["citation_validity"] == 1.0
    assert cmp["backends"]["bm25"]["splits"]["dev"]["queries"] == 8
    assert cmp["backends"]["bm25"]["splits"]["test"]["queries"] == 11
