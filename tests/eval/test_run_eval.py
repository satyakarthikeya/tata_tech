"""Evaluation: end-to-end report generation and the individual metric definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from uds_assistant.eval import metrics as m
from uds_assistant.eval import run_eval
from uds_assistant.llm import factory as llm_factory
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.spec.schema import EcuSpec, load_spec
from uds_assistant.testgen.model import Citation, SendStep, TestCase, load_tests
from uds_assistant.testgen.templates import TEMPLATES, applicable_params

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def spec() -> EcuSpec:
    return load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")


@pytest.fixture(scope="module")
def gold() -> list[TestCase]:
    return load_tests(REPO_ROOT / "data" / "gold" / "gold_tests.yaml")


@pytest.fixture(scope="module")
def full_report(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    out = tmp_path_factory.mktemp("eval_out")
    code = run_eval.main(["--mode", "mock", "--out", str(out), "--engine", "plain", "--skip-can",
                         "--skip-retrieval-compare"])
    assert code == 0
    return out, json.loads((out / "eval_report.json").read_text(encoding="utf-8"))


RATE_PATHS = [
    ("request_validity", "rate"),
    ("request_validity", "unadjusted_rate"),
    ("expected_response_accuracy", "oracle", "step_rate"),
    ("expected_response_accuracy", "oracle", "test_rate"),
    ("expected_response_accuracy", "simulator", "clean_pass_rate"),
    ("expected_response_accuracy", "gold_exact_overlap", "rate"),
    ("expected_response_accuracy", "gold_shared_prefix", "rate"),
    ("coverage", "rate"),
    ("coverage", "category_presence"),
    ("template_reuse", "rate"),
    ("citation_validity", "rate"),
    ("bug_detection", "generated", "rate"),
    ("bug_detection", "gold", "rate"),
    ("bug_detection", "union", "rate"),
    ("heldout_bug_detection", "generated", "rate"),
    ("heldout_bug_detection", "gold", "rate"),
    ("heldout_bug_detection", "union", "rate"),
    ("requirement_understanding", "splits", "test", "targets_parsed", "exact_rate"),
    ("requirement_understanding", "splits", "test", "targets_exercised", "exact_rate"),
    ("requirement_understanding", "splits", "test", "categories", "micro_recall"),
    ("requirement_understanding", "splits", "test", "preconditions", "micro_recall"),
]


def _get(d: dict[str, Any], path: tuple[str, ...]) -> Any:
    for key in path:
        d = d[key]
    return d


def test_main_writes_json_and_markdown(full_report: tuple[Path, dict[str, Any]]) -> None:
    out, report = full_report
    assert (out / "eval_report.md").exists()
    assert (out / "audit.sqlite").exists()
    for name in ("generated_tests_test.py", "gold_tests_test.py", "generated_tests.can"):
        assert (out / "exports" / name).exists()
    assert report["requested_mode"] == "mock" and report["actual_mode"] == "mock"
    assert report["modes"]["ollama"]["status"] == "not run"
    assert report["modes"]["mock"]["status"] == "completed"
    assert report["spec"]["synthetic"] is True
    assert set(report["metric_definitions"]) >= {
        "request_validity", "expected_response_accuracy", "coverage", "template_reuse_rate",
        "citation_validity", "bug_detection_rate", "pipeline_stats", "runtime",
    }
    assert report["timestamp"] and "commit" in report["git"]
    assert report["runtime_seconds"]["total"] > 0


def test_all_rates_present_and_in_unit_interval(full_report: tuple[Path, dict[str, Any]]) -> None:
    block = full_report[1]["modes"]["mock"]
    for path in RATE_PATHS:
        value = _get(block, path)
        assert value is not None, path
        assert 0.0 <= value <= 1.0, (path, value)


def test_report_is_internally_consistent(full_report: tuple[Path, dict[str, Any]]) -> None:
    report = full_report[1]
    block = report["modes"]["mock"]
    det = block["bug_detection"]
    assert det["generated"]["bugs"] == report["bug_catalog_size"] == len(det["generated"]["per_bug"])
    detected = sum(1 for b in det["generated"]["per_bug"] if b["detected"])
    assert det["generated"]["detected"] == detected
    assert det["generated"]["rate"] == pytest.approx(detected / det["generated"]["bugs"], abs=1e-4)
    assert det["union"]["detected"] >= max(det["generated"]["detected"], det["gold"]["detected"])
    assert block["generated_tests"]["count"] == block["pipeline"]["tests_kept"] > 0
    assert sum(block["coverage"]["category_totals"].values()) == block["generated_tests"]["count"]
    assert report["exports"]["run"]["passed"] is True


def test_markdown_states_synthetic_spec_and_mode(full_report: tuple[Path, dict[str, Any]]) -> None:
    text = (full_report[0] / "eval_report.md").read_text(encoding="utf-8")
    assert "The ECU spec is synthetic" in text
    assert "mode=mock" in text and "not run" in text
    assert "Bug detection per injected bug (in-sample)" in text
    assert "in-sample (templates tuned on these)" in text
    assert "## Held-out bug detection" in text
    assert "## Requirement understanding (natural requirements)" in text
    assert "pending Part B" in text
    assert "## Appendix: Self-consistency check (circular by construction)" in text
    assert "UNVERIFIED TEMPLATES" in text
    headline = text.split("## Headline metrics", 1)[1].split("\n## ", 1)[0]
    assert "accuracy vs oracle" not in headline
    order = ["1. Simulator", "2. Gold tests", "3. udsoncan", "4. Held-out", "5. Requirement",
             "6. Coverage", "7. Citation"]
    positions = [headline.index(label) for label in order]
    assert positions == sorted(positions)


def test_ollama_mode_falls_back_and_records_actual_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_factory, "ollama_reachable", lambda *a, **k: False)
    report = run_eval.run_evaluation(
        "ollama", tmp_path, "plain", requirement_ids=["REQ-001"], write_exports=False,
        run_retrieval_compare=False,
    )
    assert report["requested_mode"] == "ollama"
    assert report["actual_mode"] == "mock" and report["mode_fallback"] is True
    assert report["modes"]["ollama"]["status"] == "not run"
    assert any("not reachable" in w for w in report["setup_warnings"])
    assert "FELL BACK" in (tmp_path / "eval_report.md").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- metric units


def _manual_test(test_id: str, request_hex: str, expected: list[str]) -> TestCase:
    return TestCase(
        id=test_id, title=test_id, category="negative",
        steps=[SendStep(request_hex=request_hex, expected_responses_hex=expected)],
    )


def test_request_validity_flags_malformed_requests(spec: EcuSpec) -> None:
    ok = _manual_test("ok", "22f190", [])
    short = _manual_test("short", "22f1", [])  # truncated DID -> 0x13
    unknown_sid = _manual_test("sid", "8501", [])  # not decodable by protocol.codec
    result = m.request_validity(spec, [ok, short, unknown_sid])
    assert result["send_steps"] == 3
    assert result["decodable"] == 2
    assert result["well_formed"] == 1
    assert result["rate"] == pytest.approx(1 / 3, abs=1e-4)


def test_request_validity_exempts_declared_probes(spec: EcuSpec) -> None:
    tid = "write_did_invalid_length"
    probe = TEMPLATES[tid].instantiate(spec, applicable_params(spec, tid)[0])
    result = m.request_validity(spec, [probe])
    assert result["intentional_format_probes"] == 1
    assert result["rate"] == 1.0
    assert result["unadjusted_rate"] < 1.0


def test_expected_response_accuracy_against_oracle_and_gold(
    spec: EcuSpec, gold: list[TestCase]
) -> None:
    vin_gold = next(t for t in gold if t.id == "gold_read_vin_default")
    same = vin_gold.model_copy(update={"id": "gen_vin"}, deep=True)
    wrong = vin_gold.model_copy(update={"id": "gen_vin_wrong"}, deep=True)
    wrong.steps[0].expected_responses_hex = ["7f2231"]  # type: ignore[union-attr]
    result = m.expected_response_accuracy(spec, [same, wrong], gold, None)
    assert result["oracle"]["agreeing_steps"] == 1 and result["oracle"]["send_steps"] == 2
    assert result["gold_exact_overlap"]["overlapping_pairs"] == 2
    assert result["gold_exact_overlap"]["agreeing_pairs"] == 1


def test_template_reuse_detects_tampered_bytes(spec: EcuSpec) -> None:
    tid = "read_did_positive"
    genuine = TEMPLATES[tid].instantiate(spec, applicable_params(spec, tid)[0])
    tampered = genuine.model_copy(update={"id": "tampered"}, deep=True)
    tampered.steps[-1].expected_responses_hex = ["62f190"]  # type: ignore[union-attr]
    handmade = _manual_test("handmade", "22f190", [])
    result = m.template_reuse(spec, [genuine, tampered, handmade])
    assert result["template_instantiations"] == 1
    assert set(result["not_reproducible"]) == {"tampered", "handmade"}


def test_citation_validity_counts(spec: EcuSpec) -> None:
    corpus = build_corpus(REPO_ROOT)
    chunk = next(c for c in corpus if c.collection == "ecu_spec")
    good = Citation(source=chunk.source_path, ref=chunk.ref)
    bad = Citation(source=chunk.source_path, ref="no-such-ref")
    test = _manual_test("cit", "22f190", []).model_copy(update={"citations": [good, bad]})
    result = m.citation_validity([test], corpus)
    assert (result["citations"], result["valid"]) == (2, 1)
    assert result["tests_with_valid_citation_rate"] == 1.0


def test_coverage_table() -> None:
    a = _manual_test("a", "22f190", []).model_copy(
        update={"requirement_ids": ["R1"], "category": "positive"}
    )
    b = _manual_test("b", "22f190", []).model_copy(update={"requirement_ids": ["R1"]})
    result = m.coverage([a, b], ["R1", "R2"])
    assert result["per_requirement"]["R1"]["positive"] == 1
    assert result["per_requirement"]["R1"]["negative"] == 1
    assert result["rate"] == 0.5
    assert result["category_presence"] == pytest.approx(2 / 5)


# ----------------------------------------------------------------------------- new sections


def test_headline_keys_and_values(full_report: tuple[Path, dict[str, Any]]) -> None:
    report = full_report[1]
    head = report["headline"]
    block = report["modes"]["mock"]
    assert head["order"] == list(run_eval.HEADLINE_ORDER)
    assert [k for k in head if k in run_eval.HEADLINE_ORDER] == list(run_eval.HEADLINE_ORDER)
    agr = head["simulator_rules_agreement"]
    assert agr["total"] >= 2000 and agr["agreed"] == report["simulator_rules_agreement"]["agreed"]
    assert agr["agreed"] <= agr["total"]
    gold = head["gold_clean_pass"]
    assert gold["total"] == report["gold_tests"] == 60
    assert gold["passed"] == report["gold_clean_passed"]
    assert head["udsoncan_virtual_can"]["status"] == "skipped"  # fixture passes --skip-can
    held = head["heldout_bug_detection"]
    assert held["bugs"] == 12
    assert held["generated"]["detected"] == block["heldout_bug_detection"]["generated"]["detected"]
    ru = head["requirement_understanding"]
    assert ru["ollama"] == "pending Part B"
    assert ru["mock"]["split"] == "test" and ru["mock"]["requirements"] == 12
    tsplit = block["requirement_understanding"]["splits"]["test"]
    assert ru["mock"]["target_exact_parsed"] == tsplit["targets_parsed"]["exact"]
    assert head["citation_validity"]["valid"] == block["citation_validity"]["valid"]
    assert head["coverage"]["category_totals"] == block["coverage"]["category_totals"]


def test_heldout_section_uses_the_12_heldout_bugs(full_report: tuple[Path, dict[str, Any]]) -> None:
    from uds_assistant.simulator import HELDOUT_BUG_IDS, IMPLEMENTED_BUG_IDS

    report = full_report[1]
    held = report["modes"]["mock"]["heldout_bug_detection"]
    assert report["heldout_catalog_size"] == 12
    for suite in ("generated", "gold"):
        ids = [b["bug_id"] for b in held[suite]["per_bug"]]
        assert len(ids) == 12 and set(ids) == set(HELDOUT_BUG_IDS)
        assert not set(ids) & set(IMPLEMENTED_BUG_IDS)
        assert held[suite]["detected"] == sum(1 for b in held[suite]["per_bug"] if b["detected"])
        missed = {m["bug_id"] for m in held["analysis"][suite]["missed"]}
        assert missed == set(held[suite]["undetected"])
        assert all(m["reason"] for m in held["analysis"][suite]["missed"])
    assert held["union"]["detected"] >= max(held["generated"]["detected"], held["gold"]["detected"])
    in_sample = report["modes"]["mock"]["bug_detection"]
    assert in_sample["scope"] == run_eval.IN_SAMPLE_LABEL
    assert in_sample["generated"]["bugs"] == 26


def test_requirement_understanding_section(full_report: tuple[Path, dict[str, Any]]) -> None:
    ru = full_report[1]["modes"]["mock"]["requirement_understanding"]
    rows = ru["per_requirement"]
    assert len(rows) == 20
    assert ru["splits"]["test"]["requirements"] == 12
    assert ru["splits"]["dev"]["requirements"] == 8
    assert ru["splits"]["all"]["requirements"] == 20
    nat20 = next(r for r in rows if r["id"] == "NAT-020")
    assert nat20["label_targets"] == []
    exact = sum(1 for r in rows if r["split"] == "test" and r["parsed"]["exact"])
    assert ru["splits"]["test"]["targets_parsed"]["exact"] == exact
    fb = ru["splits"]["all"]["fallback"]
    assert fb["count"] == sum(1 for r in rows if r["fallback"])


def test_skip_retrieval_compare_recorded_as_not_run(
    full_report: tuple[Path, dict[str, Any]],
) -> None:
    out, report = full_report
    assert report["retrieval_comparison"]["status"] == "not run"
    assert "--skip-retrieval-compare" in report["retrieval_comparison"]["reason"]
    md = (out / "eval_report.md").read_text(encoding="utf-8")
    assert "## Retrieval comparison (BM25 vs Chroma)" in md
    assert "Not run:" in md
