"""Simulator vs rules engine: byte-identical responses on randomized traffic.

The simulator (written from docs/behaviour_contract.md) and the rules engine
(the oracle) are independent implementations; any disagreement fails the test
with the last 25 steps of the trace.
"""

from __future__ import annotations

import random

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.simulator.agreement import AgreementStats, DualRunner, random_request, random_step
from uds_assistant.spec.schema import EcuSpec

steps_strategy = st.lists(
    st.randoms(use_true_random=False).map(random_step), min_size=1, max_size=30
)


@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(steps=steps_strategy)
def test_random_sequences_agree(spec: EcuSpec, steps: list[tuple]) -> None:
    """Hypothesis-generated sequences of up to 30 steps give identical responses."""
    runner = DualRunner(spec)
    for step in steps:
        runner.step(step)


#: Walk seeds (documented): two independent base seeds, 60 walks x 120 steps each.
WALK_BASE_SEEDS = [20261003, 777001]

#: Every new-behaviour path (D2/D5/D6/D7) must be exercised at least this often per seed.
REQUIRED_COVERAGE = [
    "d7_suppress_0x19_silent_positive",
    "d7_suppress_0x27_seed_silent_positive",
    "d7_suppress_0x27_key_silent_positive",
    "d7_suppress_0x27_key_negative_sent",
    "d5_key_during_delay_0x24",
    "d6_multi_did_mixed_good_bad",
    "d6_multi_did_duplicates_with_skips",
    "d6_multi_did_duplicates_all_answered",
    "d6_multi_did_all_skipped_0x31",
    "d2_unsupported_type_unknown_routine",
    "d2_unsupported_type_0x31",
    "d2_unsupported_type_0x12",
]


@pytest.mark.parametrize("base_seed", WALK_BASE_SEEDS)
def test_seeded_long_walks_agree(spec: EcuSpec, base_seed: int) -> None:
    """Deterministic random walks (60 x 120 steps, >= 5000 requests) agree; new paths covered."""
    stats = AgreementStats()
    for walk in range(60):
        rng = random.Random(base_seed * 1000 + walk)
        runner = DualRunner(spec, stats)
        for _ in range(120):
            runner.step(random_step(rng))
    assert stats.requests >= 5000
    assert not stats.mismatches
    print(f"seed={base_seed} requests={stats.requests} coverage={dict(stats.coverage)}")
    for key in REQUIRED_COVERAGE:
        assert stats.coverage[key] >= 5, (key, dict(stats.coverage))


def test_seeded_single_request_fuzz(spec: EcuSpec) -> None:
    """3000 single requests, each from a short random prefix state, agree."""
    rng = random.Random(4242)
    stats = AgreementStats()
    for _ in range(3000):
        runner = DualRunner(spec, stats)
        for _ in range(rng.randrange(0, 6)):
            runner.step(random_step(rng))
        runner.step(("req", random_request(rng)))
    assert stats.requests >= 3000
    assert not stats.mismatches


def test_unlocked_paths_agree(spec: EcuSpec) -> None:
    """Directed walk: unlock both levels, then fuzz writes/routines while unlocked."""
    stats = AgreementStats()
    rng = random.Random(7)
    for i in range(60):
        runner = DualRunner(spec, stats)
        if i % 2 == 0:
            prefix = [("req", bytes.fromhex("1003")), ("req", bytes.fromhex("2701")),
                      ("key", 2, "correct")]
        else:
            prefix = [("req", bytes.fromhex("1002")), ("req", bytes.fromhex("2703")),
                      ("key", 4, "correct")]
        for step in prefix:
            runner.step(step)
        for _ in range(40):
            if rng.random() < 0.6:
                sid = rng.choice([0x2E, 0x31, 0x22, 0x14, 0x19])
                req = random_request(rng)
                while req[:1] != bytes([sid]):
                    req = random_request(rng)
                runner.step(("req", req))
            else:
                runner.step(random_step(rng))
    assert not stats.mismatches
