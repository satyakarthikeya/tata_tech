"""The review gate: only human-approved tests are run or exported unless a caller opts out.

``select_for_run`` is used by the UI, the API (``/run``, ``/export``), the demo script and the
evaluation. The last two pass ``include_unreviewed=True`` explicitly: nobody reviews tests in
those flows, so the override must be visible at the call site.
"""

from __future__ import annotations

from uds_assistant.testgen.model import TestCase

APPROVED_STATUS = "human_reviewed"
NO_APPROVED_MESSAGE = (
    "No approved tests. Approve tests on the Generate & Review tab (or use "
    "'Bulk approve all validated tests') before running or exporting. "
    "Unreviewed tests can be included only through the demo-only override."
)


class NoApprovedTestsError(ValueError):
    """Raised when the approved-only scope selects nothing."""


def select_for_run(tests: list[TestCase], *, include_unreviewed: bool = False) -> list[TestCase]:
    """Approved tests (``human_reviewed``), or every test when ``include_unreviewed`` is set."""
    if include_unreviewed:
        return list(tests)
    approved = [t for t in tests if t.review_status == APPROVED_STATUS]
    if not approved:
        raise NoApprovedTestsError(NO_APPROVED_MESSAGE)
    return approved
