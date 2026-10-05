"""Coverage of a set of tests against the ECU spec: what is touched, what is not.

:func:`coverage_report` is the one function behind the Run & Export table, ``POST /coverage``,
``coverage_report.md`` and the coverage section of ``outputs/eval_report.md``. It reads only the
tests' concrete steps (the same static walk the evaluation uses) and ``data/bcm_spec.yaml``;
nothing is executed and nothing is estimated.

"Touched" means: a service is sent, a DID / routine id is addressed by a request, an NRC is
expected in a response, a session is active when a request is sent (or entered by a positive
0x10), a security level's seed / key sub-function is sent (or the level is unlocked while a
request is sent).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from uds_assistant.eval.trace import trace_test
from uds_assistant.protocol.constants import Nrc
from uds_assistant.protocol.describe import nrc_name, service_name
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.model import TestCase

#: The spec file has no NRC list. These are the NRCs the rules engine (``rules/nrc_order.py``)
#: can emit for it; they are the "NRCs in the spec" for coverage purposes.
SPEC_NRCS: tuple[Nrc, ...] = (
    Nrc.SERVICE_NOT_SUPPORTED,
    Nrc.SUB_FUNCTION_NOT_SUPPORTED,
    Nrc.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT,
    Nrc.RESPONSE_TOO_LONG,
    Nrc.CONDITIONS_NOT_CORRECT,
    Nrc.REQUEST_SEQUENCE_ERROR,
    Nrc.REQUEST_OUT_OF_RANGE,
    Nrc.SECURITY_ACCESS_DENIED,
    Nrc.INVALID_KEY,
    Nrc.EXCEED_NUMBER_OF_ATTEMPTS,
    Nrc.REQUIRED_TIME_DELAY_NOT_EXPIRED,
    Nrc.GENERAL_PROGRAMMING_FAILURE,
    Nrc.REQUEST_CORRECTLY_RECEIVED_RESPONSE_PENDING,
    Nrc.SUB_FUNCTION_NOT_SUPPORTED_IN_ACTIVE_SESSION,
    Nrc.SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION,
)

KINDS = ("service", "did", "routine", "nrc", "session", "security_level")


def _did_ids(raw: bytes) -> list[int]:
    """DIDs addressed by a 0x22 (every 2-byte id) or 0x2E (the first id) request."""
    if not raw or raw[0] not in (0x22, 0x2E):
        return []
    body = raw[1:]
    pairs = [(body[i] << 8) | body[i + 1] for i in range(0, len(body) - 1, 2)]
    return pairs if raw[0] == 0x22 else pairs[:1]


def _routine_id(raw: bytes) -> int | None:
    return (raw[2] << 8) | raw[3] if len(raw) >= 4 and raw[0] == 0x31 else None


def _label(kind: str, key: int, spec: EcuSpec) -> str:
    if kind == "service":
        return f"{key:#04x} {service_name(key)}"
    if kind == "did":
        d = spec.get_did(key)
        return f"{key:#06x} {d.name if d else '?'}"
    if kind == "routine":
        r = spec.get_routine(key)
        return f"{key:#06x} {r.name if r else '?'}"
    if kind == "nrc":
        return f"{key:#04x} {nrc_name(key)}"
    if kind == "session":
        s = spec.get_session(key)
        return f"{key:#04x} {s.name if s else '?'}"
    lvl = spec.get_security_level(key)
    return f"{key:#04x} {lvl.name if lvl else '?'}"


def _universe(spec: EcuSpec) -> dict[str, list[int]]:
    services = sorted({sid for s in spec.sessions for sid in s.allowed_services})
    return {
        "service": services,
        "did": sorted(d.id for d in spec.dids),
        "routine": sorted(r.id for r in spec.routines),
        "nrc": sorted(int(n) for n in SPEC_NRCS),
        "session": sorted(s.id for s in spec.sessions),
        "security_level": sorted(lvl.level for lvl in spec.security_levels),
    }


def coverage_report(tests: list[TestCase], spec: EcuSpec) -> dict[str, Any]:
    """Counts by category and, per spec item, how many of ``tests`` touch it.

    Returns ``{"tests", "by_category", "items", "uncovered"}``. ``items[kind]`` is a list of
    ``{"id", "item", "tests", "positive", "negative"}`` rows for every spec item of that kind
    (``positive`` / ``negative`` are filled for services and routines/DIDs only: the number of
    tests with at least one step on that item whose expected outcome is positive / negative).
    ``uncovered[kind]`` lists the items with zero tests.
    """
    universe = _universe(spec)
    touched: dict[str, dict[int, set[str]]] = {k: {i: set() for i in universe[k]} for k in KINDS}
    pos: dict[str, dict[int, set[str]]] = {k: {i: set() for i in universe[k]} for k in KINDS}
    neg: dict[str, dict[int, set[str]]] = {k: {i: set() for i in universe[k]} for k in KINDS}
    seed_sub = {lvl.seed_subfunction: lvl.level for lvl in spec.security_levels}
    key_sub = {lvl.key_subfunction: lvl.level for lvl in spec.security_levels}

    def hit(kind: str, key: int | None, tid: str, positive: bool | None = None) -> None:
        if key is None or key not in touched[kind]:
            return
        touched[kind][key].add(tid)
        if positive is True:
            pos[kind][key].add(tid)
        elif positive is False:
            neg[kind][key].add(tid)

    for test in tests:
        tid = test.id
        for ev in trace_test(spec, test).sends:
            ok = ev.positive
            hit("service", ev.sid, tid, ok)
            for did in _did_ids(ev.request):
                hit("did", did, tid, ok)
            hit("routine", _routine_id(ev.request), tid, ok)
            for frame in ev.frames:
                if len(frame) >= 3 and frame[0] == 0x7F:
                    hit("nrc", frame[2], tid)
            hit("session", ev.session, tid)
            if ev.sid == 0x10 and ok and ev.subfunction is not None:
                hit("session", ev.subfunction, tid)
            if ev.sid == 0x27 and ev.subfunction is not None:
                hit("security_level", seed_sub.get(ev.subfunction), tid)
                hit("security_level", key_sub.get(ev.subfunction), tid)
            for level in ev.unlocked:
                hit("security_level", level, tid)

    items: dict[str, list[dict[str, Any]]] = {}
    uncovered: dict[str, list[str]] = {}
    for kind in KINDS:
        rows = []
        for key in universe[kind]:
            rows.append({
                "id": key,
                "item": _label(kind, key, spec),
                "tests": len(touched[kind][key]),
                "positive": len(pos[kind][key]),
                "negative": len(neg[kind][key]),
            })
        items[kind] = rows
        uncovered[kind] = [r["item"] for r in rows if r["tests"] == 0]
    return {
        "tests": len(tests),
        "by_category": dict(sorted(Counter(t.category for t in tests).items())),
        "items": items,
        "uncovered": uncovered,
    }


_KIND_TITLES = {
    "service": "Services",
    "did": "DIDs",
    "routine": "Routines",
    "nrc": "NRCs",
    "session": "Sessions",
    "security_level": "Security levels",
}


def coverage_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Flat table rows (kind, item, tests, positive, negative, status) for the UI."""
    rows = []
    for kind in KINDS:
        for r in report["items"][kind]:
            split = kind in ("service", "did", "routine")
            rows.append({
                "kind": _KIND_TITLES[kind],
                "item": r["item"],
                "tests": r["tests"],
                "positive": str(r["positive"]) if split else "-",
                "negative": str(r["negative"]) if split else "-",
                "status": "UNCOVERED" if r["tests"] == 0 else "covered",
            })
    return rows


