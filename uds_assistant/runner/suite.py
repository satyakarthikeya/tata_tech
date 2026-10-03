"""Run a list of :class:`TestCase` on the simulator: pass/fail, timing, bug matrix.

Built on :func:`uds_assistant.testgen.execute.run_test_on_simulator` (fresh ECU
per test, injected clock). On top of that, every ``SimulatedEcu.handle`` call is
wrapped with a wall-clock timer so each send step gets a measured handling time:

- If a step sets ``max_response_time_ms``, exceeding it **fails** the step/test.
- Otherwise the active session's P2 (or P2* when the ECU answered with
  ``7F xx 78`` response-pending first) is checked and an overrun is only
  recorded as a ``timing_warning`` (in-process wall-clock time on a desktop OS
  can be inflated by scheduling/GC and is not a property of the ECU logic).

:func:`run_bug_matrix` enables each bug alone and records which tests fail. A
bug counts as *detected* only through tests that pass on the clean simulator;
tests failing on the clean simulator are reported as *invalid* and get no
detection credit.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, Field

from uds_assistant.simulator import BugCatalog, SimulatedEcu, load_bug_catalog
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.execute import TestOutcome, run_test_on_simulator
from uds_assistant.testgen.model import TestCase

LimitSource = Literal["max_response_time_ms", "p2", "p2_star"]


class StepTiming(BaseModel):
    """Wall-clock handling time of one send step and the deadline it was checked against."""

    step_index: int
    elapsed_ms: float
    limit_ms: int
    limit_source: LimitSource
    within_limit: bool
    enforced: bool
    """True when the limit comes from the step's ``max_response_time_ms`` (failure on overrun)."""


class TestRunResult(BaseModel):
    """Outcome of one test on one ECU configuration."""

    __test__ = False  # not a pytest test class despite the name

    test_id: str
    bug_id: str | None = None
    """The injected bug (None = clean simulator). Multiple bugs are joined with ``+``."""
    passed: bool
    functional_passed: bool
    timing_passed: bool
    timing_warnings: list[str] = Field(default_factory=list)
    step_timings: list[StepTiming] = Field(default_factory=list)
    duration_ms: float
    outcome: TestOutcome

    @property
    def failure_detail(self) -> str:
        """Short description of the first failing step, or ``""``."""
        first = self.outcome.first_failure
        if first is not None:
            return f"step {first.index}: {first.detail}"
        for t in self.step_timings:
            if t.enforced and not t.within_limit:
                return f"step {t.step_index}: {t.elapsed_ms:.3f} ms > {t.limit_ms} ms"
        return ""


class SuiteResult(BaseModel):
    """Results of a whole suite on one ECU configuration."""

    bugs: list[str] = Field(default_factory=list)
    results: list[TestRunResult] = Field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def total(self) -> int:
        """Number of tests run."""
        return len(self.results)

    @property
    def passed_count(self) -> int:
        """Number of passing tests."""
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_ids(self) -> list[str]:
        """Ids of failing tests, in run order."""
        return [r.test_id for r in self.results if not r.passed]

    @property
    def passed_ids(self) -> list[str]:
        """Ids of passing tests, in run order."""
        return [r.test_id for r in self.results if r.passed]

    @property
    def pass_rate(self) -> float:
        """Fraction of passing tests (1.0 for an empty suite)."""
        return self.passed_count / self.total if self.total else 1.0

    @property
    def timing_warning_count(self) -> int:
        """Total number of non-enforced P2/P2* overruns."""
        return sum(len(r.timing_warnings) for r in self.results)


class _TimedEcu:
    """Proxy around :class:`SimulatedEcu` recording wall-clock time per ``handle``."""

    def __init__(self, ecu: SimulatedEcu, spec: EcuSpec) -> None:
        self._ecu = ecu
        self._spec = spec
        self.calls: list[tuple[float, int, int, list[bytes]]] = []
        """(elapsed_ms, p2_ms, p2_star_ms, responses) per handle call."""

    def handle(self, request: bytes, now_ms: int | None = None) -> list[bytes]:
        session = self._spec.get_session(self._ecu.session)
        p2, p2_star = (
            (session.timing.p2_ms, session.timing.p2_star_ms) if session is not None else (50, 5000)
        )
        start = time.perf_counter()
        responses = self._ecu.handle(request, now_ms)
        elapsed = (time.perf_counter() - start) * 1000.0
        self.calls.append((elapsed, p2, p2_star, list(responses)))
        return responses

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ecu, name)


def _is_pending(frame: bytes) -> bool:
    return len(frame) == 3 and frame[0] == 0x7F and frame[2] == 0x78


def run_test(test: TestCase, spec: EcuSpec, bugs: Iterable[str] | None = None) -> TestRunResult:
    """Run one test on a fresh simulator (optionally with ``bugs`` enabled)."""
    bug_list = sorted(set(bugs or ()))
    holder: list[_TimedEcu] = []

    def factory() -> SimulatedEcu:
        proxy = _TimedEcu(SimulatedEcu(spec, bugs=bug_list), spec)
        holder.append(proxy)
        return proxy  # type: ignore[return-value]  # duck-typed proxy

    start = time.perf_counter()
    outcome = run_test_on_simulator(test, factory)
    duration = (time.perf_counter() - start) * 1000.0
    calls = holder[0].calls if holder else []

    send_indices = [i for i, s in enumerate(test.steps) if s.kind == "send"]
    timings: list[StepTiming] = []
    warnings: list[str] = []
    for step_index, (elapsed, p2, p2_star, responses) in zip(send_indices, calls, strict=False):
        step = test.steps[step_index]
        explicit = getattr(step, "max_response_time_ms", None)
        if explicit is not None:
            limit, source, enforced = int(explicit), "max_response_time_ms", True
        elif responses and _is_pending(responses[0]):
            limit, source, enforced = p2_star, "p2_star", False
        else:
            limit, source, enforced = p2, "p2", False
        within = elapsed <= limit
        timings.append(
            StepTiming(
                step_index=step_index,
                elapsed_ms=round(elapsed, 4),
                limit_ms=limit,
                limit_source=source,  # type: ignore[arg-type]
                within_limit=within,
                enforced=enforced,
            )
        )
        if not within and not enforced:
            warnings.append(f"step {step_index}: {elapsed:.3f} ms > {source} {limit} ms")

    timing_passed = all(t.within_limit for t in timings if t.enforced)
    return TestRunResult(
        test_id=test.id,
        bug_id="+".join(bug_list) or None,
        passed=outcome.passed and timing_passed,
        functional_passed=outcome.passed,
        timing_passed=timing_passed,
        timing_warnings=warnings,
        step_timings=timings,
        duration_ms=round(duration, 4),
        outcome=outcome,
    )


