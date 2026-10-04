"""Pydantic models for the Q&A endpoint and its internal facts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

QAStatus = Literal["answered", "not_found"]
Confidence = Literal["high", "medium", "low"]


class QACitation(BaseModel):
    """One piece of evidence: a chunk id and an exact quote that is a substring of its text."""

    chunk_id: str
    layer: str
    source: str
    quote: str


class AskRequest(BaseModel):
    """Body of ``POST /ask``."""

    question: str = Field(min_length=1)
    mode: Literal["mock", "ollama"] | None = None
    """Optional per-request LLM mode (same values as ``/eval``); default: the server's mode."""


class AskResponse(BaseModel):
    """Result of a Q&A call."""

    answer: str
    citations: list[QACitation] = Field(default_factory=list)
    confidence: Confidence
    confidence_reason: str
    status: QAStatus
    fallback_events: list[str] = Field(default_factory=list)
    """Why the LLM phrasing was discarded for the template answer (empty if it was not)."""
    llm_mode: str = "mock"
    """``mock`` (template answer) or the LLM backend name that phrased the answer."""


class Fact(BaseModel):
    """One looked-up (deterministic) fact: its sentence, values that must survive phrasing, source."""

    key: str
    text: str
    must_include: list[str] = Field(default_factory=list)
    chunk_id: str
    quote: str
