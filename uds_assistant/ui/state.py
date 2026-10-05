"""Review-state helpers for the Generate & Review tab (audit DB through the existing store API).

The store keeps a review *status* per test (draft / validated / human_reviewed) and an append-only
decision log per run. Approve sets ``human_reviewed``; reject sets ``draft`` and logs the decision;
comments are decisions too (node ``review``), so everything is in the audit trail.
"""

from __future__ import annotations

from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.model import TestCase

REVIEW_NODE = "review"


def approve(store: AuditStore, run_id: int, test_id: str, comment: str = "") -> None:
    """Mark a test human_reviewed and log it."""
    store.set_review_status(run_id, test_id, "human_reviewed")
    store.record_decision(run_id, REVIEW_NODE, _msg(test_id, "approved", comment))


def reject(store: AuditStore, run_id: int, test_id: str, comment: str = "") -> None:
    """Send a test back to draft and log the rejection."""
    store.set_review_status(run_id, test_id, "draft")
    store.record_decision(run_id, REVIEW_NODE, _msg(test_id, "rejected", comment))


def bulk_approve_validated(
    store: AuditStore, run_id: int, tests: list[TestCase], comment: str = "bulk approve"
) -> list[str]:
    """Approve every ``validated`` test, one review-log entry each; returns the approved ids."""
    ids = [t.id for t in tests if t.review_status == "validated"]
    for test_id in ids:
        approve(store, run_id, test_id, comment)
    return ids


def add_comment(store: AuditStore, run_id: int, test_id: str, comment: str) -> None:
    """Log a free-text review comment for a test."""
    store.record_decision(run_id, REVIEW_NODE, _msg(test_id, "comment", comment))


def _msg(test_id: str, action: str, comment: str) -> str:
    return f"{test_id} | {action} | {comment.strip()}"


def review_log(store: AuditStore, run_id: int, test_id: str) -> list[tuple[str, str]]:
    """``[(action, comment)]`` for a test, oldest first."""
    out: list[tuple[str, str]] = []
    for d in store.get_decisions(run_id, REVIEW_NODE):
        tid, _, rest = d.message.partition(" | ")
        action, _, comment = rest.partition(" | ")
        if tid == test_id:
            out.append((action, comment))
    return out


def review_label(store: AuditStore, run_id: int | None, test: TestCase) -> str:
    """Status shown in the table: ``rejected`` when the last decision rejected it."""
    if run_id is None:
        return test.review_status
    verdicts = [a for a, _ in review_log(store, run_id, test.id) if a in ("approved", "rejected")]
    if test.review_status == "draft" and verdicts and verdicts[-1] == "rejected":
        return "rejected"
    return test.review_status


def approved_tests(tests: list[TestCase]) -> list[TestCase]:
    """Tests a human approved."""
    return [t for t in tests if t.review_status == "human_reviewed"]
