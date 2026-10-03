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
        ("1982", ["7f1913"]),  # 19 82 without mask byte
        ("198100", ["7f1912"]),
        ("1982ff", []),  # suppressed 19 02 FF
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
    assert ecu.handle(h("2785"), t) == [h("7f2712")]
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


# --------------------------------------------------------------------------------------
# Contract examples for the D2 / D5 / D6 / D7 behaviours
# --------------------------------------------------------------------------------------

def _vin(spec: EcuSpec) -> bytes:
    return SimulatedEcu(spec).handle(h("22f190"), 0)[0][3:]


@pytest.mark.parametrize(
    ("request_hex", "expected"),
    [
        ("3104ffff", "7f3131"),  # bad type, unknown routine
        ("31050203", "7f3131"),  # bad type, routine 0203 not allowed in extended
        ("31040201", "7f3112"),  # bad type, known routine allowed in extended
        ("31000201", "7f3112"),
        ("31800201", "7f3112"),  # suppress bit does not hide a negative
        ("31040201ff", "7f3112"),  # 0x12 before length and security
        ("31030201", "7f3133"),  # type fine: now security (locked) decides
    ],
)
def test_routine_control_unsupported_type_order(
    spec: EcuSpec, request_hex: str, expected: str
) -> None:
    ecu = SimulatedEcu(spec)
    ecu.handle(h("1003"), 0)
    assert ecu.handle(h(request_hex), 0) == [h(expected)]


def _delay_state(spec: EcuSpec) -> SimulatedEcu:
    """Extended session, three wrong keys at t=0: count 3, deadline 10000."""
    ecu = SimulatedEcu(spec)
    ecu.handle(h("1003"), 0)
    for _ in range(3):
        ecu.handle(h("2701"), 0)
        ecu.handle(h("270200000000"), 0)
    assert ecu.handle(h("2701"), 0) == [h("7f2737")]
    return ecu


def test_key_during_delay_is_sequence_error_without_state_change(spec: EcuSpec) -> None:
    ecu = _delay_state(spec)
    assert ecu.handle(h("270200000000"), 1000) == [h("7f2724")]
    assert ecu.handle(h("27029a068f73"), 1000) == [h("7f2724")]
    assert ecu.handle(h("278200000000"), 1000) == [h("7f2724")]
    assert ecu.handle(h("2701"), 5000) == [h("7f2737")]  # deadline not moved
    assert ecu.handle(h("2781"), 5000) == [h("7f2737")]
    seed = ecu.handle(h("2701"), 10000)  # key during delay did not extend it
    assert seed == [h("6701") + derive_seed(1, 3, 4)]
    assert ecu.handle(h("270200000000"), 10000) == [h("7f2736")]  # count still 3
    assert ecu.handle(h("2701"), 10001) == [h("7f2737")]  # delay re-armed from t=10000


def test_suppress_bit_on_security_access(spec: EcuSpec) -> None:
    ecu = SimulatedEcu(spec)
    ecu.handle(h("1003"), 0)
    assert ecu.handle(h("2781"), 0) == []  # seed issued, stored, counter 0 -> 1
    seed = derive_seed(1, 0, 4)
    assert ecu.handle(h("2782") + compute_key(seed, 1), 0) == []  # unlocks, silent
    assert ecu.handle(h("2701"), 0) == [h("670100000000")]  # level 1 now unlocked
    assert ecu.handle(h("2e010050"), 0) == [h("6e0100")]
    assert ecu.handle(h("2785"), 0) == [h("7f2712")]
    assert ecu.handle(h("2783"), 0) == [h("7f277e")]
    assert ecu.handle(h("2782") + bytes(4), 0) == [h("7f2724")]  # no pending seed
    ecu2 = SimulatedEcu(spec)
    ecu2.handle(h("1003"), 0)
    assert ecu2.handle(h("2781"), 0) == []
    assert ecu2.handle(h("2782") + bytes(4), 0) == [h("7f2735")]  # wrong key still reported
    assert ecu2.handle(h("2782"), 0) == [h("7f2713")]
    assert ecu2.handle(h("27810000"), 0) == [h("7f2713")]


def test_suppress_bit_on_every_subfunction_service(spec: EcuSpec) -> None:
    ecu = SimulatedEcu(spec)
    assert ecu.handle(h("1083"), 0) == []
    assert ecu.session == 3
    assert ecu.handle(h("1982ff"), 0) == []
    assert ecu.handle(h("3e80"), 0) == []
    assert ecu.handle(h("31810201"), 0) == [h("7f3133")]  # negatives are sent
    assert ecu.handle(h("1181"), 0) == []
    assert ecu.session == 1


def test_routine_suppress_and_long_running_final_response(spec: EcuSpec) -> None:
    ecu = SimulatedEcu(spec)
    ecu.handle(h("1003"), 0)
    seed = ecu.handle(h("2701"), 0)[0][2:]
    ecu.handle(h("2702") + compute_key(seed, 1), 0)
    assert ecu.handle(h("31810201"), 0) == []
    assert ecu.handle(h("31030201"), 0) == [h("7103020101")]  # RUNNING
    ecu.handle(h("1002"), 0)
    seed = ecu.handle(h("2703"), 0)[0][2:]
    ecu.handle(h("2704") + compute_key(seed, 3), 0)
    assert ecu.handle(h("31810203"), 0) == [h("7f3178"), h("7101020302")]
    assert ecu.handle(h("31030203"), 0) == [h("7103020302")]


def test_multi_did_lenient(spec: EcuSpec) -> None:
    vin = _vin(spec)
    ecu = SimulatedEcu(spec)

    def r(x: str) -> list[bytes]:
        return ecu.handle(h(x), 0)

    assert r("22f1901234") == [h("62f190") + vin]
    assert r("221234f186") == [h("62f18601")]
    assert r("2212345678") == [h("7f2231")]
    assert r("2212341234") == [h("7f2231")]
    assert r("220150") == [h("7f2231")]
    assert r("220150f186") == [h("62f18601")]
    assert r("2212340150") == [h("7f2231")]
    assert r("220100123401000150") == [h("62010032010032")]
    assert r("220160ffff0100") == [h("6201600001010032")]
    ecu.handle(h("1003"), 0)
    assert r("2201501234") == [h("62015000")]


def test_multi_did_response_length_counts_answered_only(spec: EcuSpec) -> None:
    vin = _vin(spec)
    ecu = SimulatedEcu(spec)
    assert ecu.handle(h("22" + "f190" * 216), 0) == [h("7f2214")]
    assert ecu.handle(h("22" + "f190" * 215 + "1234"), 0) == [h("62") + (h("f190") + vin) * 215]
    assert ecu.handle(h("221234" + "f190" * 216), 0) == [h("7f2214")]
