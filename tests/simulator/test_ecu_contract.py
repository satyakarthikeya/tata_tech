"""Direct checks of the simulator against examples from docs/behaviour_contract.md."""

from __future__ import annotations

import pytest

from uds_assistant.protocol.security import compute_key, derive_seed
from uds_assistant.simulator import SimulatedEcu
from uds_assistant.spec.schema import EcuSpec


def h(x: str) -> bytes:
    return bytes.fromhex(x)


@pytest.mark.parametrize(
    ("request_hex", "expected"),
    [
        ("1003", ["5003003201f4"]),
        ("3e00", ["7e00"]),
        ("3e80", []),
        ("3e81", ["7f3e12"]),
        ("2781", ["7f277f"]),  # 0x27 not allowed in default session comes first
        ("1982", ["7f1912"]),
        ("190201", ["5902ff"]),
        ("85", ["7f8511"]),
        ("", []),
        ("2e0100", ["7f2e7f"]),
        ("22f1", ["7f2213"]),
        ("22f186", ["62f18601"]),
        ("14ffffff", ["54"]),
        ("14123456", ["7f1431"]),
        ("1105", ["7f1112"]),
        ("1101", ["5101"]),
    ],
)
def test_default_session_examples(spec: EcuSpec, request_hex: str, expected: list[str]) -> None:
    assert SimulatedEcu(spec).handle(h(request_hex), now_ms=0) == [h(e) for e in expected]


def test_security_lockout_lifecycle(spec: EcuSpec) -> None:
    ecu = SimulatedEcu(spec)
    t = 0
    assert ecu.handle(h("1003"), t) == [h("5003003201f4")]
    assert ecu.handle(h("2781"), t) == [h("7f2712")]
    assert ecu.handle(h("2703"), t) == [h("7f277e")]
    assert ecu.handle(h("270200000000"), t) == [h("7f2724")]
    codes = []
    for _ in range(3):
        seed = ecu.handle(h("2701"), t)[0][2:]
        codes.append(ecu.handle(h("2702") + bytes(4 * [seed[0] ^ 0xFF]), t)[0])
    assert codes == [h("7f2735"), h("7f2735"), h("7f2736")]
    for _ in range(2):  # keep the extended session alive while the delay runs
        t += 4000
        assert ecu.handle(h("2701"), t) == [h("7f2737")]
    t += 2000  # deadline = 0 + 10000 reached
    seed = ecu.handle(h("2701"), t)[0][2:]
    assert seed == derive_seed(1, 3, 4)
    assert ecu.handle(h("270200000000"), t) == [h("7f2736")]  # counter stayed at 3
    t += 4000
    assert ecu.handle(h("2701"), t) == [h("7f2737")]


def test_unlock_write_and_session_relock(spec: EcuSpec) -> None:
    ecu = SimulatedEcu(spec)
    ecu.handle(h("1003"), 0)
    seed = ecu.handle(h("2701"), 0)[0][2:]
    assert ecu.handle(h("2702") + compute_key(seed, 1), 0) == [h("6702")]
    assert ecu.handle(h("2701"), 0) == [h("670100000000")]
    assert ecu.handle(h("2e010065"), 0) == [h("7f2e31")]  # 101 > max 100
    assert ecu.handle(h("2e010050"), 0) == [h("6e0100")]
    ecu.set_nvm_write_fault(True)
    assert ecu.handle(h("2e010051"), 0) == [h("7f2e72")]
    ecu.set_nvm_write_fault(False)
    assert ecu.handle(h("220100"), 0) == [h("62010050")]
    assert ecu.handle(h("1083"), 0) == []  # suppressed, still re-locks
    assert ecu.handle(h("2e010050"), 0) == [h("7f2e33")]


def test_s3_boundary(spec: EcuSpec) -> None:
    ecu = SimulatedEcu(spec)
    ecu.handle(h("1003"), 0)
    assert ecu.handle(h("22f186"), 5000) == [h("62f18603")]
    assert ecu.handle(h("22f186"), 10001) == [h("62f18601")]


def test_routines(spec: EcuSpec) -> None:
    ecu = SimulatedEcu(spec)
    ecu.handle(h("1003"), 0)
    assert ecu.handle(h("31010201"), 0) == [h("7f3133")]
    seed = ecu.handle(h("2701"), 0)[0][2:]
    ecu.handle(h("2702") + compute_key(seed, 1), 0)
    assert ecu.handle(h("31030201"), 0) == [h("7f3124")]
    assert ecu.handle(h("31020201"), 0) == [h("7f3124")]
    assert ecu.handle(h("31010201"), 0) == [h("7101020101")]
    assert ecu.handle(h("31010201"), 0) == [h("7f3124")]
    assert ecu.handle(h("31030201"), 0) == [h("7103020101")]
    assert ecu.handle(h("31020201"), 0) == [h("7102020103")]
    assert ecu.handle(h("3101020107"), 0) == [h("7f3113")]
    ecu.set_vehicle_speed(10)
    assert ecu.handle(h("3101020207"), 0) == [h("7f3122")]
    assert ecu.handle(h("31010203"), 0) == [h("7f3131")]  # programming-only routine
