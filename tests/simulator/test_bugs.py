"""Bug catalog: every catalog id is implemented and observably changes behaviour."""

from __future__ import annotations

import pytest

from uds_assistant.protocol.security import compute_key
from uds_assistant.simulator import IMPLEMENTED_BUG_IDS, SimulatedEcu, load_bug_catalog
from uds_assistant.spec.schema import EcuSpec

# Each scenario is a list of steps: hex request string, ("advance", ms), ("speed", kph),
# or ("key", sub) = send the correct key for the last seed of that level.
UNLOCK_L1 = ["1003", "2701", ("key", 2)]
UNLOCK_L3 = ["1002", "2703", ("key", 4)]

SCENARIOS: dict[str, list] = {
    "nrc_order_did_before_session": ["2e123401"],
    "nrc_order_security_before_length": ["1003", "2e01005000"],
    "general_reject_instead_of_0x12": ["1005"],
    "security_not_reset_on_session_change": [*UNLOCK_L1, "1003", "2e010050"],
    "s3_timeout_never_fires": ["1003", ("advance", 6000), "22f186"],
    "s3_timeout_off_by_one": ["1003", ("advance", 5000), "22f186"],
    "lockout_after_extra_attempt": [
        "1003", "2701", "270200000000", "2701", "270200000000", "2701", "270200000000",
    ],
    "lockout_delay_ignored": [
        "1003", "2701", "270200000000", "2701", "270200000000", "2701", "270200000000", "2701",
    ],
    "lockout_delay_never_expires": [
        "1003", "2701", "270200000000", "2701", "270200000000", "2701", "270200000000",
        ("advance", 4000), "3e00", ("advance", 4000), "3e00", ("advance", 2001), "2701",
    ],
    "accepts_any_key": ["1003", "2701", "270200000000"],
    "seed_not_consumed": [*UNLOCK_L1, ("key", 2)],
    "static_seed": ["1003", "2701", "2701"],
    "write_ignores_value_range": [*UNLOCK_L1, "2e0100ff", "220100"],
    "readonly_did_writable": ["1003", "2e011000", "220110"],
    "write_length_off_by_one": [*UNLOCK_L1, "2e01000000"],
    "write_positive_sid_wrong": [*UNLOCK_L1, "2e010050"],
    "session_response_missing_timing": ["1003"],
    "suppress_bit_ignored": ["3e80"],
    "negative_response_suppressed": ["3e81"],
    "routine_stop_without_start": [*UNLOCK_L1, "31020201"],
    "condition_ignored": [*UNLOCK_L1, ("speed", 30), "3101020207"],
    "dtc_clear_ignores_group": ["14123456"],
    "dtc_clear_noop": [("dtc", 0xB10101, 0x09), "1902ff", "14ffffff", "1902ff"],
    "multi_did_read_first_only": ["22f1860100"],
    "missing_response_pending": [*UNLOCK_L3, "31010203"],
    "dtc_read_ignores_mask": ["190201"],
}


def run(spec: EcuSpec, steps: list, bugs: set[str] | None = None) -> list[list[bytes]]:
    """Run a scenario on a fresh ECU; return every request's response list."""
    return run_on(SimulatedEcu(spec, bugs=bugs), steps)


def run_on(ecu: SimulatedEcu, steps: list) -> list[list[bytes]]:
    """Run a scenario on ``ecu`` starting at t=0."""
    now = 0
    seeds: dict[int, bytes] = {}
    out: list[list[bytes]] = []
    for step in steps:
        if isinstance(step, tuple) and step[0] == "advance":
            now += step[1]
            continue
        if isinstance(step, tuple) and step[0] == "dtc":
            ecu.set_dtc_status(step[1], step[2])
            continue
        if isinstance(step, tuple) and step[0] == "speed":
            ecu.set_vehicle_speed(step[1])
            continue
        if isinstance(step, tuple) and step[0] == "key":
            sub = step[1]
            req = bytes([0x27, sub]) + compute_key(seeds.get(sub - 1, bytes(4)), sub - 1)
        else:
            req = bytes.fromhex(step)
        resp = ecu.handle(req, now_ms=now)
        for frame in resp:
            if frame[:1] == b"\x67" and frame[1] % 2 == 1:
                seeds[frame[1]] = frame[2:]
        out.append(resp)
    return out


def test_catalog_loads_with_enough_bugs() -> None:
    catalog = load_bug_catalog()
    assert len(catalog.bugs) >= 15
    for bug in catalog.bugs:
        assert bug.title and bug.description and bug.expected_detection


def test_catalog_matches_implementation() -> None:
    assert set(load_bug_catalog().ids) == set(IMPLEMENTED_BUG_IDS)


def test_every_bug_has_a_scenario() -> None:
    assert set(SCENARIOS) == set(IMPLEMENTED_BUG_IDS)


@pytest.mark.parametrize("bug_id", sorted(SCENARIOS))
def test_bug_changes_behaviour(spec: EcuSpec, bug_id: str) -> None:
    """Bug-on output differs from bug-off output for the dedicated scenario."""
    clean = run(spec, SCENARIOS[bug_id])
    buggy = run(spec, SCENARIOS[bug_id], {bug_id})
    assert clean != buggy, f"{bug_id} did not change behaviour"


@pytest.mark.parametrize("bug_id", sorted(SCENARIOS))
def test_disabling_bug_restores_clean_behaviour(spec: EcuSpec, bug_id: str) -> None:
    """Enabling then disabling a bug gives exactly the clean responses."""
    clean = run(spec, SCENARIOS[bug_id])
    ecu = SimulatedEcu(spec, bugs={bug_id})
    ecu.disable_bug(bug_id)
    assert ecu.active_bugs == frozenset()
    # Re-run via a fresh ECU built with no bugs vs. this toggled one.
    toggled = run_on(ecu, SCENARIOS[bug_id])
    assert toggled == clean


def test_specific_bug_outputs(spec: EcuSpec) -> None:
    """Spot-check exact faulty bytes for a few bugs."""
    assert run(spec, ["2e123401"], {"nrc_order_did_before_session"})[0] == [bytes.fromhex("7f2e31")]
    assert run(spec, ["2e123401"])[0] == [bytes.fromhex("7f2e7f")]
    assert run(spec, ["1005"], {"general_reject_instead_of_0x12"})[0] == [bytes.fromhex("7f1010")]
    assert run(spec, ["1003"], {"session_response_missing_timing"})[0] == [bytes.fromhex("5003")]
    assert run(spec, [*UNLOCK_L3, "31010203"], {"missing_response_pending"})[-1] == [
        bytes.fromhex("7101020302")
    ]
    assert run(spec, [*UNLOCK_L3, "31010203"])[-1] == [
        bytes.fromhex("7f3178"),
        bytes.fromhex("7101020302"),
    ]


def test_unknown_bug_rejected(spec: EcuSpec) -> None:
    ecu = SimulatedEcu(spec)
    with pytest.raises(ValueError):
        ecu.enable_bug("no_such_bug")
    ecu.enable_bug("static_seed")
    assert ecu.active_bugs == frozenset({"static_seed"})
