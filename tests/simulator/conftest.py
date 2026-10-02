"""Fixtures for simulator tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.spec.schema import EcuSpec, load_spec

SPEC_PATH = Path(__file__).resolve().parents[2] / "data" / "bcm_spec.yaml"


def bcm() -> EcuSpec:
    """Load the synthetic BCM spec."""
    return load_spec(SPEC_PATH)


@pytest.fixture(scope="session")
def spec() -> EcuSpec:
    """The synthetic BCM spec."""
    return bcm()
