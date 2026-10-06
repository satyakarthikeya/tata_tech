"""Baseline coverage of imported tests, compared with generated and combined suites.

Reuses :func:`uds_assistant.eval.coverage.coverage_report` (services, DIDs, routines, NRCs,
sessions, security levels) and adds one more dimension, *timing cases*, which the base report
does not have. Everything is a static walk over the tests' own steps and ``data/bcm_spec.yaml``;
nothing is executed and nothing is estimated.

Timing cases (a fixed list, defined in :data:`TIMING_CASES`):

- ``p2_response_limit``: a send step carries an explicit ``max_response_time_ms``;
- ``response_pending``: an expected response is ``7F xx 78`` followed by the final response;
- ``s3_timeout``: a wait longer than the active non-default session's S3 returns the ECU to default;
- ``s3_keepalive``: a wait shorter than S3 inside a non-default session (the session must persist);
- ``security_delay``: a wait, then a 0x27 request, after a lockout / delay NRC (0x36 / 0x37)
  (the waits may be split by keep-alive requests).

"Newly covered" = the item has zero imported tests and at least one generated test, so the
combined suite closes that gap. "Imported only" = covered by imported tests and by no generated one.
"""

from __future__ import annotations

from typing import Any

from uds_assistant.eval.coverage import KINDS, coverage_report
from uds_assistant.eval.trace import trace_test
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.model import TestCase

TIMING_CASES: dict[str, str] = {
    "p2_response_limit": "P2 response-time limit (send step with max_response_time_ms)",
    "response_pending": "Response pending (7F xx 78, then the final response)",
    "s3_timeout": "S3 timeout drops a non-default session",
    "s3_keepalive": "Wait shorter than S3 keeps the session",
    "security_delay": "Security delay timer (wait, then 0x27 after a 0x36 / 0x37 NRC)",
}
ALL_KINDS = (*KINDS, "timing")
TITLES = {
    "service": "Services", "did": "DIDs", "routine": "Routines", "nrc": "NRCs",
    "session": "Sessions", "security_level": "Security levels", "timing": "Timing cases",
}
_LOCKOUT_NRCS = (0x36, 0x37)


def timing_cases(tests: list[TestCase], spec: EcuSpec) -> dict[str, set[str]]:
    """Which tests exercise each timing case (see module docstring)."""
    out: dict[str, set[str]] = {k: set() for k in TIMING_CASES}
    default = 0x01 if spec.get_session(0x01) is not None else spec.sessions[0].id
    for test in tests:
        if any(s.kind == "send" and s.max_response_time_ms for s in test.steps):
            out["p2_response_limit"].add(test.id)
        locked, waited = False, 0
        for ev in trace_test(spec, test).sends:
            if any(len(f) >= 3 and f[0] == 0x7F and f[2] == 0x78 for f in ev.frames):
                out["response_pending"].add(test.id)
            if ev.s3_dropped_session:
                out["s3_timeout"].add(test.id)
            if ev.idle_ms > 0 and not ev.s3_expired and ev.session != default:
                out["s3_keepalive"].add(test.id)
            if locked:
                waited += ev.idle_ms
                if ev.sid == 0x27 and waited > 0:
                    out["security_delay"].add(test.id)
            if ev.nrc in _LOCKOUT_NRCS:
                locked, waited = True, 0
            elif ev.sid == 0x27 and ev.positive:
                locked = False
    return out


def _counts(tests: list[TestCase], spec: EcuSpec) -> dict[str, dict[str, int]]:
    """``{kind: {item label: number of tests touching it}}`` for every kind incl. timing."""
    rep = coverage_report(tests, spec)
    counts = {k: {r["item"]: r["tests"] for r in rep["items"][k]} for k in KINDS}
    counts["timing"] = {v: len(ids) for v, ids in
                        ((TIMING_CASES[k], t) for k, t in timing_cases(tests, spec).items())}
    return counts


def _tag(tests: list[TestCase], prefix: str) -> list[TestCase]:
    """Copies with namespaced ids so imported and generated ids can never merge."""
    return [t.model_copy(update={"id": f"{prefix}:{t.id}"}) for t in tests]


