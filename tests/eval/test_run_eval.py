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
    ("heldout_v2_bug_detection", "generated", "rate"),
    ("heldout_v2_bug_detection", "gold", "rate"),
    ("heldout_v2_bug_detection", "union", "rate"),
    ("requirement_understanding_v2", "splits", "test2", "targets_parsed", "exact_rate"),
    ("requirement_understanding_v2", "splits", "test2", "targets_parsed", "f1"),
    ("requirement_understanding_v2", "splits", "test2", "targets_exercised", "f1"),
    ("requirement_understanding_v2", "splits", "test2", "categories", "micro_recall"),
    ("requirement_understanding_v2", "splits", "test2", "preconditions", "micro_recall"),
    ("requirement_understanding_v3", "splits", "test3", "targets_parsed", "exact_rate"),
    ("requirement_understanding_v3", "splits", "test3", "targets_parsed", "f1"),
    ("requirement_understanding_v3", "splits", "test3", "targets_exercised", "f1"),
    ("requirement_understanding_v3", "splits", "test3", "categories", "micro_recall"),
    ("requirement_understanding_v3", "splits", "test3", "preconditions", "micro_recall"),
    ("heldout_v3_bug_detection", "requirement_driven", "rate"),
    ("heldout_v3_bug_detection", "gold", "rate"),
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
    assert "not requested in this invocation (run with --mode ollama)" in text
    assert "## Mock vs Ollama — side by side" in text
    assert "## Interpretation: where the LLM helped and where it didn't" in text
    assert "## Appendix: Self-consistency check (circular by construction)" in text
    assert "UNVERIFIED TEMPLATES" in text
    headline = text.split("## Headline metrics", 1)[1].split("\n## ", 1)[0]
    assert "accuracy vs oracle" not in headline
    order = ["1. FRESH HEADLINE", "2. FRESH HEADLINE", "3. Simulator", "4. Gold tests",
             "5. udsoncan", "6. Coverage", "7. Citation", "8. Conformance sweep",
             "9. Held-out v2", "10. Requirement understanding, natural v2",
             "11. Held-out v1", "12. Requirement understanding, natural v1 test",
             "13. Requirement understanding, natural v1 dev", "14. In-sample"]
    positions = [headline.index(label) for label in order]
    assert positions == sorted(positions)
    for needle in ("Held-out v3 bugs", "FULL OUTPUT", "1a. (a) requirement-driven",
                   "1b. (b) conformance sweep alone", "1c. gold", "natural v3",
                   "2a. natural v3: parsed false positives / false negatives by kind",
                   "2b. natural v3: rejected planner choices by reason", "2c. natural v3"):
        assert needle in headline, needle
    assert "**SEEN (Part C headline; its results were known before Part D)**" in headline
    assert "**SEEN (templates designed against these misses)**" in headline
    assert "**dev (tuned on)**" in headline
    assert "**in-sample (templates tuned on these)**" in headline
    assert "Conformance sweep (size, time, runtime; no LLM)" in headline
    assert "FRESH" not in headline.split("9. Held-out v2", 1)[1].split("Rows 1-2", 1)[0]
    for heading in ("## Noise check — natural v3 (FRESH)", "### Missed held-out v2 bugs — generated suite",
                    "## Freeze verification (Part D freeze", "recorded (Part D freeze)",
                    "## Held-out v3 bug detection (15 FRESH bugs)",
                    "### Parsed false positives and false negatives by kind",
                    "### Rejected planner choices by reason", "### Trigger coverage"):
        assert heading in text, heading


