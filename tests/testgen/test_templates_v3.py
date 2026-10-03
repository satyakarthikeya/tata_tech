"""Template set v3 (Part C3): coverage templates and parameter variants.

Checks: every new template / variant instantiates for every applicable parameter set,
validates against the oracle, passes on the clean simulator and re-instantiates to the
same bytes; the parameter sets are derived from the spec (mutating a spec copy changes
them); no template text mentions any bug id or bug title from any catalog.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from uds_assistant.eval.provenance import check_test
from uds_assistant.simulator import SimulatedEcu
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen import templates_v3 as v3
from uds_assistant.testgen.execute import run_test_on_simulator
from uds_assistant.testgen.templates import TEMPLATES, applicable_params, validate_test

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTGEN_DIR = REPO_ROOT / "uds_assistant" / "testgen"

NEW_TEMPLATES = (
    "read_did_invalid_length",
    "seed_request_while_unlocked",
    "session_change_resets_routine",
    "write_did_value_retained",
)
EXTENDED = {
    # template id -> (variant field, non-default value)
    "security_invalid_key_lockout": ("recovery", "ecu_reset"),
    "condition_not_met": ("security", "locked"),
    "routine_start_results": ("suppress_positive", True),
}
MAX_TEMPLATES = 32


def _mutable(spec: EcuSpec) -> dict[str, Any]:
    return spec.model_dump(mode="python")


def _rebuild(data: dict[str, Any]) -> EcuSpec:
    return EcuSpec.model_validate(data)


def _check_all(spec: EcuSpec, template_id: str) -> int:
    params_list = applicable_params(spec, template_id)
    for params in params_list:
        tc = TEMPLATES[template_id].instantiate(spec, params)
        report = validate_test(spec, tc)
        assert report.ok, f"{template_id}/{params}: {report.mismatches}"
        outcome = run_test_on_simulator(tc, lambda: SimulatedEcu(spec))
        assert outcome.passed, f"{template_id}/{params}: {outcome.first_failure}"
        again = TEMPLATES[template_id].instantiate(spec, params.model_dump())
        assert [s.model_dump() for s in again.steps] == [s.model_dump() for s in tc.steps]
        assert check_test(spec, tc) == [], f"{template_id}/{params}: provenance"
    return len(params_list)


# ------------------------------------------------------------------ registry and instantiation


def test_template_count_within_cap() -> None:
    assert len(TEMPLATES) <= MAX_TEMPLATES
    assert set(NEW_TEMPLATES) <= set(TEMPLATES)


@pytest.mark.parametrize("template_id", [*NEW_TEMPLATES, *EXTENDED])
def test_new_and_extended_templates_pass_everywhere(template_id: str, spec: EcuSpec) -> None:
    assert _check_all(spec, template_id) > 0


@pytest.mark.parametrize("template_id", NEW_TEMPLATES)
def test_new_templates_document_their_behaviour_class(template_id: str) -> None:
    doc = inspect.getdoc(TEMPLATES[template_id].instantiate_fn) or ""
    assert doc.startswith("Behaviour class:"), template_id


@pytest.mark.parametrize(("template_id", "field_value"), list(EXTENDED.items()))
def test_extended_templates_keep_base_options_first(
    template_id: str, field_value: tuple[str, object], spec: EcuSpec
) -> None:
    """Variants are appended: the base options keep their indices (and their tests)."""
    field, value = field_value
    params = [p.model_dump() for p in applicable_params(spec, template_id)]
    flags = [p[field] == value for p in params]
    assert any(flags) and not all(flags)
    first_variant = flags.index(True)
    assert all(flags[first_variant:]), "variant options must come after all base options"
    ids = [TEMPLATES[template_id].instantiate(spec, p).id for p in params]
    assert len(set(ids)) == len(ids)


# ----------------------------------------------------------------- behaviour of the new probes


def _sends(spec: EcuSpec, template_id: str, **match: object) -> list[tuple[str, list[str]]]:
    p = next(
        p for p in applicable_params(spec, template_id)
        if all(p.model_dump().get(k) == v for k, v in match.items())
    )
    tc = TEMPLATES[template_id].instantiate(spec, p)
    return [(s.request_hex, s.expected_responses_hex) for s in tc.steps if s.kind == "send"]


def test_read_length_probes_are_odd_and_rejected(spec: EcuSpec) -> None:
    for p in applicable_params(spec, "read_did_invalid_length"):
        tc = TEMPLATES["read_did_invalid_length"].instantiate(spec, p)
        reqs = [bytes.fromhex(s.request_hex) for s in tc.steps if s.kind == "send"]
        malformed = [r for r in reqs if r[0] == 0x22 and (len(r) < 3 or (len(r) - 1) % 2)]
        assert len(malformed) == 3
        assert any(len(r) >= 4 for r in malformed)


def test_retention_value_is_in_range_non_default_and_distinct_bytes(spec: EcuSpec) -> None:
    for d in spec.dids:
        if not d.write_sessions:
            continue
        value = v3.retention_value(d)
        assert value.to_bytes(d.length, "big") != d.default_value
        if d.value_range is not None:
            assert d.value_range.min <= value <= d.value_range.max
        raw = value.to_bytes(d.length, "big")
        if d.length > 1 and d.value_range is not None and d.value_range.max >= 0x1234:
            assert len(set(raw)) == len(raw), "multi-byte probe must make byte order visible"


def test_retention_reads_back_after_transition(spec: EcuSpec) -> None:
    for p in applicable_params(spec, "write_did_value_retained"):
        tc = TEMPLATES["write_did_value_retained"].instantiate(spec, p)
        sends = [s for s in tc.steps if s.kind == "send"]
        assert sends[-1].request_hex.startswith("22")
        written = next(s for s in sends if s.request_hex.startswith("2e"))
        did_hex = written.request_hex[2:6]
        assert sends[-1].expected_responses_hex == ["62" + did_hex + written.request_hex[6:]]
        if p.after == "s3_timeout":
            assert any(s.kind == "advance_time" for s in tc.steps)
        else:
            assert any(s.request_hex.startswith("11") for s in sends)


# ------------------------------------------------------------------- spec-driven (generic-ness)


def test_params_follow_the_spec_when_entities_are_added(spec: EcuSpec) -> None:
    data = _mutable(spec)
    data["dids"].append({
        "id": 0x0A55, "name": "probe_extra_word", "length": 3, "encoding": "uint24",
        "read_sessions": [0x01, 0x03], "write_sessions": [0x03], "write_security_level": 0x01,
        "value_range": {"min": 0, "max": 0xFFFFFF}, "default_value": b"\x00\x00\x00",
    })
    data["routines"].append({
        "id": 0x0A66, "name": "probe_extra_routine", "allowed_subfunctions": [1, 2, 3],
        "sessions": [0x03], "security_level": 0x01, "results_requires_start": True,
        "stop_requires_start": True,
    })
    mutated = _rebuild(data)
    base = {t: [p.model_dump() for p in applicable_params(spec, t)] for t in NEW_TEMPLATES}
    more = {t: [p.model_dump() for p in applicable_params(mutated, t)] for t in NEW_TEMPLATES}
    assert {"did": 0x0A55, "session": 0x01} in more["read_did_invalid_length"]
    assert {"did": 0x0A55, "after": "s3_timeout"} in more["write_did_value_retained"]
    assert {"did": 0x0A55, "after": "ecu_reset"} in more["write_did_value_retained"]
    assert {"routine": 0x0A66, "transition": "session_change"} in more[
        "session_change_resets_routine"]
    for t in ("read_did_invalid_length", "write_did_value_retained",
              "session_change_resets_routine"):
        assert len(more[t]) > len(base[t])
    assert v3.retention_value(mutated.get_did(0x0A55)) == 0x123456  # type: ignore[arg-type]
    for t in (*NEW_TEMPLATES, *EXTENDED):
        _check_all(mutated, t)


def test_params_follow_the_spec_when_capabilities_are_removed(spec: EcuSpec) -> None:
    data = _mutable(spec)
    data["ecu_reset"]["supported_subfunctions"] = []
    data["security_levels"] = [lv for lv in data["security_levels"] if lv["level"] == 0x01]
    for d in data["dids"]:
        if d["write_security_level"] not in (None, 0x01):
            d["write_security_level"] = None
            d["write_sessions"] = []
    for r in data["routines"]:
        if r["security_level"] not in (None, 0x01):
            r["security_level"] = None
    mutated = _rebuild(data)

    def variants(t: str, field: str) -> set[object]:
        return {p.model_dump()[field] for p in applicable_params(mutated, t)}

    assert variants("security_invalid_key_lockout", "recovery") == {"delay"}
    assert variants("session_change_resets_routine", "transition") == {"session_change"}
    assert variants("write_did_value_retained", "after") == {"s3_timeout"}
    assert variants("seed_request_while_unlocked", "level") == {0x01}
    assert len(applicable_params(mutated, "seed_request_while_unlocked")) < len(
        applicable_params(spec, "seed_request_while_unlocked"))


# ------------------------------------------------------------------------------ no bug ids


def _bug_terms() -> list[str]:
    terms: list[str] = []
    for path in sorted((REPO_ROOT / "data" / "bugs").glob("*.yaml")):
        for bug in yaml.safe_load(path.read_text(encoding="utf-8")).get("bugs", []):
            terms.append(str(bug["id"]).lower())
            if bug.get("title"):
                terms.append(str(bug["title"]).lower())
    return terms


def _template_texts(spec: EcuSpec) -> dict[str, str]:
    texts = {
        str(p.relative_to(REPO_ROOT)): p.read_text(encoding="utf-8")
        for p in sorted(TESTGEN_DIR.glob("*.py"))
    }
    for tid, tpl in TEMPLATES.items():
        meta = [tid, tpl.id, tpl.description, inspect.getdoc(tpl.instantiate_fn) or "",
                inspect.getdoc(tpl.applicable_params_fn) or "",
                json.dumps(tpl.params_model.model_json_schema())]
        for params in applicable_params(spec, tid):
            tc = tpl.instantiate(spec, params)
            meta += [tc.id, tc.title, tc.explanation, json.dumps(tc.parameters)]
            meta += [s.description for s in tc.steps]
        texts[f"template:{tid}"] = "\n".join(meta)
    return texts


def test_no_template_mentions_any_bug_id_or_title(spec: EcuSpec) -> None:
    terms = _bug_terms()
    assert len(terms) >= 38, "expected every catalog under data/bugs/ to be scanned"
    hits = [
        (where, term)
        for where, text in _template_texts(spec).items()
        for term in terms
        if term in text.lower()
    ]
    assert hits == []
