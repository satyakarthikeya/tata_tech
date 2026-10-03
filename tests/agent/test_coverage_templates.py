"""Template set v3 (Part C3): the mock planner and the compact shortlist can select it.

The requirement texts below are made up for these tests (plausible engineer phrasing);
they are not taken from any requirements file.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.agent.conftest import SEED_REQUIREMENTS
from uds_assistant.agent import nodes, run_pipeline
from uds_assistant.agent.options import build_catalog, plan_shortlist
from uds_assistant.agent.state import PipelineDeps, PipelineState
from uds_assistant.llm.base import ParsedRequirement, estimate_tokens
from uds_assistant.llm.mock import MockLLM
from uds_assistant.llm.prompts import SYSTEM_PROMPT
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.spec.schema import EcuSpec

# (made-up requirement text, template id, required parameter values of one chosen test)
SYNTHETIC: list[tuple[str, str, dict[str, object]]] = [
    ((
        "Once security level 0x01 is unlocked, asking for another seed shall return an "
        "all-zero seed."
    ), "seed_request_while_unlocked", {"level": 0x01}),
    ((
        "The lighting self-test routine (0x0201) shall report not started after the "
        "diagnostic session is changed."
    ), "session_change_resets_routine",
     {"routine": 0x0201, "transition": "session_change"}),
    ((
        "ReadDataByIdentifier requests whose DID list length is not a whole number of "
        "identifiers shall be rejected."
    ), "read_did_invalid_length", {}),
    ((
        "The coding variant id (DID 0x0160) written in programming session shall be retained "
        "after an ECU reset."
    ), "write_did_value_retained", {"did": 0x0160, "after": "ecu_reset"}),
    ("Multi-byte coding values shall be written and reported in big-endian byte order.",
     "write_did_value_retained", {"did": 0x0160}),
    ((
        "RoutineControl start of routine 0x0203 shall honour the suppress positive response "
        "bit."
    ), "routine_start_results", {"routine": 0x0203, "suppress_positive": True}),
    ((
        "The factory reset flag (DID 0x0150) shall be reported by the BCM in extended session "
        "only."
    ), "read_did_wrong_session_or_unknown", {"did": 0x0150, "session": 0x01}),
    ((
        "Starting the door actuator calibration routine (0x0202) shall be refused while the "
        "vehicle moves."
    ), "condition_not_met", {"target": 0x0202, "security": "locked"}),
    ((
        "After three invalid keys for security level 0x01 the delay shall still apply after an "
        "ECU reset."
    ), "security_invalid_key_lockout", {"level": 0x01, "recovery": "ecu_reset"}),
]


def _run(text: str, spec: EcuSpec, retriever: Bm25Retriever) -> Any:
    return run_pipeline(text, "REQ-SYN", spec, MockLLM(), retriever, engine="plain")


@pytest.mark.parametrize(("text", "template_id", "params"), SYNTHETIC)
def test_mock_selects_coverage_templates(
    text: str, template_id: str, params: dict[str, object], spec: EcuSpec,
    retriever: Bm25Retriever,
) -> None:
    result = _run(text, spec, retriever)
    chosen = [t.parameters for t in result.tests if t.template_id == template_id]
    assert any(all(p.get(k) == v for k, v in params.items()) for p in chosen), (
        template_id, [t.id for t in result.tests])


def test_mock_is_deterministic_on_synthetic_texts(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    for text, _, _ in SYNTHETIC:
        a, b = _run(text, spec, retriever), _run(text, spec, retriever)
        assert [t.model_dump() for t in a.tests] == [t.model_dump() for t in b.tests]


def test_every_new_template_is_chosen_for_some_seed_requirement(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    chosen: set[str] = set()
    for req in SEED_REQUIREMENTS:
        result = run_pipeline(req["text"], req["id"], spec, MockLLM(), retriever, engine="plain")
        chosen |= {t.template_id or "" for t in result.tests}
    assert {"read_did_invalid_length", "seed_request_while_unlocked",
            "session_change_resets_routine", "write_did_value_retained"} <= chosen


@pytest.mark.parametrize(("text", "template_id", "params"), SYNTHETIC)
def test_shortlist_offers_coverage_templates_within_budget(
    text: str, template_id: str, params: dict[str, object], spec: EcuSpec,
    retriever: Bm25Retriever,
) -> None:
    parsed = _run(text, spec, retriever).parsed or ParsedRequirement()
    state = PipelineState(requirement_id="REQ-SYN", requirement_text=text, parsed=parsed)
    deps = PipelineDeps(spec=spec, llm=MockLLM(), retriever=retriever)
    prompt, entries = nodes.compact_plan_prompt(state, deps, build_catalog(spec), set(), 4096)
    assert estimate_tokens(SYSTEM_PROMPT, prompt) <= int(4096 * nodes.PLAN_PROMPT_BUDGET)
    assert any(e.template_id == template_id for e in entries), [
        (e.template_id, e.option_index) for e in entries]


@pytest.mark.parametrize("req", SEED_REQUIREMENTS, ids=lambda r: r["id"])
def test_seed_shortlist_is_not_cut_by_the_cap(
    req: dict[str, str], spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    """With the larger catalog every relevant option still fits under PLAN_SHORTLIST_MAX and
    the token budget (no option is dropped for a seed requirement)."""
    parsed = run_pipeline(req["text"], req["id"], spec, MockLLM(), retriever,
                          engine="plain").parsed or ParsedRequirement()
    catalog = build_catalog(spec)
    full = plan_shortlist(spec, catalog, nodes._parsed_lists(parsed))
    state = PipelineState(requirement_id=req["id"], requirement_text=req["text"], parsed=parsed)
    deps = PipelineDeps(spec=spec, llm=MockLLM(), retriever=retriever)
    prompt, entries = nodes.compact_plan_prompt(state, deps, catalog, set(), 4096)
    assert len(full) <= nodes.PLAN_SHORTLIST_MAX
    assert entries == full
    assert estimate_tokens(SYSTEM_PROMPT, prompt) <= int(4096 * nodes.PLAN_PROMPT_BUDGET)
