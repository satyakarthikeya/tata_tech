"""Builds the configured LLM backend, falling back to :class:`MockLLM` safely.

``LLM_MODE=mock`` (default) always works offline. ``LLM_MODE=ollama`` probes
``GET /api/tags`` with a short timeout; if the server is unreachable the
factory warns and returns :class:`MockLLM` (AGENT.md runtime switches).
"""

from __future__ import annotations

import warnings

import httpx

from uds_assistant.config import Config, get_config
from uds_assistant.llm.base import LLMClient
from uds_assistant.llm.client import OllamaClient, ollama_base_url, ollama_reachable
from uds_assistant.llm.mock import MockLLM


def get_llm(
    config: Config | None = None,
    *,
    probe_timeout_s: float = 2.0,
    transport: httpx.BaseTransport | None = None,
) -> LLMClient:
    """Return the LLM backend selected by ``config.llm_mode`` (default: mock)."""
    cfg = config or get_config()
    if cfg.llm_mode == "ollama":
        base_url = ollama_base_url()
        if ollama_reachable(base_url, timeout_s=probe_timeout_s, transport=transport):
            return OllamaClient(base_url=base_url, transport=transport)
        message = (
            f"LLM_MODE=ollama requested but Ollama is not reachable at {base_url}; "
            "falling back to the deterministic mock LLM."
        )
        warnings.warn(message, stacklevel=2)
        return MockLLM(fallback_events=[message])
    return MockLLM()