def run_suite(
    tests: list[TestCase],
    spec: EcuSpec,
    bugs: set[str] | None = None,
    store: AuditStore | None = None,
    run_id: int | None = None,
) -> SuiteResult:
    """Run every test on a fresh simulator with ``bugs`` enabled (None/empty = clean).

    When ``store`` and ``run_id`` are given, each result is recorded in the audit
    trail's ``results`` table with ``bug_id`` set (NULL for the clean ECU).
    """
    bug_set = set(bugs or ())
    start = time.perf_counter()
    results = [run_test(t, spec, bug_set) for t in tests]
    duration = (time.perf_counter() - start) * 1000.0
    if store is not None and run_id is not None:
        for r in results:
            store.record_result(
                run_id,
                r.test_id,
                r.passed,
                {
                    "functional_passed": r.functional_passed,
                    "timing_passed": r.timing_passed,
                    "failure": r.failure_detail,
                    "timing_warnings": r.timing_warnings,
                    "duration_ms": r.duration_ms,
                },
                bug_id=r.bug_id,
            )
    return SuiteResult(bugs=sorted(bug_set), results=results, duration_ms=round(duration, 3))


# ------------------------------------------------------------------------------ bug matrix


class InvalidTest(BaseModel):
    """A test that fails on the clean simulator (no detection credit)."""

    test_id: str
    failure: str


class BugDetection(BaseModel):
    """Detection status of one injected bug."""

    bug_id: str
    title: str = ""
    category: str = ""
    detected: bool
    detecting_tests: list[str] = Field(default_factory=list)
    """Valid tests (pass on clean ECU) that fail with this bug enabled."""
    failing_invalid_tests: list[str] = Field(default_factory=list)
    """Invalid tests failing with the bug too (not credited)."""


class BugMatrix(BaseModel):
    """Which tests fail for each bug enabled alone."""

    bug_ids: list[str]
    test_ids: list[str]
    valid_test_ids: list[str]
    invalid_tests: list[InvalidTest] = Field(default_factory=list)
    per_bug: list[BugDetection] = Field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def detected_bug_ids(self) -> list[str]:
        """Bugs caught by at least one valid test."""
        return [b.bug_id for b in self.per_bug if b.detected]

    @property
    def undetected_bug_ids(self) -> list[str]:
        """Bugs no valid test caught."""
        return [b.bug_id for b in self.per_bug if not b.detected]

    @property
    def detection_rate(self) -> float:
        """Detected bugs / bugs evaluated (0.0 when no bugs)."""
        return len(self.detected_bug_ids) / len(self.bug_ids) if self.bug_ids else 0.0

    def get(self, bug_id: str) -> BugDetection | None:
        """Detection record for ``bug_id``."""
        return next((b for b in self.per_bug if b.bug_id == bug_id), None)


def run_bug_matrix(
    tests: list[TestCase],
    spec: EcuSpec,
    bug_ids: Iterable[str] | None = None,
    store: AuditStore | None = None,
    run_id: int | None = None,
    catalog: BugCatalog | None = None,
) -> BugMatrix:
    """Enable each bug alone and record which tests fail.

    ``catalog`` (default: the original catalog) supplies titles/categories, e.g.
    the held-out catalog. ``bug_ids`` defaults to every bug in that catalog
    (catalog order). A bug is
    detected if at least one test that passes on the clean simulator fails with
    the bug enabled. Tests failing on the clean simulator are listed as invalid.
    """
    catalog = catalog if catalog is not None else load_bug_catalog()
    ids = list(bug_ids) if bug_ids is not None else catalog.ids
    start = time.perf_counter()
    clean = run_suite(tests, spec, None, store, run_id)
    valid = [r.test_id for r in clean.results if r.passed]
    valid_set = set(valid)
    invalid = [
        InvalidTest(test_id=r.test_id, failure=r.failure_detail)
        for r in clean.results
        if not r.passed
    ]
    per_bug: list[BugDetection] = []
    for bug_id in ids:
        suite = run_suite(tests, spec, {bug_id}, store, run_id)
        failing = suite.failed_ids
        detecting = [t for t in failing if t in valid_set]
        bug_def = catalog.get(bug_id)
        per_bug.append(
            BugDetection(
                bug_id=bug_id,
                title=bug_def.title if bug_def else "",
                category=bug_def.category if bug_def else "",
                detected=bool(detecting),
                detecting_tests=detecting,
                failing_invalid_tests=[t for t in failing if t not in valid_set],
            )
        )
    return BugMatrix(
        bug_ids=ids,
        test_ids=[t.id for t in tests],
        valid_test_ids=valid,
        invalid_tests=invalid,
        per_bug=per_bug,
        duration_ms=round((time.perf_counter() - start) * 1000.0, 3),
    )
