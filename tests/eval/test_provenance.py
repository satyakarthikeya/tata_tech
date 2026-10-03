"""Byte provenance: genuine template instantiations pass, tampered tests fail."""

from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.eval.provenance import check_provenance, check_test
from uds_assistant.spec.schema import EcuSpec, load_spec
from uds_assistant.testgen.model import AdvanceTimeStep, SendStep, TestCase, load_tests
from uds_assistant.testgen.templates import TEMPLATES, applicable_params

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def spec() -> EcuSpec:
    return load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")


def _genuine(spec: EcuSpec) -> list[TestCase]:
    """One instantiation per template, re-keyed the way the agent's instantiate node does."""
    out = []
    for tid, template in TEMPLATES.items():
        params = applicable_params(spec, tid)
        if not params:
            continue
        base = template.instantiate(spec, params[0])
        out.append(base.model_copy(update={
            "id": f"req_x__{base.id}", "requirement_ids": ["REQ-X"], "citations": [],
            "origin": "generated", "explanation": "LLM-written prose is allowed here",
            "review_status": "validated", "title": base.title,
        }))
    return out


def _first_send(test: TestCase) -> int:
    return next(i for i, s in enumerate(test.steps) if isinstance(s, SendStep))


def test_genuine_tests_pass(spec: EcuSpec) -> None:
    tests = _genuine(spec)
    assert len(tests) >= 20
    result = check_provenance(spec, tests)
    assert result["ok"] and result["checked"] == result["passed"] == len(tests)
    assert result["failures"] == []


def test_genuine_tests_pass_after_yaml_round_trip(spec: EcuSpec, tmp_path: Path) -> None:
    from uds_assistant.testgen.model import dump_tests

    path = tmp_path / "t.yaml"
    dump_tests(_genuine(spec), path)
    assert check_provenance(spec, load_tests(path))["ok"]


def test_tampered_request_bytes_fail(spec: EcuSpec) -> None:
    test = _genuine(spec)[0]
    i = _first_send(test)
    steps = list(test.steps)
    step = steps[i]
    assert isinstance(step, SendStep)
    steps[i] = step.model_copy(update={"request_hex": step.request_hex + "00"})
    problems = check_test(spec, test.model_copy(update={"steps": steps}))
    assert any(f"step {i} request_hex" in p for p in problems)
    assert any(f"step {i} request bytes differ" in p for p in problems)


def test_tampered_expected_response_fails(spec: EcuSpec) -> None:
    test = _genuine(spec)[0]
    i = _first_send(test)
    steps = list(test.steps)
    step = steps[i]
    assert isinstance(step, SendStep)
    steps[i] = step.model_copy(update={"expected_responses_hex": ["7f2231"]})
    result = check_provenance(spec, [test.model_copy(update={"steps": steps})])
    assert not result["ok"] and result["failed"] == 1
    assert any("expected-response bytes differ" in p for p in result["failures"][0]["problems"])


def test_tampered_time_step_and_extra_step_fail(spec: EcuSpec) -> None:
    test = _genuine(spec)[0]
    extra = test.model_copy(update={"steps": [*test.steps, AdvanceTimeStep(ms=10)]})
    assert any("step count" in p for p in check_test(spec, extra))


def test_unregistered_or_missing_template_fails(spec: EcuSpec) -> None:
    test = _genuine(spec)[0]
    for tid in ("read_did_positive (positive)", None):
        problems = check_test(spec, test.model_copy(update={"template_id": tid}))
        assert problems and "not a registered template" in problems[0]


def test_parameters_that_do_not_match_steps_fail(spec: EcuSpec) -> None:
    tests = {t.template_id: t for t in _genuine(spec)}
    test = tests["read_did_positive"]
    other = applicable_params(spec, "read_did_positive")[1].model_dump()
    assert other != test.parameters
    assert check_test(spec, test.model_copy(update={"parameters": other}))


def test_invalid_parameters_fail(spec: EcuSpec) -> None:
    test = _genuine(spec)[0]
    problems = check_test(spec, test.model_copy(update={"parameters": {"bogus": 1}}))
    assert problems and "do not validate" in problems[0]
