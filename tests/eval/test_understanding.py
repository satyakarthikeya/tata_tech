"""Unit tests: requirement-understanding scoring, precondition derivation, held-out triggers,
the live simulator/rules agreement sample and the udsoncan virtual-CAN check."""

from __future__ import annotations

from pathlib import Path

import pytest

from uds_assistant.eval import understanding as u
from uds_assistant.eval.agreement import simulator_rules_agreement
from uds_assistant.eval.can_check import run_udsoncan_sequence
from uds_assistant.eval.heldout import HELDOUT_TRIGGERS, miss_reason, trigger_counts
from uds_assistant.llm.base import ParsedRequirement
from uds_assistant.simulator import HELDOUT_BUG_IDS
from uds_assistant.spec.schema import EcuSpec, load_spec
from uds_assistant.testgen.model import (
    AdvanceTimeStep,
    SendStep,
    SetDtcStatusStep,
    SetEnvironmentStep,
    TestCase,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def spec() -> EcuSpec:
    return load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")


def _send(req: str, *resp: str) -> SendStep:
    return SendStep(request_hex=req, expected_responses_hex=list(resp))


def _test(steps: list, category: str = "positive", tid: str = "t") -> TestCase:
    return TestCase(id=tid, title=tid, category=category, steps=steps)  # type: ignore[arg-type]


# ------------------------------------------------------------------------- target scoring

SVC22, DID_F190, DID_F18C = ("service", 0x22), ("did", 0xF190), ("did", 0xF18C)


def test_score_targets_exact_and_counts() -> None:
    r = u.score_targets({SVC22, DID_F190}, {SVC22, DID_F190}, n_tests=3)
    assert r["exact"] and (r["tp"], r["fp"], r["fn"]) == (2, 0, 0)
    r = u.score_targets({SVC22, DID_F190, DID_F18C}, {SVC22, DID_F190, ("service", 0x10)}, 3)
    assert not r["exact"] and (r["tp"], r["fp"], r["fn"]) == (2, 1, 1)
    assert r["missed"] == ["did:0xF18C"] and r["extra"] == ["service:0x10"]


@pytest.mark.parametrize(
    ("predicted", "n_tests", "exact"),
    [(set(), 0, True), (set(), 2, False), ({SVC22}, 0, False)],
)
def test_score_targets_empty_label_nat020_style(
    predicted: set[u.Ident], n_tests: int, exact: bool
) -> None:
    r = u.score_targets(set(), predicted, n_tests)
    assert r["exact"] is exact
    assert r["tp"] == r["fn"] == 0 and r["fp"] == len(predicted)


def test_prf_and_recall_fraction() -> None:
    assert u.prf(2, 1, 1) == {"precision": 0.6667, "recall": 0.6667, "f1": 0.6667}
    assert u.prf(0, 0, 0) == {"precision": None, "recall": None, "f1": None}
    assert u.prf(0, 2, 3)["f1"] == 0.0
    r = u.recall_fraction(["positive", "negative", "timing"], ["negative", "session"])
    assert (r["hit"], r["required"], r["recall"]) == (1, 3, 0.3333)
    assert r["missed"] == ["positive", "timing"]
    assert u.recall_fraction([], ["positive"])["recall"] is None


def test_parsed_and_exercised_targets() -> None:
    parsed = ParsedRequirement(services=["0x22"], dids=["0xF190"], routines=["0x0201"])
    assert u.parsed_targets(parsed) == {SVC22, DID_F190, ("routine", 0x0201)}
    assert u.parsed_targets(None) == set()
    t = _test([_send("1003", "5003003201f4"), _send("22f190f18c"), _send("2e010050"),
               _send("31010201")])
    assert u.exercised_targets([t]) == {
        ("service", 0x10), SVC22, ("service", 0x2E), ("service", 0x31),
        DID_F190, DID_F18C, ("did", 0x0100), ("routine", 0x0201),
    }


def test_aggregate_micro_macro_and_fallback(spec: EcuSpec) -> None:
    req_a = u.NaturalRequirement(id="A", text="", split="test", target_services=[0x22],
                                 target_dids=[0xF190], required_categories=["positive", "negative"])
    req_empty = u.NaturalRequirement(id="E", text="", split="test")
    t = _test([_send("22f190", "62f190" + "00" * 17)])
    rows = [
        u.score_requirement(spec, req_a, ParsedRequirement(services=["0x22"]), [t], "completed"),
        u.score_requirement(spec, req_empty, None, [], "completed"),
    ]
    agg = u.aggregate_by_split(rows)["test"]
    assert agg["targets_parsed"]["exact"] == 1  # only the empty-label row (nothing produced)
    assert (agg["targets_parsed"]["tp"], agg["targets_parsed"]["fn"]) == (1, 1)
    assert agg["targets_exercised"]["exact"] == 2
    assert agg["categories"]["scored_requirements"] == 1  # empty-label row excluded
    assert agg["categories"]["micro_recall"] == 0.5
    assert agg["fallback"]["ids"] == ["E"] and agg["fallback"]["unexpected_count"] == 0


def test_load_natural_requirements() -> None:
    reqs = u.load_natural_requirements(REPO_ROOT / "data" / "requirements_natural.csv")
    assert len(reqs) == 20
    assert sum(r.split == "test" for r in reqs) == 12
    nat20 = next(r for r in reqs if r.id == "NAT-020")
    assert nat20.target_set == set() and nat20.required_preconditions == []
    nat9 = next(r for r in reqs if r.id == "NAT-009")
    assert ("did", 0x0150) in nat9.target_set
    assert "security_level_3" in nat9.required_preconditions


# ------------------------------------------------------------------- precondition derivation


def test_established_preconditions_session_security_lockout(spec: EcuSpec) -> None:
    t = _test([
        _send("1003", "5003003201f4"),
        _send("2701", "670111223344"),
        _send("270200000000", "6702"),
        _send("2701", "7f2736"),
    ])
    got = u.established_preconditions(spec, t)
    assert {"extended_session", "security_level_1", "lockout_active"} <= got
    assert "default_session" not in got and "programming_session" not in got


def test_established_preconditions_env_time_dtc_routine(spec: EcuSpec) -> None:
    t = _test([
        _send("22f190", "62f190" + "00" * 17),
        SetEnvironmentStep(vehicle_speed_kph=30),
        SetEnvironmentStep(vehicle_speed_kph=0, nvm_write_fault=True),
        SetDtcStatusStep(code="B10101", status=0x09),
        _send("1003", "5003003201f4"),
        _send("31010201", "71010201"),
        AdvanceTimeStep(ms=5001),
        _send("31030201", "7f3124"),
    ])
    got = u.established_preconditions(spec, t)
    assert got == {"default_session", "vehicle_moving", "vehicle_stationary", "nvm_fault",
                   "dtc_status_set", "extended_session", "routine_started", "s3_elapsed"}


def test_negative_outcomes_establish_nothing(spec: EcuSpec) -> None:
    t = _test([_send("1002", "7f1022"), _send("31010201", "7f3133")])
    got = u.established_preconditions(spec, t)
    assert "programming_session" not in got and "routine_started" not in got
    # a positive start of a vehicle_stationary-gated routine establishes stationary
    t2 = _test([_send("1003", "5003003201f4"), _send("3101020200", "71010202")])
    assert "vehicle_stationary" in u.established_preconditions(spec, t2)
    assert "routine_started" not in u.established_preconditions(spec, t2)  # nothing after it


# ------------------------------------------------------------------------- held-out triggers


def test_every_heldout_bug_has_a_trigger() -> None:
    assert set(HELDOUT_TRIGGERS) == set(HELDOUT_BUG_IDS)


def test_trigger_counts_and_reasons(spec: EcuSpec) -> None:
    odd = _test([_send("22f19000", "7f2213")], tid="odd")
    plain = _test([_send("22f190", "62f190" + "00" * 17)], tid="plain")
    counts = trigger_counts(spec, [odd, plain], ["read_did_odd_length_truncated", "unknown_bug"])
    assert counts == {"read_did_odd_length_truncated": 1, "unknown_bug": -1}
    assert miss_reason("read_did_odd_length_truncated", "generated", 0).startswith(
        "no generated test sends 0x22"
    )
    assert "none of their expected responses" in miss_reason(
        "read_did_odd_length_truncated", "gold", 2
    )
    assert miss_reason("unknown_bug", "gold", -1) == "no trigger analysis defined for this bug"


# ------------------------------------------------------------- live LLM-independent checks


def test_agreement_sample_is_deterministic_and_agrees(spec: EcuSpec) -> None:
    a = simulator_rules_agreement(spec, n_requests=300, seed=7)
    b = simulator_rules_agreement(spec, n_requests=300, seed=7)
    assert a == b
    assert a["requests"] >= 300
    assert a["agreed"] == a["requests"] and a["rate"] == 1.0


def test_udsoncan_virtual_can_sequence_passes(spec: EcuSpec) -> None:
    result = run_udsoncan_sequence(spec)
    assert result["status"] == "pass", result
    assert result["error"] is None
    assert result["steps"][-1].endswith("0x50")
