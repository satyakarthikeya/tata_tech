"""The timing script runs in mock mode and writes well-formed JSON."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "time_generation", ROOT / "scripts" / "time_generation.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_time_generation_mock(tmp_path: Path) -> None:
    out = tmp_path / "timing.json"
    rc = _load_script().main(
        ["--modes", "mock", "--repeats", "1", "--reqs", "REQ-001", "--out", str(out)]
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["git_hash"] and data["timestamp"]
    assert data["requirements"] == ["REQ-001"]
    (row,) = data["results"]
    assert row["mode"] == "mock" and row["requirement"] == "REQ-001"
    assert row["tests_generated"] >= 1
    assert set(row["total_s"]) == {"mean", "min", "max"}
    assert set(row["stages_s"]) == {"generate", "validate", "explain"}
    assert len(row["runs_total_s"]) == 1
