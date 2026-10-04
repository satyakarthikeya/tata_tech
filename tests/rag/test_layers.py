"""Four retrieval layers (standard / oem / ecu / project): separation, citations, consistency."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from uds_assistant.rag import layers as layers_api
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.rag.citations import citation_is_valid
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.rag.model import CORE_LAYERS, LAYERS, LayeredCitation

REPO_ROOT = Path(__file__).resolve().parents[2]
OEM_DOC = REPO_ROOT / "data" / "oem_diagnostic_guidelines.md"


@pytest.fixture(scope="module")
def corpus():
    return build_corpus(REPO_ROOT)


@pytest.fixture(scope="module")
def retriever(corpus):
    return Bm25Retriever(corpus)


def test_layers_are_exactly_four(corpus):
    assert LAYERS == ("standard", "oem", "ecu", "project")
    assert {c.layer for c in corpus} == set(LAYERS)
    assert all(v > 0 for v in layers_api.layer_counts(corpus).values())


def test_every_chunk_carries_its_layer(corpus):
    for chunk in corpus:
        assert chunk.layer == chunk.collection
        assert chunk.id.startswith(chunk.layer + ":")


def test_oem_doc_ingested_into_oem_layer_only(corpus):
    oem = [c for c in corpus if c.layer == "oem"]
    assert len(oem) >= 6
    assert {c.source_path for c in oem} == {"data/oem_diagnostic_guidelines.md"}
    from_doc = [c for c in corpus if c.source_path == "data/oem_diagnostic_guidelines.md"]
    assert len(from_doc) == len(oem)
    head = "\n".join(OEM_DOC.read_text(encoding="utf-8").splitlines()[:5])
    assert "SYNTHETIC" in head and "not a real OEM document" in head


def test_layer_sources(corpus):
    sources: dict[str, set[str]] = {}
    for c in corpus:
        sources.setdefault(c.layer, set()).add(c.source_path)
    assert sources == {k: set(v) for k, v in layers_api.LAYER_SOURCES.items()}


def test_build_corpus_layer_filter(corpus):
    core = build_corpus(REPO_ROOT, layers=CORE_LAYERS)
    assert {c.layer for c in core} == set(CORE_LAYERS)
    assert [c.id for c in core] == [c.id for c in corpus if c.layer != "oem"]
    assert {c.layer for c in build_corpus(REPO_ROOT, layers=["ecu_spec"])} == {"ecu"}


def test_oem_has_its_own_bm25_index(retriever, corpus):
    groups = retriever.index_groups
    assert groups["oem"] == sum(1 for c in corpus if c.layer == "oem")
    assert groups["core"] == sum(1 for c in corpus if c.layer != "oem")


def test_core_scores_unchanged_by_oem_layer(corpus):
    with_oem = Bm25Retriever(corpus)
    without = Bm25Retriever(build_corpus(REPO_ROOT, layers=CORE_LAYERS))
    for q in ["security access invalid key", "read VIN", "wiper sensitivity session"]:
        a = [(h.chunk.id, h.score) for h in with_oem.search(q, k=10, collections=list(CORE_LAYERS))]
        b = [(h.chunk.id, h.score) for h in without.search(q, k=10)]
        assert a == b


def test_search_layer_restricts_to_layer(retriever):
    for layer in LAYERS:
        hits = layers_api.search_layer(retriever, "security access session", layer, k=5)
        assert hits and all(h.chunk.layer == layer for h in hits)
    with pytest.raises(ValueError):
        layers_api.search_layer(retriever, "x", "nope")


def test_legacy_alias_still_accepted(retriever):
    hits = retriever.search("wiper sensitivity", k=3, collections=["ecu_spec"])
    assert hits and all(h.chunk.layer == "ecu" for h in hits)


def test_search_layers_returns_all_four(retriever):
    result = layers_api.search_layers(retriever, "diagnostic session timing", k_per_layer=2)
    assert list(result) == list(LAYERS)
    assert all(len(v) == 2 for v in result.values())


def test_lockout_policy_query_retrieves_oem_chunk(retriever):
    query = "security access lockout policy after failed attempts"
    by_layer = layers_api.search_layers(retriever, query, k_per_layer=3)
    assert by_layer["oem"][0].chunk.ref == "oem-security-access"
    assert "10000 ms" in by_layer["oem"][0].chunk.text
    # Filtering by the layer name directly gives the same answer.
    direct = retriever.search(query, k=3, collections=["oem"])
    assert [h.chunk.id for h in direct] == [h.chunk.id for h in by_layer["oem"]]
    # Other layers answer from their own sources, never from the OEM guideline.
    for layer in ("standard", "ecu", "project"):
        assert all(h.chunk.source_path != "data/oem_diagnostic_guidelines.md" for h in by_layer[layer])


def test_citations_expose_layer_and_are_valid(retriever, corpus):
    result = layers_api.search_layers(retriever, "security lockout delay", k_per_layer=2)
    for layer, hits in result.items():
        cites = layers_api.cite_hits(hits)
        assert all(isinstance(c, LayeredCitation) and c.layer == layer for c in cites)
        assert all(citation_is_valid(c, corpus) for c in cites)
        assert all("layer" in c.model_dump() for c in cites)


# ------------------------- OEM guideline numbers vs bcm_spec.yaml -------------------------


def _oem_section(name: str) -> str:
    text = OEM_DOC.read_text(encoding="utf-8")
    m = re.search(rf"^## .*\{{#{name}\}}\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    assert m, name
    return m.group(1)


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load((REPO_ROOT / "data" / "bcm_spec.yaml").read_text(encoding="utf-8"))


def _num(pattern: str, text: str) -> int:
    m = re.search(pattern, text)
    assert m, pattern
    return int(m.group(1))


def test_oem_timing_matches_spec(spec):
    sec = _oem_section("oem-session-timing")
    timings = {tuple(sorted(s["timing"].items())) for s in spec["sessions"]}
    assert len(timings) == 1
    t = spec["sessions"][0]["timing"]
    assert _num(r"P2 server time: (\d+) ms", sec) == t["p2_ms"]
    assert _num(r"P2\* extended server time: (\d+) ms", sec) == t["p2_star_ms"]
    assert _num(r"S3 server timeout: (\d+) ms", sec) == t["s3_ms"]
    assert _num(r"sent as (\d+) \(0x", sec) == t["p2_star_ms"] // 10


def test_oem_security_matches_spec(spec):
    sec = _oem_section("oem-security-access")
    levels = spec["security_levels"]
    assert {lv["max_attempts"] for lv in levels} == {_num(r"allows (\d+) failed key", sec)}
    assert {lv["delay_ms"] for lv in levels} == {_num(r"Lockout delay: (\d+) ms", sec)}
    assert {lv["seed_length"] for lv in levels} == {_num(r"seed is (\d+) bytes", sec)}
    sessions = {s["id"]: s["name"] for s in spec["sessions"]}
    for lv in levels:
        pat = (
            rf"Level 0x{lv['level']:02X} \(.*?\): seed request 0x{lv['seed_subfunction']:02X}, "
            rf"key 0x{lv['key_subfunction']:02X}, available only in the (\w+) session"
        )
        m = re.search(pat, sec)
        assert m, pat
        assert [sessions[i] for i in lv["allowed_sessions"]] == [m.group(1)]


def test_oem_did_and_reset_facts_match_spec(spec):
    did = _oem_section("oem-did-convention")
    ids = {d["id"] for d in spec["dids"]}
    mentioned = re.findall(r"\((0x[0-9A-F]{4})\)", did)
    assert mentioned
    for hex_id in mentioned:
        assert int(hex_id, 16) in ids
    reset = _oem_section("oem-ecu-reset-nvm")
    hard, soft = spec["ecu_reset"]["supported_subfunctions"]
    assert f"hard reset (0x{hard:02X})" in reset
    assert f"soft reset (0x{soft:02X})" in reset
    nvm = next(r for r in spec["routines"] if r["name"] == "nvm_factory_restore")
    assert f"(0x{nvm['id']:04X})" in reset and f"level 0x{nvm['security_level']:02X}" in reset


def test_oem_nrc_order_matches_behaviour_contract():
    sec = _oem_section("oem-nrc-usage")
    order = re.findall(r"^\d\. .*?NRC (0x[0-9A-F]{2})", sec, re.MULTILINE)
    assert order[:6] == ["0x11", "0x7F", "0x13", "0x12", "0x7E", "0x13"]
    contract = (REPO_ROOT / "docs" / "behaviour_contract.md").read_text(encoding="utf-8")
    steps = re.findall(r"^### \d+b?\. .*?→ (0x[0-9A-F]{2})", contract, re.MULTILINE)
    assert steps[:6] == order[:6]


def test_chroma_oem_layer_has_own_collection(tmp_path):
    pytest.importorskip("chromadb")
    from uds_assistant.rag.chroma import ChromaRetriever

    class FakeEmbedder:
        name = "fake"

        def embed(self, texts):
            # Deterministic bag-of-letters vectors; no model needed.
            return [
                [float(t.lower().count(ch)) + 0.01 for ch in "abcdefghijklmnopqrstuvwxyz"]
                for t in texts
            ]

    corpus = build_corpus(REPO_ROOT)
    retriever = ChromaRetriever(corpus, persist_dir=tmp_path, embedder=FakeEmbedder())
    names = retriever.chroma_collections
    assert set(names) == {"core", "oem"} and names["core"] != names["oem"]
    assert retriever.embedded_count == len(corpus)
    oem_hits = retriever.search("lockout", k=3, collections=["oem"])
    assert oem_hits and all(h.chunk.layer == "oem" for h in oem_hits)
    core_hits = retriever.search("lockout", k=3, collections=["ecu", "standard"])
    assert core_hits and all(h.chunk.layer != "oem" for h in core_hits)
    assert {h.chunk.layer for h in retriever.search("lockout", k=len(corpus))} == set(LAYERS)
