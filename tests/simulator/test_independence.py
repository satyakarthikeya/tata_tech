"""The simulator must never import the rules engine (it is an independent implementation)."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[2] / "uds_assistant" / "simulator"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                # Relative import inside uds_assistant.simulator.
                parts = ["uds_assistant", "simulator"][: max(0, 3 - node.level)]
                module = ".".join([*parts, module]) if module else ".".join(parts)
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def test_simulator_sources_exist() -> None:
    assert len(list(SIM_DIR.glob("*.py"))) >= 5


def test_no_simulator_module_imports_rules() -> None:
    for path in SIM_DIR.rglob("*.py"):
        for name in _imported_modules(path):
            assert not name.startswith("uds_assistant.rules"), f"{path.name} imports {name}"
            assert name not in {"rules"} and not name.startswith("rules."), path.name
            assert "import_module" not in path.read_text(encoding="utf-8"), path.name


def test_importing_simulator_does_not_load_rules() -> None:
    """Importing the simulator package in a fresh interpreter never pulls in the rules engine."""
    code = (
        "import sys, uds_assistant.simulator as s; "
        "print(any(m.startswith('uds_assistant.rules') for m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=SIM_DIR.parents[1],
        check=True,
    )
    assert out.stdout.strip() == "False"
