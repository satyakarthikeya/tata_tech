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
    assert any("Fresh v2 headline" in s for s in subheaders)
    assert any("Held-out v2 bug detection" in s for s in subheaders)
    assert any("Natural v2 requirement understanding" in s for s in subheaders)
    assert any("Held-out v1 bug detection" in s and "seen" in s for s in subheaders)
    # headline table + v2 per-bug (15) + v2 per-requirement (16)
    # + v1 per-bug (12) + natural v1 per-requirement (20)
    assert len(at.table) >= 1
    sizes = [len(df.value) for df in at.dataframe]
    for expected in (15, 16, 12, 20):
        assert expected in sizes, (expected, sizes)


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
    """The committed version-2 report must render both modes side by side."""
    import json

    from streamlit.testing.v1 import AppTest

    report = json.loads((REPO_ROOT / "outputs" / "eval_report.json").read_text(encoding="utf-8"))
    if report.get("report_version", 1) != 2 or "ollama" not in (report.get("modes") or {}):
        pytest.skip("committed report is not the version-2 mock+ollama report (v3 is covered below)")
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


# --------------------------------------------------------------------------------------------
# Part C: report version 3 (v2 headline, noise check, before/after, freeze status)
# --------------------------------------------------------------------------------------------

PREDATES = "n/a — report predates Part C"


def _det(detected: int, bugs: int) -> dict:
    return {"detected": detected, "bugs": bugs, "rate": round(detected / bugs, 4)}


def _heldout_block(bug_ids: list[str], detected: int, label: str) -> dict:
    per_bug = [
        {"bug_id": b, "category": "security", "detected": i < detected} for i, b in enumerate(bug_ids)
    ]
    n = len(bug_ids)
    return {
        "scope": label,
        "generated": {**_det(detected, n), "per_bug": per_bug},
        "gold": {**_det(1, n), "per_bug": [{**p, "detected": i < 1} for i, p in enumerate(per_bug)]},
        "union": _det(detected + 1, n),
        "analysis": {"triggers": {}, "generated": {"missed": []}, "gold": {"missed": []}},
        "supplementary": {
            "all_generated": {**_det(detected + 2, n), "tests": 9},
            "natural_v2_generated": {**_det(detected + 1, n), "tests": 4},
        },
    }


def _und_block(source: str, split: str, n: int, exact: int) -> dict:
    sp = {
        "requirements": n,
        "targets_parsed": {"exact": exact, "precision": 0.9, "recall": 0.5, "f1": 0.64},
        "targets_exercised": {"exact": exact, "f1": 0.6},
        "categories": {"micro_recall": 0.5, "macro_recall": 0.4},
        "preconditions": {"micro_recall": 0.6, "macro_recall": 0.5},
        "fallback": {"count": 1},
    }
    per_req = [
        {
            "id": f"R{i}",
            "split": split,
            "label_targets": ["0x0100"],
            "parsed": {"exact": i < exact},
            "tests": 3,
            "categories": {"missed": []},
        }
        for i in range(n)
    ]
    return {"source": source, "per_requirement": per_req, "splits": {split: sp}}


def _noise_check(deterministic: bool, n_runs: int) -> dict:
    runs = [
        {
            "run": k + 1,
            "used_for_main_tables": k == 0,
            "parsed_precision": 0.5,
            "parsed_recall": 0.6,
            "parsed_f1": 0.5 + 0.01 * k,
            "exercised_f1": 0.4,
            "category_recall_micro": 0.5,
            "precondition_recall_micro": 0.5,
            "tests_kept": 40 + k,
            "rejected": 2,
            "fallback_events": 0,
            "wall_total_s": 100.0,
        }
        for k in range(n_runs)
    ]
    out: dict = {
        "status": "completed",
        "deterministic": deterministic,
        "requested_runs": n_runs,
        "runs": runs,
        "summary": {"parsed_f1": {"n": n_runs, "mean": 0.51, "min": 0.5, "max": 0.52}},
        "note": "Run 1 feeds the tables.",
    }
    if deterministic:
        out["determinism_check"] = {"second_run_identical": True}
    return out


