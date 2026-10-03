"""Pure metric functions for the evaluation report (PROJECT.md section 7).

Each function takes test cases (and the spec / corpus where needed) and returns
a plain ``dict`` of counts and rates. Every rate is a fraction in ``[0, 1]``;
an empty denominator gives ``None`` (rendered as "n/a"), never a made-up value.
The exact definitions live in :data:`METRIC_DEFINITIONS` and are copied into
the JSON and Markdown reports.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from uds_assistant.protocol.codec import decode_request
from uds_assistant.rag.citations import citation_is_valid
from uds_assistant.rag.model import Chunk
from uds_assistant.rules.engine import RuleResult, RulesSession
from uds_assistant.rules.state import dtc_code_to_int, with_dtc_status
from uds_assistant.runner.suite import BugMatrix
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.model import TestCase
from uds_assistant.testgen.templates import TEMPLATES, validate_test

CATEGORIES = ("positive", "negative", "session", "security", "timing")
FORMAT_NRCS = frozenset({0x11, 0x12, 0x13})
"""NRCs meaning "the request itself is malformed/unsupported" (service, sub-function, length)."""

METRIC_DEFINITIONS: dict[str, str] = {
    "request_validity": (
        "Over every send step of every generated test: the request is replayed through the "
        "rules-engine oracle in sequence (same set-up and time steps). A request counts as "
        "well-formed if (a) protocol.codec.decode_request decodes it and (b) the oracle does not "
        "reject it with a format NRC (0x11 serviceNotSupported, 0x12 subFunctionNotSupported, "
        "0x13 incorrectMessageLengthOrInvalidFormat), unless that NRC is listed in the "
        "template's declared intended_nrcs (a deliberate malformed-request probe such as "
        "write_did_invalid_length -> 0x13). rate = well-formed / send steps. The unadjusted "
        "rate (no intent exemption) is reported alongside."
    ),
    "expected_response_accuracy": (
        "SELF-CONSISTENCY CHECK, circular by construction (expected bytes are produced by "
        "the same oracle; reported in an appendix, not a headline). oracle: share of generated send steps whose expected response frames equal a fresh "
        "rules-engine re-run of the test (and share of whole tests with zero mismatches). "
        "simulator: share of generated tests passing on the bug-free independent simulator. "
        "gold: (1) exact overlap = generated tests whose full step sequence (requests and "
        "set-up/time steps, ignoring expected responses) is identical to a gold test; agreement "
        "= identical expected responses on every step. (2) shared-prefix overlap = every "
        "distinct send step reached by an identical step prefix from power-on in both a "
        "generated and a gold test (deduplicated by prefix); agreement = identical expected "
        "frames for that step."
    ),
    "coverage": (
        "Number of generated tests per category (positive/negative/session/security/timing) "
        "per requirement. rate = requirements with >= 1 generated test / requirements; "
        "category_presence = categories with >= 1 test across the suite / 5."
    ),
    "template_reuse_rate": (
        "Share of generated tests whose template_id is a registered template AND whose steps "
        "are byte-identical to a fresh instantiation of that template with the test's stored "
        "parameters (independent re-check of byte provenance)."
    ),
    "citation_validity": (
        "Share of all citations attached to generated tests for which "
        "rag.citations.citation_is_valid is true against the evaluation corpus (source+ref "
        "exists; a quote must appear verbatim and its hex identifiers must belong to the chunk)."
    ),
    "bug_detection_rate": (
        "Each catalog bug is enabled alone in a fresh simulator per test. A bug is detected if "
        ">= 1 test that passes on the clean simulator fails with the bug enabled. Tests failing "
        "on the clean simulator are reported as invalid and get no credit. rate = detected bugs "
        "/ catalog bugs. Reported for the generated suite, the hand-written gold suite "
        "(baseline) and their union. The 26-bug catalog (data/bugs/bug_catalog.yaml) is "
        "IN-SAMPLE: templates v2 were added after inspecting which of these bugs v1 missed."
    ),
    "heldout_bug_detection_rate": (
        "Same procedure as bug_detection_rate on the 12 held-out bugs in "
        "data/bugs/heldout_catalog.yaml, written by a subagent that could not see templates, "
        "gold tests, eval, LLM or agent code. HEADLINE = held-out generated-suite detection. "
        "Missed-bug reasons come from a static trigger analysis (eval/heldout.py): whether "
        "any test applies the stimulus the bug description needs; reporting only."
    ),
    "simulator_rules_agreement": (
        "A deterministic seeded random sample (eval/agreement.py; >= 5000 requests over "
        "60-step walks with clock advances, environment/DTC changes and computed seed/key "
        "handshakes) is sent to a bug-free SimulatedEcu and a RulesSession in lockstep. "
        "agreed = requests with byte-identical response frames; a walk stops at its first "
        "disagreement."
    ),
    "udsoncan_virtual_can": (
        "udsoncan.Client over ISO-TP on a python-can virtual bus against the simulator: "
        "10 03 -> 27 01 seed -> 27 02 key -> 22 0100 -> 2E 0100 50 -> 22 0100 read-back == "
        "0x50. pass/fail (fail includes any exception, with its text); 'skipped' with "
        "--skip-can."
    ),
    "gold_clean_pass": "Gold tests passing on the bug-free simulator / gold tests.",
    "pipeline_stats": (
        "Per requirement: kept tests, dropped tests (failed validation), rejected planner "
        "choices, plan attempts (retries = attempts - 1), run status."
    ),
    "runtime": "Wall-clock seconds per evaluation phase and in total (machine dependent).",
}


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def oracle_replay(spec: EcuSpec, test: TestCase) -> list[tuple[int, RuleResult]]:
    """Replay ``test`` through a fresh :class:`RulesSession`; one result per send step."""
    rs = RulesSession(spec, now_ms=0)
    out: list[tuple[int, RuleResult]] = []
    for i, step in enumerate(test.steps):
        if step.kind == "send":
            out.append((i, rs.send(step.request_bytes)))
        elif step.kind == "advance_time":
            rs.advance(step.ms)
        elif step.kind == "set_environment":
            rs.set_environment(
                vehicle_speed_kph=step.vehicle_speed_kph, nvm_write_fault=step.nvm_write_fault
            )
        elif step.kind == "set_dtc_status":
            rs.state = with_dtc_status(rs.state, dtc_code_to_int(step.code), step.status)
    return out


def request_validity(spec: EcuSpec, tests: list[TestCase]) -> dict[str, Any]:
    """Request-validity metric (see :data:`METRIC_DEFINITIONS`)."""
    total = decodable = no_format_nrc = valid = intentional = 0
    invalid_examples: list[dict[str, Any]] = []
    for test in tests:
        tpl = TEMPLATES.get(test.template_id or "")
        intended = tpl.intended_nrcs if tpl is not None else frozenset()
        for index, result in oracle_replay(spec, test):
            total += 1
            request = result.request
            try:
                decode_request(request)
                ok_decode = True
            except ValueError:
                ok_decode = False
            nrc = int(result.nrc) if result.nrc is not None else None
            format_rejected = nrc in FORMAT_NRCS
            decodable += ok_decode
            no_format_nrc += ok_decode and not format_rejected
            is_intentional = format_rejected and nrc in intended
            intentional += ok_decode and is_intentional
            if ok_decode and (not format_rejected or is_intentional):
                valid += 1
            elif len(invalid_examples) < 10:
                invalid_examples.append(
                    {"test_id": test.id, "step": index, "request_hex": request.hex(),
                     "nrc": f"0x{nrc:02X}" if nrc is not None else None, "decodable": ok_decode}
                )
    return {
        "send_steps": total,
        "decodable": decodable,
        "not_format_rejected": no_format_nrc,
        "intentional_format_probes": intentional,
        "well_formed": valid,
        "rate": _rate(valid, total),
        "unadjusted_rate": _rate(no_format_nrc, total),
        "invalid_examples": invalid_examples,
    }


def _signature(test: TestCase) -> list[tuple[Any, ...]]:
    sig: list[tuple[Any, ...]] = []
    for step in test.steps:
        if step.kind == "send":
            sig.append(("send", step.request_hex))
        elif step.kind == "advance_time":
            sig.append(("advance", step.ms))
        elif step.kind == "set_environment":
            sig.append(("env", step.vehicle_speed_kph, step.nvm_write_fault))
        else:
            sig.append(("dtc", step.code.upper(), step.status))
    return sig


def expected_response_accuracy(
    spec: EcuSpec,
    tests: list[TestCase],
    gold: list[TestCase],
    clean_pass_rate: float | None,
) -> dict[str, Any]:
    """Expected-response accuracy vs the oracle, the simulator and the gold tests."""
    steps_total = steps_agree = tests_ok = 0
    for test in tests:
        replay = dict(oracle_replay(spec, test))
        for i, step in enumerate(test.steps):
            if step.kind == "send":
                steps_total += 1
                actual = [r.hex() for r in replay[i].responses]
                steps_agree += actual == step.expected_responses_hex
        tests_ok += validate_test(spec, test).ok

    gold_sigs = [(g, _signature(g)) for g in gold]
    exact_pairs = exact_agree = 0
    exact_examples: list[dict[str, str]] = []
    prefix_expect: dict[tuple[tuple[Any, ...], ...], tuple[list[str], list[str]]] = {}
    for test in tests:
        sig = _signature(test)
        for g, gsig in gold_sigs:
            if sig == gsig:
                exact_pairs += 1
                same = all(
                    a.kind != "send" or a.expected_responses_hex == b.expected_responses_hex
                    for a, b in zip(test.steps, g.steps, strict=True)
                )
                exact_agree += same
                if len(exact_examples) < 10:
                    exact_examples.append({"generated": test.id, "gold": g.id,
                                           "agree": str(same).lower()})
            n = 0
            while n < min(len(sig), len(gsig)) and sig[n] == gsig[n]:
                n += 1
            for k in range(n):
                if sig[k][0] != "send":
                    continue
                key = tuple(sig[: k + 1])
                if key not in prefix_expect:
                    prefix_expect[key] = (
                        test.steps[k].expected_responses_hex,  # type: ignore[union-attr]
                        g.steps[k].expected_responses_hex,  # type: ignore[union-attr]
                    )
    prefix_agree = sum(1 for a, b in prefix_expect.values() if a == b)
    return {
        "oracle": {
            "send_steps": steps_total,
            "agreeing_steps": steps_agree,
            "step_rate": _rate(steps_agree, steps_total),
            "tests": len(tests),
            "tests_fully_agreeing": tests_ok,
            "test_rate": _rate(tests_ok, len(tests)),
        },
        "simulator": {"clean_pass_rate": clean_pass_rate},
        "gold_exact_overlap": {
            "overlapping_pairs": exact_pairs,
            "agreeing_pairs": exact_agree,
            "rate": _rate(exact_agree, exact_pairs),
            "examples": exact_examples,
        },
        "gold_shared_prefix": {
            "distinct_shared_send_steps": len(prefix_expect),
            "agreeing": prefix_agree,
            "rate": _rate(prefix_agree, len(prefix_expect)),
        },
    }


def coverage(tests: list[TestCase], requirement_ids: list[str]) -> dict[str, Any]:
    """Tests per category per requirement."""
    table: dict[str, dict[str, int]] = {
        rid: dict.fromkeys(CATEGORIES, 0) for rid in requirement_ids
    }
    for test in tests:
        for rid in test.requirement_ids:
            table.setdefault(rid, dict.fromkeys(CATEGORIES, 0))[test.category] += 1
    totals = Counter(t.category for t in tests)
    with_tests = sum(1 for rid in requirement_ids if sum(table[rid].values()) > 0)
    present = sum(1 for c in CATEGORIES if totals.get(c, 0) > 0)
    multi = sum(
        1 for rid in requirement_ids if sum(1 for c in CATEGORIES if table[rid][c] > 0) >= 2
    )
    return {
        "per_requirement": table,
        "category_totals": {c: totals.get(c, 0) for c in CATEGORIES},
        "requirements": len(requirement_ids),
        "requirements_with_tests": with_tests,
        "rate": _rate(with_tests, len(requirement_ids)),
        "category_presence": _rate(present, len(CATEGORIES)),
        "requirements_with_2plus_categories": multi,
        "multi_category_rate": _rate(multi, len(requirement_ids)),
    }


def template_reuse(spec: EcuSpec, tests: list[TestCase]) -> dict[str, Any]:
    """Share of tests that are exact instantiations of a registered template."""
    reused = 0
    per_template: Counter[str] = Counter()
    mismatched: list[str] = []
    for test in tests:
        tpl = TEMPLATES.get(test.template_id or "")
        ok = False
        if tpl is not None:
            try:
                fresh = tpl.instantiate(spec, dict(test.parameters))
                ok = [s.model_dump() for s in fresh.steps] == [s.model_dump() for s in test.steps]
            except Exception:  # noqa: BLE001 - any failure means "not reproducible"
                ok = False
        if ok:
            reused += 1
            per_template[str(test.template_id)] += 1
        else:
            mismatched.append(test.id)
    return {
        "tests": len(tests),
        "template_instantiations": reused,
        "rate": _rate(reused, len(tests)),
        "templates_registered": len(TEMPLATES),
        "templates_used": len(per_template),
        "per_template": dict(sorted(per_template.items())),
        "not_reproducible": mismatched[:20],
    }


def citation_validity(tests: list[TestCase], corpus: list[Chunk]) -> dict[str, Any]:
    """Share of citations that resolve to a real chunk (and quote it faithfully)."""
    total = valid = tests_with_valid = 0
    invalid_examples: list[dict[str, Any]] = []
    for test in tests:
        any_valid = False
        for citation in test.citations:
            total += 1
            if citation_is_valid(citation, corpus):
                valid += 1
                any_valid = True
            elif len(invalid_examples) < 10:
                invalid_examples.append({"test_id": test.id, **citation.model_dump()})
        tests_with_valid += any_valid
    return {
        "citations": total,
        "valid": valid,
        "rate": _rate(valid, total),
        "tests_with_valid_citation": tests_with_valid,
        "tests_with_valid_citation_rate": _rate(tests_with_valid, len(tests)),
        "invalid_examples": invalid_examples,
    }


def bug_detection(matrix: BugMatrix) -> dict[str, Any]:
    """Serializable summary of a :class:`BugMatrix`."""
    return {
        "bugs": len(matrix.bug_ids),
        "detected": len(matrix.detected_bug_ids),
        "rate": round(matrix.detection_rate, 4) if matrix.bug_ids else None,
        "tests": len(matrix.test_ids),
        "valid_tests": len(matrix.valid_test_ids),
        "invalid_tests": [t.model_dump() for t in matrix.invalid_tests],
        "undetected": matrix.undetected_bug_ids,
        "per_bug": [b.model_dump() for b in matrix.per_bug],
    }


def union_detection(a: BugMatrix, b: BugMatrix) -> dict[str, Any]:
    """Bugs detected by either suite."""
    detected = [bid for bid in a.bug_ids if bid in set(a.detected_bug_ids) | set(b.detected_bug_ids)]
    only_a = [bid for bid in a.detected_bug_ids if bid not in set(b.detected_bug_ids)]
    only_b = [bid for bid in b.detected_bug_ids if bid not in set(a.detected_bug_ids)]
    return {
        "bugs": len(a.bug_ids),
        "detected": len(detected),
        "rate": _rate(len(detected), len(a.bug_ids)),
        "undetected": [bid for bid in a.bug_ids if bid not in detected],
        "only_generated": only_a,
        "only_gold": only_b,
    }
