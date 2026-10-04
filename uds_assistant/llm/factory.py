"""Builds the Ollama LLM client; Ollama is required (no offline stand-in)."""

from __future__ import annotations

import httpx

from uds_assistant.llm.base import LLMError
from uds_assistant.llm.client import OllamaClient, ollama_base_url, ollama_model, ollama_reachable

START_OLLAMA_HINT = f"Start Ollama and pull {ollama_model()}"


class OllamaUnavailableError(LLMError):
    """Ollama is not reachable; the API maps this to HTTP 503."""


def get_llm(
    *, probe_timeout_s: float = 2.0, transport: httpx.BaseTransport | None = None
) -> OllamaClient:
    """Return an :class:`OllamaClient`, or raise :class:`OllamaUnavailableError` if it is down."""
    base_url = ollama_base_url()
    if not ollama_reachable(base_url, timeout_s=probe_timeout_s, transport=transport):
        raise OllamaUnavailableError(f"Ollama is not reachable at {base_url}. {START_OLLAMA_HINT}")
    return OllamaClient(base_url=base_url, transport=transport)
