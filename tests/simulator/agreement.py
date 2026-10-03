"""Shared machinery for simulator-vs-rules-engine agreement testing.

A *step* is one of:

- ``("req", bytes)``                 raw request
- ``("key", sub, mode)``             sendKey built at run time from the last seed seen
  (mode: ``correct`` / ``wrong`` / ``random:<hex>`` / ``short``)
- ``("advance", ms)``                move both clocks forward
- ``("env", speed, nvm_fault)``      change the environment on both sides
- ``("dtc", code, status)``          inject a DTC status on both sides
- ``("seq", [steps])``               a multi-step macro scenario
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from uds_assistant.protocol.security import compute_key
from uds_assistant.rules import RulesSession
from uds_assistant.rules.state import with_dtc_status
from uds_assistant.simulator import SimulatedEcu
from uds_assistant.spec.schema import EcuSpec

Step = tuple[Any, ...]

SIDS = [0x10, 0x11, 0x14, 0x19, 0x22, 0x27, 0x2E, 0x31, 0x3E]
ODD_SIDS = [0x00, 0x01, 0x23, 0x28, 0x34, 0x50, 0x7F, 0x85, 0xFF]
DIDS = [0xF190, 0xF187, 0xF18C, 0xF186, 0x0100, 0x0101, 0x0110, 0x0111, 0x0120,
        0x0130, 0x0131, 0x0140, 0x0150, 0x0160, 0x1234, 0xFFFF, 0x0000]
RIDS = [0x0201, 0x0202, 0x0203, 0x0204, 0xFF00, 0xFFFF]
DTC_GROUPS = [0xFFFFFF, 0xB10101, 0xB10205, 0xB10310, 0xB10102, 0x000000]
ADVANCES = [0, 1, 10, 50, 1000, 4999, 5000, 5001, 6000, 9999, 10000, 10001, 15000, 30000]
SPEEDS = [0, 0, 0, 1, 50, 255, 300]


@dataclass
class AgreementStats:
    """Counts of compared requests."""

    requests: int = 0
    mismatches: list[str] = field(default_factory=list)
    #: counts of requests that hit the D2/D5/D6/D7 paths (see ``DualRunner._classify``)
    coverage: Counter[str] = field(default_factory=Counter)


def _u16(v: int) -> bytes:
    return (v & 0xFFFF).to_bytes(2, "big")


def random_request(rng: random.Random) -> bytes:
    """A biased random request: mostly well-formed, often subtly wrong."""
    roll = rng.random()
    if roll < 0.04:
        return bytes(rng.randrange(256) for _ in range(rng.randrange(0, 8)))
    sid = rng.choice(ODD_SIDS) if roll < 0.08 else rng.choice(SIDS)
    sup = 0x80 if rng.random() < 0.15 else 0x00
    if sid == 0x10:
        body = [rng.choice([1, 2, 3, 3, 4, 0, 0x7F]) | sup]
    elif sid == 0x11:
        body = [rng.choice([1, 3, 2, 4, 5]) | sup]
    elif sid == 0x14:
        body = list(rng.choice(DTC_GROUPS).to_bytes(3, "big"))
    elif sid == 0x19:
        body = [rng.choice([0x02, 0x02, 0x01, 0x82, 0x82, 0x81, 0x8A, 0x0A])]
        if rng.random() < 0.9:
            body.append(rng.choice([0x00, 0x01, 0x08, 0xFF, rng.randrange(256)]))
    elif sid == 0x22:
        n = rng.choice([1, 1, 2, 2, 3, 4, 6])
        dids = [rng.choice(DIDS) for _ in range(n)]
        if n >= 2 and rng.random() < 0.3:
            dids[rng.randrange(n)] = dids[rng.randrange(n)]  # force a duplicate
        body = [b for d in dids for b in _u16(d)]
    elif sid == 0x27:
        sub = rng.choice([1, 1, 3, 3, 2, 4, 5, 0x81, 0x81, 0x83, 0x82, 0x84, 0x85, 0])
        body = [sub] + ([rng.randrange(256) for _ in range(4)] if sub % 2 == 0 else [])
        if sub & 0x7F in (1, 2, 3, 4) and rng.random() < 0.4 and sub & 0x80 == 0:
            body[0] |= 0x80
    elif sid == 0x2E:
        did = rng.choice(DIDS)
        length = rng.choice([1, 1, 1, 2, 0, 17])
        if rng.random() < 0.5:
            val = [rng.choice([0, 1, 3, 5, 15, 16, 50, 100, 101, 255])]
            val = val + [0] * (length - 1) if length >= 1 else []
        else:
            val = [rng.randrange(256) for _ in range(length)]
        body = list(_u16(did)) + val
    elif sid == 0x31:
        sub = rng.choice([1, 1, 2, 3, 4, 0, 5, 0x7F, rng.randrange(0x80)]) | sup
        opt = [rng.randrange(256) for _ in range(rng.choice([0, 0, 1, 2]))]
        body = [sub] + list(_u16(rng.choice(RIDS))) + opt
    elif sid == 0x3E:
        body = [rng.choice([0, 0, 1]) | sup]
    else:
        body = [rng.randrange(256) for _ in range(rng.randrange(0, 4))]
    if rng.random() < 0.05 and body:
        body = body[:-1]
    elif rng.random() < 0.05:
        body = body + [rng.randrange(256)]
    return bytes([sid] + body)


def _req(hexstr: str) -> Step:
    return ("req", bytes.fromhex(hexstr))


def _macro(rng: random.Random) -> list[Step]:
    """Multi-step scenarios that reach deep states (unlocked, lockout, routines, writes)."""
    kind = rng.randrange(9)
    if kind == 0:  # unlock level 1 in extended session
        return [_req("1003"), _req("2701"), ("key", 2, rng.choice(["correct"] * 4 + ["wrong"]))]
    if kind == 1:  # unlock level 3 in programming session
        return [_req("1002"), _req("2703"), ("key", 4, rng.choice(["correct"] * 4 + ["wrong"]))]
    if kind == 2:  # brute force towards lockout
        sub = rng.choice([1, 3])
        steps: list[Step] = [_req("1003" if sub == 1 else "1002")]
        for _ in range(rng.randrange(1, 6)):
            steps += [("req", bytes([0x27, sub])), ("key", sub + 1, "wrong")]
            if rng.random() < 0.3:
                steps.append(("advance", rng.choice([100, 5000, 9999, 10000, 10001])))
        return steps
    if kind == 3:  # routine traffic
        rid = rng.choice([0x0201, 0x0202, 0x0203])
        steps = []
        for _ in range(rng.randrange(1, 5)):
            sub = rng.choice([1, 1, 2, 3]) | (0x80 if rng.random() < 0.15 else 0)
            opt = b"" if rid == 0x0202 and sub & 0x7F == 1 else b""
            steps.append(("req", bytes([0x31, sub]) + _u16(rid) + opt))
        return steps
    if kind == 4:  # valid-looking writes
        steps = []
        for _ in range(rng.randrange(1, 4)):
            did = rng.choice([0x0100, 0x0101, 0x0120, 0x0130, 0x0131, 0x0150, 0x0160, 0xF190])
            length = 2 if did == 0x0160 else 1
            val = rng.choice([0, 1, 2, 5, 15, 16, 80, 100, 101, 255])
            steps.append(("req", bytes([0x2E]) + _u16(did) + val.to_bytes(length, "big")))
            if rng.random() < 0.5:
                steps.append(("req", bytes([0x22]) + _u16(did)))
        return steps
    if kind == 6:  # keys while the delay runs (D5), then expiry
        steps = [_req("1003")]
        for _ in range(3):
            steps += [_req("2701"), ("key", 2, "wrong")]
        for _ in range(rng.randrange(1, 4)):
            steps.append(("advance", rng.choice([0, 1000, 4999, 5000])))
            steps.append(
                rng.choice(
                    [
                        ("key", 2, "correct"),
                        ("key", 2, "wrong"),
                        ("key", 0x82, "correct"),
                        _req("2701"),
                        _req("2781"),
                        _req("270200000000"),
                    ]
                )
            )
        steps += [
            ("advance", rng.choice([5000, 10000, 10001])),
            _req("2701"),
            ("key", 2, rng.choice(["wrong", "correct"])),
            _req("2701"),
        ]
        return steps
    if kind == 7:  # suppressed seed / key (D7)
        level, session = rng.choice([(1, "1003"), (3, "1002")])
        key_sub = level + 1 + rng.choice([0, 0x80])
        return [
            _req(session),
            ("req", bytes([0x27, level | 0x80])),
            ("key", key_sub, rng.choice(["correct", "correct", "wrong"])),
            ("req", bytes([0x27, level])),
            ("req", bytes([0x22]) + _u16(0xF186)),
            ("req", bytes([0x19, 0x82, rng.randrange(256)])),
        ]
    if kind == 8:  # lenient multi-DID and RoutineControl with odd control types (D6, D2)
        steps = [_req(rng.choice(["1001", "1003"]))]
        for _ in range(rng.randrange(2, 5)):
            dids = [rng.choice(DIDS) for _ in range(rng.randrange(2, 6))]
            steps.append(("req", bytes([0x22]) + b"".join(_u16(d) for d in dids)))
            ctype = rng.choice([0, 4, 5, 0x7F, 0x84, 0x80])
            opt = bytes(rng.choice([0, 0, 1, 2]))
            steps.append(("req", bytes([0x31, ctype]) + _u16(rng.choice(RIDS)) + opt))
        return steps
    # DTC traffic
    return [("req", bytes([0x19, 0x02, rng.randrange(256)])),
            ("req", bytes([0x14]) + rng.choice(DTC_GROUPS).to_bytes(3, "big"))]


def random_step(rng: random.Random) -> Step:
    """A biased random step for sequences (``("seq", [...])`` for multi-step macros)."""
    roll = rng.random()
    if roll < 0.25:
        return ("seq", _macro(rng))
    roll = rng.random()
    if roll < 0.12:
        return ("advance", rng.choice(ADVANCES) if rng.random() < 0.8 else rng.randrange(40000))
    if roll < 0.17:
        return ("env", rng.choice(SPEEDS), rng.random() < 0.25)
    if roll < 0.20:
        return ("dtc", rng.choice(DTC_GROUPS[1:4]), rng.choice([0x01, 0x08, 0x09, 0x2F, 0xFF]))
    if roll < 0.30:
        return (
            "key",
            rng.choice([2, 4, 2, 4, 0x82, 0x84]),
            rng.choice(["correct", "correct", "wrong", "short"]),
        )
    if roll < 0.40:
        return ("req", bytes([0x10, rng.choice([2, 3, 3])]))
    if roll < 0.48:
        return ("req", bytes([0x27, rng.choice([1, 3, 1, 3, 0x81, 0x83])]))
    return ("req", random_request(rng))


class DualRunner:
    """Drives a bug-free SimulatedEcu and a RulesSession in lockstep."""

    def __init__(self, spec: EcuSpec, stats: AgreementStats | None = None) -> None:
        self.ecu = SimulatedEcu(spec)
        self.rules = RulesSession(spec, now_ms=0)
        self.now = 0
        self.stats = stats if stats is not None else AgreementStats()
        self.log: list[str] = []

    def _key_request(self, sub: int, mode: str) -> bytes:
        level = (sub & 0x7F) - 1
        # the seed may have been requested with the response suppressed, so read the
        # simulator's pending seed (a missing/stale one just makes a wrong key)
        seed = self.ecu.mem.pending_seeds.get(level, b"\x00\x00\x00\x00")
        key = compute_key(seed, level)
        if mode == "wrong":
            key = bytes([key[0] ^ 0x01]) + key[1:]
        elif mode == "short":
            key = key[:3]
        return bytes([0x27, sub]) + key

    def step(self, step: Step) -> None:
        """Apply one step; on a request, compare responses and raise on mismatch."""
        kind = step[0]
        if kind == "seq":
            for sub_step in step[1]:
                self.step(sub_step)
            return
        if kind == "advance":
            self.now += int(step[1])
            self.log.append(f"advance {step[1]} -> t={self.now}")
            return
        if kind == "dtc":
            code, status = int(step[1]), int(step[2])
            self.ecu.set_dtc_status(code, status)
            self.rules.state = with_dtc_status(self.rules.state, code, status)
            self.log.append(f"dtc {code:06x} status={status:02x}")
            return
        if kind == "env":
            speed, fault = int(step[1]), bool(step[2])
            self.ecu.set_environment(vehicle_speed_kph=speed, nvm_write_fault=fault)
            self.rules.set_environment(vehicle_speed_kph=speed, nvm_write_fault=fault)
            self.log.append(f"env speed={speed} nvm_fault={fault}")
            return
        request = self._key_request(step[1], step[2]) if kind == "key" else bytes(step[1])
        in_delay = self._key_in_delay(request)
        sim = self.ecu.handle(request, now_ms=self.now)
        ref = self.rules.send(request, now_ms=self.now).responses
        self.stats.requests += 1
        self.log.append(
            f"t={self.now} {request.hex(' ')} -> sim={[r.hex(' ') for r in sim]} "
            f"rules={[r.hex(' ') for r in ref]}"
        )
        if sim != ref:
            msg = "\n".join(self.log[-25:])
            self.stats.mismatches.append(msg)
            raise AssertionError(f"Simulator/rules disagreement:\n{msg}")
        self._classify(request, sim, in_delay)

    def _key_in_delay(self, request: bytes) -> bool:
        """True if ``request`` is a 0x27 key for a level whose delay is running right now."""
        if len(request) < 2 or request[0] != 0x27 or (request[1] & 0x7F) % 2:
            return False
        lock = self.ecu.mem.lockouts.get((request[1] & 0x7F) - 1)
        return bool(lock and lock.deadline_ms is not None and self.now < lock.deadline_ms)

    def _classify(self, req: bytes, resp: list[bytes], in_delay: bool) -> None:
        """Count how often each new (D2/D5/D6/D7) path is exercised."""
        cov = self.stats.coverage
        first = resp[0] if resp else b""
        sub = req[1] if len(req) > 1 else 0
        if req[:1] == b"\x19" and sub & 0x80:
            cov["d7_suppress_0x19_total"] += 1
            if not resp:
                cov["d7_suppress_0x19_silent_positive"] += 1
        if req[:1] == b"\x27" and sub & 0x80:
            kind = "seed" if (sub & 0x7F) % 2 else "key"
            cov[f"d7_suppress_0x27_{kind}_total"] += 1
            if not resp:
                cov[f"d7_suppress_0x27_{kind}_silent_positive"] += 1
            elif first[:1] == b"\x7f":
                cov[f"d7_suppress_0x27_{kind}_negative_sent"] += 1
        if in_delay:
            cov["d5_key_during_delay_total"] += 1
            if first == bytes([0x7F, 0x27, 0x24]):
                cov["d5_key_during_delay_0x24"] += 1
        if req[:1] == b"\x22" and len(req) >= 5:
            requested = [req[i : i + 2] for i in range(1, len(req), 2)]
            if first == bytes([0x7F, 0x22, 0x31]):
                cov["d6_multi_did_all_skipped_0x31"] += 1
            elif first[:1] == b"\x62":
                shown, pos = 0, 1
                while pos < len(first):
                    did = self.ecu.spec.get_did(int.from_bytes(first[pos : pos + 2], "big"))
                    assert did is not None
                    pos += 2 + did.length
                    shown += 1
                duplicates = len(set(requested)) < len(requested)
                if shown < len(requested):
                    cov["d6_multi_did_mixed_good_bad"] += 1
                    if duplicates:
                        cov["d6_multi_did_duplicates_with_skips"] += 1
                elif duplicates:
                    cov["d6_multi_did_duplicates_all_answered"] += 1
            elif first == bytes([0x7F, 0x22, 0x14]):
                cov["d6_multi_did_0x14"] += 1
        if req[:1] == b"\x31" and len(req) >= 4 and (sub & 0x7F) not in (1, 2, 3):
            if self.ecu.spec.get_routine(int.from_bytes(req[2:4], "big")) is None:
                cov["d2_unsupported_type_unknown_routine"] += 1
            if first == bytes([0x7F, 0x31, 0x31]):
                cov["d2_unsupported_type_0x31"] += 1
            elif first == bytes([0x7F, 0x31, 0x12]):
                cov["d2_unsupported_type_0x12"] += 1
            elif first[:1] == b"\x7f":
                cov["d2_unsupported_type_other_nrc"] += 1
