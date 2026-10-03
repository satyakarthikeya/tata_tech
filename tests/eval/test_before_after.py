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
    code = ba.main(["--report", str(rep), "--out", str(out), "--sws-doc", str(sws)])
    assert code == 0 and "Part C: before / after" in out.read_text(encoding="utf-8")
