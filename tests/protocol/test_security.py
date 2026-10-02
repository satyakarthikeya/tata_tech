"""Tests for the synthetic seed/key algorithm and lockout state machine."""

from __future__ import annotations

import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from uds_assistant.protocol.security import (
    SecurityLockoutState,
    clear_expired_lockout,
    compute_key,
    generate_seed,
    is_delay_active,
    is_key_valid,
    record_failed_attempt,
    record_successful_unlock,
)


def test_generate_seed_deterministic_given_rng_seed() -> None:
    seed1 = generate_seed(4, random.Random(42))
    seed2 = generate_seed(4, random.Random(42))
    assert seed1 == seed2
    assert len(seed1) == 4


def test_generate_seed_rejects_non_positive_length() -> None:
    with pytest.raises(ValueError):
        generate_seed(0, random.Random(1))


def test_compute_key_deterministic() -> None:
    seed = bytes([0x12, 0x34, 0x56, 0x78])
    key1 = compute_key(seed, level=0x01)
    key2 = compute_key(seed, level=0x01)
    assert key1 == key2
    assert is_key_valid(seed, 0x01, key1)


def test_compute_key_differs_by_level() -> None:
    seed = bytes([0x12, 0x34, 0x56, 0x78])
    assert compute_key(seed, level=0x01) != compute_key(seed, level=0x03)


def test_is_key_valid_rejects_wrong_key() -> None:
    seed = bytes([0x01, 0x02, 0x03, 0x04])
    key = compute_key(seed, level=0x01)
    wrong = bytes((b + 1) % 256 for b in key)
    assert not is_key_valid(seed, 0x01, wrong)


@given(
    seed=st.binary(min_size=1, max_size=8),
    level=st.integers(min_value=1, max_value=0x7F),
)
def test_compute_key_roundtrip_property(seed: bytes, level: int) -> None:
    key = compute_key(seed, level)
    assert len(key) == len(seed)
    assert is_key_valid(seed, level, key)


def test_lockout_triggers_on_max_attempt() -> None:
    state = SecurityLockoutState()
    state, triggered = record_failed_attempt(state, now_ms=0, max_attempts=3, delay_ms=10_000)
    assert not triggered
    state, triggered = record_failed_attempt(state, now_ms=100, max_attempts=3, delay_ms=10_000)
    assert not triggered
    state, triggered = record_failed_attempt(state, now_ms=200, max_attempts=3, delay_ms=10_000)
    assert triggered
    assert state.failed_attempts == 3
    assert state.locked_until_ms == 200 + 10_000


def test_delay_active_until_expiry() -> None:
    state = SecurityLockoutState(failed_attempts=3, locked_until_ms=10_000)
    assert is_delay_active(state, now_ms=5_000)
    assert not is_delay_active(state, now_ms=10_000)
    assert not is_delay_active(state, now_ms=20_000)


def test_clear_expired_lockout() -> None:
    state = SecurityLockoutState(failed_attempts=3, locked_until_ms=10_000)
    still_locked = clear_expired_lockout(state, now_ms=5_000)
    assert still_locked.locked_until_ms == 10_000
    cleared = clear_expired_lockout(state, now_ms=10_000)
    assert cleared.locked_until_ms is None
    assert cleared.failed_attempts == 3  # attempt counter is not reset by expiry


def test_successful_unlock_clears_state() -> None:
    state = SecurityLockoutState(failed_attempts=2, locked_until_ms=None)
    cleared = record_successful_unlock()
    assert cleared.failed_attempts == 0
    assert cleared.locked_until_ms is None
    assert state.failed_attempts == 2  # original untouched (pure function)
