from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.spec.schema import EcuSpec, load_spec
from uds_assistant.testgen.model import TestCase, load_tests

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = REPO_ROOT / "data" / "gold" / "gold_tests.yaml"


@pytest.fixture(scope="session")
def spec() -> EcuSpec:
    return load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")


@pytest.fixture(scope="session")
def gold_tests() -> list[TestCase]:
    return load_tests(GOLD_PATH)
