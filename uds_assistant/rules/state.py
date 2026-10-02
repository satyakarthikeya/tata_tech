"""Immutable ECU state model consumed and produced by the rules engine.

Nothing in this module reads the wall clock; time is always injected as
``now_ms``. The engine never mutates an :class:`EcuState`; it builds a new one
with :meth:`pydantic.BaseModel.model_copy` and fresh containers.
"""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, ConfigDict, Field

from uds_assistant.protocol.security import SecurityLockoutState
from uds_assistant.spec.schema import EcuSpec

DEFAULT_SESSION_ID = 0x01

#: Condition names a spec may list under ``conditions.requires``.
KNOWN_CONDITIONS: frozenset[str] = frozenset({"vehicle_stationary"})

#: DID names whose value is derived live from the state instead of stored.
DYNAMIC_DID_ACTIVE_SESSION = "active_diagnostic_session"
DYNAMIC_DID_VEHICLE_SPEED = "vehicle_speed_kph"


class RoutineStatus(IntEnum):
    """One-byte routine status record returned in RoutineControl responses."""

    NOT_STARTED = 0x00
    RUNNING = 0x01
    COMPLETED = 0x02
    STOPPED = 0x03


class EnvironmentConditions(BaseModel):
    """Vehicle/ECU conditions outside the diagnostic protocol itself."""

    model_config = ConfigDict(frozen=True)

    vehicle_speed_kph: int = Field(default=0, ge=0)
    nvm_write_fault: bool = False

    @property
    def vehicle_stationary(self) -> bool:
        """True when the vehicle speed is exactly 0 km/h."""
        return self.vehicle_speed_kph == 0

    def is_met(self, condition: str) -> bool:
        """Return True if the named precondition currently holds.

        Unknown condition names are treated as *not met* (fail safe).
        """
        if condition == "vehicle_stationary":
            return self.vehicle_stationary
        return False


class EcuState(BaseModel):
    """Complete diagnostic state of the ECU as seen by the rules engine."""

    model_config = ConfigDict(frozen=True)

    active_session: int = DEFAULT_SESSION_ID
    unlocked_level: int | None = None
    lockouts: dict[int, SecurityLockoutState] = Field(default_factory=dict)
    pending_seeds: dict[int, bytes] = Field(default_factory=dict)
    seed_counter: int = Field(default=0, ge=0)
    routine_status: dict[int, RoutineStatus] = Field(default_factory=dict)
    dtc_status: dict[int, int] = Field(default_factory=dict)
    did_values: dict[int, bytes] = Field(default_factory=dict)
    environment: EnvironmentConditions = Field(default_factory=EnvironmentConditions)
    last_request_ms: int | None = None
    now_ms: int = 0

    @property
    def started_routines(self) -> frozenset[int]:
        """Routine ids started since the last session change / reset."""
        return frozenset(self.routine_status)

    @property
    def running_routines(self) -> frozenset[int]:
        """Routine ids whose status is currently RUNNING."""
        return frozenset(r for r, s in self.routine_status.items() if s == RoutineStatus.RUNNING)


def dtc_code_to_int(code: str) -> int:
    """Convert a spec DTC code string such as ``"B10101"`` to its 3-byte integer."""
    return int(code.replace("0x", "").replace(" ", ""), 16)


def initial_state(spec: EcuSpec, now_ms: int = 0) -> EcuState:
    """Return the power-on :class:`EcuState` for ``spec``.

    Default session, all levels locked with fresh lockout counters, no seeds
    pending, no routines started, DTC statuses from ``initial_status``, DID
    values from ``default_value`` (zero-filled when empty), vehicle stationary,
    no NVM fault, S3 timer idle.
    """
    return EcuState(
        active_session=DEFAULT_SESSION_ID,
        lockouts={lvl.level: SecurityLockoutState() for lvl in spec.security_levels},
        dtc_status={dtc_code_to_int(d.code): d.initial_status for d in spec.dtcs},
        did_values={d.id: d.default_value or bytes(d.length) for d in spec.dids},
        now_ms=now_ms,
    )


def with_environment(
    state: EcuState,
    *,
    vehicle_speed_kph: int | None = None,
    nvm_write_fault: bool | None = None,
) -> EcuState:
    """Return a copy of ``state`` with the given environment fields replaced."""
    env = state.environment
    update: dict[str, object] = {}
    if vehicle_speed_kph is not None:
        update["vehicle_speed_kph"] = vehicle_speed_kph
    if nvm_write_fault is not None:
        update["nvm_write_fault"] = nvm_write_fault
    new_env = EnvironmentConditions.model_validate({**env.model_dump(), **update})
    return state.model_copy(update={"environment": new_env})


def with_dtc_status(state: EcuState, code: int, status: int) -> EcuState:
    """Return a copy of ``state`` with DTC ``code`` set to ``status`` (test/sim helper)."""
    return state.model_copy(update={"dtc_status": {**state.dtc_status, code: status & 0xFF}})
