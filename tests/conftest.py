"""Shared fixtures. Nothing here needs Ollama, the embedding model or the network."""

from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.spec.schema import load_spec
from uds_assistant.store.audit import AuditStore

ROOT = Path(__file__).resolve().parents[1]
IMPORTS = ROOT / "data" / "imports"


@pytest.fixture(scope="session")
def spec():
    return load_spec(ROOT / "data" / "bcm_spec.yaml")


@pytest.fixture
def store():
    with AuditStore(":memory:") as s:
        yield s


@pytest.fixture
def regression_text() -> str:
    return (IMPORTS / "legacy_bcm_regression.yaml").read_text(encoding="utf-8")


@pytest.fixture
def errors_text() -> str:
    return (IMPORTS / "legacy_bcm_with_errors.yaml").read_text(encoding="utf-8")
