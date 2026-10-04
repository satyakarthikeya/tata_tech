"""Q&A confidence: thin wrapper over the shared rule in :mod:`uds_assistant.agent.confidence`."""

from __future__ import annotations

from uds_assistant.agent.confidence import GOOD_COVERAGE, answer_confidence
from uds_assistant.qa.models import Confidence

__all__ = ["GOOD_COVERAGE", "qa_confidence"]


def qa_confidence(
    *, status: str, deterministic: bool, coverage: float = 0.0, fallback_used: bool = False
) -> tuple[Confidence, str]:
    """Return ``(confidence, reason)`` for a Q&A answer (see the shared module for the rules)."""
    return answer_confidence(
        status=status, deterministic=deterministic, coverage=coverage, fallback_used=fallback_used
    )