def _mode_block(deterministic: bool, n_runs: int) -> dict:
    return {
        "status": "completed",
        "generated_tests": {"count": 50},
        "bug_detection": {"generated": _det(25, 26), "gold": _det(20, 26)},
        "heldout_bug_detection": _heldout_block([f"v1_{i}" for i in range(12)], 10, "v1 scope"),
        "heldout_v2_bug_detection": _heldout_block([f"v2_{i}" for i in range(15)], 2, "v2 scope"),
        "requirement_understanding": _und_block("data/requirements_natural.csv", "test", 12, 5),
        "requirement_understanding_v2": _und_block(
            "data/requirements_natural_v2.csv", "test2", 16, 3
        ),
        "noise_check": _noise_check(deterministic, n_runs),
        "coverage": {
            "category_totals": {"positive": 3},
            "requirements_with_tests": 15,
            "requirements": 15,
            "rate": 1.0,
        },
        "citation_validity": {"valid": 9, "citations": 9, "rate": 1.0},
        "provenance": {"passed": 5, "checked": 5},
    }


def _freeze(ok: bool) -> dict:
    return {
        "source": "PROGRESS.md",
        "error": None,
        "all_ok": ok,
        "commit": {"recorded": "a" * 40, "head": "b" * 40, "recorded_is_ancestor_of_head": True},
        "paths": {
            "uds_assistant/testgen": {
                "expected": "c" * 40,
                "head": ("c" if ok else "d") * 40,
                "matches": ok,
                "worktree_clean": True,
            }
        },
    }


def _report(version: int = 3, ollama: bool = True, freeze_ok: bool = True) -> dict:
    modes = {"mock": _mode_block(True, 1)}
    if ollama:
        modes["ollama"] = _mode_block(False, 3)
    else:
        modes["ollama"] = {"status": "not run", "reason": "not requested"}
    rep: dict = {
        "report_version": version,
        "timestamp": "t",
        "actual_mode": "mock",
        "modes": modes,
        "simulator_rules_agreement": {"agreed": 10, "requests": 10, "rate": 1.0},
        "udsoncan_virtual_can": {"status": "pass"},
        "gold_tests": 60,
        "gold_clean_passed": 60,
        "gold_clean_pass_rate": 1.0,
        "freeze": _freeze(freeze_ok),
    }
    if version < 3:
        for blk in modes.values():
            for key in ("heldout_v2_bug_detection", "requirement_understanding_v2", "noise_check"):
                blk.pop(key, None)
        rep.pop("freeze")
    return rep


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, report: dict, before_after: str | None = None):
    import json

    from streamlit.testing.v1 import AppTest

    rp = tmp_path / "eval_report.json"
    rp.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setenv("UDS_EVAL_REPORT", str(rp))
    ba = tmp_path / "before_after.md"
    if before_after is not None:
        ba.write_text(before_after, encoding="utf-8")
    monkeypatch.setenv("UDS_BEFORE_AFTER", str(ba))
    at = AppTest.from_file(str(UI_FILE), default_timeout=60)
    at.run()
    assert not at.exception
    return at


BEFORE_AFTER = (
    "# Part C: before / after\n\nBefore = frozen baseline.\n\n"
    "| Metric | mock before | mock after |\n|---|---|---|\n| SYNTHETIC-ROW | 1 | 2 |\n"
)