def coverage_markdown(report: dict[str, Any], heading: str = "# Coverage report") -> str:
    """Markdown rendering of :func:`coverage_report` (zero-test items in bold)."""
    lines = [heading, ""]
    cats = ", ".join(f"{k} {v}" for k, v in report["by_category"].items()) or "none"
    lines += [f"{report['tests']} tests. By category: {cats}.", ""]
    total_unc = sum(len(v) for v in report["uncovered"].values())
    lines += [
        (
            f"Spec items with ZERO tests: {total_unc}. "
            "(NRC universe = the NRCs the rules engine can emit; the spec file lists none.)"
        ),
        "",
    ]
    for kind in KINDS:
        rows = report["items"][kind]
        split = kind in ("service", "did", "routine")
        lines.append(f"## {_KIND_TITLES[kind]}")
        lines.append("")
        lines.append("| Item | Tests | Positive | Negative |" if split else "| Item | Tests |")
        lines.append("|---|---|---|---|" if split else "|---|---|")
        for r in rows:
            name = f"**{r['item']} — UNCOVERED**" if r["tests"] == 0 else r["item"]
            cells = [name, str(r["tests"])]
            if split:
                cells += [str(r["positive"]), str(r["negative"])]
            lines.append("| " + " | ".join(cells) + " |")
        unc = report["uncovered"][kind]
        lines += ["", "Zero tests: " + (", ".join(unc) if unc else "none"), ""]
    return "\n".join(lines)
