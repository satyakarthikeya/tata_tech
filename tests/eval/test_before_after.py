"""The before / after generator: SWS parsing, the frozen baseline JSON and the rendered table."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from uds_assistant.eval import before_after as ba

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMMIT = "38aa7197d0a330f6f2f8f550fb3796ea5ae9db20"

SWS_SAMPLE = """# x
| # | what | req | engine | sws | impact |
|---|---|---|---|---|---|
| D1 | open one | `a` | `b` | `c` | medium |
| D2 | **FIXED 2026-10-03.** fixed one | `a` | `b` | `c` | high |
| D3 | open two | `a` | `b` | `c` | none |
| D4 | **FIXED 2026-10-03.** fixed two | `a` | `b` | `c` | high |

## D1 - not a table row
| D9 | stray row outside the table counts too | x | y | z | w |
"""


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    return json.loads((REPO_ROOT / ba.BASELINE_PATH).read_text(encoding="utf-8"))


def test_sws_open_count_parses_fixed_and_open_rows() -> None:
    got = ba.sws_open_count(SWS_SAMPLE)
    assert got["open_ids"] == ["D1", "D3", "D9"] and got["fixed_ids"] == ["D2", "D4"]
    assert (got["open"], got["fixed"], got["total"]) == (3, 2, 5)


def test_sws_counts_come_from_the_real_doc() -> None:
    text = (REPO_ROOT / "docs" / "SWS_DISAGREEMENTS.md").read_text(encoding="utf-8")
    got = ba.sws_open_count(text)
    assert got["total"] == 9 and got["open"] + got["fixed"] == 9
    assert got["fixed"] == sum(1 for ln in text.splitlines()
                               if ln.startswith("| D") and "**FIXED" in ln)
    assert set(got["fixed_ids"]).isdisjoint(got["open_ids"])


def test_baseline_json_values(baseline: dict[str, Any]) -> None:
    assert baseline["source"]["commit"] == BASE_COMMIT
    assert baseline["sws_disagreements"]["open"] == 9
    mock, ollama = baseline["modes"]["mock"], baseline["modes"]["ollama"]
    for blk in (mock, ollama):
        assert [blk["heldout_v1"][k]["detected"] for k in ("generated", "gold", "union")] == [3, 3, 5]
        assert blk["heldout_v1"]["generated"]["bugs"] == 12
        assert blk["understanding_v1_test"]["requirements"] == 12
        assert blk["explain_calls_per_requirement"]["derived_from_tests_kept"] is True
    assert mock["understanding_v1_test"]["parsed_precision"] == 0.9333
    assert mock["understanding_v1_test"]["parsed_fp"] == 1
    assert ollama["understanding_v1_test"]["parsed_precision"] == 0.5116
    assert ollama["understanding_v1_test"]["parsed_fp"] == 21
    assert ollama["rejected"]["total"] == 10 and mock["rejected"]["total"] == 0
    assert ollama["latency_per_requirement_s"]["mean"] == 30.785
    assert ollama["latency_per_requirement_s"]["p95"] == 43.405
    assert mock["latency_per_requirement_s"]["mean"] == 0.254


def test_baseline_json_matches_the_pre_part_c_commit(baseline: dict[str, Any]) -> None:
    def show(path: str) -> str:
        proc = subprocess.run(["git", "show", f"{BASE_COMMIT}:{path}"], cwd=REPO_ROOT,
                              capture_output=True, text=True, encoding="utf-8", check=False)
        if proc.returncode != 0:
            pytest.skip("pre-Part-C commit not available in this checkout")
        return proc.stdout

    old = json.loads(show("outputs/eval_report.json"))
    sws = ba.sws_open_count(show("docs/SWS_DISAGREEMENTS.md"))
    assert ba.extract_baseline(old, sws, BASE_COMMIT) == baseline


def _mock_only_report() -> dict[str, Any]:
    """A tiny mock-only report with just the keys the generator reads."""
    det = {k: {"detected": d, "bugs": n, "rate": d / n} for k, (d, n) in
           {"generated": (2, 15), "gold": (5, 15), "union": (5, 15)}.items()}
    split = {
        "requirements": 16,
        "targets_parsed": {"exact": 1, "precision": 0.9, "recall": 0.5, "f1": 0.6429,
                           "tp": 9, "fp": 1, "fn": 9},
        "targets_exercised": {"exact": 0, "f1": 0.4},
        "categories": {"micro_recall": 0.5, "macro_recall": 0.5},
        "preconditions": {"micro_recall": 0.6, "macro_recall": 0.6},
        "fallback": {"count": 2},
    }
    rows = [{"requirement_id": f"R{i}", "node_llm_calls": {"explain": 1}} for i in range(3)]
    mock = {
        "status": "completed",
        "heldout_v2_bug_detection": {**copy.deepcopy(det)},
        "heldout_bug_detection": {**copy.deepcopy(det)},
        "bug_detection": {**copy.deepcopy(det)},
        "requirement_understanding": {"splits": {"test": split, "dev": split}},
        "requirement_understanding_v2": {"splits": {"test2": split}},
        "pipeline": {"per_requirement": rows, "rejected": 0},
        "pipeline_natural": {"per_requirement": [], "rejected": 2},
        "pipeline_natural_v2": {"rejected": 1},
        "latency": {"per_requirement_wall_s": {"all": {"mean": 0.3, "p95": 0.6}}},
    }
    return {"timestamp": "T", "git": {"commit": "abc"}, "template_set_version": "v3",
            "modes": {"mock": mock, "ollama": {"status": "not run", "reason": "x"}}}


def test_render_on_a_mock_only_report_marks_ollama_not_run(baseline: dict[str, Any]) -> None:
    sws = ba.sws_open_count(SWS_SAMPLE)
    md = ba.render_before_after(baseline, _mock_only_report(), sws)
    lines = {ln.split("|")[1].strip(): [c.strip() for c in ln.split("|")[2:-1]]
             for ln in md.splitlines() if ln.startswith("| ") and "---" not in ln}
    v2 = lines["**Held-out v2, FRESH (15 bugs): generated / gold / union**"]
    assert v2 == ["n/a (no v2 before)", "2/15 / 5/15 / 5/15", "n/a (no v2 before)", "not run"]
    v1 = lines["Held-out v1, SEEN (12 bugs): generated / gold / union"]
    assert v1 == ["3/12 / 3/12 / 5/12", "2/15 / 5/15 / 5/15", "3/12 / 3/12 / 5/12", "not run"]
    fp = lines["Parsed precision / false positives, v1 test split (SEEN)"]
    assert fp == ["0.933 / 1 FP", "0.900 / 1 FP", "0.512 / 21 FP", "not run"]
    assert lines["Rejected planner choices (15 seed + 20 natural v1)"] == ["0", "2", "10", "not run"]
    assert lines["Rejected planner choices, natural v2 (16, FRESH)"][1] == "1"
    assert lines["Latency per requirement, mean / p95 (35 requirements)"][:2] == [
        "0.25 s / 0.45 s", "0.30 s / 0.60 s"]
    assert lines["Latency per requirement, mean / p95 (35 requirements)"][3] == "not run"
    assert lines["Explain LLM calls per requirement, mean (min-max)"][1] == "1.00 (1-1)"
    assert lines["SWS disagreements open"] == ["9", "3", "9", "3"]
    assert "**Comparability.**" in md and "no completed ollama mode" in md


def test_render_has_fixed_note_and_all_rows(baseline: dict[str, Any]) -> None:
    md = ba.render_before_after(baseline, _mock_only_report(), ba.sws_open_count(SWS_SAMPLE))
    for needle in ("no v2 before", "SEEN", "FRESH", "deterministic", "+-0.05 F1",
                   "derived from tests kept", "SWS disagreements open"):
        assert needle in md
    assert md.count("\n| ") >= 20


def test_cli_renders_from_a_report_file(tmp_path: Path) -> None:
    rep = tmp_path / "eval_report.json"
    rep.write_text(json.dumps(_mock_only_report()), encoding="utf-8")
    sws = tmp_path / "sws.md"
    sws.write_text(SWS_SAMPLE, encoding="utf-8")
    out = tmp_path / "sub" / "before_after.md"
    code = ba.main(["--part", "c", "--report", str(rep), "--out", str(out),
                    "--sws-doc", str(sws)])
    assert code == 0 and "Part C: before / after" in out.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- Part D


@pytest.fixture(scope="module")
def baseline_d() -> dict[str, Any]:
    return json.loads((REPO_ROOT / ba.BASELINE_D_PATH).read_text(encoding="utf-8"))


def test_baseline_d_values(baseline_d: dict[str, Any]) -> None:
    assert baseline_d["source"]["commit"] == ba.PART_C_FINAL_COMMIT
    assert baseline_d["sws_disagreements"]["open"] == 5
    assert baseline_d["sws_disagreements"]["open_ids"] == ["D1", "D3", "D4", "D8", "D9"]
    mock, ollama = baseline_d["modes"]["mock"], baseline_d["modes"]["ollama"]
    for blk in (mock, ollama):
        h = blk["heldout_v2"]
        assert [h[k]["detected"] for k in ("requirement_driven", "gold", "union")] == [2, 5, 5]
        assert h["full_output"] is None  # Part C had no sweep
        assert blk["understanding_v2"]["requirements"] == 16
    assert (mock["suite_sizes"]["requirement_driven"], ollama["suite_sizes"]["requirement_driven"]
            ) == (206, 66)
    v2 = ollama["understanding_v2"]
    assert v2["by_kind"]["fp"] == {"service": 25, "did": 5, "routine": 0, "dtc": 0}
    assert sum(v2["by_kind"]["fp"].values()) == v2["parsed_fp"] == 30
    assert round(v2["parsed_precision"], 3) == 0.565
    v1 = ollama["understanding_v1_test"]
    assert sum(v1["by_kind"]["fp"].values()) == v1["parsed_fp"] == 21
    assert mock["understanding_v2"]["by_kind"]["fp"] == {"service": 0, "did": 0, "routine": 0,
                                                         "dtc": 0}
    rej = ollama["rejected"]
    assert rej["seed_and_natural_v1"]["total"] == 15 and rej["natural_v2"]["total"] == 12
    assert rej["seed_and_natural_v1"]["by_reason"] == {
        "unknown_template_id": 2, "option_index_out_of_range": 3, "option_not_in_shortlist": 10,
        "duplicate_or_other": 0}
    assert rej["natural_v2"]["by_reason"]["unknown_template_id"] == 6
    assert mock["rejected"]["natural_v2"]["total"] == 0
    assert ollama["latency_per_requirement_s"] == {"n": 35, "mean": 21.369, "p95": 28.516}
    assert ollama["explain_calls_per_requirement"]["mean"] == 1.0


def test_baseline_d_matches_the_part_c_final_report(baseline_d: dict[str, Any]) -> None:
    try:
        fresh = ba.extract_baseline_d_from_git(REPO_ROOT, ba.PART_C_FINAL_COMMIT)
    except (subprocess.CalledProcessError, OSError):
        pytest.skip("Part C final commit not available in this checkout")
    assert fresh == baseline_d


def _block_d(v2_fp: dict[str, int]) -> dict[str, Any]:
    def split(fp: int) -> dict[str, Any]:
        return {
            "requirements": 2,
            "targets_parsed": {"exact": 1, "precision": 0.5, "recall": 0.5, "f1": 0.5,
                               "tp": 1, "fp": fp, "fn": 1},
            "targets_exercised": {"exact": 0, "f1": 0.4},
            "categories": {"micro_recall": 0.5, "macro_recall": 0.5},
            "preconditions": {"micro_recall": 0.6, "macro_recall": 0.6},
            "fallback": {"count": 1},
        }

    def row(rid: str, sp: str, extra: list[str]) -> dict[str, Any]:
        part = {"missed": ["did:0xF190"], "extra": extra}
        return {"id": rid, "split": sp, "label_targets": ["service:0x22", "did:0xF190"],
                "parsed": part, "exercised": part}

    def pipe(reasons: list[str]) -> dict[str, Any]:
        return {"per_requirement": [{
            "requirement_id": "R", "tests": 1, "node_llm_calls": {"explain": 1},
            "rejected_reasons": reasons}], "rejected": len(reasons)}

    det = {k: {"detected": d, "bugs": 15, "rate": d / 15, "tests": 1} for k, d in
           {"generated": 2, "gold": 5, "union": 5}.items()}
    ru2 = {"per_requirement": [row("A", "test2", ["service:0x10"] * v2_fp["service"]
                                   + ["did:0x0150"] * v2_fp["did"])],
           "splits": {"test2": split(sum(v2_fp.values()))}}
    ru1 = {"per_requirement": [row("B", "test", [])], "splits": {"test": split(0)}}
    v3 = {"bugs": 15, "full_output": {"detected": 9, "bugs": 15, "rate": 0.6},
          "requirement_driven": {"detected": 2, "bugs": 15, "rate": 0.1333},
          "conformance": {"detected": 8, "bugs": 15, "rate": 0.5333},
          "gold": {"detected": 4, "bugs": 15, "rate": 0.2667},
          "suite_sizes": {"requirement_driven": 100, "conformance": 1200, "full_output": 1300,
                          "gold": 60}}
    return {
        "status": "completed",
        "generated_tests": {"count": 100},
        "suite_sizes": {"requirement_driven": 100, "conformance": 1200, "full_output": 1300},
        "heldout_v2_bug_detection": det,
        "part_d_detection": {"heldout_v2": {"full_output": {"detected": 9, "bugs": 15}}},
        "heldout_v3_bug_detection": v3,
        "requirement_understanding": ru1,
        "requirement_understanding_v2": ru2,
        "requirement_understanding_v3": {
            "per_requirement": [row("C", "test3", ["service:0x2E"])],
            "splits": {"test3": split(1)}},
        "pipeline": pipe([]),
        "pipeline_natural": pipe(["plan: x[1]: option was not in the offered shortlist"]),
        "pipeline_natural_v2": pipe(["plan: y[0]: unknown template id 'y'"]),
        "pipeline_natural_v3": pipe(["plan: z[9]: option_index 9 out of range for z (3 options)"]),
        "latency": {"per_requirement_wall_s": {"all": {"n": 35, "mean": 0.3, "p95": 0.6}}},
        "noise_check": {"status": "not run"},
    }


def _report_d(ollama: bool) -> dict[str, Any]:
    noise = {"status": "completed", "runs": [{}, {}, {}],
             "summary": {"parsed_f1": {"mean": 0.6, "min": 0.55, "max": 0.65}}}
    modes = {"mock": _block_d({"service": 0, "did": 0}),
             "ollama": ({**_block_d({"service": 3, "did": 1}), "noise_check": noise}
                        if ollama else {"status": "not run", "reason": "x"})}
    return {"timestamp": "T", "git": {"commit": "abc"}, "template_set_version": "v3",
            "report_version": 5, "modes": modes}


def _rows(md: str) -> dict[str, list[str]]:
    return {ln.split("|")[1].strip(): [c.strip() for c in ln.split("|")[2:-1]]
            for ln in md.splitlines() if ln.startswith("| ") and "---" not in ln}


def test_render_d_on_a_mock_only_report_marks_ollama_not_run(baseline_d: dict[str, Any]) -> None:
    sws = ba.sws_open_count(SWS_SAMPLE)
    md = ba.render_before_after_d(baseline_d, _report_d(ollama=False), sws)
    rows = _rows(md)
    full = rows["**Held-out v3 bugs (15): FULL OUTPUT = requirement-driven + sweep (headline)**"]
    assert full == ["**9/15**", "not run"]
    assert rows["(b) conformance sweep alone (LLM-independent)"] == ["8/15", "not run"]
    assert rows["Suite sizes (tests)"][0] == "100 requirement-driven, 1200 sweep, 1300 full output"
    assert rows["Natural v3: parsed false positives by kind"] == ["service 1", "not run"]
    assert rows["Natural v3: rejected planner choices by reason"][0] == (
        "1 (option index out of range 1)")
    v2fp = rows["Natural v2 (SEEN): parsed false positives by kind"]
    assert v2fp == ["none", "none", "service 25, did 5", "not run"]
    full2 = rows["Held-out v2 bugs (SEEN): FULL OUTPUT (Part C had no sweep: = requirement-driven)"]
    assert full2 == ["2/15", "9/15", "2/15", "not run"]
    sizes = rows["requirement-driven / full output (Part C: no sweep)"]
    assert sizes[0] == "206 requirement-driven / 206 full output"
    assert sizes[1] == "100 requirement-driven / 1300 full output"
    assert sizes[3] == "not run"
    assert rows["SWS disagreements open"] == ["5", "3"]
    lat = rows["Latency per requirement, mean / p95"]
    assert lat[0] == "0.27 s / 0.46 s" and lat[1] == "0.30 s / 0.60 s" and lat[3] == "not run"
    assert "**Comparability.**" in md and "no completed ollama mode" in md
    for needle in ("different from the v1 and v2 sets", "SEEN", "noise", "LLM-independent"):
        assert needle in md


def test_render_d_with_ollama_shows_noise_and_both_modes(baseline_d: dict[str, Any]) -> None:
    md = ba.render_before_after_d(baseline_d, _report_d(ollama=True),
                                  ba.sws_open_count(SWS_SAMPLE))
    assert "no completed ollama mode" not in md
    rows = _rows(md)
    assert rows["Natural v3: noise check"][1] == (
        "3 run(s), parsed F1 mean 0.600 (min-max 0.550-0.650)")
    assert rows["Natural v3: parsed false positives by kind"] == ["service 1", "service 1"]


def test_cli_part_d_renders_and_make_baseline_roundtrips(
    tmp_path: Path, baseline_d: dict[str, Any]
) -> None:
    rep = tmp_path / "eval_report.json"
    rep.write_text(json.dumps(_report_d(ollama=False)), encoding="utf-8")
    sws = tmp_path / "sws.md"
    sws.write_text(SWS_SAMPLE, encoding="utf-8")
    out = tmp_path / "sub" / "before_after.md"
    code = ba.main(["--report", str(rep), "--out", str(out), "--sws-doc", str(sws)])
    assert code == 0 and "# Part D: before / after" in out.read_text(encoding="utf-8")
    try:
        old = ba._git_show(REPO_ROOT, ba.PART_C_FINAL_COMMIT, "outputs/eval_report.json")
        old_sws = ba._git_show(REPO_ROOT, ba.PART_C_FINAL_COMMIT, "docs/SWS_DISAGREEMENTS.md")
    except (subprocess.CalledProcessError, OSError):
        pytest.skip("Part C final commit not available in this checkout")
    (tmp_path / "old.json").write_text(old, encoding="utf-8")
    (tmp_path / "old_sws.md").write_text(old_sws, encoding="utf-8")
    target = tmp_path / "baseline.json"
    code = ba.main(["--part", "d", "--make-baseline", str(tmp_path / "old.json"),
                    "--baseline-sws", str(tmp_path / "old_sws.md"), "--baseline", str(target)])
    assert code == 0 and json.loads(target.read_text(encoding="utf-8")) == baseline_d
    target2 = tmp_path / "baseline2.json"
    assert ba.main(["--make-baseline-from-git", "--baseline", str(target2)]) == 0
    assert json.loads(target2.read_text(encoding="utf-8")) == baseline_d
