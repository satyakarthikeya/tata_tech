"""Shared helpers and a tiny setup DSL for rules-engine tests."""

from __future__ import annotations

from pathlib import Path

from uds_assistant.protocol.security import compute_key
from uds_assistant.rules.engine import RulesSession
from uds_assistant.rules.state import with_dtc_status
from uds_assistant.spec.schema import EcuSpec, load_spec

SPEC_PATH = Path(__file__).resolve().parents[2] / "data" / "bcm_spec.yaml"
_SPEC = load_spec(SPEC_PATH)

#: security level -> (seed subfunction, key subfunction)
_LEVEL_SUBS = {1: (0x01, 0x02), 3: (0x03, 0x04)}


def bcm_spec() -> EcuSpec:
    """The synthetic BCM spec (loaded once per test run)."""
    return _SPEC


def hx(text: str) -> bytes:
    """Parse a space-separated hex string."""
    return bytes.fromhex(text)


def unlock(session: RulesSession, level: int) -> None:
    """Request a seed and send the correct key for ``level``; assert success."""
    seed_sub, key_sub = _LEVEL_SUBS[level]
    seed_resp = session.send(bytes([0x27, seed_sub])).final_response
    assert seed_resp is not None and seed_resp[:2] == bytes([0x67, seed_sub]), seed_resp
    key = compute_key(seed_resp[2:], level)
    resp = session.send(bytes([0x27, key_sub]) + key).final_response
    assert resp == bytes([0x67, key_sub]), resp


def bad_key(session: RulesSession, level: int) -> bytes | None:
    """Request a seed then send a guaranteed-wrong key; return the key response."""
    seed_sub, key_sub = _LEVEL_SUBS[level]
    seed_resp = session.send(bytes([0x27, seed_sub])).final_response
    assert seed_resp is not None and seed_resp[0] == 0x67, seed_resp
    wrong = bytes(b ^ 0xFF for b in compute_key(seed_resp[2:], level))
    return session.send(bytes([0x27, key_sub]) + wrong).final_response


def run_setup(session: RulesSession, steps: list[str]) -> None:
    """Execute setup tokens.

    Tokens: ``ext``/``prog`` (session change), ``unlockN``, ``badkeyN``,
    ``speed=K``, ``nvm_fault``, ``dtc:CODE=SS``, ``t=MS`` (set clock),
    ``+MS`` (advance clock), or a hex request to send.
    """
    for step in steps:
        if step == "ext":
            assert session.send("1003").final_response is not None
        elif step == "prog":
            assert session.send("1002").final_response is not None
        elif step.startswith("unlock"):
            unlock(session, int(step[len("unlock") :]))
        elif step.startswith("badkey"):
            bad_key(session, int(step[len("badkey") :]))
        elif step.startswith("speed="):
            session.set_environment(vehicle_speed_kph=int(step.split("=")[1]))
        elif step == "nvm_fault":
            session.set_environment(nvm_write_fault=True)
        elif step.startswith("dtc:"):
            code, status = step[4:].split("=")
            session.state = with_dtc_status(session.state, int(code, 16), int(status, 16))
        elif step.startswith("t="):
            session.now_ms = int(step[2:])
        elif step.startswith("+"):
            session.advance(int(step[1:]))
        else:
            session.send(hx(step))
