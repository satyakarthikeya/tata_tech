"""Byte provenance: every generated test must be exactly what its template produces.

The correctness rule of the project is that the LLM never produces bytes that reach a
final test. This module checks that rule after the fact: each generated test is
re-instantiated from ``TEMPLATES[test.template_id].instantiate(spec, params)`` (or, for the
requirement-independent conformance sweep, from its own registry, which the planner never
sees; :func:`uds_assistant.testgen.conformance.resolve_template`) where
``params`` are the test's *stored* parameters re-validated through the template's
``params_model``, and every step (request bytes, expected responses, time / environment /
DTC-status steps, including their descriptions and timing limits) must be identical.

A mismatch, an unregistered ``template_id``, parameters that do not validate, or
parameters that do not round-trip are all hard failures and are reported with details.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.conformance import resolve_template
from uds_assistant.testgen.model import TestCase

MAX_FAILURE_DETAILS = 50
"""Cap on the failure records stored in the report (the counts are always complete)."""


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def _step_diffs(got: list[dict[str, Any]], want: list[dict[str, Any]]) -> list[str]:
    diffs: list[str] = []
    if len(got) != len(want):
        diffs.append(f"step count {len(got)} != template {len(want)}")
    for i, (g, w) in enumerate(zip(got, want, strict=False)):
        for key in sorted(set(g) | set(w)):
            if g.get(key) != w.get(key):
                diffs.append(f"step {i} {key}: test={g.get(key)!r} template={w.get(key)!r}")
    return diffs


def check_test(spec: EcuSpec, test: TestCase) -> list[str]:
    """Return the provenance problems of one generated test (empty list = provenance OK)."""
    tid = test.template_id
    template = resolve_template(tid)
    if template is None:
        return [f"template_id {tid!r} is not a registered template"]
    try:
        params = template.params_model.model_validate(test.parameters)
    except ValueError as exc:
        name = template.params_model.__name__
        return [f"stored parameters do not validate against {name}: {exc}"]
    try:
        ref = template.instantiate(spec, params)
    except Exception as exc:  # noqa: BLE001 - a failure to re-instantiate is itself a finding
        return [f"re-instantiation failed: {type(exc).__name__}: {exc}"]
    problems: list[str] = []
    if _canon(params.model_dump()) != _canon(test.parameters):
        problems.append(
            f"stored parameters do not round-trip: test={test.parameters!r} "
            f"validated={params.model_dump()!r}"
        )
    if ref.template_id != tid:
        problems.append(f"template {tid!r} produced template_id {ref.template_id!r}")
    if ref.category != test.category:
        problems.append(f"category {test.category!r} != template {ref.category!r}")
    got = [s.model_dump(mode="json") for s in test.steps]
    want = [s.model_dump(mode="json") for s in ref.steps]
    problems += _step_diffs(got, want)
    # Byte-level comparison of every send step (independent of the dict comparison above).
    for i, (g, w) in enumerate(zip(test.steps, ref.steps, strict=False)):
        if g.kind == "send" and w.kind == "send":
            if g.request_bytes != w.request_bytes:
                problems.append(f"step {i} request bytes differ")
            if g.expected_response_bytes != w.expected_response_bytes:
                problems.append(f"step {i} expected-response bytes differ")
    return list(dict.fromkeys(problems))


def check_provenance(spec: EcuSpec, tests: Iterable[TestCase]) -> dict[str, Any]:
    """Check every test; return ``{checked, passed, failed, ok, failures[...]}``."""
    checked = passed = 0
    failures: list[dict[str, Any]] = []
    for test in tests:
        checked += 1
        problems = check_test(spec, test)
        if problems:
            failures.append({
                "test_id": test.id,
                "template_id": test.template_id,
                "requirement_ids": list(test.requirement_ids),
                "problems": problems,
            })
        else:
            passed += 1
    return {
        "checked": checked,
        "passed": passed,
        "failed": checked - passed,
        "ok": checked == passed,
        "failures": failures[:MAX_FAILURE_DETAILS],
        "definition": (
            "each generated test re-instantiated from TEMPLATES[template_id].instantiate(spec, "
            "params_model.model_validate(test.parameters)) (conformance-sweep tests: from the "
            "conformance registry, which the planner never sees); template_id must be registered, "
            "parameters must round-trip, and every step must be identical (request and "
            "expected-response bytes, time/environment/DTC steps, descriptions, timing limits)."
        ),
    }
