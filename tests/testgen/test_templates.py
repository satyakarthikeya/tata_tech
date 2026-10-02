from __future__ import annotations

import pytest

from uds_assistant.simulator import SimulatedEcu
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.execute import run_test_on_simulator
from uds_assistant.testgen.templates import TEMPLATES, applicable_params, validate_test


def test_registry_size() -> None:
    # Upper bound raised from 20 in Phase 7 (template set v2, DECISIONS.md [EVAL-TPL-V2]).
    assert 8 <= len(TEMPLATES) <= 30


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_every_applicable_param_instantiates_validates_and_passes(
    template_id: str, spec: EcuSpec
) -> None:
    tpl = TEMPLATES[template_id]
    params_list = applicable_params(spec, template_id)
    assert params_list, f"{template_id} has no applicable params for this spec"
    for params in params_list:
        tc = tpl.instantiate(spec, params)
        assert tc.template_id == template_id
        assert tc.origin == "generated"

        report = validate_test(spec, tc)
        assert report.ok, f"{template_id}/{params}: {report.mismatches}"

        outcome = run_test_on_simulator(tc, lambda: SimulatedEcu(spec))
        assert outcome.passed, f"{template_id}/{params}: {outcome.first_failure}"


def test_applicable_params_dict_input_also_works(spec: EcuSpec) -> None:
    tpl = TEMPLATES["read_did_positive"]
    params = applicable_params(spec, "read_did_positive")[0]
    tc_from_model = tpl.instantiate(spec, params)
    tc_from_dict = tpl.instantiate(spec, params.model_dump())
    assert tc_from_model.steps == tc_from_dict.steps


def test_validate_test_detects_tampered_expectation(spec: EcuSpec) -> None:
    tpl = TEMPLATES["read_did_positive"]
    params = applicable_params(spec, "read_did_positive")[0]
    tc = tpl.instantiate(spec, params)
    tc.steps[0].expected_responses_hex = ["ffffff"]
    report = validate_test(spec, tc)
    assert not report.ok
    assert report.mismatches
