"""Structural guarantees: NRCs are decided in exactly one function, and every check is cited."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import uds_assistant.rules as rules_pkg

RULES_DIR = Path(rules_pkg.__file__).resolve().parent
NRC_ORDER = RULES_DIR / "nrc_order.py"
DECISIONS = RULES_DIR.parents[1] / "DECISIONS.md"


def _nrc_member_accesses(node: ast.AST) -> list[ast.Attribute]:
    """All ``Nrc.<MEMBER>`` attribute accesses under ``node``."""
    return [
        sub
        for sub in ast.walk(node)
        if isinstance(sub, ast.Attribute)
        and isinstance(sub.value, ast.Name)
        and sub.value.id == "Nrc"
    ]


def _functions_naming_nrc_members(path: Path) -> list[str]:
    """Names of functions (incl. nested) that access an ``Nrc.<MEMBER>`` attribute."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _nrc_member_accesses(node)
    ]


def test_exactly_one_function_in_nrc_order_returns_nrcs() -> None:
    assert _functions_naming_nrc_members(NRC_ORDER) == ["evaluate_nrc"]
    tree = ast.parse(NRC_ORDER.read_text(encoding="utf-8"))
    total = len(_nrc_member_accesses(tree))
    inside = sum(
        len(_nrc_member_accesses(n))
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "evaluate_nrc"
    )
    assert total == inside  # no NRC member used at module level either


def test_no_other_rules_module_names_an_nrc() -> None:
    for path in RULES_DIR.glob("*.py"):
        if path.name == "nrc_order.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert _nrc_member_accesses(tree) == [], path.name


def test_every_nrc_decision_has_a_source_comment() -> None:
    lines = NRC_ORDER.read_text(encoding="utf-8").splitlines()
    nrc_lines = [i for i, line in enumerate(lines) if "nrc=Nrc." in line]
    assert len(nrc_lines) >= 20
    for idx in nrc_lines:
        window = lines[max(0, idx - 30) : idx]
        assert any("# Source:" in w for w in window), f"line {idx + 1} lacks a Source comment"
    for line in lines:
        if "# Source:" in line:
            assert (
                "udsoncan behaviour" in line
                or "design decision — see DECISIONS.md" in line
                or "SWS_Dcm_" in line
            ), line


def test_cited_decision_tags_exist_in_decisions_md() -> None:
    text = NRC_ORDER.read_text(encoding="utf-8")
    decisions = DECISIONS.read_text(encoding="utf-8")
    tags = set(re.findall(r"DECISIONS\.md \[(R-[A-Za-z0-9-]+)\]", text))
    assert len(tags) >= 10
    for tag in tags:
        assert f"[{tag}]" in decisions, tag
