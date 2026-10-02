"""Ollama-backed :class:`~uds_assistant.llm.base.LLMClient` (``LLM_MODE=ollama``).

Talks to a local Ollama server over HTTP (``/api/chat``) with ``stream=false``
and temperature 0. Structured calls pass the pydantic model's JSON schema as
Ollama's ``format`` so the model is constrained to that shape; the reply is
still validated with pydantic, and an invalid reply is re-prompted with the
validation error. Transport errors (connection refused, timeouts) and 5xx
responses are retried with bounded exponential backoff.

No model is downloaded or contacted by the test suite: tests drive this class
through ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from uds_assistant.llm.base import LLMError

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "qwen2.5:3b-instruct-q4_K_M"
DEFAULT_BASE_URL = "http://localhost:11434"


def ollama_base_url() -> str:
    """Base URL from ``OLLAMA_HOST`` (default ``http://localhost:11434``)."""
    raw = os.environ.get("OLLAMA_HOST", "").strip() or DEFAULT_BASE_URL
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    return raw.rstrip("/")


def ollama_model() -> str:
    """Model tag from ``OLLAMA_MODEL`` (default ``qwen2.5:3b-instruct-q4_K_M``)."""
    return os.environ.get("OLLAMA_MODEL", "").strip() or DEFAULT_MODEL


class OllamaClient:
    """Minimal synchronous Ollama chat client with retries and schema validation."""

    name = "ollama"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        *,
        timeout_s: float = 120.0,
        max_retries: int = 2,
        backoff_s: float = 0.5,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model or ollama_model()
        self.base_url = (base_url or ollama_base_url()).rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max(0, max_retries)
        self.backoff_s = backoff_s
        self._transport = transport
        self._sleep = sleep

    # ------------------------------------------------------------------ request building

    def build_chat_body(
        self, messages: list[dict[str, str]], schema: type[BaseModel] | None = None
    ) -> dict[str, Any]:
        """Build the ``/api/chat`` JSON body (exposed for tests)."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0},
        }
        if schema is not None:
            body["format"] = schema.model_json_schema()
        return body

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url, timeout=self.timeout_s, transport=self._transport
        )

    def _post_chat(self, body: dict[str, Any]) -> str:
        """POST once (with transport-level retries) and return the message content."""
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with self._client() as client:
                    resp = client.post("/api/chat", json=body)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"server error {resp.status_code}", request=resp.request, response=resp
                    )
                if resp.status_code >= 400:
                    raise LLMError(f"Ollama rejected the request ({resp.status_code}): {resp.text}")
                payload = resp.json()
                content = (payload.get("message") or {}).get("content")
                if not isinstance(content, str):
                    raise LLMError(f"Ollama response has no message content: {payload!r}")
                return content
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self._sleep(self.backoff_s * (2**attempt))
        raise LLMError(
            f"Ollama unreachable after {self.max_retries + 1} attempt(s): {last_error}"
        ) from last_error

    # ------------------------------------------------------------------------ public API

    def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        """Ask for JSON matching ``schema``; re-prompt with the error if invalid."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        last_error = ""
        for _ in range(self.max_retries + 1):
            content = self._post_chat(self.build_chat_body(messages, schema))
            try:
                return schema.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = str(exc)
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply was not valid JSON for the required schema. "
                            f"Error: {last_error}\nReply again with only a JSON object that "
                            "matches the schema."
                        ),
                    },
                ]
        raise LLMError(
            f"Ollama did not return valid {schema.__name__} JSON after "
            f"{self.max_retries + 1} attempt(s): {last_error}"
        )

    def complete_text(self, system: str, prompt: str) -> str:
        """Ask for free text."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        return self._post_chat(self.build_chat_body(messages)).strip()


def ollama_reachable(
    base_url: str | None = None,
    *,
    timeout_s: float = 2.0,
    transport: httpx.BaseTransport | None = None,
) -> bool:
    """Probe ``GET /api/tags`` with a short timeout; True if the server answers 200."""
    url = (base_url or ollama_base_url()).rstrip("/")
    try:
        with httpx.Client(base_url=url, timeout=timeout_s, transport=transport) as client:
            return client.get("/api/tags").status_code == 200
    except httpx.HTTPError:
        return False
