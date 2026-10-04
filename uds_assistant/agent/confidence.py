"""Shared confidence rule: ``high | medium | low`` plus a one-line reason.

Used for every Q&A answer (:func:`answer_confidence`) and every generated test
(:func:`generated_test_confidence`). Pure functions, no I/O, no model calls; the same inputs always
give the same output. It lives in ``agent/`` next to the grounding logic whose written-vs-
inferred test it reuses; ``qa.confidence.qa_confidence`` is a thin wrapper.

Rule: start at a base level, subtract one level per *signal that fires* (a signal costs at
most one level however often it fires), floor at ``low``. The reason names every signal that
fired, decisive (first) one first; with no signal it says why the level is the base.

Generated tests (base ``high``):

==========================  =========================================================  ====
Signal                      Fires when                                                 Cost
==========================  =========================================================  ====
inferred target             a service/DID/routine id the test exercises is neither      -1
                            written in the requirement text (hex id) nor named by a
                            spec name/lexical pattern (see ``grounding.target_is_written``)
weak retrieval              the best cited hit scores < :data:`WEAK_SCORE` (or no       -1
                            citation matches a retrieved hit)
rejections / retries        the requirement had >= 1 planner/instantiate/validator      -1
                            rejection or planner retry
grounding drops             parse grounding dropped >= 1 ungrounded item                -1
fallback events             an LLM-fallback event applies (explain fallback for this    -1
                            test, or a requirement-wide parse/plan failure)
==========================  =========================================================  ====

Q&A answers: ``not_found`` -> ``low``; deterministic spec/NRC lookup -> ``high``;
retrieval-only -> ``medium`` if the best sentence covers >= :data:`GOOD_COVERAGE` of the
question terms, else ``low`` (never ``high``); a discarded LLM phrasing (fallback) costs one
level.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

Confidence = Literal["high", "medium", "low"]

ORDER: tuple[Confidence, ...] = ("low", "medium", "high")

WEAK_SCORE = 0.5
"""Cosine similarity (Chroma + BGE) below which the best cited hit counts as weak support."""

GOOD_COVERAGE = 0.8
"""Retrieval-only Q&A answers need the best sentence to cover this share of the question terms."""


def _lower(level: Confidence, steps: int) -> Confidence:
    return ORDER[max(0, ORDER.index(level) - steps)]


def _join(reasons: list[str]) -> str:
    return "; ".join(reasons)


def generated_test_confidence(
    *,
    inferred: Sequence[str] = (),
    top_score: float | None = None,
    rejections: int = 0,
    retries: int = 0,
    grounding_drops: int = 0,
    fallbacks: Sequence[str] = (),
) -> tuple[Confidence, str]:
    """Confidence of one generated test.

    ``inferred``: labels of the test's targets not written in the requirement (e.g.
    ``["0x27"]``). ``top_score``: best cited hit's score (None = no cited hit retrieved).
    ``rejections``/``retries``: planner/validator rejections and planner re-plans for the
    requirement. ``grounding_drops``: items dropped by parse grounding. ``fallbacks``: the
    fallback events that apply to this test.
    """
    reasons: list[str] = []
    if inferred:
        reasons.append(
            "inferred target " + ", ".join(inferred) + " (not in text)"
        )
    if top_score is None or top_score < WEAK_SCORE:
        shown = "no matching hit" if top_score is None else f"best cited hit {top_score:.2f}"
        reasons.append(f"weak retrieval ({shown} < {WEAK_SCORE:g})")
    if rejections or retries:
        parts = []
        if rejections:
            parts.append(f"{rejections} rejection{'s' if rejections != 1 else ''}")
        if retries:
            parts.append(f"{retries} planner retr{'ies' if retries != 1 else 'y'}")
        reasons.append(" and ".join(parts))
    if grounding_drops:
        reasons.append(f"{grounding_drops} grounding drop{'s' if grounding_drops != 1 else ''}")
    if fallbacks:
        reasons.append(
            f"{len(fallbacks)} fallback event{'s' if len(fallbacks) != 1 else ''}"
            f" ({fallbacks[0][:60]})"
        )
    if not reasons:
        return "high", "all targets written in the requirement; strong retrieval; no rejections, drops or fallbacks"
    return _lower("high", len(reasons)), _join(reasons)


def answer_confidence(
    *, status: str, deterministic: bool, coverage: float = 0.0, fallback_used: bool = False
) -> tuple[Confidence, str]:
    """Confidence of one Q&A answer (rules in the module docstring)."""
    if status != "answered":
        return "low", "no approved source supports an answer"
    if deterministic:
        level: Confidence = "high"
        reason = "facts looked up deterministically in the parsed ECU spec / NRC table"
    elif coverage >= GOOD_COVERAGE:
        level = "medium"
        reason = f"retrieval only; best sentence covers {coverage:.0%} of the question terms"
    else:
        level = "low"
        reason = f"retrieval only; weak match (best sentence covers {coverage:.0%} of the question terms)"
    if fallback_used:
        level = _lower(level, 1)
        reason += "; LLM phrasing was rejected and the template answer used"
    return level, reason
