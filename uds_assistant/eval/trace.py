"""Static walk over a :class:`TestCase`: what each send step does and in which tracked state.

Used by the evaluation only (requirement understanding and held-out bug analysis).
Nothing is executed: the walk reads the concrete request bytes and the *expected*
response frames stored in the test (which come from the rules-engine oracle) and
tracks a coarse tester-side view of the ECU state:

- session: starts at the spec's default session; a positive ``0x10`` response sets
  it, a positive ``0x11`` reset or an idle gap longer than the active session's S3
  returns it to default;
- unlocked security levels: a positive sendKey adds the level; any session change,
  reset or S3 timeout clears them;
- environment: last vehicle speed / NVM-fault set by a ``set_environment`` step.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.model import TestCase

NEGATIVE = 0x7F
PENDING_NRC = 0x78


@dataclass(frozen=True)
class SendEvent:
    """One send step and the tracked state *before* it was sent."""

    index: int
    request: bytes
    frames: tuple[bytes, ...]
    session: int
    unlocked: frozenset[int]
    vehicle_speed_kph: int
    nvm_write_fault: bool
    idle_ms: int
    """Clock advance since the previous send step (or since power-on)."""
    s3_expired: bool
    """True if ``idle_ms`` exceeded the S3 time of the session active before this step."""

    @property
    def sid(self) -> int | None:
        """Service id of the request (None for an empty request)."""
        return self.request[0] if self.request else None

    @property
    def subfunction(self) -> int | None:
        """Second request byte with the suppress bit masked (None if absent)."""
        return self.request[1] & 0x7F if len(self.request) > 1 else None

    @property
    def nrc(self) -> int | None:
        """Final negative response code, ignoring ``0x78`` response-pending frames."""
        for frame in reversed(self.frames):
            if len(frame) >= 3 and frame[0] == NEGATIVE and frame[2] != PENDING_NRC:
                return frame[2]
        return None

    @property
    def positive(self) -> bool:
        """Expected outcome is positive (a positive final frame, or suppressed = no frame)."""
        if self.sid is None or self.nrc is not None:
            return False
        finals = [f for f in self.frames if not (len(f) >= 3 and f[0] == NEGATIVE)]
        if not finals:
            return not self.frames
        return finals[-1][0] == (self.sid + 0x40) & 0xFF


@dataclass
class TestTrace:
    """Result of :func:`trace_test`."""

    __test__ = False  # not a pytest class

    sends: list[SendEvent] = field(default_factory=list)
    speeds_set: list[int] = field(default_factory=list)
    nvm_fault_set: bool = False
    dtc_status_set: bool = False


def _s3_ms(spec: EcuSpec, session: int) -> int:
    sess = spec.get_session(session)
    return sess.timing.s3_ms if sess is not None else 5000


def trace_test(spec: EcuSpec, test: TestCase) -> TestTrace:
    """Walk ``test`` statically (see module docstring)."""
    default = 0x01 if spec.get_session(0x01) is not None else spec.sessions[0].id
    key_to_level = {lvl.key_subfunction: lvl.level for lvl in spec.security_levels}
    out = TestTrace()
    session, unlocked = default, frozenset[int]()
    speed, fault, idle = 0, False, 0
    for i, step in enumerate(test.steps):
        if step.kind == "advance_time":
            idle += step.ms
            continue
        if step.kind == "set_environment":
            if step.vehicle_speed_kph is not None:
                speed = step.vehicle_speed_kph
                out.speeds_set.append(speed)
            if step.nvm_write_fault is not None:
                fault = step.nvm_write_fault
                out.nvm_fault_set = out.nvm_fault_set or step.nvm_write_fault
            continue
        if step.kind == "set_dtc_status":
            out.dtc_status_set = True
            continue
        expired = idle > _s3_ms(spec, session)
        if expired and session != default:
            session, unlocked = default, frozenset()
        event = SendEvent(
            index=i,
            request=step.request_bytes,
            frames=tuple(step.expected_response_bytes),
            session=session,
            unlocked=unlocked,
            vehicle_speed_kph=speed,
            nvm_write_fault=fault,
            idle_ms=idle,
            s3_expired=expired,
        )
        out.sends.append(event)
        idle = 0
        if event.positive and event.subfunction is not None:
            if event.sid == 0x10:
                session, unlocked = event.subfunction, frozenset()
            elif event.sid == 0x11:
                session, unlocked = default, frozenset()
            elif event.sid == 0x27 and event.subfunction in key_to_level:
                unlocked = unlocked | {key_to_level[event.subfunction]}
    return out


def request_did_ids(request: bytes) -> list[int]:
    """DIDs named by a 0x22 (every complete pair) or 0x2E (first pair) request."""
    if not request:
        return []
    if request[0] == 0x22:
        body = request[1:]
        return [int.from_bytes(body[k : k + 2], "big") for k in range(0, len(body) - 1, 2)]
    if request[0] == 0x2E and len(request) >= 3:
        return [int.from_bytes(request[1:3], "big")]
    return []


def request_routine_id(request: bytes) -> int | None:
    """Routine id of a 0x31 request (None if too short or another service)."""
    if len(request) >= 4 and request[0] == 0x31:
        return int.from_bytes(request[2:4], "big")
    return None
