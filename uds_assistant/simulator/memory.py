"""Mutable ECU memory for the simulator.

Written from ``docs/behaviour_contract.md`` (never from the rules engine). This
is deliberately a plain mutable dataclass: the simulated ECU is the one place
in the project where in-place mutable state is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from uds_assistant.spec.schema import EcuSpec

DEFAULT_SESSION = 0x01

# Routine status byte values used on the wire.
ROUTINE_NEVER_STARTED = 0x00
ROUTINE_RUNNING = 0x01
ROUTINE_COMPLETED = 0x02
ROUTINE_STOPPED = 0x03


def dtc_number(code: str) -> int:
    """Return the 3-byte DTC number for a spec code such as ``"B10101"``."""
    return int(code.replace("0x", "").replace(" ", ""), 16)


@dataclass
class LevelLockout:
    """Failed-attempt counter and optional lockout deadline for one security level."""

    failures: int = 0
    deadline_ms: int | None = None


@dataclass
class EcuMemory:
    """Everything the simulated ECU remembers between requests."""

    session: int = DEFAULT_SESSION
    unlocked_level: int | None = None
    lockouts: dict[int, LevelLockout] = field(default_factory=dict)
    pending_seeds: dict[int, bytes] = field(default_factory=dict)
    seed_counter: int = 0
    routine_status: dict[int, int] = field(default_factory=dict)
    dtc_status: dict[int, int] = field(default_factory=dict)
    did_store: dict[int, bytes] = field(default_factory=dict)
    vehicle_speed_kph: int = 0
    nvm_write_fault: bool = False
    last_request_ms: int | None = None

    @classmethod
    def power_on(cls, spec: EcuSpec) -> EcuMemory:
        """Build the power-on memory image for ``spec``."""
        mem = cls()
        for lvl in spec.security_levels:
            mem.lockouts[lvl.level] = LevelLockout()
        for dtc in spec.dtcs:
            mem.dtc_status[dtc_number(dtc.code)] = dtc.initial_status
        for did in spec.dids:
            mem.did_store[did.id] = bytes(did.default_value) or bytes(did.length)
        return mem

    def drop_volatile(self, new_session: int, *, keep_security: bool = False) -> None:
        """Enter ``new_session`` and forget unlock state, pending seeds and routine status."""
        self.session = new_session
        if not keep_security:
            self.unlocked_level = None
        self.pending_seeds.clear()
        self.routine_status.clear()
