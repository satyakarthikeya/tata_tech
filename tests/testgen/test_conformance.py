"""Part D2: the requirement-independent conformance sweep."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

from uds_assistant.eval.provenance import check_provenance, check_test
from uds_assistant.runner import run_suite
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen import conformance as conf
from uds_assistant.testgen.model import TestCase
from uds_assistant.testgen.templates import TEMPLATES, validate_test

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(conf.__file__)
EQUIVALENCE_FILE = REPO_ROOT / "outputs" / "partD" / "mock_equivalence_D2.json"


@pytest.fixture(scope="module")
def suite(spec: EcuSpec) -> conf.ConformanceSuite:
    return conf.build_conformance_suite(spec)


@pytest.fixture(scope="module")
def tests(suite: conf.ConformanceSuite) -> list[TestCase]:
    return suite.tests


# ------------------------------------------------------------------------------- basics


def test_size_cap_ids_and_metadata(tests: list[TestCase]) -> None:
    assert 0 < len(tests) <= conf.MAX_SUITE_SIZE == 1200
    ids = [t.id for t in tests]
    assert len(ids) == len(set(ids))
    for t in tests:
        assert t.template_id == conf.CONFORMANCE_TEMPLATE_ID
        assert t.origin == "generated" and t.review_status == "validated"
        assert t.requirement_ids == []
        assert t.citations and all(c.source == "behaviour_contract" for c in t.citations)
        assert t.category in {"positive", "negative", "session", "security", "timing"}
        assert set(t.parameters) == {"setup", "stimulus", "probes"}


def test_every_case_passes_on_the_clean_simulator_and_the_oracle(
    spec: EcuSpec, tests: list[TestCase]
) -> None:
    result = run_suite(tests, spec)
    assert result.passed_count == len(tests), [r.test_id for r in result.results if not r.passed][:5]
    for t in tests[:: max(1, len(tests) // 100)]:
        assert validate_test(spec, t).ok


def test_byte_provenance_holds_for_every_case(spec: EcuSpec, tests: list[TestCase]) -> None:
    prov = check_provenance(spec, tests)
    assert prov["ok"] and prov["checked"] == prov["passed"] == len(tests)


def test_tampered_conformance_case_fails_provenance(spec: EcuSpec, tests: list[TestCase]) -> None:
    t = tests[0]
    i = next(i for i, s in enumerate(t.steps) if s.kind == "send")
    steps = list(t.steps)
    steps[i] = steps[i].model_copy(update={"expected_responses_hex": ["7f1010"]})
    assert check_test(spec, t.model_copy(update={"steps": steps}))
    bad = t.model_copy(update={"parameters": {**t.parameters, "probes": "other"}})
    assert check_test(spec, bad)


def test_generation_is_deterministic(spec: EcuSpec, tests: list[TestCase]) -> None:
    again = conf.generate_conformance_suite(spec)
    assert [t.model_dump(mode="json") for t in again] == [t.model_dump(mode="json") for t in tests]


def test_every_case_reinstantiates_from_its_parameters(spec: EcuSpec, tests: list[TestCase]) -> None:
    tpl = conf.CONFORMANCE_TEMPLATES[conf.CONFORMANCE_TEMPLATE_ID]
    for t in tests[:: max(1, len(tests) // 50)]:
        ref = tpl.instantiate(spec, t.parameters)
        assert ref.id == t.id and ref.steps == t.steps


def test_every_case_ends_with_the_fixed_probe_set(spec: EcuSpec, tests: list[TestCase]) -> None:
    n_probe_sends = (1 + sum(1 for r in spec.routines if conf.RC_RESULTS in r.allowed_subfunctions)
                     + len(spec.security_levels) + 1 + (1 if spec.dtcs else 0))
    for t in tests:
        tail = t.steps[-(n_probe_sends + 1):]
        assert [s.kind for s in tail].count("advance_time") == 1
        assert all(s.description.startswith("Probe:") for s in tail if s.kind == "send")


def test_selection_stats(suite: conf.ConformanceSuite) -> None:
    st = suite.stats
    assert st["selected"] == st["tests"] == len(suite.tests)
    assert st["phases"][0]["covered"] == st["phases"][0]["items"]  # phase 1 fully covered
    assert sum(p["added_tests"] for p in st["phases"]) == st["selected"]
    assert set(st["selected_by_family"]) >= {"10", "11", "14", "19", "22", "27", "2e", "31", "3e"}


# --------------------------------------------------------------------------- generality


def _drop_did(spec: EcuSpec) -> tuple[EcuSpec, int]:
    did = next(d for d in reversed(spec.dids) if d.write_sessions)
    return spec.model_copy(update={"dids": [d for d in spec.dids if d.id != did.id]}), did.id


def _drop_routine(spec: EcuSpec) -> tuple[EcuSpec, int]:
    rid = spec.routines[-1].id
    return spec.model_copy(update={"routines": [r for r in spec.routines if r.id != rid]}), rid


def _drop_level(spec: EcuSpec) -> tuple[EcuSpec, int]:
    lvl = spec.security_levels[-1].level
    return spec.model_copy(update={
        "security_levels": [s for s in spec.security_levels if s.level != lvl],
        "dids": [d for d in spec.dids if d.write_security_level != lvl],
        "routines": [r for r in spec.routines if r.security_level != lvl],
    }), lvl


def test_dropping_a_did_or_routine_changes_the_catalogs(spec: EcuSpec) -> None:
    base_stim = {s.id for s in conf.stimulus_catalog(spec)}
    base_setup = {s.id for s in conf.setup_catalog(spec)}
    for mutate, width in ((_drop_did, 4), (_drop_routine, 4)):
        mspec, ident = mutate(spec)
        tag = f"{ident:0{width}x}"
        stim = {s.id for s in conf.stimulus_catalog(mspec)}
        setups = {s.id for s in conf.setup_catalog(mspec)}
        assert any(tag in s for s in base_stim) and not any(tag in s for s in stim)
        assert stim < base_stim
        assert not any(tag in s for s in setups) and setups <= base_setup


def test_dropping_a_security_level_changes_the_catalogs(spec: EcuSpec) -> None:
    mspec, lvl = _drop_level(spec)
    tag = f"{lvl:02x}"
    for ids in ({s.id for s in conf.stimulus_catalog(mspec)},
                {s.id for s in conf.setup_catalog(mspec)}):
        assert not any(re.search(rf"(seed|key|u|lock|fail){tag}", i) for i in ids)
    assert any(f"u{tag}" in s.id for s in conf.setup_catalog(spec))


def test_suite_for_a_mutated_spec_is_valid_and_differs(spec: EcuSpec, tests: list[TestCase]) -> None:
    mspec, rid = _drop_routine(spec)
    mtests = conf.generate_conformance_suite(mspec)
    assert 0 < len(mtests) <= conf.MAX_SUITE_SIZE
    assert not any(f"{rid:04x}" in t.id for t in mtests)
    assert {t.id for t in mtests} != {t.id for t in tests}
    assert run_suite(mtests, mspec).passed_count == len(mtests)
    assert check_provenance(mspec, mtests)["ok"]


def test_generator_source_has_no_spec_identifier_literals(spec: EcuSpec) -> None:
    ids = {d.id for d in spec.dids} | {r.id for r in spec.routines}
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    ints = {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and type(n.value) is int}
    assert not ints & ids, sorted(ints & ids)
    text = SOURCE.read_text(encoding="utf-8").lower()
    for ident in ids:
        assert not re.search(rf"(?<![0-9a-z]){ident:04x}(?![0-9a-z])", text), f"{ident:#06x}"
        assert not re.search(rf"0x0*{ident:x}(?![0-9a-z])", text), f"{ident:#06x}"


# ----------------------------------------------------------------------- independence


def _all_bug_ids() -> set[str]:
    """Every bug id in every catalog under data/bugs/ (only this TEST reads the catalogs)."""
    from uds_assistant.simulator import load_bug_catalog

    out: set[str] = set()
    for path in sorted((REPO_ROOT / "data" / "bugs").glob("*.yaml")):
        out |= set(load_bug_catalog(path).ids)
    return out


def test_no_bug_id_in_source_tests_or_template_metadata(tests: list[TestCase]) -> None:
    bug_ids = _all_bug_ids()
    assert len(bug_ids) >= 50  # every catalog was read
    tpl = conf.CONFORMANCE_TEMPLATE
    haystacks = [SOURCE.read_text(encoding="utf-8"), tpl.id, tpl.description,
                 json.dumps([t.model_dump(mode="json") for t in tests])]
    for text in haystacks:
        hits = sorted(b for b in bug_ids if b in text)
        assert not hits, f"{len(hits)} bug id(s) found"


def test_generator_does_not_import_the_simulator() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    modules += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert modules and not any("simulator" in mod or "heldout" in mod or "bugs" in mod
                               for mod in modules)


# --------------------------------------------------------------------------- planner


def test_conformance_template_is_not_offered_to_the_planner(spec: EcuSpec) -> None:
    from uds_assistant.agent.options import build_catalog

    assert conf.CONFORMANCE_TEMPLATE_ID not in TEMPLATES
    offered = {opt.template_id for opt in build_catalog(spec)}
    assert offered == set(TEMPLATES)
    assert conf.CONFORMANCE_TEMPLATE_ID not in offered
    assert conf.resolve_template(conf.CONFORMANCE_TEMPLATE_ID) is conf.CONFORMANCE_TEMPLATE
    assert conf.resolve_template("read_did_positive") is TEMPLATES["read_did_positive"]
    assert conf.resolve_template("nope") is None and conf.resolve_template(None) is None


def mock_seed_signature(spec: EcuSpec, tmp: Path) -> dict[str, object]:
    """Ids and steps of every test the mock pipeline generates for the seed requirements."""
    from uds_assistant.agent import resolve_engine, run_pipeline
    from uds_assistant.config import Config, get_config
    from uds_assistant.eval.run_eval import load_requirements
    from uds_assistant.llm.factory import get_llm
    from uds_assistant.rag.factory import get_retriever
    from uds_assistant.rag.ingest import build_corpus
    from uds_assistant.store.audit import AuditStore

    cfg = get_config()
    llm = get_llm(Config(llm_mode="mock", retriever=cfg.retriever))
    retriever = get_retriever(cfg, chunks=build_corpus(REPO_ROOT))
    store = AuditStore(tmp / "audit.sqlite")
    engine = resolve_engine("auto")
    per_req: dict[str, str] = {}
    ids: list[str] = []
    for req in load_requirements(REPO_ROOT / "data" / "requirements_seed.csv"):
        res = run_pipeline(req["text"], req["id"], spec, llm, retriever, store, engine=engine)
        rows = [[t.id, t.template_id, json.dumps(t.parameters, sort_keys=True, default=str),
                 [s.model_dump(mode="json") for s in t.steps]] for t in res.tests]
        ids += [t.id for t in res.tests]
        per_req[req["id"]] = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    store.close()
    total = hashlib.sha256(json.dumps(per_req, sort_keys=True).encode()).hexdigest()
    return {"tests": len(ids), "test_ids": ids, "per_requirement_sha256": per_req,
            "sha256": total}


def test_mock_seed_output_unchanged(spec: EcuSpec, tmp_path: Path) -> None:
    """The mock's seed-requirement tests (ids and steps) equal the D2 before/after record."""
    recorded = json.loads(EQUIVALENCE_FILE.read_text(encoding="utf-8"))
    assert recorded["identical"] is True
    now = mock_seed_signature(spec, tmp_path)
    assert now["tests"] == recorded["after"]["tests"]
    assert now["test_ids"] == recorded["after"]["test_ids"]
    assert now["sha256"] == recorded["after"]["sha256"]
