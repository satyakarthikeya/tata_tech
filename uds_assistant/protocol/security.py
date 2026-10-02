"""Synthetic SecurityAccess (0x27) seed/key algorithm and lockout tracking.

This is a project-invented algorithm for a *synthetic* ECU spec, not a real
OEM secret algorithm. It exists purely so the rules engine, simulator, and
tests have something deterministic and independently re-computable to check
against.

Algorithm (documented here, not copied from anywhere):

    key = bytes(
        ((seed_byte ^ secret_for_level) rotated left by 3 bits) + level
        for each seed_byte in seed, taken modulo 256
    )

where ``secret_for_level`` is a per-level constant byte derived as
``0xA5 + level`` (mod 256), and the rotation is an 8-bit circular left
rotation applied before the final ``+ level`` addition (also mod 256).

Seed generation is deterministic given an injectable RNG so tests can
reproduce exact seed/key pairs without relying on wall-clock entropy.

Lockout state is modelled as a pure, immutable pydantic model:
:class:`SecurityLockoutState`. All transitions are pure functions that take
the current state and an injected ``now_ms`` clock reading and return a new
state plus an outcome (allowed / NRC). No function here reads the wall clock.
"""

from __future__ import annotations

import random

from pydantic import BaseModel

_ROTATE_BITS = 3
_SECRET_BASE = 0xA5


def _secret_for_level(level: int) -> int:
    """Per-level XOR secret constant: ``0xA5 + level`` (mod 256)."""
    return (_SECRET_BASE + level) & 0xFF


def _rotl8(value: int, bits: int) -> int:
    """Circular left-rotate an 8-bit value by ``bits`` positions."""
    bits %= 8
    return ((value << bits) | (value >> (8 - bits))) & 0xFF


def generate_seed(length: int, rng: random.Random) -> bytes:
    """Generate a deterministic pseudo-random seed of ``length`` bytes.

    ``rng`` must be an already-seeded :class:`random.Random` instance so
    callers (tests, the simulator) fully control reproducibility; this
    function never touches wall-clock time or OS entropy itself.
    """
    if length < 1:
        raise ValueError("Seed length must be at least 1 byte.")
    return bytes(rng.randrange(0, 256) for _ in range(length))


def compute_key(seed: bytes, level: int) -> bytes:
    """Compute the expected key for ``seed`` at security ``level``.

    See module docstring for the documented synthetic algorithm.
    """
    secret = _secret_for_level(level)
    out = bytearray()
    for seed_byte in seed:
        rotated = _rotl8(seed_byte ^ secret, _ROTATE_BITS)
        out.append((rotated + level) & 0xFF)
    return bytes(out)


def is_key_valid(seed: bytes, level: int, key: bytes) -> bool:
    """Return True if ``key`` matches the expected key for ``seed``/``level``."""
    return compute_key(seed, level) == key


class SecurityLockoutState(BaseModel):
    """Pure, immutable per-level SecurityAccess attempt-tracking state.

    ``failed_attempts`` counts consecutive invalid keys since the last
    successful unlock or lockout clear. ``locked_until_ms`` is ``None`` when
    not locked out, else the clock reading (ms) at which the lockout expires.
    """

    failed_attempts: int = 0
    locked_until_ms: int | None = None

    @property
    def is_locked(self) -> bool:
        """True if a lockout delay is currently recorded (caller must compare to clock)."""
        return self.locked_until_ms is not None


def is_delay_active(state: SecurityLockoutState, now_ms: int) -> bool:
    """Return True if the lockout delay recorded in ``state`` has not yet expired at ``now_ms``."""
    return state.locked_until_ms is not None and now_ms < state.locked_until_ms


def record_failed_attempt(
    state: SecurityLockoutState, now_ms: int, max_attempts: int, delay_ms: int
) -> tuple[SecurityLockoutState, bool]:
    """Record one failed key attempt.

    Returns ``(new_state, lockout_just_triggered)``. ``lockout_just_triggered``
    is True exactly on the attempt that reaches ``max_attempts`` (the rules
    engine maps that attempt to NRC 0x36 ``EXCEED_NUMBER_OF_ATTEMPTS``); a
    request made while the delay is still active is a separate case handled
    by the caller via :func:`is_delay_active` (NRC 0x37).
    """
    new_count = state.failed_attempts + 1
    if new_count >= max_attempts:
        return (
            SecurityLockoutState(failed_attempts=new_count, locked_until_ms=now_ms + delay_ms),
            True,
        )
    return SecurityLockoutState(failed_attempts=new_count, locked_until_ms=None), False


def record_successful_unlock() -> SecurityLockoutState:
    """Return the cleared lockout state after a successful key verification."""
    return SecurityLockoutState(failed_attempts=0, locked_until_ms=None)


def clear_expired_lockout(state: SecurityLockoutState, now_ms: int) -> SecurityLockoutState:
    """Return a state with the lockout cleared if ``now_ms`` has passed ``locked_until_ms``.

    Does not reset ``failed_attempts``; only the delay gate (0x37) is cleared.
    """
    if state.locked_until_ms is not None and now_ms >= state.locked_until_ms:
        return SecurityLockoutState(failed_attempts=state.failed_attempts, locked_until_ms=None)
    return state
