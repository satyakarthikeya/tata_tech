"""Exports: generated pytest files actually run (in-process and over virtual CAN); CAPL text."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from uds_assistant.export import CAPL_BANNER, render_pytest, to_capl, to_pytest
from uds_assistant.spec.schema import EcuSpec, load_spec
from uds_assistant.testgen.model import TestCase, load_tests
from uds_assistant.testgen.templates import TEMPLATES, applicable_params

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def spec() -> EcuSpec:
    return load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")


@pytest.fixture(scope="module")
def gold() -> list[TestCase]:
    return load_tests(REPO_ROOT / "data" / "gold" / "gold_tests.yaml")


@pytest.fixture(scope="module")
def generated(spec: EcuSpec) -> list[TestCase]:
    """Every option of every template (the generated tests' full byte space)."""
    return [
        TEMPLATES[tid].instantiate(spec, p)
        for tid in TEMPLATES
        for p in applicable_params(spec, tid)
    ]


def _run_pytest(path: Path, transport: str = "inprocess") -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, UDS_EXPORT_TRANSPORT=transport)
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(path), "-q", "-p", "no:cacheprovider", "-rs"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, env=env, check=False,
    )


def _exported_steps(source: str) -> dict[str, list[tuple]]:
    """Map exported test function name -> literal step list passed to run_steps()."""
    out: dict[str, list[tuple]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            call = node.body[-1].value  # type: ignore[attr-defined]
            out[node.name] = ast.literal_eval(call.args[0])
    return out


def test_exported_bytes_equal_testcase_bytes(gold: list[TestCase]) -> None:
    steps = _exported_steps(render_pytest(gold))
    assert len(steps) == len(gold)
    for test in gold:
        exported = steps["test_" + test.id]
        sends = [s for s in exported if s[0] == "send"]
        originals = [s for s in test.steps if s.kind == "send"]
        assert [(s[1], s[2]) for s in sends] == [
            (o.request_hex, o.expected_responses_hex) for o in originals
        ]
        assert len(exported) == len(test.steps)


def test_gold_export_runs_and_passes(tmp_path: Path, gold: list[TestCase]) -> None:
    path = to_pytest(gold, tmp_path / "gold_export_test.py")
    proc = _run_pytest(path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"{len(gold)} passed" in proc.stdout


def test_generated_export_runs_and_passes(tmp_path: Path, generated: list[TestCase]) -> None:
    path = to_pytest(generated, tmp_path / "generated_export_test.py")
    proc = _run_pytest(path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"{len(generated)} passed" in proc.stdout


def test_export_detects_a_wrong_expectation(tmp_path: Path, gold: list[TestCase]) -> None:
    broken = next(t for t in gold if t.id == "gold_read_vin_default").model_copy(deep=True)
    broken.steps[0].expected_responses_hex = ["7f2231"]  # type: ignore[union-attr]
    path = to_pytest([broken], tmp_path / "broken_export_test.py")
    proc = _run_pytest(path)
    assert proc.returncode != 0
    assert "1 failed" in proc.stdout


def test_export_over_virtual_can_subset(tmp_path: Path, gold: list[TestCase]) -> None:
    wanted = [
        "gold_read_vin_default",  # multi-frame ISO-TP response
        "gold_write_secured_positive_lighting",  # seed/key + write over CAN
        "gold_routine_nvm_restore_long_running",  # 7F 31 78 then final positive
        "gold_tester_present_suppressed",  # no response expected
        "gold_s3_timeout_reverts",  # has a time-advance step -> skipped in CAN mode
    ]
    subset = [t for t in gold if t.id in wanted]
    assert len(subset) == len(wanted)
    path = to_pytest(subset, tmp_path / "can_export_test.py")
    proc = _run_pytest(path, transport="can")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "4 passed, 1 skipped" in proc.stdout
    assert "time-advance step" in proc.stdout


def test_capl_export(tmp_path: Path, gold: list[TestCase]) -> None:
    path = to_capl(gold, tmp_path / "gold.can")
    text = path.read_text(encoding="utf-8")
    assert CAPL_BANNER in text.splitlines()[1]
    assert text.count("\ntestcase TC_") == len(gold)
    assert "byte req0[3] = {0x22, 0xF1, 0x90};" in text
    assert "testWaitForDiagResponse" in text and "testWaitForTimeout(5001);" in text
    assert "void MainTest()" in text
    assert text.count("{") == text.count("}")
