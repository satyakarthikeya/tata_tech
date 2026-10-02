"""Fixtures for rules-engine tests."""

from __future__ import annotations

import pytest

from tests.rules.helpers import bcm_spec
from uds_assistant.spec.schema import EcuSpec


@pytest.fixture(scope="session")
def spec() -> EcuSpec:
    """The synthetic BCM spec."""
    return bcm_spec()
