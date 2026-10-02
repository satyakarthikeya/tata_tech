"""The stateful simulated ECU.

Implemented independently of the rules engine, from ``docs/behaviour_contract.md``
and the spec YAML. It must never import :mod:`uds_assistant.rules` (enforced by
``tests/simulator/test_independence.py``).

Structure: a pre-processing step (clock: S3 timeout, lockout expiry), a generic
gate shared by all services (supported / session / length / subfunction), and a
dispatch table of per-service handler objects (:mod:`.services`). Negative
outcomes travel as :class:`~.services.Reject` exceptions.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable

from uds_assistant.simulator import bugs as B
from uds_assistant.simulator.memory import DEFAULT_SESSION, EcuMemory, dtc_number
from uds_assistant.simulator.services import (
    NRC_BAD_LENGTH,
    NRC_GENERAL_REJECT,
    NRC_OUT_OF_RANGE,
    NRC_SERVICE_NOT_SUPPORTED,
    NRC_SERVICE_WRONG_SESSION,
    NRC_SUBFUNCTION_NOT_SUPPORTED,
    Outcome,
    Reject,
    ServiceHandler,
    build_handler_table,
)
from uds_assistant.spec.schema import EcuSpec

Clock = Callable[[], int]


class SimulatedEcu:
    """A simulated ECU that answers raw UDS requests with raw UDS responses.

    ``bugs`` is a set of bug ids (see :mod:`uds_assistant.simulator.bugs`) to
    inject. ``clock`` (optional) returns the current time in ms and is used when
    :meth:`handle` is called without ``now_ms``; without a clock the ECU keeps
    an internal time that only moves via :meth:`advance` or explicit ``now_ms``.
    """

    def __init__(
        self,
        spec: EcuSpec,
        bugs: Iterable[str] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.spec = spec
        self._clock = clock
        self._bugs: set[str] = set()
        for bug_id in bugs or ():
            self.enable_bug(bug_id)
        self._handlers: dict[int, ServiceHandler] = build_handler_table()
        self._supported_sids = {sid for s in spec.sessions for sid in s.allowed_services}
        self._lock = threading.RLock()
        self.now_ms = 0
        self.mem = EcuMemory.power_on(spec)

    # ----------------------------------------------------------------- bugs
    def bug(self, bug_id: str) -> bool:
        """True if ``bug_id`` is injected."""
        return bug_id in self._bugs

    def enable_bug(self, bug_id: str) -> None:
        """Inject a bug by id; raises ``ValueError`` for unknown ids."""
        if bug_id not in B.IMPLEMENTED_BUG_IDS:
            raise ValueError(f"Unknown bug id {bug_id!r}.")
        self._bugs.add(bug_id)

    def disable_bug(self, bug_id: str) -> None:
        """Remove an injected bug (no-op if not active)."""
        self._bugs.discard(bug_id)

    @property
    def active_bugs(self) -> frozenset[str]:
        """Currently injected bug ids."""
        return frozenset(self._bugs)

    # ---------------------------------------------------------- environment
    def set_vehicle_speed(self, kph: int) -> None:
        """Set the simulated vehicle speed (km/h, >= 0)."""
        if kph < 0:
            raise ValueError("Vehicle speed must be >= 0.")
        with self._lock:
            self.mem.vehicle_speed_kph = kph

    def set_nvm_write_fault(self, active: bool) -> None:
        """Enable/disable the injected NVM write fault (NRC 0x72 on writes/clears)."""
        with self._lock:
            self.mem.nvm_write_fault = active

    def set_environment(
        self, *, vehicle_speed_kph: int | None = None, nvm_write_fault: bool | None = None
    ) -> None:
        """Convenience setter for both environment inputs."""
        if vehicle_speed_kph is not None:
            self.set_vehicle_speed(vehicle_speed_kph)
        if nvm_write_fault is not None:
            self.set_nvm_write_fault(nvm_write_fault)

    def set_dtc_status(self, code: int | str, status: int) -> None:
        """Inject a DTC status byte (e.g. to simulate a detected fault)."""
        number = dtc_number(code) if isinstance(code, str) else code
        with self._lock:
            if number not in self.mem.dtc_status:
                raise ValueError(f"Unknown DTC {number:#08x}.")
            self.mem.dtc_status[number] = status & 0xFF

    def reset_state(self) -> None:
        """Return to the power-on state (environment and injected bugs are kept)."""
        with self._lock:
            speed, fault = self.mem.vehicle_speed_kph, self.mem.nvm_write_fault
            self.mem = EcuMemory.power_on(self.spec)
            self.mem.vehicle_speed_kph, self.mem.nvm_write_fault = speed, fault

    def advance(self, delta_ms: int) -> None:
        """Move the internal clock forward (used when no ``now_ms``/clock is given)."""
        self.now_ms += delta_ms

    @property
    def session(self) -> int:
        """Currently active diagnostic session."""
        return self.mem.session

    # ------------------------------------------------------------- handling
    def handle(self, request: bytes, now_ms: int | None = None) -> list[bytes]:
        """Process one request and return the frames the ECU sends (possibly none)."""
        with self._lock:
            if now_ms is not None:
                self.now_ms = now_ms
            elif self._clock is not None:
                self.now_ms = self._clock()
            req = bytes(request)
            self._tick()
            if not req:
                return []
            self.mem.last_request_ms = self.now_ms
            return self._respond(req)

    def _tick(self) -> None:
        """Apply time-driven transitions: S3 session timeout, then lockout expiry."""
        mem = self.mem
        if (
            mem.session != DEFAULT_SESSION
            and mem.last_request_ms is not None
            and not self.bug(B.S3_TIMEOUT_NEVER_FIRES)
        ):
            session = self.spec.get_session(mem.session)
            s3 = session.timing.s3_ms if session is not None else 0
            idle = self.now_ms - mem.last_request_ms
            expired = idle >= s3 if self.bug(B.S3_TIMEOUT_OFF_BY_ONE) else idle > s3
            if expired:
                mem.drop_volatile(DEFAULT_SESSION)
        if not self.bug(B.LOCKOUT_DELAY_NEVER_EXPIRES):
            for lock in mem.lockouts.values():
                if lock.deadline_ms is not None and self.now_ms >= lock.deadline_ms:
                    lock.deadline_ms = None

    def _respond(self, req: bytes) -> list[bytes]:
        sid = req[0]
        handler = self._handlers.get(sid)
        suppress = bool(
            handler is not None and handler.suppress_bit and len(req) >= 2 and req[1] & 0x80
        )
        try:
            outcome = self._run(handler, sid, req, suppress)
        except Reject as rej:
            if suppress and self.bug(B.NEGATIVE_RESPONSE_SUPPRESSED):
                return []
            return [bytes([0x7F, sid, rej.nrc])]
        if suppress and outcome.suppressible and not self.bug(B.SUPPRESS_BIT_IGNORED):
            return []
        return list(outcome.frames)

    def _run(
        self, handler: ServiceHandler | None, sid: int, req: bytes, suppress: bool
    ) -> Outcome:
        if (
            self.bug(B.NRC_ORDER_DID_BEFORE_SESSION)
            and sid in (0x22, 0x2E)
            and len(req) >= 3
            and self.spec.get_did(int.from_bytes(req[1:3], "big")) is None
        ):
            raise Reject(NRC_OUT_OF_RANGE)
        if handler is None or sid not in self._supported_sids:
            raise Reject(NRC_SERVICE_NOT_SUPPORTED)
        session = self.spec.get_session(self.mem.session)
        if session is None or sid not in session.allowed_services:
            raise Reject(NRC_SERVICE_WRONG_SESSION)
        if not handler.length_ok(req):
            raise Reject(NRC_BAD_LENGTH)
        sub: int | None = None
        if handler.uses_subfunction:
            sub = req[1] & 0x7F if handler.suppress_bit else req[1]
            if sub not in handler.subfunctions(self):
                bad = self.bug(B.GENERAL_REJECT_INSTEAD_OF_0X12)
                raise Reject(NRC_GENERAL_REJECT if bad else NRC_SUBFUNCTION_NOT_SUPPORTED)
            handler.check_subfunction_session(self, sub)
            if not handler.subfunction_length_ok(self, sub, req):
                raise Reject(NRC_BAD_LENGTH)
        return handler.execute(self, req, sub)
