"""udsoncan over a python-can virtual bus against the simulator, run as part of the evaluation.

Sequence: extended session -> requestSeed level 1 -> sendKey (computed) -> read DID
0x0100 -> write 0x50 -> read back, using :class:`udsoncan.client.Client` over
ISO-TP (simulator transport helpers). Any exception or wrong value is a fail with
the error text; the check never raises.
"""

from __future__ import annotations

import contextlib
import time
import traceback
from typing import Any

from uds_assistant.protocol.security import compute_key
from uds_assistant.simulator import EcuCanServer, SimulatedEcu
from uds_assistant.simulator.transport import ECU_TO_TESTER_ID, TESTER_TO_ECU_ID, make_isotp_stack
from uds_assistant.spec.schema import EcuSpec

DID = 0x0100
WRITE_VALUE = 0x50


def _client_config(udsoncan: Any) -> dict[str, Any]:
    class U8Codec(udsoncan.DidCodec):  # type: ignore[misc,name-defined]
        """1-byte unsigned DID value."""

        def encode(self, value: int) -> bytes:  # type: ignore[override]
            return bytes([value])

        def decode(self, data: bytes) -> int:  # type: ignore[override]
            return data[0]

        def __len__(self) -> int:
            return 1

    config = dict(udsoncan.configs.default_client_config)
    config.update({
        "data_identifiers": {DID: U8Codec()},
        "request_timeout": 5.0,
        "p2_timeout": 2.0,
        "p2_star_timeout": 5.0,
        "use_server_timing": False,
        "exception_on_negative_response": True,
        "exception_on_invalid_response": True,
        "exception_on_unexpected_response": True,
    })
    return config


def run_udsoncan_sequence(spec: EcuSpec) -> dict[str, Any]:
    """Run the sequence; returns ``{"status": "pass"|"fail", "steps": [...], "error": ...}``."""
    steps: list[str] = []
    start = time.perf_counter()
    server = None
    bus = notifier = None
    try:
        import can
        import udsoncan
        from udsoncan.client import Client
        from udsoncan.connections import PythonIsoTpConnection

        channel = f"uds_eval_{time.monotonic_ns()}"
        server = EcuCanServer(SimulatedEcu(spec), channel=channel).start()
        bus = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
        notifier = can.Notifier(bus, [], timeout=0.05)
        stack = make_isotp_stack(bus, notifier, rx_id=ECU_TO_TESTER_ID, tx_id=TESTER_TO_ECU_ID)
        with Client(PythonIsoTpConnection(stack), config=_client_config(udsoncan)) as client:
            if not client.change_session(3).positive:
                raise AssertionError("change_session(3) not positive")
            steps.append("10 03 extended session: positive")
            seed = bytes(client.request_seed(1).service_data.seed)
            steps.append(f"27 01 seed: {seed.hex()}")
            if not client.send_key(2, compute_key(seed, 1)).positive:
                raise AssertionError("send_key not positive")
            steps.append("27 02 key: positive (unlocked)")
            before = client.read_data_by_identifier(DID).service_data.values[DID]
            steps.append(f"22 {DID:04X} read: 0x{before:02X}")
            if not client.write_data_by_identifier(DID, WRITE_VALUE).positive:
                raise AssertionError("write not positive")
            steps.append(f"2E {DID:04X} write 0x{WRITE_VALUE:02X}: positive")
            after = client.read_data_by_identifier(DID).service_data.values[DID]
            steps.append(f"22 {DID:04X} read-back: 0x{after:02X}")
            if after != WRITE_VALUE:
                raise AssertionError(f"read-back 0x{after:02X} != written 0x{WRITE_VALUE:02X}")
        if server.errors:
            raise AssertionError(f"server errors: {server.errors[:3]}")
        status, error = "pass", None
    except Exception as exc:  # noqa: BLE001 - any failure is reported, never raised
        status = "fail"
        error = f"{type(exc).__name__}: {exc}".strip()
        tb = traceback.format_exc(limit=2).strip().splitlines()
        steps.append(f"error: {error} ({tb[-1] if tb else ''})")
    finally:
        if notifier is not None:
            with contextlib.suppress(Exception):
                notifier.stop()
        if bus is not None:
            with contextlib.suppress(Exception):
                bus.shutdown()
        if server is not None:
            with contextlib.suppress(Exception):
                server.stop()
    return {
        "status": status,
        "error": error,
        "steps": steps,
        "seconds": round(time.perf_counter() - start, 3),
        "transport": "udsoncan.Client over ISO-TP on python-can virtual bus",
    }
