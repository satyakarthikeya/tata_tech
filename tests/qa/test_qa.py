"""Unit tests for the cited Q&A module (mock mode unless marked needs_model)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from uds_assistant.api.app import create_app
from uds_assistant.qa import NOT_FOUND_ANSWER
from uds_assistant.qa.text import resolve_quote, sentence_spans

from .conftest import ROOT, FakeLLM

# ----------------------------------------------------------------------------- lookups


@pytest.mark.parametrize(
    ("question", "needles", "chunk"),
    [
        ("Can the VIN be written in any diagnostic session?", ["17 bytes", "read-only"], "ecu:did:VIN"),
        ("What is DID 0x0100 write access?", ["extended session", "0x01", "writable"],
         "ecu:did:interior_lighting_brightness_pct"),
        ("what is F187?", ["10 bytes"], "ecu:did:manufacturer_part_number"),
        ("Which session and security level does routine 0x0203 require?", ["programming", "0x03"],
         "ecu:routine:nvm_factory_restore"),
        ("What is the P2* timeout?", ["P2* = 5000 ms"], "ecu:session:extended"),
        ("How many wrong keys are allowed for security level 0x01?", ["3 attempts", "10000 ms"],
         "ecu:security_level:extended_diag"),
        ("Which sessions allow SecurityAccess (0x27)?", ["programming", "extended", "not in the default"],
         "ecu:session:programming"),
    ],
)
def test_spec_lookups(ask, question, needles, chunk):
    r = ask(question)
    assert r.status == "answered" and r.confidence == "high"
    for n in needles:
        assert n.lower() in r.answer.lower()
    assert chunk in {c.chunk_id for c in r.citations}


def test_nrc_lookup_cites_standard_layer(ask):
    r = ask("What does NRC 0x33 mean?")
    assert "securityAccessDenied" in r.answer
    assert [c.chunk_id for c in r.citations] == ["standard:nrcs"]
    assert r.citations[0].layer == "standard"


def test_door_lock_name_alias(ask):
    r = ask("Is the driver door lock status DID writable?")
    assert "0x0110" in r.answer and "read-only" in r.answer


# ----------------------------------------------------------------------------- not_found


@pytest.mark.parametrize(
    "question",
    [
        "What is DID 0x1234?",
        "What does NRC 0x99 mean?",
        "What is the maximum block length of RequestDownload (0x34)?",
        "Which session does routine 0x0299 need?",
        "How many attempts does security level 0x05 allow?",
        "What is the DID for the tire pressure reading on this BCM?",
    ],
)
def test_not_found(ask, question):
    r = ask(question)
    assert r.status == "not_found"
    assert r.answer == NOT_FOUND_ANSWER
    assert r.citations == [] and r.confidence == "low"


# ----------------------------------------------------------------------------- citations


def test_every_citation_quote_is_substring(ask, env):
    by_id = {c.id: c for c in env["chunks"]}
    for q in ["What is the suppress-positive-response bit?", "What happens when the S3 timer expires?",
              "Which NRC is returned when WriteDataByIdentifier data has the wrong length?",
              "What is DID 0xF190?"]:
        r = ask(q)
        for c in r.citations:
            assert c.quote in by_id[c.chunk_id].text
            assert c.layer == by_id[c.chunk_id].layer


def test_conceptual_answer_quotes_retrieved_sentence(ask):
    r = ask("What is the suppress-positive-response bit?")
    assert r.status == "answered" and r.confidence in ("medium", "low")
    assert "no response at all" in r.answer


def test_resolve_quote_rejects_non_substring_and_accepts_rewrap():
    text = "The ECU falls back to the\n  default session when S3 expires."
    assert resolve_quote("falls back to the default session", text) == "falls back to the\n  default session"
    assert resolve_quote("falls back to the programming session", text) is None
    assert resolve_quote("short", text) is None


def test_sentence_spans_are_exact_slices():
    text = "First sentence is here.\n- A bullet item that is long enough.\n\nThird paragraph is also here."
    spans = sentence_spans(text)
    assert len(spans) == 3
    assert all(text[s:e] == text[s:e].strip() for s, e in spans)


# ----------------------------------------------------------------------------- fake LLM


def test_llm_phrasing_accepted_when_facts_survive(ask):
    llm = FakeLLM({"answer": "DID 0xF190 (VIN) is 17 bytes, readable in the default, programming, "
                             "extended sessions, and read-only."})
    r = ask("Can the VIN be written in any diagnostic session?", llm=llm)
    assert r.fallback_events == [] and r.llm_mode == "fake-ollama"
    assert r.answer.startswith("DID 0xF190")


def test_llm_dropping_a_fact_falls_back_to_template(ask):
    llm = FakeLLM({"answer": "The VIN cannot be written."})
    r = ask("Can the VIN be written in any diagnostic session?", llm=llm)
    assert r.fallback_events and "missing fact value" in r.fallback_events[0]
    assert "17 bytes" in r.answer and r.confidence == "medium"


def test_llm_introducing_a_value_is_rejected(ask):
    llm = FakeLLM({"answer": "DID 0xF190 (VIN) is 17 bytes, readable in the default, programming, "
                             "extended sessions, read-only, and needs security level 0x07."})
    r = ask("Can the VIN be written in any diagnostic session?", llm=llm)
    assert r.fallback_events and "introduced value '0x07'" in r.fallback_events[0]
    assert "0x07" not in r.answer


def test_llm_claim_with_fabricated_quote_is_dropped(ask):
    llm = FakeLLM({"claims": [{"text": "The bit is bit 3.", "chunk_id": "standard:svc-0x3e",
                               "quote": "bit 3 of the sub-function suppresses everything"}]})
    r = ask("What is the suppress-positive-response bit?", llm=llm)
    assert r.fallback_events and "quote not found" in r.fallback_events[0]
    assert "bit 7" in r.answer  # template (verbatim sentence) used instead


def test_llm_claim_with_valid_quote_is_kept(ask):
    r0 = ask("What is the suppress-positive-response bit?")
    c0 = r0.citations[0]
    quote = c0.quote[:60]
    llm = FakeLLM({"claims": [{"text": "For the services in this scope.", "chunk_id": c0.chunk_id, "quote": quote}]})
    r = ask("What is the suppress-positive-response bit?", llm=llm)
    assert r.fallback_events == []
    assert any(c.quote == quote for c in r.citations)


def test_llm_claim_not_supported_by_its_quote_is_dropped(ask):
    r0 = ask("What is the suppress-positive-response bit?")
    c0 = r0.citations[0]
    llm = FakeLLM({"claims": [{"text": "The bit is also known as the magic override flag.",
                               "chunk_id": c0.chunk_id, "quote": c0.quote[:60]}]})
    r = ask("What is the suppress-positive-response bit?", llm=llm)
    assert any("of its terms occur in its quote" in e for e in r.fallback_events)
    assert "magic" not in r.answer


def test_llm_not_called_for_not_found(ask):
    llm = FakeLLM()
    assert ask("What is DID 0x1234?", llm=llm).status == "not_found"
    assert llm.prompts == []


# ----------------------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(repo_root=ROOT, db_path=tmp_path / "a.sqlite"))


def test_ask_endpoint_answered(client):
    r = client.post("/ask", json={"question": "What is the length of DID 0xF190?"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "answered" and body["confidence"] == "high"
    assert body["citations"][0]["chunk_id"] == "ecu:did:VIN"
    assert set(body["citations"][0]) == {"chunk_id", "layer", "source", "quote"}
    assert "confidence_reason" in body


def test_ask_endpoint_not_found_and_validation(client):
    body = client.post("/ask", json={"question": "What is DID 0x9999?"}).json()
    assert body["status"] == "not_found" and body["answer"] == NOT_FOUND_ANSWER
    assert client.post("/ask", json={"question": ""}).status_code == 422


# ----------------------------------------------------------------------------- real model


@pytest.mark.needs_model
def test_ollama_answers_are_verified(env):
    from uds_assistant.config import Config
    from uds_assistant.llm.factory import get_llm
    from uds_assistant.qa import answer_question

    llm = get_llm(Config(llm_mode="ollama"))
    if llm.name == "mock":
        pytest.skip("Ollama not reachable")
    by_id = {c.id: c for c in env["chunks"]}
    for q, needle in [("Can the VIN be written in any diagnostic session?", "17"),
                      ("What is the suppress-positive-response bit?", "bit")]:
        r = answer_question(q, spec=env["spec"], chunks=env["chunks"], retriever=env["retriever"],
                            llm=llm, lookup=env["lookup"])
        assert r.status == "answered" and needle in r.answer
        assert all(c.quote in by_id[c.chunk_id].text for c in r.citations)
