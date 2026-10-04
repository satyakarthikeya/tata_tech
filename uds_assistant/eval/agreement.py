"""Live simulator <-> rules-engine agreement sample for the evaluation report.

A deterministic, seeded random sample of request sequences (with clock advances,
environment changes, DTC injections and computed seed/key handshakes) is fed in
lockstep to a bug-free :class:`SimulatedEcu` and a :class:`RulesSession`. Every
request whose response frames are byte-identical counts as agreed. After a
disagreement the walk is abandoned (the two states may have diverged) and a new
walk starts.
"""

from __future__ import annotations

import random
from typing import Any

from uds_assistant.protocol.security import compute_key
from uds_assistant.rules import RulesSession
from uds_assistant.rules.state import with_dtc_status
from uds_assistant.simulator import SimulatedEcu
from uds_assistant.spec.schema import EcuSpec

DEFAULT_SEED = 20261003
DEFAULT_REQUESTS = 5000
WALK_LENGTH = 60

_SIDS = (0x10, 0x11, 0x14, 0x19, 0x22, 0x27, 0x2E, 0x31, 0x3E)
_ODD_SIDS = (0x00, 0x23, 0x28, 0x34, 0x85, 0xFF)
_ADVANCES = (1, 10, 100, 1000, 4999, 5000, 5001, 9999, 10000, 10001, 20000)
_SPEEDS = (0, 0, 0, 5, 80, 255)
_DTC_GROUPS = (0xFFFFFF, 0xB10101, 0xB10205, 0xB10310, 0x000000)
_STATUSES = (0x01, 0x08, 0x09, 0x2F)


def _u16(v: int) -> bytes:
    return (v & 0xFFFF).to_bytes(2, "big")


class _Sampler:
    def __init__(self, spec: EcuSpec, rng: random.Random) -> None:
        self.rng = rng
        self.dids = [d.id for d in spec.dids] + [0x1234, 0xFFFF]
        self.rids = [r.id for r in spec.routines] + [0xFF00]
        self.levels = [(lv.level, lv.seed_subfunction, lv.key_subfunction)
                       for lv in spec.security_levels]

    def request(self) -> bytes:
        rng = self.rng
        if rng.random() < 0.04:
            return bytes(rng.randrange(256) for _ in range(rng.randrange(0, 6)))
        sid = rng.choice(_ODD_SIDS) if rng.random() < 0.04 else rng.choice(_SIDS)
        sup = 0x80 if rng.random() < 0.12 else 0x00
        body: list[int]
        if sid == 0x10:
            body = [rng.choice([1, 2, 3, 3, 4, 0x7F]) | sup]
        elif sid == 0x11:
            body = [rng.choice([1, 3, 2, 5]) | sup]
        elif sid == 0x14:
            body = list(rng.choice(_DTC_GROUPS).to_bytes(3, "big"))
        elif sid == 0x19:
            body = [rng.choice([0x02, 0x02, 0x01, 0x0A]), rng.randrange(256)]
        elif sid == 0x22:
            body = [b for _ in range(rng.choice([1, 1, 2, 3])) for b in _u16(rng.choice(self.dids))]
        elif sid == 0x27:
            sub = rng.choice([1, 2, 3, 4, 5, 0])
            body = [sub] + ([rng.randrange(256) for _ in range(4)] if sub % 2 == 0 else [])
        elif sid == 0x2E:
            did = rng.choice(self.dids)
            body = list(_u16(did)) + [rng.choice([0, 1, 3, 5, 16, 100, 255])
                                      for _ in range(rng.choice([1, 1, 2, 0]))]
        elif sid == 0x31:
            sub = rng.choice([1, 1, 2, 3, 4]) | sup
            body = [sub] + list(_u16(rng.choice(self.rids))) + [0] * rng.choice([0, 0, 1])
        elif sid == 0x3E:
            body = [rng.choice([0, 0, 1]) | sup]
        else:
            body = [rng.randrange(256) for _ in range(rng.randrange(0, 3))]
        if body and rng.random() < 0.05:
            body = body[:-1]
        return bytes([sid, *body])

    def step(self) -> tuple[Any, ...]:
        rng = self.rng
        roll = rng.random()
        if roll < 0.10:
            return ("advance", rng.choice(_ADVANCES))
        if roll < 0.15:
            return ("env", rng.choice(_SPEEDS), rng.random() < 0.2)
        if roll < 0.18:
            return ("dtc", rng.choice(_DTC_GROUPS[1:4]), rng.choice(_STATUSES))
        if roll < 0.30 and self.levels:
            level, seed_sub, key_sub = rng.choice(self.levels)
            return ("unlock", level, seed_sub, key_sub, rng.random() < 0.75)
        if roll < 0.40:
            return ("req", bytes([0x10, rng.choice([2, 3, 3])]))
        return ("req", self.request())


class _Dual:
    def __init__(self, spec: EcuSpec) -> None:
        self.ecu = SimulatedEcu(spec)
        self.rules = RulesSession(spec, now_ms=0)
        self.now = 0

    def send(self, request: bytes) -> tuple[bool, list[bytes]]:
        sim = self.ecu.handle(request, now_ms=self.now)
        ref = list(self.rules.send(request, now_ms=self.now).responses)
        return sim == ref, sim


def simulator_rules_agreement(
    spec: EcuSpec, n_requests: int = DEFAULT_REQUESTS, seed: int = DEFAULT_SEED
) -> dict[str, Any]:
    """Run the seeded sample until at least ``n_requests`` requests were compared."""
    rng = random.Random(seed)
    sampler = _Sampler(spec, rng)
    total = agreed = walks = 0
    mismatches: list[dict[str, Any]] = []
    while total < n_requests:
        walks += 1
        dual = _Dual(spec)

        def compare(request: bytes, dual: _Dual = dual, walk: int = walks) -> list[bytes] | None:
            """Send to both sides; frames if they agree, else None (and record it)."""
            nonlocal total, agreed
            ok, frames = dual.send(request)
            total += 1
            if ok:
                agreed += 1
                return frames
            if len(mismatches) < 5:
                mismatches.append({"walk": walk, "t_ms": dual.now, "request": request.hex()})
            return None

        for _ in range(WALK_LENGTH):
            step = sampler.step()
            kind = step[0]
            if kind == "advance":
                dual.now += int(step[1])
                continue
            if kind == "env":
                dual.ecu.set_environment(vehicle_speed_kph=step[1], nvm_write_fault=step[2])
                dual.rules.set_environment(vehicle_speed_kph=step[1], nvm_write_fault=step[2])
                continue
            if kind == "dtc":
                dual.ecu.set_dtc_status(step[1], step[2])
                dual.rules.state = with_dtc_status(dual.rules.state, step[1], step[2])
                continue
            if kind == "unlock":
                level, seed_sub, key_sub, correct = step[1], step[2], step[3], step[4]
                frames = compare(bytes([0x27, seed_sub]))
                if frames is None:
                    break
                seed_bytes = frames[0][2:] if frames and frames[0][0] == 0x67 else bytes(4)
                key = compute_key(seed_bytes, level)
                if not correct:
                    key = bytes([key[0] ^ 0x01]) + key[1:]
                if compare(bytes([0x27, key_sub]) + key) is None:
                    break
            elif compare(step[1]) is None:
                break
    return {
        "seed": seed,
        "walks": walks,
        "requests": total,
        "agreed": agreed,
        "rate": round(agreed / total, 4) if total else None,
        "mismatch_examples": mismatches,
    }
