"""Transports: in-process, and ISO-TP over a python-can virtual bus (incl. a udsoncan client)."""

from __future__ import annotations

import itertools
import time
from collections.abc import Iterator

import can
import pytest
import udsoncan
from udsoncan.client import Client
from udsoncan.connections import PythonIsoTpConnection
from udsoncan.exceptions import NegativeResponseException

from uds_assistant.protocol.security import compute_key
from uds_assistant.simulator import (
    EcuCanServer,
    InProcessTransport,
    IsoTpClientTransport,
    SimulatedEcu,
)
from uds_assistant.simulator.transport import (
    ECU_TO_TESTER_ID,
    TESTER_TO_ECU_ID,
    make_isotp_stack,
)
from uds_assistant.spec.schema import EcuSpec

_channel_ids = itertools.count()


def fresh_channel() -> str:
    """A unique virtual-bus channel name so tests never share traffic."""
    return f"uds_sim_test_{next(_channel_ids)}_{time.monotonic_ns()}"


# ----------------------------------------------------------------------------- in-process
def test_in_process_transport(spec: EcuSpec) -> None:
    transport = InProcessTransport(SimulatedEcu(spec))
    assert transport.send(bytes.fromhex("1003"), now_ms=0) == [bytes.fromhex("5003003201f4")]
    assert transport.send(bytes.fromhex("3e80"), now_ms=10) == []
    assert transport.send(b"", now_ms=20) == []


def test_clock_injection(spec: EcuSpec) -> None:
    now = [0]
    ecu = SimulatedEcu(spec, clock=lambda: now[0])
    ecu.handle(bytes.fromhex("1003"))
    now[0] = 5001
    assert ecu.handle(bytes.fromhex("22f186")) == [bytes.fromhex("62f18601")]


def test_reset_state_and_environment(spec: EcuSpec) -> None:
    ecu = SimulatedEcu(spec)
    ecu.handle(bytes.fromhex("1003"), now_ms=0)
    ecu.set_vehicle_speed(300)
    assert ecu.handle(bytes.fromhex("220140"), now_ms=1) == [bytes.fromhex("620140ff")]
    ecu.reset_state()
    assert ecu.session == 0x01
    assert ecu.handle(bytes.fromhex("220140"), now_ms=2) == [bytes.fromhex("620140ff")]


# ----------------------------------------------------------------------------- virtual CAN
@pytest.fixture()
def can_server(spec: EcuSpec) -> Iterator[tuple[EcuCanServer, str]]:
    channel = fresh_channel()
    server = EcuCanServer(SimulatedEcu(spec), channel=channel)
    server.start()
    try:
        yield server, channel
    finally:
        server.stop()
    assert not server.errors


def test_isotp_client_round_trip(can_server: tuple[EcuCanServer, str]) -> None:
    _, channel = can_server
    with IsoTpClientTransport(channel, timeout=2.0) as client:
        assert client.send(bytes.fromhex("1003")) == [bytes.fromhex("5003003201f4")]
        # Multi-frame response (VIN, 20 bytes) exercises ISO-TP segmentation.
        vin = client.send(bytes.fromhex("22f190"))
        assert vin == [bytes.fromhex("62f190") + b"SYNTHETICBM000001"]
        assert client.send(bytes.fromhex("3e80"), timeout=0.3) == []


def test_response_pending_over_can(can_server: tuple[EcuCanServer, str]) -> None:
    _, channel = can_server
    with IsoTpClientTransport(channel, timeout=2.0) as client:
        assert client.send(bytes.fromhex("1002"))[0][:2] == bytes.fromhex("5002")
        seed = client.send(bytes.fromhex("2703"))[0][2:]
        assert client.send(bytes.fromhex("2704") + compute_key(seed, 3)) == [
            bytes.fromhex("6704")
        ]
        assert client.send(bytes.fromhex("31010203")) == [
            bytes.fromhex("7f3178"),
            bytes.fromhex("7101020302"),
        ]


class U8Codec(udsoncan.DidCodec):
    """1-byte unsigned DID value."""

    def encode(self, value: int) -> bytes:  # type: ignore[override]
        return bytes([value])

    def decode(self, data: bytes) -> int:  # type: ignore[override]
        return data[0]

    def __len__(self) -> int:
        return 1


def _udsoncan_config() -> dict:
    config = dict(udsoncan.configs.default_client_config)
    config.update(
        {
            "data_identifiers": {0x0100: U8Codec(), 0xF190: udsoncan.AsciiCodec(17)},
            "request_timeout": 5.0,
            "p2_timeout": 2.0,
            "p2_star_timeout": 5.0,
            "use_server_timing": False,
            "exception_on_negative_response": True,
            "exception_on_invalid_response": True,
            "exception_on_unexpected_response": True,
        }
    )
    return config


@pytest.fixture()
def uds_client(can_server: tuple[EcuCanServer, str]) -> Iterator[Client]:
    _, channel = can_server
    bus = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
    notifier = can.Notifier(bus, [], timeout=0.05)
    stack = make_isotp_stack(bus, notifier, rx_id=ECU_TO_TESTER_ID, tx_id=TESTER_TO_ECU_ID)
    conn = PythonIsoTpConnection(stack)
    try:
        with Client(conn, config=_udsoncan_config()) as client:
            yield client
    finally:
        notifier.stop()
        bus.shutdown()


def test_udsoncan_full_sequence(uds_client: Client) -> None:
    """extended session -> seed -> key -> read 0x0100 -> write 0x50 -> read back."""
    resp = uds_client.change_session(3)
    assert resp.positive
    seed_resp = uds_client.request_seed(1)
    seed = bytes(seed_resp.service_data.seed)
    assert len(seed) == 4
    key_resp = uds_client.send_key(2, compute_key(seed, 1))
    assert key_resp.positive
    before = uds_client.read_data_by_identifier(0x0100)
    assert before.service_data.values[0x0100] == 0x32
    assert uds_client.write_data_by_identifier(0x0100, 0x50).positive
    after = uds_client.read_data_by_identifier(0x0100)
    assert after.service_data.values[0x0100] == 0x50
    vin = uds_client.read_data_by_identifier(0xF190)
    assert vin.service_data.values[0xF190] == "SYNTHETICBM000001"


def test_udsoncan_negative_response(uds_client: Client) -> None:
    """Write in extended session without unlocking -> NegativeResponseException 0x33."""
    uds_client.change_session(3)
    with pytest.raises(NegativeResponseException) as excinfo:
        uds_client.write_data_by_identifier(0x0100, 0x50)
    assert excinfo.value.response.code == 0x33
