"""Test-case schema, reusable templates, and a simple step executor.

Public entry points:

- :mod:`.model` — :class:`TestCase`, step types, :func:`load_tests`/:func:`dump_tests`.
- :mod:`.templates` — ``TEMPLATES`` registry, :func:`applicable_params`, :func:`validate_test`.
- :mod:`.execute` — :func:`run_test_on_simulator`.
"""

from __future__ import annotations

from uds_assistant.testgen.execute import StepOutcome, TestOutcome, run_test_on_simulator
from uds_assistant.testgen.model import (
    AdvanceTimeStep,
    Citation,
    SendStep,
    SetDtcStatusStep,
    SetEnvironmentStep,
    TestCase,
    TestStep,
    dump_tests,
    load_tests,
)
from uds_assistant.testgen.templates import (
    TEMPLATES,
    Template,
    ValidationReport,
    applicable_params,
    validate_test,
)

__all__ = [
    "TEMPLATES",
    "AdvanceTimeStep",
    "Citation",
    "SendStep",
    "SetDtcStatusStep",
    "SetEnvironmentStep",
    "StepOutcome",
    "Template",
    "TestCase",
    "TestOutcome",
    "TestStep",
    "ValidationReport",
    "applicable_params",
    "dump_tests",
    "load_tests",
    "run_test_on_simulator",
    "validate_test",
]
