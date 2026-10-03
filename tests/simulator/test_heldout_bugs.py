"""Held-out bug catalog: every id is implemented, flagged held-out, and changes exact bytes."""

from __future__ import annotations

import pytest

from uds_assistant.protocol.security import compute_key, derive_seed
from uds_assistant.simulator import (
    HELDOUT_BUG_CATALOG_PATH,
    HELDOUT_BUG_IDS,
    IMPLEMENTED_BUG_IDS,
    SimulatedEcu,
    load_bug_catalog,
)
from uds_assistant.spec.schema import EcuSpec

# Steps: hex request string, ("advance", ms), ("speed", kph),
# or ("key", sub) = send the correct key for the last seed of that level.
UNLOCK_L1 = ["1003", "2701", ("key", 2)]
UNLOCK_L3 = ["1002", "2703", ("key", 4)]
BAD_KEY_X3 = ["2701", "270200000000"] * 3


def h(x: str) -> bytes:
    return bytes.fromhex(x)


# bug id -> (scenario, expected last response bug OFF, expected last response bug ON).
# ``None`` means "checked separately" (seed bytes depend on the seed counter).
CASES: dict[str, tuple[list, list[bytes] | None, list[bytes] | None]] = {
    "routine_state_survives_session_change": (
        [*UNLOCK_L1, "31010201", *UNLOCK_L1, "31030201"],
        [h("7f3124")],
        [h("7103020101")],
    ),
    "failed_attempts_reset_by_seed_request": (
        ["1003", *BAD_KEY_X3],
        [h("7f2736")],
        [h("7f2735")],
    ),
    "seed_returned_while_unlocked": (
        [*UNLOCK_L1, "2701"],
        [h("670100000000")],
        [h("6701") + derive_seed(1, 1, 4)],
    ),
    "nrc_order_condition_before_security": (
        ["1003", ("speed", 30), "3101020207"],
        [h("7f3133")],
        [h("7f3122")],
    ),
    "read_did_odd_length_truncated": (["22f18600"], [h("7f2213")], [h("62f18601")]),
    "read_did_session_restriction_ignored": (["220150"], [h("7f2231")], [h("62015000")]),
    "uint16_did_stored_byte_swapped": (
        [*UNLOCK_L3, "2e01601234", "220160"],
        [h("6201601234")],
        [h("6201603412")],
    ),
    "s3_not_refreshed_by_tester_present": (
        ["1003", ("advance", 4000), "3e00", ("advance", 4000), "22f186"],
        [h("62f18603")],
        [h("62f18601")],
    ),
    "ecu_reset_clears_security_lockout": (
        ["1003", *BAD_KEY_X3, "1101", "1003", "2701"],
        [h("7f2737")],
        [h("6701") + derive_seed(1, 3, 4)],
    ),
    "s3_timeout_reverts_written_dids": (
        [*UNLOCK_L1, "2e010050", ("advance", 6000), "220100"],
        [h("62010050")],
        [h("62010032")],
    ),
    "session_suppress_bit_not_masked": (["1083", "22f186"], [h("62f18603")], [h("62f18601")]),
    "suppress_bit_echoed_in_response": (
        [*UNLOCK_L3, "31810203"],
        [h("7f3178"), h("7101020302")],
        [h("7f3178"), h("7181020302")],
    ),
}


def run(spec: EcuSpec, steps: list, bugs: set[str] | None = None) -> list[list[bytes]]:
    """Run a scenario on a fresh ECU starting at t=0; return every request's responses."""
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


def test_heldout_catalog_matches_implementation() -> None:
    catalog = load_bug_catalog(HELDOUT_BUG_CATALOG_PATH)
    assert len(catalog.bugs) == 12
    assert set(catalog.ids) == set(HELDOUT_BUG_IDS)
    for bug in catalog.bugs:
        assert bug.heldout is True
        assert bug.title and bug.description and bug.expected_detection


def test_heldout_ids_do_not_collide_with_original_catalog() -> None:
    original = load_bug_catalog()
    assert not set(original.ids) & set(HELDOUT_BUG_IDS)
    assert not IMPLEMENTED_BUG_IDS & HELDOUT_BUG_IDS
    assert all(not b.heldout for b in original.bugs)


def test_every_heldout_bug_has_a_case() -> None:
    assert set(CASES) == set(HELDOUT_BUG_IDS)


@pytest.mark.parametrize("bug_id", sorted(CASES))
def test_heldout_bug_changes_exact_bytes(spec: EcuSpec, bug_id: str) -> None:
    """Last response differs between bug OFF and bug ON, with the exact expected bytes."""
    steps, clean_last, buggy_last = CASES[bug_id]
    clean = run(spec, steps)
    buggy = run(spec, steps, {bug_id})
    assert clean[-1] == clean_last
    assert buggy[-1] == buggy_last
    assert clean[-1] != buggy[-1]


@pytest.mark.parametrize("bug_id", sorted(CASES))
def test_heldout_bug_toggle_restores_clean(spec: EcuSpec, bug_id: str) -> None:
    """Enabling then disabling a held-out bug gives the clean responses."""
    ecu = SimulatedEcu(spec, bugs={bug_id})
    assert ecu.active_bugs == frozenset({bug_id})
    ecu.disable_bug(bug_id)
    assert ecu.active_bugs == frozenset()
    steps = CASES[bug_id][0]
    assert run_on(ecu, steps) == run(spec, steps)


def test_session_suppress_bit_not_masked_negative_frame(spec: EcuSpec) -> None:
    """With the bug, `10 83` itself is answered 7F 10 12 instead of silence."""
    assert run(spec, ["1083"])[0] == []
    assert run(spec, ["1083"], {"session_suppress_bit_not_masked"})[0] == [h("7f1012")]


def test_unknown_bug_still_rejected(spec: EcuSpec) -> None:
    ecu = SimulatedEcu(spec)
    with pytest.raises(ValueError):
        ecu.enable_bug("no_such_heldout_bug")
    ecu.enable_bug("static_seed")
    ecu.enable_bug("seed_returned_while_unlocked")
    assert ecu.active_bugs == frozenset({"static_seed", "seed_returned_while_unlocked"})