def compare_coverage(
    imported: list[TestCase], generated: list[TestCase], spec: EcuSpec
) -> dict[str, Any]:
    """Baseline (imported) vs generated vs combined coverage, with the per-item differences."""
    imp, gen = _tag(imported, "imported"), _tag(generated, "generated")
    base, gcov, comb = _counts(imp, spec), _counts(gen, spec), _counts(imp + gen, spec)
    rows: dict[str, list[dict[str, Any]]] = {}
    newly: dict[str, list[str]] = {}
    only_imp: dict[str, list[str]] = {}
    still: dict[str, list[str]] = {}
    summary: dict[str, dict[str, int]] = {}
    for kind in ALL_KINDS:
        rows[kind] = [
            {"item": item, "imported": n, "generated": gcov[kind][item],
             "combined": comb[kind][item]}
            for item, n in base[kind].items()
        ]
        newly[kind] = [r["item"] for r in rows[kind] if r["imported"] == 0 and r["generated"] > 0]
        only_imp[kind] = [r["item"] for r in rows[kind] if r["imported"] > 0 and r["generated"] == 0]
        still[kind] = [r["item"] for r in rows[kind] if r["combined"] == 0]
        summary[kind] = {
            "items": len(rows[kind]),
            "imported": sum(r["imported"] > 0 for r in rows[kind]),
            "generated": sum(r["generated"] > 0 for r in rows[kind]),
            "combined": sum(r["combined"] > 0 for r in rows[kind]),
        }
    return {
        "tests": {"imported": len(imported), "generated": len(generated),
                  "combined": len(imported) + len(generated)},
        "summary": summary,
        "rows": rows,
        "newly_covered": newly,
        "imported_only": only_imp,
        "still_uncovered": still,
    }


def comparison_markdown(cmp: dict[str, Any], heading: str = "# Imported-test baseline coverage") -> str:
    """Markdown report for download (same data as :func:`compare_coverage`)."""
    n = cmp["tests"]
    lines = [
        heading, "",
        (
            "Synthetic ECU spec (`data/bcm_spec.yaml`). Static coverage of the tests' own steps; "
            "nothing here was executed. Imported tests are the user's existing suite (not "
            "AI-generated); generated tests come from the assistant's pipeline. Both need human "
            "review before they run; simulator or approved lab bench only."
        ), "",
        f"Imported {n['imported']} tests, generated {n['generated']} tests, combined {n['combined']}.",
        "", "## Summary (items touched / items in the spec)", "",
        "| Kind | Imported (baseline) | Generated | Combined | Newly covered by generated |",
        "|---|---|---|---|---|",
    ]
    for kind in ALL_KINDS:
        s = cmp["summary"][kind]
        lines.append(f"| {TITLES[kind]} | {s['imported']}/{s['items']} | {s['generated']}/{s['items']}"
                     f" | {s['combined']}/{s['items']} | {len(cmp['newly_covered'][kind])} |")
    lines += ["", "## Newly covered (zero imported tests, at least one generated test)", ""]
    any_new = False
    for kind in ALL_KINDS:
        if cmp["newly_covered"][kind]:
            any_new = True
            lines.append(f"- **{TITLES[kind]}:** " + "; ".join(cmp["newly_covered"][kind]))
    if not any_new:
        lines.append("- none")
    lines += ["", "## Covered only by imported tests", ""]
    any_imp = False
    for kind in ALL_KINDS:
        if cmp["imported_only"][kind]:
            any_imp = True
            lines.append(f"- **{TITLES[kind]}:** " + "; ".join(cmp["imported_only"][kind]))
    if not any_imp:
        lines.append("- none")
    lines += ["", "## Still uncovered by the combined suite", ""]
    any_gap = False
    for kind in ALL_KINDS:
        if cmp["still_uncovered"][kind]:
            any_gap = True
            lines.append(f"- **{TITLES[kind]}:** " + "; ".join(cmp["still_uncovered"][kind]))
    if not any_gap:
        lines.append("- none")
    lines += ["", "## Per-item tests (imported / generated / combined)", ""]
    for kind in ALL_KINDS:
        lines += [f"### {TITLES[kind]}", "", "| Item | Imported | Generated | Combined |", "|---|---|---|---|"]
        for r in cmp["rows"][kind]:
            mark = " (new)" if r["item"] in cmp["newly_covered"][kind] else ""
            lines.append(f"| {r['item']}{mark} | {r['imported']} | {r['generated']} | {r['combined']} |")
        lines.append("")
    return "\n".join(lines)
