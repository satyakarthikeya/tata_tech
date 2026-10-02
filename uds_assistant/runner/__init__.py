"""Test runner: execute test suites on the simulator, timing, and bug-detection matrix.

Public API: :func:`run_suite`, :func:`run_test`, :func:`run_bug_matrix` and the
result models :class:`SuiteResult`, :class:`TestRunResult`, :class:`BugMatrix`.
"""

from __future__ import annotations

from uds_assistant.runner.suite import (
    BugDetection,
    BugMatrix,
    InvalidTest,
    StepTiming,
    SuiteResult,
    TestRunResult,
    run_bug_matrix,
    run_suite,
    run_test,
)

__all__ = [
    "BugDetection",
    "BugMatrix",
    "InvalidTest",
    "StepTiming",
    "SuiteResult",
    "TestRunResult",
    "run_bug_matrix",
    "run_suite",
    "run_test",
]
