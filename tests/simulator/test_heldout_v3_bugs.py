"""Held-out v3 bug catalog: every id is implemented, tagged heldout_v3, and changes exact bytes."""

from __future__ import annotations

import pytest

from tests.simulator.test_heldout_bugs import BAD_KEY_X3, UNLOCK_L1, UNLOCK_L3, h
from uds_assistant.protocol.security import compute_key, derive_seed
from uds_assistant.simulator import (
    ALL_BUG_IDS,
    DEFAULT_BUG_CATALOG_PATH,
    HELDOUT_BUG_CATALOG_PATH,
    HELDOUT_BUG_IDS,
    HELDOUT_V2_BUG_CATALOG_PATH,
    HELDOUT_V2_BUG_IDS,
    HELDOUT_V3_BUG_CATALOG_PATH,
    HELDOUT_V3_BUG_IDS,
    IMPLEMENTED_BUG_IDS,
    SimulatedEcu,
    load_bug_catalog,
)
from uds_assistant.spec.schema import EcuSpec

# Steps: hex request, ("advance", ms), ("speed", kph), ("dtc", code, status), ("key", sub).
CASES: dict[str, tuple[list, list[bytes], list[bytes]]] = {
    "session_switch_keeps_pending_seed": (
        ["1003", "2701", "1003", ("key", 2)],
        [h("7f2724")],
        [h("6702")],
    ),
    "session_response_p2_star_in_ms": (["1003"], [h("5003003201f4")], [h("500300321388")]),
    "failed_key_keeps_pending_seed": (
        ["1003", "2701", "270200000000", ("key", 2)],
        [h("7f2724")],
        [h("6702")],
    ),
    "lockout_expiry_resets_attempt_count": (
        ["1003", *BAD_KEY_X3, ("advance", 10000), "1003", "2701", "270200000000"],
        [h("7f2736")],
        [h("7f2735")],
    ),
    "nrc_order_subfunction_before_length": (["3e0500"], [h("7f3e13")], [h("7f3e12")]),
    "nrc_order_write_range_before_condition": (
        [("speed", 10), *UNLOCK_L3, "2e015005"],
        [h("7f2e22")],
        [h("7f2e31")],
    ),
    "routine_results_trailing_bytes_accepted": (
        [*UNLOCK_L1, "31010201", "31030201ff"],
        [h("7f3113")],
        [h("7103020101")],
    ),
    "read_did_speed_not_clamped": (
        [("speed", 300), "220140"],
        [h("620140ff")],
        [h("6201402c")],
    ),
    "write_stores_value_before_range_rejection": (
        [*UNLOCK_L1, "2e010065", "220100"],
        [h("62010032")],
        [h("62010065")],
    ),
    "routine_stop_reports_completed_status": (
        [*UNLOCK_L1, "31010201", "31020201"],
        [h("7102020103")],
        [h("7102020102")],
    ),
    "dtc_clear_single_clears_neighbour": (
        [("dtc", "B10101", 0x08), ("dtc", "B10205", 0x08), "14b10101", "1902ff"],
        [h("5902ff" + "b1020508")],
        [h("5902ff")],
    ),
    "dtc_read_reports_masked_status": (
        [("dtc", "B10101", 0x2F), "190201"],
        [h("5902ff" + "b101012f")],
        [h("5902ff" + "b1010101")],
    ),
    "ecu_reset_resets_seed_counter": (
        ["1003", "2701", ("key", 2), "1103", "1003", "2701"],
        [h("6701") + derive_seed(1, 1, 4)],
        [h("6701") + derive_seed(1, 0, 4)],
    ),
    "s3_timeout_clears_dtc_status": (
        ["1003", ("dtc", "B10101", 0x08), ("advance", 6000), "1902ff"],
        [h("5902ff" + "b1010108")],
        [h("5902ff")],
    ),
    "suppressed_request_does_not_restart_s3": (
        ["1003", ("advance", 4000), "3e80", ("advance", 4000), "22f186"],
        [h("62f18603")],
        [h("62f18601")],
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
        if isinstance(step, tuple) and step[0] == "dtc":
            ecu.set_dtc_status(step[1], step[2])
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
    catalog = load_bug_catalog(HELDOUT_V3_BUG_CATALOG_PATH)
    assert len(catalog.bugs) == 15
    assert set(catalog.ids) == set(HELDOUT_V3_BUG_IDS)
    for bug in catalog.bugs:
        assert bug.heldout_v3 is True
        assert bug.title and bug.description and bug.expected_detection


def test_ids_do_not_collide_with_any_other_catalog() -> None:
    for path in (DEFAULT_BUG_CATALOG_PATH, HELDOUT_BUG_CATALOG_PATH, HELDOUT_V2_BUG_CATALOG_PATH):
        other = load_bug_catalog(path)
        assert not set(other.ids) & set(HELDOUT_V3_BUG_IDS)
        assert all(not b.heldout_v3 for b in other.bugs)
    assert not IMPLEMENTED_BUG_IDS & HELDOUT_V3_BUG_IDS
    assert not HELDOUT_BUG_IDS & HELDOUT_V3_BUG_IDS
    assert not HELDOUT_V2_BUG_IDS & HELDOUT_V3_BUG_IDS
    assert HELDOUT_V3_BUG_IDS <= ALL_BUG_IDS


def test_every_bug_has_a_case() -> None:
    assert set(CASES) == set(HELDOUT_V3_BUG_IDS)


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
    """Enabling then disabling a v3 bug leaves no active bugs."""
    ecu = SimulatedEcu(spec, bugs={bug_id})
    assert ecu.active_bugs == frozenset({bug_id})
    ecu.disable_bug(bug_id)
    assert ecu.active_bugs == frozenset()


def test_unknown_bug_still_rejected(spec: EcuSpec) -> None:
    with pytest.raises(ValueError):
        SimulatedEcu(spec).enable_bug("no_such_v3_bug")