def test_ollama_mode_falls_back_and_records_actual_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_factory, "ollama_reachable", lambda *a, **k: False)
    report = run_eval.run_evaluation(
        "ollama", tmp_path, "plain", requirement_ids=["REQ-001"], write_exports=False,
        run_retrieval_compare=False, conformance=False,
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
    chunk = next(c for c in corpus if c.collection == "ecu")
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
    assert ru["ollama"].startswith("not run: not requested")
    assert head["heldout_bug_detection"]["by_mode"]["mock"]["generated"]["detected"] == held["generated"]["detected"]
    assert report["provenance_ok"] is True
    prov = block["provenance"]
    assert prov["checked"] == prov["passed"] > block["generated_tests"]["count"]
    assert prov["seed"]["checked"] == block["generated_tests"]["count"]
    assert prov["natural_v2"]["checked"] == block["pipeline_natural_v2"]["tests_kept"] > 0
    assert prov["checked"] == (prov["seed"]["checked"] + prov["natural"]["checked"]
                               + prov["natural_v2"]["checked"] + prov["natural_v3"]["checked"])
    assert prov["natural_v3"]["checked"] == block["pipeline_natural_v3"]["tests_kept"] > 0
    progress = (REPO_ROOT / "PROGRESS.md").read_text(encoding="utf-8")
    recorded = run_eval.parse_freeze_table(progress, "Part D freeze")
    assert recorded["commit"] and len(recorded["paths"]) >= 7
    assert set(report["freeze"]["paths"]) == set(recorded["paths"])
    assert report["freeze"]["all_ok"] == (
        all(v["matches"] and v["worktree_clean"] for v in report["freeze"]["paths"].values())
        and report["freeze"]["commit"]["recorded_is_ancestor_of_head"] is True)
    assert report["report_version"] == run_eval.REPORT_VERSION == 5
    order = head["order"]
    assert order[:2] == ["heldout_v3_bug_detection", "requirement_understanding_v3"]
    assert order[2:7] == ["simulator_rules_agreement", "gold_clean_pass", "udsoncan_virtual_can",
                          "coverage", "citation_validity"]
    assert order[-6:] == ["heldout_v2_bug_detection", "requirement_understanding_v2",
                          "heldout_bug_detection", "requirement_understanding",
                          "requirement_understanding_dev", "in_sample_bug_detection"]
    assert report["freeze"]["section"] == "Part D freeze"
    h2 = head["heldout_v2_bug_detection"]
    assert h2["bugs"] == 15
    assert h2["generated"]["detected"] == block["heldout_v2_bug_detection"]["generated"]["detected"]
    assert h2["by_mode"]["mock"]["union"]["detected"] >= h2["by_mode"]["mock"]["generated"]["detected"]
    assert set(h2["supplementary_by_mode"]["mock"]) == {"all_generated", "natural_v2_generated"}
    assert h2["label"] == run_eval.HELDOUT_V2_LABEL and "SEEN" in h2["label"]
    assert h2["full_output_by_mode"]["mock"]["bugs"] == 15
    h3 = head["heldout_v3_bug_detection"]
    assert h3["bugs"] == 15 and h3["label"] == run_eval.HELDOUT_V3_LABEL
    m3 = block["heldout_v3_bug_detection"]
    assert h3["full_output"]["detected"] == m3["full_output"]["detected"]
    assert h3["requirement_driven"]["detected"] == m3["requirement_driven"]["detected"]
    assert h3["conformance"]["detected"] == m3["conformance"]["detected"]
    assert h3["gold"]["detected"] == m3["gold"]["detected"]
    assert h3["by_mode"]["ollama"].startswith("not run")
    assert head["conformance_sweep"]["status"] == "completed"
    assert head["conformance_sweep"]["tests"] == report["conformance"]["tests"]
    ru3 = head["requirement_understanding_v3"]
    assert ru3["mock"]["split"] == "test3" and ru3["mock"]["requirements"] == 16
    assert set(ru3["mock"]["fp_by_kind"]) >= {"service", "did", "routine"}
    assert sum(ru3["mock"]["rejected_by_reason"].values()) == ru3["mock"]["rejected"]
    ru2 = head["requirement_understanding_v2"]
    assert ru2["mock"]["split"] == "test2" and ru2["mock"]["requirements"] == 16
    assert ru2["ollama"].startswith("not run: not requested")
    assert head["requirement_understanding_dev"]["mock"]["split"] == "dev"
    assert head["in_sample_bug_detection"]["bugs"] == 26
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


# ----------------------------------------------------------------------------- B4: two modes


class _FakeOllama(llm_factory.MockLLM):
    """A mock backend posing as the Ollama client (no server needed)."""

    name = "fake-ollama"


def _patch_fake_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    real_get_llm = run_eval.get_llm

    def fake_get_llm(cfg: Any = None, **kw: Any) -> Any:
        if cfg is not None and cfg.llm_mode == "ollama":
            return _FakeOllama()
        return real_get_llm(cfg, **kw)

    monkeypatch.setattr(run_eval, "get_llm", fake_get_llm)
    monkeypatch.setattr(run_eval, "OllamaClient", _FakeOllama)


def test_ollama_mode_runs_mock_side_by_side(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fake_ollama(monkeypatch)
    report = run_eval.run_evaluation(
        "ollama", tmp_path, "plain", requirement_ids=["REQ-001"], write_exports=False,
        run_can=False, run_retrieval_compare=False, agreement_requests=20, conformance=False,
    )
    assert report["actual_mode"] == "ollama" and report["mode_fallback"] is False
    assert report["modes_run"] == ["mock", "ollama"]
    for name in ("mock", "ollama"):
        blk = report["modes"][name]
        assert blk["status"] == "completed"
        assert blk["provenance"]["ok"] and blk["provenance"]["checked"] > 0
        assert blk["latency"]["per_requirement_wall_s"]["all"]["n"] == 21
        assert blk["pipeline_natural"]["requirements"] == 20
    head = report["headline"]
    assert head["modes_completed"] == ["mock", "ollama"]
    assert isinstance(head["requirement_understanding"]["ollama"], dict)
    assert isinstance(head["heldout_bug_detection"]["by_mode"]["mock"], dict)
    md = (tmp_path / "eval_report.md").read_text(encoding="utf-8")
    assert "# Details — mode=mock" in md and "# Details — mode=ollama" in md
    assert "### Latency per requirement (wall clock)" in md
    assert "Byte provenance — all generated tests" in md


def test_no_mock_compare_skips_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fake_ollama(monkeypatch)
    report = run_eval.run_evaluation(
        "ollama", tmp_path, "plain", requirement_ids=["REQ-001"], write_exports=False,
        run_can=False, run_retrieval_compare=False, natural=False, agreement_requests=20,
        compare_mock=False, conformance=False,
    )
    assert report["modes_run"] == ["ollama"]
    assert report["modes"]["mock"]["status"] == "not run"
    assert report["baseline_comparison"] is None


def test_provenance_failure_exits_nonzero_after_writing_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import functools

    from uds_assistant.eval import provenance

    def tampered(spec: Any, tests: Any) -> dict[str, Any]:
        tests = list(tests)
        if tests:
            tests[0] = tests[0].model_copy(update={"template_id": "not_a_template"})
        return provenance.check_provenance(spec, tests)

    monkeypatch.setattr(run_eval, "check_provenance", tampered)
    monkeypatch.setattr(run_eval, "run_evaluation", functools.partial(
        run_eval.run_evaluation, requirement_ids=["REQ-001"], natural=False,
        agreement_requests=20, conformance=False))
    code = run_eval.main(["--mode", "mock", "--out", str(tmp_path), "--engine", "plain",
                          "--skip-can", "--skip-retrieval-compare", "--no-export-run"])
    assert code == run_eval.PROVENANCE_EXIT_CODE
    report = json.loads((tmp_path / "eval_report.json").read_text(encoding="utf-8"))
    assert report["provenance_ok"] is False
    fails = report["modes"]["mock"]["provenance"]["seed"]["failures"]
    assert fails and "not a registered template" in fails[0]["problems"][0]
    assert "FAILED" in (tmp_path / "eval_report.md").read_text(encoding="utf-8")


def test_percentile_nearest_rank() -> None:
    assert run_eval.percentile_nearest_rank([], 95) is None
    assert run_eval.percentile_nearest_rank([3.0], 95) == 3.0
    vals = [float(i) for i in range(1, 21)]  # 1..20
    assert run_eval.percentile_nearest_rank(vals, 95) == 19.0
    assert run_eval.percentile_nearest_rank(vals, 100) == 20.0


def test_rerender_adds_interpretation(
    full_report: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    import shutil

    src, _ = full_report
    shutil.copy(src / "eval_report.json", tmp_path / "eval_report.json")
    note = tmp_path / "interp.md"
    note.write_text("Measured prose.", encoding="utf-8")
    before = json.loads((tmp_path / "eval_report.json").read_text(encoding="utf-8"))
    run_eval.rerender(tmp_path, note)
    after = json.loads((tmp_path / "eval_report.json").read_text(encoding="utf-8"))
    assert after["interpretation"]["text"] == "Measured prose."
    assert {k: v for k, v in after.items() if k != "interpretation"} == \
        {k: v for k, v in before.items() if k != "interpretation"}
    assert "Measured prose." in (tmp_path / "eval_report.md").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- v2 sections


def test_heldout_v2_section_uses_the_15_v2_bugs(full_report: tuple[Path, dict[str, Any]]) -> None:
    from uds_assistant.simulator import HELDOUT_BUG_IDS, HELDOUT_V2_BUG_IDS, IMPLEMENTED_BUG_IDS

    report = full_report[1]
    held = report["modes"]["mock"]["heldout_v2_bug_detection"]
    assert report["heldout_v2_catalog_size"] == 15
    for suite in ("generated", "gold"):
        ids = [b["bug_id"] for b in held[suite]["per_bug"]]
        assert len(ids) == 15 and set(ids) == set(HELDOUT_V2_BUG_IDS)
        assert not set(ids) & (set(IMPLEMENTED_BUG_IDS) | set(HELDOUT_BUG_IDS))
        assert held[suite]["detected"] == sum(1 for b in held[suite]["per_bug"] if b["detected"])
    assert held["union"]["detected"] >= max(held["generated"]["detected"], held["gold"]["detected"])
    ana = held["analysis"]
    for suite in ("generated", "gold", "all_generated", "natural_v2_generated"):
        counts = ana[suite]["trigger_counts"]
        assert set(counts) == set(HELDOUT_V2_BUG_IDS) and min(counts.values()) >= 0
    missed = {m["bug_id"] for m in ana["generated"]["missed"]}
    assert missed == set(held["generated"]["undetected"])
    assert all(m["reason"] and "no trigger analysis" not in m["reason"]
               for m in ana["generated"]["missed"])
    # the headline "generated suite" is the seed-requirement suite; the supplements are others
    supp = held["supplementary"]
    n_seed = report["modes"]["mock"]["generated_tests"]["count"]
    nat2 = report["modes"]["mock"]["pipeline_natural_v2"]["tests_kept"]
    nat1 = report["modes"]["mock"]["pipeline_natural"]["tests_kept"]
    assert supp["natural_v2_generated"]["tests"] == nat2
    assert supp["all_generated"]["tests"] == n_seed + nat1 + nat2
    assert supp["all_generated"]["detected"] >= held["generated"]["detected"]
    assert held["scope"] == run_eval.HELDOUT_V2_LABEL
    # v1 stays labelled as seen
    assert report["modes"]["mock"]["heldout_bug_detection"]["label"] == run_eval.HELDOUT_V1_SEEN_LABEL


def test_natural_v2_understanding_section(full_report: tuple[Path, dict[str, Any]]) -> None:
    ru = full_report[1]["modes"]["mock"]["requirement_understanding_v2"]
    rows = ru["per_requirement"]
    assert len(rows) == 16 and {r["split"] for r in rows} == {"test2"}
    assert ru["source"] == "data/requirements_natural_v2.csv"
    assert set(ru["splits"]) == {"test2", "all"}
    assert ru["splits"]["test2"]["requirements"] == 16
    exact = sum(1 for r in rows if r["parsed"]["exact"])
    assert ru["splits"]["test2"]["targets_parsed"]["exact"] == exact
    nat16 = next(r for r in rows if r["id"] == "NAT2-016")
    assert nat16["label_targets"] == []
    # v1 layout is unchanged: test / dev / all
    assert set(full_report[1]["modes"]["mock"]["requirement_understanding"]["splits"]) == {
        "test", "dev", "all"}


def test_mock_noise_check_is_one_run_plus_determinism_check(
    full_report: tuple[Path, dict[str, Any]],
) -> None:
    nc = full_report[1]["modes"]["mock"]["noise_check"]
    assert nc["status"] == "completed" and nc["deterministic"] is True
    assert len(nc["runs"]) == 1 and nc["runs"][0]["used_for_main_tables"] is True
    assert nc["determinism_check"]["second_run_identical"] is True
    for key, sp in nc["summary"].items():
        assert sp["min"] == sp["max"] == sp["mean"], key
    assert nc["set"] == "v3"
    ru = full_report[1]["modes"]["mock"]["requirement_understanding_v3"]["splits"]["test3"]
    assert nc["runs"][0]["parsed_f1"] == ru["targets_parsed"]["f1"]


def test_explain_calls_recorded_per_requirement(full_report: tuple[Path, dict[str, Any]]) -> None:
    pipe = full_report[1]["modes"]["mock"]["pipeline"]
    assert all("explain" in r["node_llm_calls"] or r["tests"] == 0
               for r in pipe["per_requirement"])
    assert pipe["explain_llm_calls"] == sum(r["node_llm_calls"].get("explain", 0)
                                            for r in pipe["per_requirement"])


def test_freeze_table_parse_and_info(tmp_path: Path) -> None:
    import subprocess

    text = (
        "## Part C plan\n\n| `x` | `" + "a" * 40 + "` |\n\n"
        "## Part C freeze (2026)\n\n| What | Hash |\n|---|---|\n"
        "| Commit | `" + "1" * 40 + "` |\n"
        "| `pkg/frozen` tree | `" + "2" * 40 + "` |\n"
        "| `pkg/frozen/f.py` blob | `" + "3" * 40 + "` |\n\n## Next\n\n| `y` | `" + "b" * 40 + "` |\n"
    )
    parsed = run_eval.parse_freeze_table(text)
    assert parsed == {"commit": "1" * 40, "paths": {"pkg/frozen": "2" * 40,
                                                    "pkg/frozen/f.py": "3" * 40}}

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=tmp_path,
            capture_output=True, text=True, check=True).stdout.strip()

    git("init", "-q")
    (tmp_path / "pkg" / "frozen").mkdir(parents=True)
    (tmp_path / "pkg" / "frozen" / "f.py").write_text("x = 1\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "freeze")
    commit, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD:pkg/frozen")
    blob = git("rev-parse", "HEAD:pkg/frozen/f.py")

    def write_progress(tree_hash: str) -> None:
        (tmp_path / "PROGRESS.md").write_text(
            f"## Part C freeze (x)\n\n| What | Hash |\n|---|---|\n| Commit | `{commit}` |\n"
            f"| `pkg/frozen` tree | `{tree_hash}` |\n| `pkg/frozen/f.py` blob | `{blob}` |\n",
            encoding="utf-8")

    write_progress(tree)
    info = run_eval.freeze_info(tmp_path)
    assert info["all_ok"] is True and info["commit"]["recorded_is_ancestor_of_head"] is True
    write_progress("0" * 40)
    bad = run_eval.freeze_info(tmp_path)
    assert bad["all_ok"] is False and bad["paths"]["pkg/frozen"]["matches"] is False
    write_progress(tree)
    (tmp_path / "pkg" / "frozen" / "f.py").write_text("x = 2\n", encoding="utf-8")
    dirty = run_eval.freeze_info(tmp_path)
    assert dirty["all_ok"] is False and dirty["paths"]["pkg/frozen"]["worktree_clean"] is False
    (tmp_path / "PROGRESS.md").unlink()
    missing = run_eval.freeze_info(tmp_path)
    assert missing["all_ok"] is False and "not found" in missing["error"]


# ----------------------------------------------------------------------------- noise check


class _VaryingOllama(llm_factory.MockLLM):
    """A fake Ollama whose parse varies from call to call (no server needed)."""

    name = "fake-ollama-varying"

    def __init__(self) -> None:
        super().__init__()
        self.parse_calls = 0

    def complete_json(self, system: str, prompt: str, schema: Any) -> Any:
        from uds_assistant.llm.base import ParsedRequirement

        out = super().complete_json(system, prompt, schema)
        if issubclass(schema, ParsedRequirement):
            self.parse_calls += 1
            phase = self.parse_calls % 3
            data = out.model_dump()
            if phase == 0:
                data["dids"] = []
            elif phase == 2 and "0x3E" not in data["services"]:
                data["services"] = [*data["services"], "0x3E"]
            return schema.model_validate(data)
        return out


def _patch_varying_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    real_get_llm = run_eval.get_llm

    def fake_get_llm(cfg: Any = None, **kw: Any) -> Any:
        if cfg is not None and cfg.llm_mode == "ollama":
            return _VaryingOllama()
        return real_get_llm(cfg, **kw)

    monkeypatch.setattr(run_eval, "get_llm", fake_get_llm)
    monkeypatch.setattr(run_eval, "OllamaClient", _VaryingOllama)


def test_noise_runs_report_every_run_and_mean_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import statistics

    _patch_varying_ollama(monkeypatch)
    report = run_eval.run_evaluation(
        "ollama", tmp_path, "plain", requirement_ids=["REQ-001"], write_exports=False,
        run_can=False, run_retrieval_compare=False, agreement_requests=20, noise_runs=3,
        conformance=False,
    )
    nc = report["modes"]["ollama"]["noise_check"]
    assert nc["status"] == "completed" and nc["requested_runs"] == 3 and len(nc["runs"]) == 3
    assert [r["run"] for r in nc["runs"]] == [1, 2, 3]
    assert [r["used_for_main_tables"] for r in nc["runs"]] == [True, False, False]
    # run 1 is exactly the run behind the main tables
    assert nc["set"] == "v3"
    ru = report["modes"]["ollama"]["requirement_understanding_v3"]["splits"]["test3"]
    assert nc["runs"][0]["parsed_f1"] == ru["targets_parsed"]["f1"]
    assert nc["runs"][0]["tests_kept"] == report["modes"]["ollama"]["pipeline_natural_v3"]["tests_kept"]
    # natural v2 is SEEN and keeps a single run
    assert len(report["modes"]["ollama"]["requirement_understanding_v2"]["per_requirement"]) == 16
    # the fake varies, so the runs differ and the range is non-trivial
    f1s = [r["parsed_f1"] for r in nc["runs"]]
    assert len(set(f1s)) > 1
    for key in run_eval.NOISE_METRICS:
        vals = [r[key] for r in nc["runs"] if r[key] is not None]
        sp = nc["summary"][key]
        assert sp["n"] == len(vals)
        assert sp["min"] == pytest.approx(min(vals), abs=1e-4)
        assert sp["max"] == pytest.approx(max(vals), abs=1e-4)
        assert sp["mean"] == pytest.approx(statistics.fmean(vals), abs=1e-4)
    # mock was run alongside and is deterministic
    assert report["modes"]["mock"]["noise_check"]["deterministic"] is True
    # provenance: every extra run is checked and counted in the mode total
    prov = report["modes"]["ollama"]["provenance"]
    assert [e["run"] for e in prov["noise_extra_runs"]] == [2, 3]
    assert all(e["provenance"]["checked"] > 0 and e["provenance"]["ok"]
               for e in prov["noise_extra_runs"])
    assert prov["checked"] > prov["seed"]["checked"] + prov["natural"]["checked"] \
        + prov["natural_v2"]["checked"] + prov["natural_v3"]["checked"]
    assert report["provenance_ok"] is True
    md = (tmp_path / "eval_report.md").read_text(encoding="utf-8")
    assert "mean (min–max) over all runs" in md
    assert "1 (used for the main tables)" in md and "2 (extra)" in md and "3 (extra)" in md
    assert "never the best run" in md


def test_noise_runs_default_is_one_and_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_varying_ollama(monkeypatch)
    report = run_eval.run_evaluation(
        "ollama", tmp_path, "plain", requirement_ids=["REQ-001"], write_exports=False,
        run_can=False, run_retrieval_compare=False, agreement_requests=20, compare_mock=False,
        conformance=False,
    )
    nc = report["modes"]["ollama"]["noise_check"]
    assert len(nc["runs"]) == 1 and nc["requested_runs"] == 1
    assert report["modes"]["ollama"]["provenance"]["noise_extra_runs"] == []
    with pytest.raises(ValueError, match="noise_runs"):
        run_eval.run_evaluation("mock", tmp_path, noise_runs=0)
    args = run_eval.build_parser().parse_args(["--mode", "ollama", "--noise-runs", "3"])
    assert args.noise_runs == 3 and run_eval.build_parser().parse_args([]).noise_runs == 1


def test_provenance_failure_in_a_noise_run_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import functools

    from uds_assistant.eval import provenance

    _patch_varying_ollama(monkeypatch)
    nat2_calls = {"n": 0}

    def tamper_second_nat2_check(spec: Any, tests: Any) -> dict[str, Any]:
        tests = list(tests)
        if tests and any(r.startswith("NAT3") for r in tests[0].requirement_ids):
            nat2_calls["n"] += 1
            if nat2_calls["n"] == 2:  # run 1 (in the noise check) is call 1, extra run 2 is call 2
                tests[0] = tests[0].model_copy(update={"template_id": "not_a_template"})
        return provenance.check_provenance(spec, tests)

    monkeypatch.setattr(run_eval, "check_provenance", tamper_second_nat2_check)
    monkeypatch.setattr(run_eval, "run_evaluation", functools.partial(
        run_eval.run_evaluation, requirement_ids=["REQ-001"], agreement_requests=20,
        conformance=False))
    code = run_eval.main(["--mode", "ollama", "--out", str(tmp_path), "--engine", "plain",
                          "--skip-can", "--skip-retrieval-compare", "--no-export-run",
                          "--no-mock-compare", "--noise-runs", "3"])
    assert code == run_eval.PROVENANCE_EXIT_CODE
    report = json.loads((tmp_path / "eval_report.json").read_text(encoding="utf-8"))
    assert report["provenance_ok"] is False
    extra = report["modes"]["ollama"]["provenance"]["noise_extra_runs"]
    assert extra[0]["provenance"]["ok"] is False and extra[1]["provenance"]["ok"] is True
    assert "FAILED" in (tmp_path / "eval_report.md").read_text(encoding="utf-8")


def test_rerender_with_before_after_flag(
    full_report: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    import shutil

    shutil.copy(full_report[0] / "eval_report.json", tmp_path / "eval_report.json")
    code = run_eval.main(["--rerender", "--out", str(tmp_path), "--before-after"])
    assert code == 0
    assert (tmp_path / "partD" / "before_after.md").exists()
    assert not (tmp_path / "partC").exists()


def test_before_after_from_the_full_mock_report(
    full_report: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    import shutil

    shutil.copy(full_report[0] / "eval_report.json", tmp_path / "eval_report.json")
    target = run_eval.write_before_after(tmp_path)
    assert target == tmp_path / "partD" / "before_after.md"
    md = target.read_text(encoding="utf-8")
    block = full_report[1]["modes"]["mock"]
    v3 = block["heldout_v3_bug_detection"]
    rows = {ln.split("|")[1].strip(): [c.strip() for c in ln.split("|")[2:-1]]
            for ln in md.splitlines() if ln.startswith("| ") and "---" not in ln}
    full = rows["**Held-out v3 bugs (15): FULL OUTPUT = requirement-driven + sweep (headline)**"]
    assert full == [f"**{v3['full_output']['detected']}/15**", "not run"]
    assert rows["(a) requirement-driven only (comparable with Part C)"][0] == (
        f"{v3['requirement_driven']['detected']}/15")
    assert rows["(b) conformance sweep alone (LLM-independent)"][0] == (
        f"{v3['conformance']['detected']}/15")
    assert rows["(d) gold (LLM-independent)"][0] == f"{v3['gold']['detected']}/15"
    v2req = rows["Held-out v2 bugs (15, SEEN): requirement-driven (generated)"]
    assert v2req[1] == f"{block['heldout_v2_bug_detection']['generated']['detected']}/15"
    assert v2req[3] == "not run" and v2req[0] == "2/15" and v2req[2] == "2/15"
    from uds_assistant.eval import before_after as ba

    n_open = ba.sws_open_count(
        (REPO_ROOT / "docs" / "SWS_DISAGREEMENTS.md").read_text(encoding="utf-8"))["open"]
    assert rows["SWS disagreements open"] == ["5", str(n_open)]
    assert n_open == 5
    for needle in ("(i) FRESH v3 rows", "(ii) SEEN v2 rows", "(iii) Rejected planner choices",
                   "(iv) Parsed false positives by kind", "(v) Latency and explain calls",
                   "(vi) SWS disagreements", "(vii) Test counts", "**Comparability.**",
                   "no completed ollama mode"):
        assert needle in md, needle


def test_summary_lines_lead_with_fresh_v3(full_report: tuple[Path, dict[str, Any]]) -> None:
    lines = run_eval.summary_lines(full_report[1])
    assert lines[0].startswith("mode=mock FRESH held-out v3 bugs (15): FULL OUTPUT (headline)")
    assert "(b) conformance sweep alone" in lines[0] and "gold " in lines[0]
    assert lines[1].startswith("mode=mock FRESH natural v3 (test3) understanding: parsed exact")
    assert "parsed FP by kind [" in lines[1] and "FN by kind [" in lines[1]
    assert any(ln.startswith("mode=mock SEEN:") for ln in lines)


# ----------------------------------------------------------------------------- Part D (D2)


def test_part_d_conformance_rows(full_report: tuple[Path, dict[str, Any]]) -> None:
    """Structure only: (a) requirement-driven, (b) conformance sweep, (c) = (a) union (b)."""
    out, report = full_report
    conf = report["conformance"]
    assert conf["status"] == "completed" and conf["llm_independent"] is True
    assert 0 < conf["tests"] <= 1200 and conf["clean_simulator_passed"] == conf["tests"]
    assert conf["provenance"]["ok"] and conf["provenance"]["checked"] == conf["tests"]
    assert conf["bug_matrix_runtime_s"]["total"] > 0 and conf["generation_s"] > 0
    assert set(report["part_d_catalogs"]) >= {"heldout_v2", "heldout_v1", "in_sample"}
    block = report["modes"]["mock"]
    pdd = block["part_d_detection"]
    assert set(pdd) == set(report["part_d_catalogs"])
    v2 = pdd["heldout_v2"]
    assert v2["requirement_driven"]["detected"] == (
        block["heldout_v2_bug_detection"]["generated"]["detected"])
    assert pdd["heldout_v1"]["requirement_driven"]["detected"] == (
        block["heldout_bug_detection"]["generated"]["detected"])
    assert pdd["in_sample"]["requirement_driven"]["detected"] == (
        block["bug_detection"]["generated"]["detected"])
    for row in pdd.values():
        a, b, c = row["requirement_driven"], row["conformance"], row["full_output"]
        assert max(a["detected"], b["detected"]) <= c["detected"] <= a["detected"] + b["detected"]
        assert c["bugs"] == a["bugs"] == b["bugs"]
    assert report["conformance"]["detection"]["heldout_v2"]["detected"] == v2["conformance"]["detected"]
    assert "part_d_detection" in report["metric_definitions"]
    md = (out / "eval_report.md").read_text(encoding="utf-8")
    assert "## Part D — conformance sweep and full-output bug detection" in md
    assert "identical in every mode" in md


def test_union_from_detections_and_catalog_hook() -> None:
    a = {"tests": 2, "per_bug": [{"bug_id": "x", "detected": True},
                                 {"bug_id": "y", "detected": False},
                                 {"bug_id": "z", "detected": False}]}
    b = {"tests": 3, "per_bug": [{"bug_id": "x", "detected": False},
                                 {"bug_id": "y", "detected": True},
                                 {"bug_id": "z", "detected": False}]}
    u = run_eval.union_from_detections(a, b)
    assert u["detected"] == 2 and u["undetected"] == ["z"] and u["tests"] == 5
    assert u["only_requirement_driven"] == ["x"] and u["only_conformance"] == ["y"]
    from uds_assistant.simulator import load_bug_catalog

    cats = run_eval.resolve_part_d_catalogs(load_bug_catalog())
    assert list(cats)[:3] == ["heldout_v2", "heldout_v1", "in_sample"]
    keys = [k for k, _l, _a in run_eval.PART_D_CATALOGS]
    assert "heldout_v3" in keys  # the hook for a later fresh set (skipped while absent)


def test_freeze_info_prefers_the_part_d_table(tmp_path: Path) -> None:
    """When both tables exist the newest ("Part D freeze") is used; "Part C freeze" is the fallback."""
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=tmp_path,
            capture_output=True, text=True, check=True).stdout.strip()

    git("init", "-q")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "f.py").write_text("x = 1\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "freeze")
    commit, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD:pkg")
    old = ("## Part C freeze (old)\n\n| What | Hash |\n|---|---|\n"
           f"| Commit | `{commit}` |\n| `pkg` tree | `{'0' * 40}` |\n\n")
    new = ("## Part D freeze (new)\n\n| What | Hash |\n|---|---|\n"
           f"| Commit | `{commit}` |\n| `pkg` tree | `{tree}` |\n")
    (tmp_path / "PROGRESS.md").write_text(old + new, encoding="utf-8")
    info = run_eval.freeze_info(tmp_path)
    assert info["section"] == "Part D freeze" and info["all_ok"] is True
    (tmp_path / "PROGRESS.md").write_text(old, encoding="utf-8")
    fallback = run_eval.freeze_info(tmp_path)
    assert fallback["section"] == "Part C freeze" and fallback["all_ok"] is False
    (tmp_path / "PROGRESS.md").write_text("nothing here\n", encoding="utf-8")
    missing = run_eval.freeze_info(tmp_path)
    assert missing["all_ok"] is False and "no hash table" in missing["error"]


# ----------------------------------------------------------------------------- Part D (D5a)


def test_heldout_v3_block_structure(full_report: tuple[Path, dict[str, Any]]) -> None:
    from uds_assistant.simulator import (
        HELDOUT_BUG_IDS,
        HELDOUT_V2_BUG_IDS,
        HELDOUT_V3_BUG_IDS,
        IMPLEMENTED_BUG_IDS,
    )

    report = full_report[1]
    block = report["modes"]["mock"]
    held = block["heldout_v3_bug_detection"]
    assert report["heldout_v3_catalog_size"] == held["bugs"] == 15
    ids = [b["bug_id"] for b in held["per_bug"]]
    assert set(ids) == set(HELDOUT_V3_BUG_IDS) and len(ids) == 15
    assert not set(ids) & (set(IMPLEMENTED_BUG_IDS) | set(HELDOUT_BUG_IDS) | set(HELDOUT_V2_BUG_IDS))
    assert held["scope"] == run_eval.HELDOUT_V3_LABEL and "FRESH" in held["scope"]
    a, b, c = held["requirement_driven"], held["conformance"], held["full_output"]
    assert max(a["detected"], b["detected"]) <= c["detected"] <= a["detected"] + b["detected"]
    assert held["headline_suite"] == "full_output"
    # per-bug flags agree with the totals
    assert sum(1 for x in held["per_bug"] if x["requirement_driven"]) == a["detected"]
    assert sum(1 for x in held["per_bug"] if x["conformance"]) == b["detected"]
    assert sum(1 for x in held["per_bug"] if x["full_output"]) == c["detected"]
    assert sum(1 for x in held["per_bug"] if x["gold"]) == held["gold"]["detected"]
    for x in held["per_bug"]:
        assert x["full_output"] == (x["requirement_driven"] or x["conformance"])
        assert set(x["detected_by"]) <= {"requirement_driven", "conformance", "gold"}
        assert set(x["trigger_counts"]) >= {"requirement_driven", "conformance", "full_output",
                                            "gold", "all_generated", "natural_v3_generated"}
        assert min(x["trigger_counts"].values()) >= 0
        assert (x["reason_if_missed"] is None) == bool(x["full_output"])
    # every miss has a one-line reason from the v3 trigger table
    missed = {x["bug_id"] for x in held["missed_by_headline"]}
    assert missed == set(c["undetected"])
    assert all(x["reason"] and "no trigger analysis" not in x["reason"]
               for x in held["missed_by_headline"])
    # (a) is exactly the Part D requirement-driven row, (b) the sweep's own detection
    pdd = block["part_d_detection"]["heldout_v3"]
    assert pdd["requirement_driven"]["detected"] == a["detected"]
    assert pdd["conformance"]["detected"] == b["detected"]
    assert pdd["gold"]["detected"] == held["gold"]["detected"]
    assert report["conformance"]["detection"]["heldout_v3"]["detected"] == b["detected"]
    assert held["suite_sizes"]["full_output"] == (
        block["generated_tests"]["count"] + report["conformance"]["tests"])
    assert block["suite_sizes"] == {**block["suite_sizes"], "requirement_driven":
                                    block["generated_tests"]["count"]}
    # supplementary rows use their own suites
    supp = held["supplementary"]
    nat3 = block["pipeline_natural_v3"]["tests_kept"]
    assert supp["natural_v3_generated"]["tests"] == nat3
    assert supp["all_generated"]["tests"] == (
        block["generated_tests"]["count"] + block["pipeline_natural"]["tests_kept"]
        + block["pipeline_natural_v2"]["tests_kept"] + nat3)
    tsum = held["trigger_summary"]["full_output"]
    assert tsum["bugs"] == 15 and 0 <= tsum["bugs_with_stimulus"] <= 15


def test_natural_v3_understanding_and_breakdowns(
    full_report: tuple[Path, dict[str, Any]],
) -> None:
    report = full_report[1]
    block = report["modes"]["mock"]
    ru = block["requirement_understanding_v3"]
    rows = ru["per_requirement"]
    assert len(rows) == 16 and {r["split"] for r in rows} == {"test3"}
    assert ru["source"] == "data/requirements_natural_v3.csv" and ru["seen"] is False
    assert set(ru["splits"]) == {"test3", "all"}
    assert block["requirement_understanding_v2"]["seen"] is True
    # FP / FN by kind add up to the totals
    split = ru["splits"]["test3"]
    kinds = split["by_kind"]["parsed"]
    assert {"service", "did", "routine", "dtc"} <= set(kinds)
    assert sum(v["fp"] for v in kinds.values()) == split["targets_parsed"]["fp"]
    assert sum(v["fn"] for v in kinds.values()) == split["targets_parsed"]["fn"]
    assert sum(v["tp"] for v in kinds.values()) == split["targets_parsed"]["tp"]
    # rejections by reason add up in every set
    for key in ("pipeline", "pipeline_natural", "pipeline_natural_v2", "pipeline_natural_v3"):
        pipe = block[key]
        assert set(pipe["rejected_by_reason"]) == {
            "unknown_template_id", "option_index_out_of_range", "option_not_in_shortlist",
            "duplicate_or_other"}
        assert sum(pipe["rejected_by_reason"].values()) == pipe["rejected"]
    assert report["natural_requirements_v3"] == 16
    assert "natural_v3_understanding" in report["metric_definitions"]
    assert {"by_kind", "rejected_by_reason", "seen_sets"} <= set(report["metric_definitions"])
    pipe3 = block["pipeline_natural_v3"]
    assert {r["split"] for r in pipe3["per_requirement"]} == {"test3"}
    latency = block["latency"]["per_requirement_wall_s"]
    assert latency["natural_v3"]["n"] == 16 and latency["all_with_v3"]["n"] == 67


def test_v3_quick_run_without_sweep_and_natural(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--skip-conformance style: the v3 block reports (a) and gold; (b) / (c) are 'not run'."""
    monkeypatch.setattr(llm_factory, "ollama_reachable", lambda *a, **k: False)
    report = run_eval.run_evaluation(
        "mock", tmp_path, "plain", requirement_ids=["REQ-001"], write_exports=False,
        run_can=False, run_retrieval_compare=False, agreement_requests=20, natural=False,
        conformance=False)
    held = report["modes"]["mock"]["heldout_v3_bug_detection"]
    assert isinstance(held["requirement_driven"], dict) and isinstance(held["gold"], dict)
    assert held["conformance"].startswith("not run") and held["full_output"].startswith("not run")
    assert held["headline_suite"] == "requirement_driven"
    assert all(b["full_output"] is None and b["conformance"] is None for b in held["per_bug"])
    assert held["supplementary"]["natural_v3_generated"].startswith("not run")
    assert report["modes"]["mock"]["requirement_understanding_v3"] == {"status": "not run"}
    assert report["modes"]["mock"]["part_d_detection"]["status"].startswith("not run")
    head = report["headline"]
    assert head["requirement_understanding_v3"]["mock"] == {"status": "not run"}
    assert head["conformance_sweep"]["status"] == "not run"
    md = (tmp_path / "eval_report.md").read_text(encoding="utf-8")
    assert "not run (conformance sweep skipped)" in md
    # the Part D before/after also renders on this stripped report
    assert run_eval.write_before_after(tmp_path).exists()


def test_new_cli_defaults_and_help() -> None:
    parser = run_eval.build_parser()
    text = parser.format_help()
    assert "natural v3" in text and "partD/before_after.md" in text
    args = parser.parse_args(["--mode", "ollama", "--noise-runs", "3", "--before-after"])
    assert args.noise_runs == 3 and args.before_after is True and args.mode == "ollama"
    assert [ns.key for ns in run_eval.NATURAL_SETS] == ["v1", "v2", "v3"]
    assert run_eval.NOISE_SET == "v3"
    assert [ns.seen for ns in run_eval.NATURAL_SETS] == [True, True, False]
