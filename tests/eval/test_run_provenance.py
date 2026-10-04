"""Run provenance, History placement, Q&A and timing sections of the evaluation report (E2)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from uds_assistant.eval import run_eval
from uds_assistant.eval.run_provenance import run_tag, short_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "outputs"
NEEDED = [OUT / "eval_report.json", OUT / "qa" / "qa_eval.json",
          OUT / "timing" / "tool_timing.json", OUT / "partC" / "before_after.md",
          OUT / "partD" / "before_after.md"]

pytestmark = pytest.mark.skipif(not all(p.exists() for p in NEEDED),
                                reason="committed outputs/ artifacts are missing")


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any], str]:
    out = tmp_path_factory.mktemp("rerender")
    for p in NEEDED:
        dest = out / p.relative_to(OUT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, dest)
    # start from the stored report without the extras so the test exercises the attach step
    rep = json.loads((out / "eval_report.json").read_text(encoding="utf-8"))
    for k in ("provenance", "qa", "timing", "history", "headline_cards", "success_metrics"):
        rep.pop(k, None)
    (out / "eval_report.json").write_text(json.dumps(rep), encoding="utf-8")
    assert run_eval.main(["--rerender", "--out", str(out)]) == 0
    report = json.loads((out / "eval_report.json").read_text(encoding="utf-8"))
    return out, report, (out / "eval_report.md").read_text(encoding="utf-8")


def test_short_hash_and_run_tag() -> None:
    assert short_hash("9e66f7a4d7ac4ee7a35a3edd8eb40683c5162f32") == "9e66f7a"
    assert short_hash("3a8c4e36c4244b45fa0b300aa683d7cf2519eec4+dirty") == "3a8c4e3+dirty"
    assert short_hash(None) == "n/a"
    tag = run_tag({"date": "2026-10-04", "git_short": "abc1234", "dirty": True})
    assert "2026-10-04" in tag and "abc1234" in tag and "uncommitted" in tag


def test_report_starts_with_run_provenance(rendered: tuple[Path, dict[str, Any], str]) -> None:
    _, report, md = rendered
    lines = md.splitlines()
    assert lines[0].startswith("# Evaluation report")
    assert lines[2] == "## Run provenance"
    block = md.split("## Run provenance", 1)[1].split("\n## ", 1)[0]
    prov = report["provenance"]
    for key in ("main_eval", "qa", "timing"):
        assert prov[key]["git_short"] in block
        assert prov[key]["timestamp"] in block


def test_every_section_header_states_its_run(rendered: tuple[Path, dict[str, Any], str]) -> None:
    _, report, md = rendered
    main_tag = run_tag(report["provenance"]["main_eval"])
    headers = [ln for ln in md.splitlines() if ln.startswith(("# ", "## "))]
    exempt = ("# Evaluation report", "## Run provenance", "## History",
              "## Ollama explain fallback events")  # the E1 note carries its own date and hash
    for h in headers:
        if h.startswith(exempt):
            continue
        assert " — run " in h, h
    qa_h = next(h for h in headers if h.startswith("## Diagnostic Q&A"))
    tm_h = next(h for h in headers if h.startswith("## Tool-side timing"))
    assert run_tag(report["provenance"]["qa"]) in qa_h
    assert run_tag(report["provenance"]["timing"]) in tm_h
    assert main_tag in next(h for h in headers if h.startswith("## Headline metrics"))
    assert main_tag not in qa_h and main_tag not in tm_h


def test_history_is_last_and_labelled_historical(
        rendered: tuple[Path, dict[str, Any], str]) -> None:
    _, report, md = rendered
    top = [ln for ln in md.splitlines() if ln.startswith("## ")]
    assert top[-1] == "## History"
    before, history = md.split("\n## History\n", 1)
    assert "Part C: before / after" not in before and "Part D: before / after" not in before
    assert "before / after" in history
    subs = [ln for ln in history.splitlines() if ln.startswith("### ") and "before / after" in ln]
    assert len(subs) == 2 and all("**historical**" in s for s in subs)
    for key in ("part_c", "part_d"):
        for h in report["history"][key]["run_hashes"]:
            assert h in history
    assert re.search(r"Headline metrics — run", before)


def test_qa_and_timing_sections_match_their_json(
        rendered: tuple[Path, dict[str, Any], str]) -> None:
    _, _, md = rendered
    qa = json.loads((OUT / "qa" / "qa_eval.json").read_text(encoding="utf-8"))["results"]
    sec = md.split("## Diagnostic Q&A", 1)[1].split("\n## ", 1)[0]
    for r in qa.values():
        assert f"{r['answer_accuracy'] * 100:.1f}% ({r['answer_accuracy_n']}/{r['n_answerable']})" in sec
        assert str(r["fallback_events"]) in sec
    tm = json.loads((OUT / "timing" / "tool_timing.json").read_text(encoding="utf-8"))
    tsec = md.split("## Tool-side timing", 1)[1].split("\n## ", 1)[0]
    first = tm["results"][0]
    assert f"{first['total_s']['mean']} s" in tsec
    assert "pending owner measurement" in tsec


def test_json_extras(rendered: tuple[Path, dict[str, Any], str]) -> None:
    _, report, _ = rendered
    prov = report["provenance"]
    assert set(prov) >= {"main_eval", "qa", "timing", "history"}
    assert prov["qa"]["git_commit"] == json.loads(
        (OUT / "qa" / "qa_eval.json").read_text(encoding="utf-8"))["git_hash"]
    assert report["history"]["part_d"]["label"] == "historical"
    assert set(report["qa"]["modes"]) == {"mock", "ollama"}
    assert "mean_of_requirement_means_s" in report["timing"]["modes"]["mock"]
    cards = {c["id"]: c for c in report["headline_cards"]}
    full = cards["v3_bugs_full_output"]
    assert full["run"] == "main_eval" and full["git_short"] == prov["main_eval"]["git_short"]
    for m, blk in report["modes"].items():
        r = blk["part_d_detection"]["heldout_v3"]["full_output"]
        assert full["values"][m]["detected"] == r["detected"]
    assert cards["qa_answer_accuracy"]["run"] == "qa"
    assert cards["timing_mean_s"]["run"] == "timing"
    ids = {m["id"] for m in report["success_metrics"]}
    assert ids == {"test_design_time", "generation_accuracy", "coverage", "reuse_rate",
                   "defect_detection"}
    assert next(m for m in report["success_metrics"]
                if m["id"] == "test_design_time")["manual_comparison"] == "pending owner measurement"


def test_missing_inputs_are_omitted_not_invented(tmp_path: Path) -> None:
    shutil.copy(OUT / "eval_report.json", tmp_path / "eval_report.json")
    assert run_eval.main(["--rerender", "--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "eval_report.json").read_text(encoding="utf-8"))
    assert report["provenance"]["qa"] is None and "qa" not in report
    assert report["provenance"]["timing"] is None and "timing" not in report
    assert report["history"] == {}
    md = (tmp_path / "eval_report.md").read_text(encoding="utf-8")
    assert "## Diagnostic Q&A" not in md and "## Tool-side timing" not in md
    assert "No historical tables found" in md
    tm_row = next(m for m in report["success_metrics"] if m["id"] == "test_design_time")
    assert tm_row["values"] == {} and tm_row["status"].startswith("not measured")