def _v2_table(at):
    for df in at.dataframe:
        v = df.value
        if "Metric" in v.columns and v["Metric"].astype(str).str.startswith("A. Held-out v2").any():
            return v
    raise AssertionError("v2 headline table not found")


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_v3_report_shows_v2_headline_noise_before_after_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    at = _app(tmp_path, monkeypatch, _report(), BEFORE_AFTER)
    subheaders = [s.value for s in at.subheader]
    assert any("Fresh v2 headline" in s for s in subheaders)
    assert any("Noise check" in s for s in subheaders)
    assert any("Before / after" in s for s in subheaders)
    assert any("Freeze status" in s for s in subheaders)
    assert any("seen (templates designed against these misses)" in s for s in subheaders)
    # (a) v2 headline for both modes
    v2 = _v2_table(at)
    row_a = v2.iloc[0]
    assert "generated 2/15 (13.3%) (HEADLINE)" in row_a["mock"]
    assert "generated 2/15" in row_a["ollama"] and "union 3/15" in row_a["ollama"]
    row_b = v2.iloc[1]
    assert "test2 split (n=16)" in row_b["mock"] and "3/16" in row_b["ollama"]
    # (b) noise: every ollama run, mean and range, mock determinism check
    all_runs = [df.value for df in at.dataframe if "used for main tables" in df.value.columns]
    assert sorted(len(r) for r in all_runs) == [1, 3]
    captions = " ".join(c.value for c in at.caption)
    assert "parsed_f1: mean 0.51 (range 0.5 to 0.52, n=3)" in captions
    assert "Second run identical: True" in captions
    # (c) before/after markdown rendered (without its H1)
    md = " ".join(m.value for m in at.markdown)
    assert "SYNTHETIC-ROW" in md and "# Part C: before / after" not in md
    # (d) v1 rows are labelled seen; in-sample still labelled as tuned on
    headline = next(t.value for t in at.table if "ollama" in t.value.columns and len(t.value) == 7)
    assert "SEEN" in headline[headline["Metric"].str.startswith("4.")].iloc[0]["Metric"]
    assert "SEEN" in headline[headline["Metric"].str.startswith("5.")].iloc[0]["Metric"]
    assert "HEADLINE" not in headline[headline["Metric"].str.startswith("4.")].iloc[0]["mock"]
    assert any("tuned on" in m.label for m in at.metric)
    # (e) freeze ok
    assert any("MATCH" in s.value for s in at.success)
    assert not at.error
    # (f) comparison and retrieval sections still there (retrieval absent in the fixture: n/a)
    assert any("Mock vs Ollama" in s for s in subheaders)
    assert any("Retrieval comparison not in this report" in c.value for c in at.caption)
    assert not any("did NOT beat" in i.value for i in at.info)


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_v3_freeze_mismatch_is_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(tmp_path, monkeypatch, _report(freeze_ok=False), BEFORE_AFTER)
    assert any("MISMATCH" in e.value for e in at.error)
    assert not any('MATCH' in x.value and 'MISMATCH' not in x.value for x in at.success)
    freeze = next(df.value for df in at.dataframe if "worktree clean" in df.value.columns)
    assert list(freeze["result"]) == ["MISMATCH"]


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_v3_ollama_not_run_degrades_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    at = _app(tmp_path, monkeypatch, _report(ollama=False), before_after=None)
    v2 = _v2_table(at)
    assert set(v2["ollama"]) == {"not run yet"}
    assert "generated 2/15" in v2.iloc[0]["mock"]
    captions = " ".join(c.value for c in at.caption)
    assert "ollama: noise check not run yet" in captions
    assert "Before/after table not generated yet" in captions


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_v2_report_shows_v1_and_na_for_v2_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(tmp_path, monkeypatch, _report(version=2), BEFORE_AFTER)
    v2 = _v2_table(at)
    for col in ("mock", "ollama"):
        assert set(v2[col]) == {PREDATES}
    captions = " ".join(c.value for c in at.caption)
    assert f"Noise check: {PREDATES}" in captions
    assert f"Freeze status: {PREDATES}" in captions
    subheaders = [s.value for s in at.subheader]
    assert any("Held-out bug detection" in s for s in subheaders)
    assert any("Requirement understanding" in s for s in subheaders)
    assert not any("seen (templates designed" in s for s in subheaders)
    headline = next(t.value for t in at.table if "ollama" in t.value.columns and len(t.value) == 7)
    assert "SEEN" not in " ".join(headline["Metric"])
    assert any("did NOT beat" in i.value for i in at.info)


REQ_BRIGHTNESS = (
    "Writing the interior lighting brightness DID (0x0100) shall require extended session "
    "and security level 0x01."
)


