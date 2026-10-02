"""Pluggable LLM layer: deterministic mock and local Ollama backends.

The LLM only produces structured choices (identifiers, intents, template ids,
option indices) and prose — never bytes. See :mod:`.base`.
"""

from __future__ import annotations

from uds_assistant.llm.base import (
    LLMClient,
    LLMError,
    ParsedRequirement,
    PlannedTest,
    TestPlan,
    build_prompt,
    extract_context,
)
from uds_assistant.llm.client import OllamaClient, ollama_reachable
from uds_assistant.llm.factory import get_llm
from uds_assistant.llm.mock import MockLLM

__all__ = [
    "LLMClient",
    "LLMError",
    "MockLLM",
    "OllamaClient",
    "ParsedRequirement",
    "PlannedTest",
    "TestPlan",
    "build_prompt",
    "extract_context",
    "get_llm",
    "ollama_reachable",
]
