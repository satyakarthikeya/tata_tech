"""Placeholder confidence rule for Q&A answers (to be replaced by a shared module).

All of the computation lives in :func:`qa_confidence` so it can be swapped out later.
"""

from __future__ import annotations

from uds_assistant.qa.models import Confidence

GOOD_COVERAGE = 0.8
"""Retrieval-only answers need the best sentence to cover at least this share of the question's
content words to count as a "good score"."""

_ORDER: tuple[Confidence, ...] = ("low", "medium", "high")


def qa_confidence(
    *, status: str, deterministic: bool, coverage: float = 0.0, fallback_used: bool = False
) -> tuple[Confidence, str]:
    """Return ``(confidence, reason)``.

    - ``not_found`` -> low (nothing in the approved sources supports an answer).
    - deterministic spec/NRC lookup -> high.
    - retrieval-only with ``coverage >= GOOD_COVERAGE`` -> medium, otherwise low.
    - an LLM phrasing that was discarded for the template answer lowers the level by one.
    """
    if status != "answered":
        return "low", "no approved source supports an answer"
    if deterministic:
        level: Confidence = "high"
        reason = "facts looked up deterministically in the parsed ECU spec / NRC table"
    elif coverage >= GOOD_COVERAGE:
        level, reason = "medium", f"retrieval only; best sentence covers {coverage:.0%} of the question terms"
    else:
        level, reason = "low", f"retrieval only; weak match (best sentence covers {coverage:.0%} of the question terms)"
    if fallback_used:
        level = _ORDER[max(0, _ORDER.index(level) - 1)]
        reason += "; LLM phrasing was rejected and the template answer used"
    return level, reason
