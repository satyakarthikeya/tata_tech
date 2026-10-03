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
        "[5] Held-out evaluation headline",
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
