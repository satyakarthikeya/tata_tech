"""Smoke test: the demo script runs end to end with default arguments."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_demo_default_runs() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "demo.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    for marker in (
        "[1] Load the ECU spec",
        "[2] Pick a requirement",
        "[3] Run the suite on the CLEAN simulator",
        "[4] Inject bug",
        "[5] Evaluation headline",
    ):
        assert marker in proc.stdout
    assert "FAIL at step" in proc.stdout


def _run_demo(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    import os

    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "demo.py"), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
        env=env,
    )


def test_demo_headline_shows_both_modes() -> None:
    proc = _run_demo("--offline")
    assert proc.returncode == 0, proc.stderr
    assert "HELD-OUT bug detection (12 bugs)" in proc.stdout
    assert "mock" in proc.stdout and "ollama" in proc.stdout
    assert "did NOT beat the mock" in proc.stdout


def test_demo_llm_ollama_falls_back_to_mock_when_unreachable() -> None:
    """Point OLLAMA_HOST at a closed port so no real Ollama (or GPU) is ever touched."""
    proc = _run_demo("--llm", "ollama", env_extra={"OLLAMA_HOST": "http://127.0.0.1:9"})
    assert proc.returncode == 0, proc.stderr
    assert "WARNING" in proc.stdout
    assert "NOT ollama" in proc.stdout
    assert "llm=mock" in proc.stdout


def test_demo_heldout_v2_bug_runs_and_is_labelled() -> None:
    proc = _run_demo("--req", "REQ-006", "--bug", "write_range_upper_bound_exclusive")
    assert proc.returncode == 0, proc.stderr
    assert "Bug set: held-out v2 (FRESH" in proc.stdout
    assert "FAIL at step" in proc.stdout


def test_demo_heldout_v1_bug_is_labelled_seen() -> None:
    proc = _run_demo("--offline", "--bug", "read_did_odd_length_truncated")
    assert proc.returncode == 0, proc.stderr
    assert "Bug set: held-out v1 (SEEN" in proc.stdout


def test_demo_unknown_bug_lists_all_sets() -> None:
    proc = _run_demo("--bug", "nonsense")
    assert proc.returncode == 2
    assert "write_range_upper_bound_exclusive" in proc.stdout  # v2 ids are accepted choices


def test_demo_old_report_says_v2_not_available() -> None:
    """The committed report may be version 2 or 3; a v2 report must degrade, not crash."""
    import json

    report = json.loads((ROOT / "outputs" / "eval_report.json").read_text(encoding="utf-8"))
    proc = _run_demo("--offline")
    assert proc.returncode == 0, proc.stderr
    if report.get("report_version", 1) < 3:
        assert "Fresh v2 headline: n/a" in proc.stdout
    else:
        assert "FRESH v2 headline" in proc.stdout


def _synthetic_v3_report(path: Path) -> None:
    import json

    det = {"detected": 4, "rate": 4 / 15}
    det12 = {"detected": 9, "rate": 0.75}
    ru = {
        "requirements": 16,
        "target_exact_parsed": 7,
        "target_precision_parsed": 0.9,
        "target_recall_parsed": 0.5,
        "target_f1_parsed": 0.64,
    }
    report = {
        "report_version": 3,
        "freeze": {"all_ok": True},
        "headline": {
            "mode": "mock",
            "simulator_rules_agreement": {"agreed": 10, "total": 10},
            "gold_clean_pass": {"passed": 60, "total": 60},
            "udsoncan_virtual_can": {"status": "pass"},
            "heldout_v2_bug_detection": {
                "bugs": 15,
                "by_mode": {
                    "mock": {"generated": det, "gold": det, "union": det},
                    "ollama": "not run: not requested in this invocation",
                },
            },
            "requirement_understanding_v2": {"mock": ru, "ollama": "not run: not requested"},
            "heldout_bug_detection": {
                "bugs": 12,
                "by_mode": {
                    "mock": {"generated": det12, "gold": det12, "union": det12},
                    "ollama": "not run: not requested in this invocation",
                },
            },
            "requirement_understanding": {
                "mock": {**ru, "requirements": 12},
                "ollama": "not run: not requested",
            },
        },
        "modes": {"mock": {"noise_check": {"status": "completed", "deterministic": True,
                                           "determinism_check": {"second_run_identical": True}}}},
    }
    path.write_text(json.dumps(report), encoding="utf-8")


def test_demo_reads_v3_report_fresh_rows_first(tmp_path: Path) -> None:
    rp = tmp_path / "eval_report.json"
    _synthetic_v3_report(rp)
    proc = _run_demo(
        "--offline",
        env_extra={"UDS_EVAL_REPORT": str(rp), "UDS_BEFORE_AFTER": str(tmp_path / "missing.md")},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert out.index("FRESH v2 headline") < out.index("SEEN / tuned-on rows")
    assert "HELD-OUT v2 bug detection (15 bugs" in out
    assert "mock    generated 4/15 (26.7%)" in out
    assert "ollama  not run: not requested" in out
    assert "noise check ollama: not run yet" in out
    assert "Part C freeze: all recorded hashes match and are clean = True" in out
    assert "Before/after table: not generated yet" in out
    assert "did NOT beat" not in out  # no verdict is hard-coded for a v3 report


def test_demo_missing_report_does_not_crash(tmp_path: Path) -> None:
    proc = _run_demo("--offline", env_extra={"UDS_EVAL_REPORT": str(tmp_path / "nope.json")})
    assert proc.returncode == 0, proc.stderr
    assert "not found" in proc.stdout
