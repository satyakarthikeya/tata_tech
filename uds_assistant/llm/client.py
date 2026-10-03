"""Ollama-backed :class:`~uds_assistant.llm.base.LLMClient` (``LLM_MODE=ollama``).

Talks to a local Ollama server over HTTP (``/api/chat``) with ``stream=false``,
temperature 0 for every call (parse, plan *and* explain: greedy decoding keeps
runs reproducible and the explain prose is short, so there is no reason to
sample), a bounded context window (``num_ctx`` 4096 by default so the KV cache
fits a 4 GB GPU; ``OLLAMA_NUM_CTX`` overrides) and a ``keep_alive`` so the
model stays loaded between pipeline nodes. Structured calls pass the pydantic model's JSON schema as
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

from uds_assistant.llm.base import LLMError, LLMStats, estimate_tokens
from uds_assistant.llm.prompts import SCHEMA_RETRY_INSTRUCTION

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "qwen2.5:3b-instruct-q4_K_M"
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_NUM_CTX = 4096
DEFAULT_KEEP_ALIVE = "10m"
DEFAULT_TEMPERATURE = 0
DEFAULT_SEED = 0
TRUNCATION_MARGIN_TOKENS = 16


def ollama_base_url() -> str:
    """Base URL from ``OLLAMA_HOST`` (default ``http://localhost:11434``)."""
    raw = os.environ.get("OLLAMA_HOST", "").strip() or DEFAULT_BASE_URL
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    return raw.rstrip("/")


def ollama_model() -> str:
    """Model tag from ``OLLAMA_MODEL`` (default ``qwen2.5:3b-instruct-q4_K_M``)."""
    return os.environ.get("OLLAMA_MODEL", "").strip() or DEFAULT_MODEL


def ollama_num_ctx() -> int:
    """Context window from ``OLLAMA_NUM_CTX`` (default 4096; invalid values ignored)."""
    raw = os.environ.get("OLLAMA_NUM_CTX", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_NUM_CTX
    return value if value > 0 else DEFAULT_NUM_CTX


def ollama_keep_alive() -> str:
    """Model keep-alive from ``OLLAMA_KEEP_ALIVE`` (default ``10m``)."""
    return os.environ.get("OLLAMA_KEEP_ALIVE", "").strip() or DEFAULT_KEEP_ALIVE


class OllamaClient:
    """Minimal synchronous Ollama chat client with retries and schema validation."""

    name = "ollama"
    supports_json_schema = True
    """``complete_json`` accepts a custom ``json_schema`` (sent as Ollama's ``format``)."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        *,
        timeout_s: float = 120.0,
        max_retries: int = 2,
        backoff_s: float = 0.5,
        num_ctx: int | None = None,
        keep_alive: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model or ollama_model()
        self.base_url = (base_url or ollama_base_url()).rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max(0, max_retries)
        self.backoff_s = backoff_s
        self.num_ctx = num_ctx or ollama_num_ctx()
        self.keep_alive = keep_alive or ollama_keep_alive()
        self.temperature = temperature
        self.stats = LLMStats()
        self.fallback_events: list[str] = []
        self.truncation_events: list[str] = []
        """Verbatim "prompt likely truncated: ..." messages, one per affected request."""
        self._transport = transport
        self._sleep = sleep

    @property
    def context_tokens(self) -> int:
        """Context window (tokens) the agent must budget prompts against: ``num_ctx``."""
        return self.num_ctx

    # ------------------------------------------------------------------ truncation check

    def check_truncation(self, body: dict[str, Any], payload: dict[str, Any]) -> str | None:
        """Record and return a truncation message if this request's prompt was likely cut.

        Ollama silently shortens a prompt longer than ``num_ctx``: it keeps the first few
        tokens and the tail, and the evaluated prompt is then about ``num_ctx / 2`` tokens
        (measured on Ollama 0.35: ``prompt_eval_count`` 2050 for any over-long prompt at
        ``num_ctx`` 4096). Flagged when ``prompt_eval_count`` reaches ``num_ctx`` (minus a
        small margin), when it sits at that ``num_ctx / 2`` cut point while the estimated
        prompt is much larger, or when the estimated prompt alone exceeds ``num_ctx``.
        """
        texts = [str(m.get("content", "")) for m in body.get("messages", [])]
        est = estimate_tokens(*texts)
        raw = payload.get("prompt_eval_count")
        pec = raw if isinstance(raw, int) else None
        n = self.num_ctx
        at_limit = pec is not None and pec >= n - TRUNCATION_MARGIN_TOKENS
        at_cut = (
            pec is not None
            and abs(pec - n // 2) <= TRUNCATION_MARGIN_TOKENS
            and est > 0.75 * n
        )
        too_big = est > n
        if not (at_limit or at_cut or too_big):
            return None
        message = (
            f"prompt likely truncated: prompt_eval_count={pec if pec is not None else 'n/a'} "
            f"num_ctx={n} estimated_prompt_tokens={est}"
        )
        self.stats.truncations += 1
        self.truncation_events.append(message)
        return message

    # ------------------------------------------------------------------ request building

    def build_chat_body(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel] | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the ``/api/chat`` JSON body (exposed for tests)."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
                "seed": DEFAULT_SEED,
            },
        }
        if json_schema is not None:
            body["format"] = json_schema
        elif schema is not None:
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
            if attempt > 0:
                self.stats.retries += 1
            self.stats.http_requests += 1
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
                self.check_truncation(body, payload)
                return content
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self._sleep(self.backoff_s * (2**attempt))
        raise LLMError(
            f"Ollama unreachable after {self.max_retries + 1} attempt(s): {last_error}"
        ) from last_error

    # ------------------------------------------------------------------------ public API

    def complete_json(
        self, system: str, prompt: str, schema: type[T], json_schema: dict[str, Any] | None = None
    ) -> T:
        """Ask for JSON matching ``schema``; re-prompt with the error if invalid.

        ``json_schema`` (optional) is sent as the ``format`` instead of ``schema``'s own JSON
        schema, e.g. a per-call schema with enums; the reply is still validated with ``schema``.
        """
        self.stats.calls += 1
        start = time.perf_counter()
        try:
            return self._complete_json(system, prompt, schema, json_schema)
        except LLMError:
            self.stats.errors += 1
            raise
        finally:
            self.stats.latency_ms += (time.perf_counter() - start) * 1000

    def _complete_json(
        self, system: str, prompt: str, schema: type[T], json_schema: dict[str, Any] | None = None
    ) -> T:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        last_error = ""
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                self.stats.retries += 1
            content = self._post_chat(self.build_chat_body(messages, schema, json_schema))
            try:
                return schema.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValidationError) as exc:
                self.stats.json_failures += 1
                last_error = str(exc)
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": SCHEMA_RETRY_INSTRUCTION.format(error=last_error),
                    },
                ]
        raise LLMError(
            f"Ollama did not return valid {schema.__name__} JSON after "
            f"{self.max_retries + 1} attempt(s): {last_error}"
        )

    def complete_text(self, system: str, prompt: str) -> str:
        """Ask for free text."""
        self.stats.calls += 1
        start = time.perf_counter()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        try:
            return self._post_chat(self.build_chat_body(messages)).strip()
        except LLMError:
            self.stats.errors += 1
            raise
        finally:
            self.stats.latency_ms += (time.perf_counter() - start) * 1000


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
