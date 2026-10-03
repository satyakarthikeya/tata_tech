"""Shared pytest configuration.

Auto-skips tests marked ``needs_model`` unless ``RUN_MODEL_TESTS=1`` is set in
the environment, so the model-dependent phases (Ollama, ChromaDB embeddings)
can be written and left untested on offline/low-resource machines.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, settings

# The ``too_slow`` health check measures data-generation speed, not correctness. It
# fails spuriously when the machine is busy (full suite, model server running).
# Every assertion and example count is unchanged.
settings.register_profile("uds", suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("uds")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``needs_model`` tests unless RUN_MODEL_TESTS=1 is set."""
    if os.environ.get("RUN_MODEL_TESTS") == "1":
        return
    skip_marker = pytest.mark.skip(reason="needs_model test; set RUN_MODEL_TESTS=1 to run")
    for item in items:
        if "needs_model" in item.keywords:
            item.add_marker(skip_marker)