def _generate(requirement: str = REQ_BRIGHTNESS):
    """Fresh app with a generated suite (mock LLM); the audit DB is the per-test temp DB."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(UI_FILE), default_timeout=120)
    at.run()
    at.text_area(key="req_text").set_value(requirement)
    next(b for b in at.button if b.label == "Generate tests").click().run()
    assert not at.exception
    return at


def _run(at, label: str | None = None):
    if label is not None:
        at.selectbox(key="bug_choice").select(label)
    at.radio(key="run_scope").set_value("all tests")
    next(b for b in at.button if b.label == "Run on simulator").click().run()
    assert not at.exception
    return at


def _generate_and_run(requirement: str, bug_prefix: str, bug_id: str):
    at = _run(_generate(requirement))
    clean_metric = next(m.value for m in at.metric if m.label == "Passed")
    label = next(
        o
        for o in at.selectbox(key="bug_choice").options
        if o.startswith(bug_prefix) and f" {bug_id} " in o
    )
    return _run(at, label), clean_metric


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_bug_selectbox_labels_in_sample_and_all_heldout_sets() -> None:
    """The Run tab needs generated tests; the bug dropdown lists all four catalogs."""
    from uds_assistant.simulator import HELDOUT_BUG_IDS, HELDOUT_V2_BUG_IDS, HELDOUT_V3_BUG_IDS

    at = _generate(REQ_BRIGHTNESS)
    sb = at.selectbox(key="bug_choice")
    assert sb.options[0].startswith("no bug")
    assert any(o.startswith("[in-sample]") for o in sb.options)
    for prefix, ids in (
        ("[held-out v1]", HELDOUT_BUG_IDS),
        ("[held-out v2]", HELDOUT_V2_BUG_IDS),
        ("[held-out v3, fresh]", HELDOUT_V3_BUG_IDS),
    ):
        assert len([o for o in sb.options if o.startswith(prefix)]) == len(ids), prefix


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_ui_clean_run_then_in_sample_bug_shows_expected_vs_actual() -> None:
    """The click-through of docs/UI_CHECKLIST.md (Generate, Run clean, Run with a bug), mock LLM."""
    at, clean = _generate_and_run(REQ_BRIGHTNESS, "[in-sample]", "write_ignores_value_range")
    passed, total = clean.split("/")
    assert passed == total  # clean simulator: everything passes
    res = next(df.value for df in at.dataframe if "failure" in df.value.columns)
    failed = res[res["result"] == "FAIL"]
    assert len(failed) >= 1
    assert "expected" in " ".join(failed["failure"]) and "got" in " ".join(failed["failure"])
    assert any(s.value.startswith("Bug caught by") for s in at.success)
    assert any(b.label == "Approve" for b in at.button)


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_ui_heldout_v2_bug_can_be_injected() -> None:
    at, clean = _generate_and_run(
        "The tester shall be able to read the VIN (DID 0xF190) in any diagnostic session.",
        "[held-out v2]",
        "multi_did_read_dedups_repeats",
    )
    passed, total = clean.split("/")
    assert passed == total
    assert any("failure" in df.value.columns for df in at.dataframe)


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_ui_shows_llm_backend_and_ollama_fallback_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sidebar probe says Ollama is up but the pipeline's own probe fails (closed port): the
    existing mock fallback is shown on the page as a warning instead of only in the terminal."""
    from streamlit.testing.v1 import AppTest

    from uds_assistant.ui import env

    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    monkeypatch.setattr(env, "ollama_status", lambda: (True, "Ollama reachable (patched)"))
    at = AppTest.from_file(str(UI_FILE), default_timeout=120)
    at.run()
    at.radio(key="llm_mode").set_value("ollama").run()
    at.text_area(key="req_text").set_value(REQ_BRIGHTNESS)
    next(b for b in at.button if b.label == "Generate tests").click().run()
    assert not at.exception
    assert any("LLM backend used: mock" in c.value for c in at.caption)
    assert any("falling back to the deterministic mock LLM" in w.value for w in at.warning)


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
def test_ui_default_run_reports_mock_backend_without_fallback() -> None:
    at = _generate()
    assert any("LLM backend used: mock" in c.value for c in at.caption)
    assert not any(w.value.startswith("Fallback:") for w in at.warning)


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit not installed")
@pytest.mark.parametrize(
    ("prefix", "bug_id", "test_id", "failure"),
    [
        (
            "[in-sample]",
            "write_ignores_value_range",
            "req_ui_001__tpl_write_oor_0100",
            "step 3: expected ['7f2e31'], got ['6e0100']",
        ),
        (
            "[held-out v1]",
            "seed_returned_while_unlocked",
            "req_ui_001__tpl_seed_while_unlocked_01",
            "step 3: expected ['670100000000'], got ['670132a31485']",
        ),
        (
            "[held-out v2]",
            "session_reentry_keeps_unlock",
            "req_ui_001__tpl_session_relock_01",
            "step 4: expected ['7f2e33'], got ['6e0100']",
        ),
    ],
)
def test_ui_checklist_expected_failures(
    prefix: str, bug_id: str, test_id: str, failure: str
) -> None:
    """Pins the exact screen contents quoted in docs/UI_CHECKLIST.md (Run tab)."""
    at, clean = _generate_and_run(REQ_BRIGHTNESS, prefix, bug_id)
    assert clean == "18/18"
    res = next(df.value for df in at.dataframe if "failure" in df.value.columns)
    failed = res[res["result"] == "FAIL"]
    assert list(failed["test_id"]) == [test_id]
    assert list(failed["failure"]) == [failure]
    assert next(m.value for m in at.metric if m.label == "Passed") == "17/18"
