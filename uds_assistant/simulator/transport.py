"""Transports for talking to a :class:`~uds_assistant.simulator.ecu.SimulatedEcu`.

- :class:`InProcessTransport` — direct function call (default; deterministic).
- :class:`EcuCanServer` — runs the ECU behind ISO-TP on a python-can virtual
  bus in a background thread (wall-clock monotonic ms for timing).
- :class:`IsoTpClientTransport` — a small tester-side ISO-TP client for the
  same virtual bus (udsoncan can be used instead; see :func:`make_isotp_stack`).
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Any, Self

import can
import isotp

from uds_assistant.simulator.ecu import SimulatedEcu

DEFAULT_CHANNEL = "uds_sim"
TESTER_TO_ECU_ID = 0x7E0
ECU_TO_TESTER_ID = 0x7E8

ISOTP_PARAMS: dict[str, Any] = {
    "stmin": 0,
    "blocksize": 0,
    "tx_padding": 0x00,
    "rx_flowcontrol_timeout": 2000,
    "rx_consecutive_frame_timeout": 2000,
    "max_frame_size": 4095,
}


def monotonic_ms() -> int:
    """Wall-clock monotonic time in ms (only used by the CAN server)."""
    return time.monotonic_ns() // 1_000_000


def make_isotp_stack(
    bus: can.BusABC, notifier: can.Notifier, rx_id: int, tx_id: int
) -> isotp.NotifierBasedCanStack:
    """Build (but do not start) a normal 11-bit ISO-TP stack on ``bus``."""
    address = isotp.Address(isotp.AddressingMode.Normal_11bits, rxid=rx_id, txid=tx_id)
    return isotp.NotifierBasedCanStack(bus, notifier, address=address, params=dict(ISOTP_PARAMS))


class InProcessTransport:
    """Call the ECU directly; ``now_ms`` defaults to the ECU's own clock handling."""

    def __init__(self, ecu: SimulatedEcu) -> None:
        self.ecu = ecu

    def send(self, request: bytes, now_ms: int | None = None) -> list[bytes]:
        """Send one request and return all response frames."""
        return self.ecu.handle(bytes(request), now_ms)

    def close(self) -> None:
        """Nothing to release (API symmetry with the CAN transports)."""


class _VirtualBusEndpoint:
    """Owns a virtual bus + notifier + ISO-TP stack, with idempotent teardown."""

    def __init__(self, channel: str, interface: str, rx_id: int, tx_id: int) -> None:
        self.bus = can.Bus(interface=interface, channel=channel, receive_own_messages=False)
        self.notifier = can.Notifier(self.bus, [], timeout=0.05)
        self.stack = make_isotp_stack(self.bus, self.notifier, rx_id, tx_id)
        self.stack.start()

    def close(self) -> None:
        for step in (self.stack.stop, self.notifier.stop, self.bus.shutdown):
            with contextlib.suppress(Exception):  # best-effort shutdown
                step()


class EcuCanServer:
    """Serve a :class:`SimulatedEcu` over ISO-TP on a python-can virtual bus.

    Use as a context manager or call :meth:`start` / :meth:`stop`. The ECU's
    responses (e.g. ``7F 31 78`` then the final positive) are sent in order.
    """

    def __init__(
        self,
        ecu: SimulatedEcu,
        channel: str = DEFAULT_CHANNEL,
        *,
        interface: str = "virtual",
        rx_id: int = TESTER_TO_ECU_ID,
        tx_id: int = ECU_TO_TESTER_ID,
    ) -> None:
        self.ecu = ecu
        self.channel = channel
        self.interface = interface
        self.rx_id = rx_id
        self.tx_id = tx_id
        self._endpoint: _VirtualBusEndpoint | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self.errors: list[BaseException] = []

    def start(self) -> Self:
        """Open the bus and start the serving thread; returns once it is ready."""
        if self._thread is not None:
            return self
        self._stop.clear()
        self._ready.clear()
        self._endpoint = _VirtualBusEndpoint(self.channel, self.interface, self.rx_id, self.tx_id)
        self._thread = threading.Thread(target=self._serve, name="EcuCanServer", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            self.stop()
            raise RuntimeError("EcuCanServer thread did not start.")
        return self

    def _serve(self) -> None:
        endpoint = self._endpoint
        assert endpoint is not None
        self._ready.set()
        while not self._stop.is_set():
            try:
                data = endpoint.stack.recv(block=True, timeout=0.05)
                if data is None:
                    continue
                for frame in self.ecu.handle(bytes(data), now_ms=monotonic_ms()):
                    endpoint.stack.send(frame)
            except Exception as exc:  # noqa: BLE001 - keep serving, record for tests
                self.errors.append(exc)

    def stop(self) -> None:
        """Stop the serving thread and release the bus."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._endpoint is not None:
            self._endpoint.close()
            self._endpoint = None

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


class IsoTpClientTransport:
    """Tester-side ISO-TP client on a virtual bus: ``send(request) -> list[bytes]``.

    Collects ``7F xx 78`` (response pending) frames and keeps waiting for the
    final response. A request with no answer (suppressed) returns ``[]`` after
    ``timeout`` seconds.
    """

    def __init__(
        self,
        channel: str = DEFAULT_CHANNEL,
        *,
        interface: str = "virtual",
        rx_id: int = ECU_TO_TESTER_ID,
        tx_id: int = TESTER_TO_ECU_ID,
        timeout: float = 2.0,
    ) -> None:
        self.timeout = timeout
        self._endpoint = _VirtualBusEndpoint(channel, interface, rx_id, tx_id)

    def send(self, request: bytes, timeout: float | None = None) -> list[bytes]:
        """Send ``request`` and return every response frame up to the final one."""
        stack = self._endpoint.stack
        while stack.available():
            stack.recv()
        stack.send(bytes(request))
        frames: list[bytes] = []
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return frames
            data = stack.recv(block=True, timeout=remaining)
            if data is None:
                return frames
            frame = bytes(data)
            frames.append(frame)
            if not (len(frame) == 3 and frame[0] == 0x7F and frame[2] == 0x78):
                return frames
            deadline = time.monotonic() + (self.timeout if timeout is None else timeout)

    def close(self) -> None:
        """Release the bus."""
        self._endpoint.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
