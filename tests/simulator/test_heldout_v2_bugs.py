"""Held-out v2 bug catalog: every id is implemented, tagged heldout_v2, and changes exact bytes."""

from __future__ import annotations

import pytest

from tests.simulator.test_heldout_bugs import BAD_KEY_X3, UNLOCK_L1, h
from uds_assistant.protocol.security import compute_key, derive_seed
from uds_assistant.simulator import (
    ALL_BUG_IDS,
    DEFAULT_BUG_CATALOG_PATH,
    HELDOUT_BUG_CATALOG_PATH,
    HELDOUT_BUG_IDS,
    HELDOUT_V2_BUG_CATALOG_PATH,
    HELDOUT_V2_BUG_IDS,
    IMPLEMENTED_BUG_IDS,
    SimulatedEcu,
    load_bug_catalog,
)
from uds_assistant.spec.schema import EcuSpec

_KEY0_L1 = compute_key(derive_seed(1, 0, 4), 1)
_PREFIX_KEY = (_KEY0_L1[:2] + bytes([_KEY0_L1[2] ^ 0xFF, _KEY0_L1[3]])).hex()

# Steps: hex request, ("advance", ms), ("speed", kph), ("nvm", bool), ("key", sub).
CASES: dict[str, tuple[list, list[bytes], list[bytes]]] = {
    "session_reentry_keeps_unlock": (
        [*UNLOCK_L1, "1003", "2e010050"],
        [h("7f2e33")],
        [h("6e0100")],
    ),
    "s3_restart_skipped_on_negative_response": (
        ["1003", ("advance", 4000), "1105", ("advance", 4000), "22f186"],
        [h("62f18603")],
        [h("62f18601")],
    ),
    "s3_timeout_resets_lockout_counters": (
        ["1003", *BAD_KEY_X3, ("advance", 6000), "1003", "2701"],
        [h("7f2737")],
        [h("6701") + derive_seed(1, 3, 4)],
    ),
    "ecu_reset_keeps_session": (["1003", "1103", "22f186"], [h("62f18601")], [h("62f18603")]),
    "seed_request_keeps_stale_pending_seed": (
        ["1003", "2701", "2701", ("key", 2)],
        [h("6702")],
        [h("7f2735")],
    ),
    "key_compare_prefix_only": (
        ["1003", "2701", "2702" + _PREFIX_KEY],
        [h("7f2735")],
        [h("6702")],
    ),
    "lockout_counter_pooled_across_levels": (
        ["1003", "2701", "270200000000", "2701", "270200000000", "1002", "2703", "270400000000"],
        [h("7f2735")],
        [h("7f2736")],
    ),
    "nrc_order_range_before_security": (["1003", "2e010165"], [h("7f2e33")], [h("7f2e31")]),
    "nrc_order_nvm_fault_before_group_check": (
        ["1003", ("nvm", True), "14123456"],
        [h("7f1431")],
        [h("7f1472")],
    ),
    "read_dtc_trailing_bytes_accepted": (["190201ff"], [h("7f1913")], [h("5902ff")]),
    "routine_option_record_overlong_accepted": (
        [*UNLOCK_L1, "31010201aa"],
        [h("7f3113")],
        [h("7101020101")],
    ),
    "write_range_upper_bound_exclusive": (
        [*UNLOCK_L1, "2e010064"],
        [h("6e0100")],
        [h("7f2e31")],
    ),
    "multi_did_read_dedups_repeats": (
        ["22010001000100"],
        [h("620100320100320100" + "32")],
        [h("62010032")],
    ),
    "routine_restart_after_stop_blocked": (
        [*UNLOCK_L1, "31010201", "31020201", "31010201"],
        [h("7101020101")],
        [h("7f3124")],
    ),
    "suppressed_seed_request_not_stored": (
        ["1003", "2781", "2702" + _KEY0_L1.hex()],
        [h("6702")],
        [h("7f2724")],
    ),
}


def run(spec: EcuSpec, steps: list, bugs: set[str] | None = None) -> list[list[bytes]]:
    """Run a scenario on a fresh ECU starting at t=0; return every request's responses."""
    ecu = SimulatedEcu(spec, bugs=bugs)
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
        if isinstance(step, tuple) and step[0] == "nvm":
            ecu.set_nvm_write_fault(step[1])
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


def test_catalog_matches_implementation() -> None:
    catalog = load_bug_catalog(HELDOUT_V2_BUG_CATALOG_PATH)
    assert len(catalog.bugs) == 15
    assert set(catalog.ids) == set(HELDOUT_V2_BUG_IDS)
    for bug in catalog.bugs:
        assert bug.heldout_v2 is True
        assert bug.title and bug.description and bug.expected_detection


def test_ids_do_not_collide_with_any_other_catalog() -> None:
    for path in (DEFAULT_BUG_CATALOG_PATH, HELDOUT_BUG_CATALOG_PATH):
        other = load_bug_catalog(path)
        assert not set(other.ids) & set(HELDOUT_V2_BUG_IDS)
        assert all(not b.heldout_v2 for b in other.bugs)
    assert not IMPLEMENTED_BUG_IDS & HELDOUT_V2_BUG_IDS
    assert not HELDOUT_BUG_IDS & HELDOUT_V2_BUG_IDS
    assert HELDOUT_V2_BUG_IDS <= ALL_BUG_IDS


def test_every_bug_has_a_case() -> None:
    assert set(CASES) == set(HELDOUT_V2_BUG_IDS)


@pytest.mark.parametrize("bug_id", sorted(CASES))
def test_bug_changes_exact_bytes(spec: EcuSpec, bug_id: str) -> None:
    """Last response differs between bug OFF and bug ON, with the exact expected bytes."""
    steps, clean_last, buggy_last = CASES[bug_id]
    clean = run(spec, steps)
    buggy = run(spec, steps, {bug_id})
    assert clean[-1] == clean_last
    assert buggy[-1] == buggy_last
    assert clean[-1] != buggy[-1]


@pytest.mark.parametrize("bug_id", sorted(CASES))
def test_bug_toggle_restores_clean(spec: EcuSpec, bug_id: str) -> None:
    """Enabling then disabling a v2 bug leaves no active bugs."""
    ecu = SimulatedEcu(spec, bugs={bug_id})
    assert ecu.active_bugs == frozenset({bug_id})
    ecu.disable_bug(bug_id)
    assert ecu.active_bugs == frozenset()


def test_unknown_bug_still_rejected(spec: EcuSpec) -> None:
    with pytest.raises(ValueError):
        SimulatedEcu(spec).enable_bug("no_such_v2_bug")
