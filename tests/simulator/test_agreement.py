"""Simulator vs rules engine: byte-identical responses on randomized traffic.

The simulator (written from docs/behaviour_contract.md) and the rules engine
(the oracle) are independent implementations; any disagreement fails the test
with the last 25 steps of the trace.
"""

from __future__ import annotations

import random

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


def test_seeded_long_walks_agree(spec: EcuSpec) -> None:
    """Deterministic random walks (40 x 100 steps) through state space agree."""
    stats = AgreementStats()
    for seed in range(40):
        rng = random.Random(1000 + seed)
        runner = DualRunner(spec, stats)
        for _ in range(100):
            runner.step(random_step(rng))
    assert stats.requests > 2500
    assert not stats.mismatches


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
