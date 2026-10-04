from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.qa.lookup import FactLookup
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.spec.schema import load_spec

ROOT = Path(__file__).resolve().parents[2]


class FakeLLM:
    """Scripted LLM: returns the next prepared payload, validated through the requested schema."""

    name = "fake-ollama"
    supports_json_schema = True

    def __init__(self, *payloads: dict):
        self.payloads = list(payloads)
        self.prompts: list[str] = []

    def complete_json(self, system, prompt, schema, json_schema=None):
        self.prompts.append(prompt)
        return schema.model_validate(self.payloads.pop(0))

    def complete_text(self, system, prompt):
        return ""


@pytest.fixture(scope="session")
def env():
    chunks = build_corpus(ROOT)
    spec = load_spec(ROOT / "data" / "bcm_spec.yaml")
    return {
        "chunks": chunks,
        "spec": spec,
        "retriever": get_retriever(chunks=chunks),
        "lookup": FactLookup(spec, chunks),
    }


@pytest.fixture
def ask(env):
    from uds_assistant.qa import answer_question

    def _ask(question, llm=None):
        return answer_question(
            question, spec=env["spec"], chunks=env["chunks"], retriever=env["retriever"],
            llm=llm, lookup=env["lookup"],
        )

    return _ask
