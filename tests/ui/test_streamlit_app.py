"""Checks for the Streamlit UI that don't require streamlit to run the app.

The package must import cleanly without streamlit installed (AGENT.md: a
model/optional-dependent module uses lazy imports so the rest of the package
stays importable). ``uds_assistant/ui/streamlit_app.py`` is a script that
imports streamlit at top level (that's expected for a Streamlit script), so
instead we check: (1) nothing else in the package imports it or streamlit,
(2) the file at least compiles, and (3), only if streamlit is actually
installed, a headless smoke run via ``streamlit.testing.v1.AppTest``.
"""

from __future__ import annotations

import ast
import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_FILE = REPO_ROOT / "uds_assistant" / "ui" / "streamlit_app.py"

try:
    import streamlit  # noqa: F401

    _HAS_STREAMLIT = True
except ImportError:
    _HAS_STREAMLIT = False


def test_ui_file_compiles() -> None:
    py_compile.compile(str(UI_FILE), doraise=True)


def test_package_imports_without_streamlit() -> None:
    """``import uds_assistant`` must succeed in a fresh interpreter with
    streamlit hidden, proving no module outside ``ui/`` depends on it."""
    code = (
        "import sys, builtins\n"
        "real_import = builtins.__import__\n"
        "def blocked(name, *a, **k):\n"
        "    if name == 'streamlit' or name.startswith('streamlit.'):\n"
        "        raise ImportError('streamlit blocked for this test')\n"
        "    return real_import(name, *a, **k)\n"
        "builtins.__import__ = blocked\n"
        "import uds_assistant\n"
        "import uds_assistant.api.app\n"
        "import uds_assistant.ui\n"
        "print('OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK" in proc.stdout


def test_no_module_outside_ui_imports_streamlit() -> None:
    """AST-scan every non-ui package module for a top-level ``import streamlit``."""
    pkg_root = REPO_ROOT / "uds_assistant"
    offenders: list[str] = []
    for path in pkg_root.rglob("*.py"):
        if "ui" in path.relative_to(pkg_root).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "streamlit" for a in node.names):
                offenders.append(str(path))
            if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "streamlit":
                offenders.append(str(path))
    assert offenders == []


def test_streamlit_ast_has_module_level_import() -> None:
    """Sanity: the UI script itself does import streamlit (it's a script, not a lib)."""
    tree = ast.parse(UI_FILE.read_text(encoding="utf-8"))
    has_streamlit_import = any(
        isinstance(node, ast.Import) and any(a.name == "streamlit" for a in node.names)
        for node in tree.body
    )
    assert has_streamlit_import


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_app_runs_headless_without_exceptions() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(UI_FILE), default_timeout=60)
    at.run()
    assert not at.exception


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_app_shows_headline_heldout_and_understanding() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(UI_FILE), default_timeout=60)
    at.run()
    assert not at.exception
    subheaders = [s.value for s in at.subheader]
    assert any("Headline metrics" in s for s in subheaders)
    assert any("Held-out bug detection" in s for s in subheaders)
    assert any("Requirement understanding" in s for s in subheaders)
    # headline table (7 rows) + held-out per-bug (12) + understanding splits and per-requirement
    assert len(at.table) >= 1
    assert any(len(df.value) == 12 for df in at.dataframe)
    assert any(len(df.value) == 20 for df in at.dataframe)


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_bug_multiselect_labels_heldout_and_in_sample() -> None:
    """Run section needs generated tests, so seed session state directly."""
    from streamlit.testing.v1 import AppTest

    from uds_assistant.simulator import HELDOUT_BUG_IDS

    at = AppTest.from_file(str(UI_FILE), default_timeout=60)
    at.run()
    at.button[0].click().run()  # "Generate tests" with the default requirement
    assert not at.exception
    ms = next(m for m in at.multiselect if "Inject bug" in m.label)
    assert any(o.startswith("[in-sample]") for o in ms.options)
    held = [o for o in ms.options if o.startswith("[held-out]")]
    assert len(held) == len(HELDOUT_BUG_IDS)


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_app_tolerates_older_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A report without held-out / understanding / agreement keys must not crash the UI."""
    import json

    from streamlit.testing.v1 import AppTest

    old = {"timestamp": "x", "actual_mode": "mock", "modes": {"mock": {"generated_tests": {"count": 1}}}}
    report_path = tmp_path / "old_report.json"
    report_path.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setenv("UDS_EVAL_REPORT", str(report_path))
    at = AppTest.from_file(str(UI_FILE), default_timeout=60)
    at.run()
    assert not at.exception
    assert any("older report" in c.value for c in at.caption)


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_app_shows_mock_vs_ollama_comparison() -> None:
    """The committed report (version 2) must render both modes side by side."""
    import json

    from streamlit.testing.v1 import AppTest

    report = json.loads((REPO_ROOT / "outputs" / "eval_report.json").read_text(encoding="utf-8"))
    if report.get("report_version", 1) < 2 or "ollama" not in (report.get("modes") or {}):
        pytest.skip("committed report has no ollama mode")
    at = AppTest.from_file(str(UI_FILE), default_timeout=60)
    at.run()
    assert not at.exception
    subheaders = [s.value for s in at.subheader]
    assert any("Mock vs Ollama" in s for s in subheaders)
    assert any("Retrieval comparison" in s for s in subheaders)
    headline = next(t.value for t in at.table if "ollama" in t.value.columns)
    assert list(headline.columns) == ["Metric", "mock", "ollama"]
    assert len(headline) == 7
    held = headline[headline["Metric"].str.startswith("4.")].iloc[0]
    assert "generated 3/12 (25.0%)" in held["mock"]
    assert "generated 3/12 (25.0%)" in held["ollama"]
    comparison = next(t.value for t in at.table if t.value["Metric"].str.contains("provenance").any())
    prov = comparison[comparison["Metric"].str.contains("provenance")].iloc[0]
    assert prov["mock"] == "343/343 passed"
    assert prov["ollama"] == "158/158 passed"
    lat = comparison[comparison["Metric"].str.startswith("Wall-clock")].iloc[0]
    assert "30.785" in lat["ollama"]
    assert any("did NOT beat" in i.value for i in at.info)
    # retrieval table: dev/test/all x bm25/chroma
    assert any(len(df.value) == 6 and "MRR" in df.value.columns for df in at.dataframe)


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_app_degrades_when_only_mock_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A report with only a mock block shows n/a in the ollama column and no comparison claim."""
    import json

    from streamlit.testing.v1 import AppTest

    src = json.loads((REPO_ROOT / "outputs" / "eval_report.json").read_text(encoding="utf-8"))
    mock_only = {k: v for k, v in src.items() if k != "retrieval_comparison"}
    mock_only["modes"] = {"mock": src["modes"]["mock"]}
    path = tmp_path / "mock_only.json"
    path.write_text(json.dumps(mock_only), encoding="utf-8")
    monkeypatch.setenv("UDS_EVAL_REPORT", str(path))
    at = AppTest.from_file(str(UI_FILE), default_timeout=60)
    at.run()
    assert not at.exception
    headline = next(t.value for t in at.table if "ollama" in t.value.columns)
    assert set(headline["ollama"]) == {"n/a"}
    assert not any("did NOT beat" in i.value for i in at.info)
    assert any("Retrieval comparison not in this report" in c.value for c in at.caption)
