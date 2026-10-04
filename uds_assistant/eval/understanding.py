"""Requirement understanding: score pipeline output on the labelled natural requirements.

Input labels: ``data/requirements_natural.csv`` (splits ``test`` / ``dev``) and
``data/requirements_natural_v2.csv`` (split ``test2``) and ``data/requirements_natural_v3.csv``
(split ``test3``), all with the same schema; see ``data/requirements_natural.md`` for the label
semantics.
For each requirement the agent pipeline produced a :class:`ParsedRequirement` and
a list of generated tests; this module turns both into comparable sets and scores
them. Every function here is pure; definitions are in :data:`UNDERSTANDING_DEFINITIONS`.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from uds_assistant.eval.breakdown import by_kind
from uds_assistant.eval.trace import request_did_ids, request_routine_id, trace_test
from uds_assistant.llm.base import ParsedRequirement
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.model import TestCase

Ident = tuple[str, int]
"""A typed identifier: ``("service", 0x22)``, ``("did", 0xF190)`` or ``("routine", 0x0201)``."""

SPLITS = ("test", "dev", "test2", "test3", "all")
PRECONDITIONS = (
    "default_session", "extended_session", "programming_session", "security_level_1",
    "security_level_3", "vehicle_stationary", "vehicle_moving", "nvm_fault", "dtc_status_set",
    "routine_started", "s3_elapsed", "lockout_active",
)

PRECONDITION_MAPPING: dict[str, str] = {
    "default_session": "a request other than 0x10 is sent while the tracked session is the "
    "default session (no session change before it, or after a reset / S3 timeout), or a "
    "positive 10 01",
    "extended_session": "a 0x10 request with sub-function 0x03 (suppress bit masked) whose "
    "expected outcome is positive",
    "programming_session": "a 0x10 request with sub-function 0x02 whose expected outcome is "
    "positive",
    "security_level_N": "a sendKey (0x27, the level's key sub-function from the spec) whose "
    "expected outcome is positive; level 0x01 -> security_level_1, 0x03 -> security_level_3",
    "vehicle_moving": "a set_environment step with vehicle_speed_kph > 0",
    "vehicle_stationary": "a set_environment step with vehicle_speed_kph == 0, or a positive "
    "0x2E write / 0x31 start of a DID / routine whose spec conditions require "
    "vehicle_stationary",
    "nvm_fault": "a set_environment step with nvm_write_fault = true",
    "dtc_status_set": "a set_dtc_status step",
    "routine_started": "a positive 0x31 startRoutine (sub-function 0x01) followed by at least "
    "one later send step",
    "s3_elapsed": "clock advanced by more than the active session's S3 time between two send "
    "steps",
    "lockout_active": "an expected 7F 27 36 (exceededNumberOfAttempts) or 7F 27 37 "
    "(requiredTimeDelayNotExpired) response",
}

UNDERSTANDING_DEFINITIONS: dict[str, str] = {
    "target_identification": (
        "Label set = target_services U target_dids U target_routines (typed, so service 0x22 "
        "and DID 0x0022 differ). Two predicted sets: (a) 'parsed' = services U dids U routines "
        "of the ParsedRequirement returned by the pipeline; (b) 'exercised' = every SID of "
        "every send step in the requirement's generated tests, every DID named by a 0x22 "
        "(all complete pairs) or 0x2E (first pair) request, and every routine id of a 0x31 "
        "request. Exact match = predicted set equals label set; for a requirement with an "
        "empty label set (NAT-020, unsupported) exact match additionally requires zero "
        "generated tests. Micro precision / recall / F1 sum TP / FP / FN over requirements."
    ),
    "category_recall": (
        "|required_categories n categories of the requirement's generated tests| / "
        "|required_categories|. Micro = summed numerators / summed denominators; macro = mean "
        "over requirements with >= 1 required category (NAT-020 has none and is excluded)."
    ),
    "precondition_recall": (
        "|required_preconditions n preconditions established by >= 1 generated test| / "
        "|required_preconditions|, `none` skipped (requirements whose label is `none` are "
        "excluded). 'Established' is derived statically from each test's concrete steps and "
        "oracle-expected responses (mapping below). Micro and macro as for categories."
    ),
    "fallback": (
        "A requirement counts as fallback / produced-nothing if the pipeline status is not "
        "'completed', or the parsed requirement has no services, DIDs or routines, or it kept "
        "zero tests. Reported with the list of ids (for NAT-020 producing nothing is the "
        "correct outcome)."
    ),
}


class NaturalRequirement(BaseModel):
    """One labelled row of ``requirements_natural.csv``."""

    id: str
    text: str
    split: str
    target_services: list[int] = Field(default_factory=list)
    target_dids: list[int] = Field(default_factory=list)
    target_routines: list[int] = Field(default_factory=list)
    required_categories: list[str] = Field(default_factory=list)
    required_preconditions: list[str] = Field(default_factory=list)
    ambiguous: bool = False

    @property
    def target_set(self) -> set[Ident]:
        """Typed label identifiers."""
        return (
            {("service", s) for s in self.target_services}
            | {("did", d) for d in self.target_dids}
            | {("routine", r) for r in self.target_routines}
        )


def _split_tokens(raw: str | None) -> list[str]:
    return [t.strip() for t in (raw or "").split(";") if t.strip()]


def load_natural_requirements(path: Path) -> list[NaturalRequirement]:
    """Read a labelled natural requirements CSV (v1, v2 or v3: same schema, any ``split``)."""
    with path.open(encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("id")]
    return [
        NaturalRequirement(
            id=r["id"],
            text=r["text"],
            split=r["split"].strip(),
            target_services=[int(x, 16) for x in _split_tokens(r["target_services"])],
            target_dids=[int(x, 16) for x in _split_tokens(r["target_dids"])],
            target_routines=[int(x, 16) for x in _split_tokens(r["target_routines"])],
            required_categories=_split_tokens(r["required_categories"]),
            required_preconditions=[
                p for p in _split_tokens(r["required_preconditions"]) if p != "none"
            ],
            ambiguous=r.get("ambiguous", "").strip().lower() == "true",
        )
        for r in rows
    ]


# ------------------------------------------------------------------------- predicted sets


def parsed_targets(parsed: ParsedRequirement | None) -> set[Ident]:
    """Typed identifiers named by the parsed requirement."""
    if parsed is None:
        return set()
    return (
        {("service", int(s, 16)) for s in parsed.services}
        | {("did", int(d, 16)) for d in parsed.dids}
        | {("routine", int(r, 16)) for r in parsed.routines}
    )


def exercised_targets(tests: Iterable[TestCase]) -> set[Ident]:
    """Typed identifiers actually sent by the tests (see definitions)."""
    out: set[Ident] = set()
    for test in tests:
        for step in test.steps:
            if step.kind != "send":
                continue
            req = step.request_bytes
            if not req:
                continue
            out.add(("service", req[0]))
            out.update(("did", d) for d in request_did_ids(req))
            rid = request_routine_id(req)
            if rid is not None:
                out.add(("routine", rid))
    return out


def established_preconditions(spec: EcuSpec, test: TestCase) -> set[str]:
    """Preconditions a test establishes, derived from its steps (:data:`PRECONDITION_MAPPING`)."""
    tr = trace_test(spec, test)
    default = 0x01 if spec.get_session(0x01) is not None else spec.sessions[0].id
    key_to_level = {lvl.key_subfunction: lvl.level for lvl in spec.security_levels}
    out: set[str] = set()
    if any(s > 0 for s in tr.speeds_set):
        out.add("vehicle_moving")
    if any(s == 0 for s in tr.speeds_set):
        out.add("vehicle_stationary")
    if tr.nvm_fault_set:
        out.add("nvm_fault")
    if tr.dtc_status_set:
        out.add("dtc_status_set")
    for pos, ev in enumerate(tr.sends):
        if ev.s3_expired:
            out.add("s3_elapsed")
        if ev.sid is None:
            continue
        if ev.sid != 0x10 and ev.session == default:
            out.add("default_session")
        if ev.sid == 0x27 and ev.nrc in (0x36, 0x37):
            out.add("lockout_active")
        if not ev.positive:
            continue
        sub = ev.subfunction
        if ev.sid == 0x10 and sub is not None:
            name = {0x01: "default_session", 0x02: "programming_session",
                    0x03: "extended_session"}.get(sub)
            if name:
                out.add(name)
        elif ev.sid == 0x27 and sub in key_to_level:
            out.add(f"security_level_{key_to_level[sub]}")
        elif ev.sid == 0x2E:
            for did in request_did_ids(ev.request):
                did_def = spec.get_did(did)
                if did_def is not None and "vehicle_stationary" in did_def.conditions.requires:
                    out.add("vehicle_stationary")
        elif ev.sid == 0x31 and sub == 0x01:
            rid = request_routine_id(ev.request)
            rdef = spec.get_routine(rid) if rid is not None else None
            if rdef is not None and "vehicle_stationary" in rdef.conditions.requires:
                out.add("vehicle_stationary")
            if pos < len(tr.sends) - 1:
                out.add("routine_started")
    return out


# ------------------------------------------------------------------------------- scoring


def _ident_str(ident: Ident) -> str:
    kind, value = ident
    return f"{kind}:0x{value:02X}" if kind == "service" else f"{kind}:0x{value:04X}"


def score_targets(label: set[Ident], predicted: set[Ident], n_tests: int) -> dict[str, Any]:
    """Per-requirement target scoring (exact match + TP/FP/FN)."""
    if label:
        exact = predicted == label
    else:
        exact = not predicted and n_tests == 0
    return {
        "exact": exact,
        "tp": len(label & predicted),
        "fp": len(predicted - label),
        "fn": len(label - predicted),
        "missed": sorted(_ident_str(i) for i in label - predicted),
        "extra": sorted(_ident_str(i) for i in predicted - label),
    }


def recall_fraction(required: Iterable[str], produced: Iterable[str]) -> dict[str, Any]:
    """``|required n produced| / |required|`` with the missing items (None if nothing required)."""
    req = set(required)
    hit = req & set(produced)
    return {
        "required": len(req),
        "hit": len(hit),
        "recall": round(len(hit) / len(req), 4) if req else None,
        "missed": sorted(req - hit),
    }


def prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    """Micro precision / recall / F1 (None on an empty denominator)."""
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    if p is None or r is None:
        f = None
    else:
        f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": None if p is None else round(p, 4),
            "recall": None if r is None else round(r, 4),
            "f1": None if f is None else round(f, 4)}


def score_requirement(
    spec: EcuSpec,
    req: NaturalRequirement,
    parsed: ParsedRequirement | None,
    tests: list[TestCase],
    status: str,
) -> dict[str, Any]:
    """Score one requirement's pipeline output against its labels."""
    label = req.target_set
    produced_categories = sorted({t.category for t in tests})
    established: set[str] = set()
    for t in tests:
        established |= established_preconditions(spec, t)
    p_targets = parsed_targets(parsed)
    reasons = []
    if status != "completed":
        reasons.append(f"status={status}")
    if not p_targets:
        reasons.append("no parsed services/DIDs/routines")
    if not tests:
        reasons.append("zero tests")
    return {
        "id": req.id,
        "split": req.split,
        "ambiguous": req.ambiguous,
        "status": status,
        "tests": len(tests),
        "label_targets": sorted(_ident_str(i) for i in label),
        "parsed": score_targets(label, p_targets, len(tests)),
        "exercised": score_targets(label, exercised_targets(tests), len(tests)),
        "categories": recall_fraction(req.required_categories, produced_categories),
        "produced_categories": produced_categories,
        "preconditions": recall_fraction(req.required_preconditions, established),
        "established_preconditions": sorted(established),
        "fallback": bool(reasons),
        "fallback_reasons": reasons,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"requirements": len(rows)}
    for kind in ("parsed", "exercised"):
        exact = sum(1 for r in rows if r[kind]["exact"])
        tp = sum(r[kind]["tp"] for r in rows)
        fp = sum(r[kind]["fp"] for r in rows)
        fn = sum(r[kind]["fn"] for r in rows)
        out[f"targets_{kind}"] = {
            "exact": exact,
            "exact_rate": round(exact / len(rows), 4) if rows else None,
            "tp": tp, "fp": fp, "fn": fn,
            **prf(tp, fp, fn),
        }
    for key in ("categories", "preconditions"):
        scored = [r[key] for r in rows if r[key]["required"]]
        req_total = sum(s["required"] for s in scored)
        hit_total = sum(s["hit"] for s in scored)
        out[key] = {
            "scored_requirements": len(scored),
            "hit": hit_total,
            "required": req_total,
            "micro_recall": round(hit_total / req_total, 4) if req_total else None,
            "macro_recall": round(sum(s["recall"] for s in scored) / len(scored), 4)
            if scored else None,
        }
    out["by_kind"] = by_kind(rows)
    fallback = [r["id"] for r in rows if r["fallback"]]
    unexpected = [r["id"] for r in rows if r["fallback"] and r["label_targets"]]
    out["fallback"] = {
        "count": len(fallback),
        "ids": fallback,
        "unexpected_count": len(unexpected),
        "unexpected_ids": unexpected,
        "note": "unexpected = excluding requirements with an empty label set (e.g. NAT-020), "
        "for which producing nothing is correct",
    }
    return out


def aggregate_by_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregates for every split present among ``rows`` (plus ``all``).

    The v1 file gives ``test`` and ``dev``; the v2 file gives ``test2``; the v3 file gives
    ``test3``. A split with no rows is omitted, except that ``test`` and ``dev`` are always
    present when ``rows`` has no ``test2`` / ``test3`` rows (the v1 layout), so v1 reports
    keep their shape.
    """
    present = {r["split"] for r in rows}
    names = [s for s in ("test", "dev", "test2", "test3") if s in present]
    if not present & {"test2", "test3"}:
        names = ["test", "dev"]
    out = {name: _aggregate([r for r in rows if r["split"] == name]) for name in names}
    out["all"] = _aggregate(rows)
    return out
