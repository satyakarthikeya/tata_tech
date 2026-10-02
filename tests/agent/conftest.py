from __future__ import annotations

import csv
from pathlib import Path

import pytest

from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.rag.model import Chunk
from uds_assistant.spec.schema import EcuSpec, load_spec

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_seed_requirements() -> list[dict[str, str]]:
    with (REPO_ROOT / "data" / "requirements_seed.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


SEED_REQUIREMENTS = load_seed_requirements()


@pytest.fixture(scope="session")
def spec() -> EcuSpec:
    return load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")


@pytest.fixture(scope="session")
def corpus() -> list[Chunk]:
    return build_corpus(REPO_ROOT)


@pytest.fixture(scope="session")
def retriever(corpus: list[Chunk]) -> Bm25Retriever:
    return Bm25Retriever(corpus)
