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
