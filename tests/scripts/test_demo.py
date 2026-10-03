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
