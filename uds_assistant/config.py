"""Central runtime configuration read from environment variables.

Only two switches exist in Phase 1: ``LLM_MODE`` and ``RETRIEVER``. Both default
to the lightweight, fully-offline option. An invalid value falls back to the
default and emits a warning rather than raising, so a typo in the environment
never crashes the whole pipeline.
"""

from __future__ import annotations

import os
import warnings
from typing import Literal

from pydantic import BaseModel, Field

LlmMode = Literal["mock", "ollama"]
RetrieverBackend = Literal["bm25", "chroma"]

_VALID_LLM_MODES: tuple[LlmMode, ...] = ("mock", "ollama")
_VALID_RETRIEVERS: tuple[RetrieverBackend, ...] = ("bm25", "chroma")


class Config(BaseModel):
    """Validated runtime configuration for the whole assistant."""

    llm_mode: LlmMode = Field(default="mock")
    retriever: RetrieverBackend = Field(default="bm25")


def _read_enum_env(name: str, valid: tuple[str, ...], default: str) -> str:
    """Read an environment variable, falling back to ``default`` with a warning."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw not in valid:
        warnings.warn(
            f"Invalid value {raw!r} for {name} (expected one of {valid}); "
            f"falling back to default {default!r}.",
            stacklevel=2,
        )
        return default
    return raw


def get_config() -> Config:
    """Build the runtime :class:`Config` from environment variables.

    Reads ``LLM_MODE`` (default ``mock``) and ``RETRIEVER`` (default ``bm25``).
    An invalid value for either falls back to its default and warns; no
    further fallback logic (e.g. probing for Ollama reachability) happens here.
    """
    llm_mode = _read_enum_env("LLM_MODE", _VALID_LLM_MODES, "mock")
    retriever = _read_enum_env("RETRIEVER", _VALID_RETRIEVERS, "bm25")
    return Config(llm_mode=llm_mode, retriever=retriever)  # type: ignore[arg-type]
