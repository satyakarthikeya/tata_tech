"""Shared pytest configuration.

Auto-skips tests marked ``needs_model`` unless ``RUN_MODEL_TESTS=1`` is set in
the environment, so the model-dependent phases (Ollama, ChromaDB embeddings)
can be written and left untested on offline/low-resource machines.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``needs_model`` tests unless RUN_MODEL_TESTS=1 is set."""
    if os.environ.get("RUN_MODEL_TESTS") == "1":
        return
    skip_marker = pytest.mark.skip(reason="needs_model test; set RUN_MODEL_TESTS=1 to run")
    for item in items:
        if "needs_model" in item.keywords:
            item.add_marker(skip_marker)
