"""Streamlit engineering UI for the UDS diagnostics assistant.

Run with::

    streamlit run uds_assistant/ui/streamlit_app.py

Flow: enter a plain-English requirement -> generate cited, validated test
cases -> review them (categories, request/response hex, citations, review
status) -> run them on the ECU simulator, optionally with injected bugs ->
inspect results -> view the mock vs ollama evaluation report -> export to
pytest/CAPL.

This module calls the pipeline directly (no network hop to the FastAPI
service) and talks to the same :mod:`uds_assistant.store.audit` audit trail.
Nothing else in ``uds_assistant`` imports this module, so the package stays
importable without streamlit installed (see ``uds_assistant/ui/__init__.py``
and ``tests/ui/test_streamlit_app.py``).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import streamlit as st

from uds_assistant.agent import run_pipeline
from uds_assistant.config import get_config
from uds_assistant.export import render_capl, render_pytest
from uds_assistant.llm.factory import get_llm
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.runner import run_suite
from uds_assistant.simulator import (
    HELDOUT_BUG_CATALOG_PATH,
    HELDOUT_BUG_IDS,
    HELDOUT_V2_BUG_CATALOG_PATH,
    HELDOUT_V2_BUG_IDS,
    load_bug_catalog,
)
from uds_assistant.spec.schema import load_spec
from uds_assistant.store.audit import AuditStore

REPO_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_BANNER = (
    "Generated tests require human review before execution on real hardware. "
    "The ECU spec is synthetic. Audit trail: outputs/ui_audit.sqlite."
)


@st.cache_resource
def _load_backend() -> dict[str, object]:
    cfg = get_config()
    spec = load_spec(REPO_ROOT / "data" / "bcm_spec.yaml")
    corpus = build_corpus(REPO_ROOT)
    retriever = get_retriever(cfg, chunks=corpus)
    llm = get_llm(cfg)
    store = AuditStore(REPO_ROOT / "outputs" / "ui_audit.sqlite")
    catalog = load_bug_catalog()
    try:
        heldout_catalog = load_bug_catalog(HELDOUT_BUG_CATALOG_PATH)
    except (OSError, ValueError):  # held-out catalog missing: in-sample bugs only
        heldout_catalog = None
    try:
        heldout_v2_catalog = load_bug_catalog(HELDOUT_V2_BUG_CATALOG_PATH)
    except (OSError, ValueError):  # v2 catalog missing: older bug sets only
        heldout_v2_catalog = None
    return {
        "cfg": cfg,
        "spec": spec,
        "retriever": retriever,
        "llm": llm,
        "store": store,
        "catalog": catalog,
        "heldout_catalog": heldout_catalog,
        "heldout_v2_catalog": heldout_v2_catalog,
    }


def _init_state() -> None:
    if "tests" not in st.session_state:
        st.session_state.tests = []
    if "run_id" not in st.session_state:
        st.session_state.run_id = None
    if "requirement_id" not in st.session_state:
        st.session_state.requirement_id = "REQ-UI-001"
    if "run_results" not in st.session_state:
        st.session_state.run_results = None


def _generate_section(backend: dict[str, object]) -> None:
    st.header("1. Generate tests from a requirement")
    requirement_text = st.text_area(
        "Diagnostic requirement (plain English)",
        value="The tester shall be able to read the VIN (DID 0xF190) in any diagnostic session.",
        height=100,
    )
    requirement_id = st.text_input("Requirement id", value=st.session_state.requirement_id)
    if st.button("Generate tests", type="primary"):
        if not requirement_text.strip():
            st.error("Requirement text must not be empty.")
        else:
            with st.spinner("Running parse -> retrieve -> plan -> instantiate -> validate -> explain..."):
                result = run_pipeline(
                    requirement_text,
                    requirement_id,
                    backend["spec"],
                    backend["llm"],
                    backend["retriever"],
                    backend["store"],
                )
            st.session_state.tests = result.tests
            st.session_state.run_id = result.run_id
            st.session_state.requirement_id = requirement_id
            st.session_state.run_results = None
            st.success(
                f"Generated {len(result.tests)} test(s), dropped {len(result.dropped)}. "
                f"run_id={result.run_id}"
            )
            st.caption(f"LLM backend used: {result.llm}; engine: {result.engine}.")
            for event in result.fallback_events:
                st.warning(f"Fallback: {event}")
            for note in result.notes:
                st.info(note)


def _tests_table(backend: dict[str, object]) -> None:
    st.header("2. Review generated tests")
    st.warning(GOVERNANCE_BANNER)
    tests = st.session_state.tests
    if not tests:
        st.caption("No tests generated yet.")
        return
    rows = [
        {
            "id": t.id,
            "category": t.category,
            "template_id": t.template_id or "(gold)",
            "review_status": t.review_status,
            "confidence": t.confidence or "-",
            "steps": len(t.steps),
            "citations": len(t.citations),
        }
        for t in tests
    ]
    st.dataframe(rows, use_container_width=True)

    selected_id = st.selectbox("Inspect test", options=[t.id for t in tests])
    selected = next(t for t in tests if t.id == selected_id)
    st.subheader(selected.title)
    st.write(selected.explanation or "(no explanation)")
    st.markdown("**Steps (hex)**")
    for i, step in enumerate(selected.steps):
        if step.kind == "send":
            st.code(
                f"[{i}] -> {step.request_hex}\n"
                f"[{i}] <- {' | '.join(step.expected_responses_hex) or '(no response)'}",
                language="text",
            )
        else:
            st.code(f"[{i}] {step.kind}: {step.model_dump(exclude={'kind'})}", language="text")
    st.markdown("**Citations**")
    for c in selected.citations:
        st.caption(f"{c.source} / {c.ref}" + (f" -- \"{c.quote}\"" if c.quote else ""))

    if st.session_state.run_id is not None and st.button(
        f"Mark {selected.id} as human_reviewed"
    ):
        backend["store"].set_review_status(st.session_state.run_id, selected.id, "human_reviewed")
        st.session_state.tests = backend["store"].get_tests(st.session_state.run_id)
        st.rerun()


def _run_section(backend: dict[str, object]) -> None:
    st.header("3. Run on the ECU simulator")
    tests = st.session_state.tests
    if not tests:
        st.caption("Generate tests first.")
        return
    catalog = backend["catalog"]
    bug_options = {f"[in-sample] {b.id} ({b.title})": b.id for b in catalog.bugs}
    heldout_catalog = backend.get("heldout_catalog")
    if heldout_catalog is not None:
        for b in heldout_catalog.bugs:
            if b.id in HELDOUT_BUG_IDS:
                bug_options[f"[held-out v1, seen] {b.id} ({b.title})"] = b.id
    heldout_v2_catalog = backend.get("heldout_v2_catalog")
    if heldout_v2_catalog is not None:
        for b in heldout_v2_catalog.bugs:
            if b.id in HELDOUT_V2_BUG_IDS:
                bug_options[f"[held-out v2, fresh] {b.id} ({b.title})"] = b.id
    chosen_labels = st.multiselect("Inject bug(s) (optional)", options=list(bug_options))
    chosen_bugs = {bug_options[label] for label in chosen_labels}
    if st.button("Run suite on simulator"):
        with st.spinner("Running..."):
            suite = run_suite(
                tests,
                backend["spec"],
                chosen_bugs,
                store=backend["store"],
                run_id=st.session_state.run_id,
            )
        st.session_state.run_results = suite
    suite = st.session_state.run_results
    if suite is not None:
        st.metric("Passed", f"{suite.passed_count}/{suite.total}")
        st.dataframe(
            [
                {
                    "test_id": r.test_id,
                    "passed": r.passed,
                    "functional_passed": r.functional_passed,
                    "timing_passed": r.timing_passed,
                    "failure": r.failure_detail,
                    "duration_ms": r.duration_ms,
                }
                for r in suite.results
            ],
            use_container_width=True,
        )


MODES = ("mock", "ollama")
NA = "n/a"
HEADLINE_NOTE = (
    "On the held-out TEST split the local 3B model (ollama) did NOT beat the deterministic "
    "mock on any headline metric: higher parsed-target recall but much lower precision, "
    "held-out bug detection equal, and about 120x slower. Mock stays the default."
)


def _pct(rate: object) -> str:
    return f"{rate * 100:.1f}%" if isinstance(rate, (int, float)) else "?"


def _frac(block: object) -> str:
    """``hit/all (pct)`` from a detection block, ``n/a`` if keys are missing."""
    if not isinstance(block, dict) or "detected" not in block:
        return NA
    return f"{block['detected']}/{block.get('bugs', '?')} ({_pct(block.get('rate'))})"


def _get(obj: object, *path: str, default: object = NA) -> object:
    """Nested dict lookup that returns ``default`` instead of raising."""
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _mode_blocks(report: dict) -> dict[str, dict]:
    """Per-mode result blocks (``{}`` for a mode the report does not hold)."""
    modes = report.get("modes") or {}
    out: dict[str, dict] = {}
    for m in MODES:
        blk = modes.get(m)
        ok = isinstance(blk, dict) and blk.get("status", "completed") == "completed"
        out[m] = blk if ok else {}
    return out


def _understanding_text(
    block: dict, key: str = "requirement_understanding", split: str = "test"
) -> str:
    und = ((block.get(key) or {}).get("splits") or {}).get(split) or {}
    if not und:
        return NA
    n = und.get("requirements", "?")
    tp, te = und.get("targets_parsed", {}), und.get("targets_exercised", {})
    cat, pre, fb = und.get("categories", {}), und.get("preconditions", {}), und.get("fallback", {})
    return (
        f"{split} split (n={n}): target exact match parsed {tp.get('exact', '?')}/{n} "
        f"(F1 {tp.get('f1', '?')}), exercised {te.get('exact', '?')}/{n} (F1 {te.get('f1', '?')}); "
        f"category recall {_pct(cat.get('micro_recall'))} micro / {_pct(cat.get('macro_recall'))} macro; "
        f"precondition recall {_pct(pre.get('micro_recall'))} micro / "
        f"{_pct(pre.get('macro_recall'))} macro; fallback/nothing {fb.get('count', '?')}/{n}"
    )


def _heldout_text(block: dict, key: str = "heldout_bug_detection", tag: bool = True) -> str:
    held = block.get(key) or {}
    if not held:
        return NA
    return (
        f"generated {_frac(held.get('generated'))}{' (HEADLINE)' if tag else ''} | gold {_frac(held.get('gold'))} | "
        f"union {_frac(held.get('union'))}"
    )


def _coverage_text(block: dict) -> str:
    cov = block.get("coverage") or {}
    cats = cov.get("category_totals") or {}
    if not cats:
        return NA
    return (
        ", ".join(f"{k} {v}" for k, v in cats.items())
        + f"; requirements with >=1 test {cov.get('requirements_with_tests', '?')}/"
        f"{cov.get('requirements', '?')} ({_pct(cov.get('rate'))})"
    )


def _citation_text(block: dict) -> str:
    cit = block.get("citation_validity") or {}
    if "valid" not in cit:
        return NA
    return f"{cit.get('valid')}/{cit.get('citations')} ({_pct(cit.get('rate'))})"


def _headline_rows(
    report: dict, blocks: dict[str, dict] | None = None, v3: bool = False
) -> list[dict[str, str]]:
    """The 7-row headline table with one column per mode, built defensively.

    From report version 3 on the v1 held-out and natural rows are labelled SEEN (the Part C
    templates were designed against those misses); the fresh v2 rows live in
    :func:`_v2_headline_rows`.
    """
    blocks = blocks if blocks is not None else _mode_blocks(report)
    agree = report.get("simulator_rules_agreement") or {}
    can = report.get("udsoncan_virtual_can") or {}
    agree_txt = (
        f"{agree.get('agreed', NA)}/{agree.get('requests', NA)} ({_pct(agree.get('rate'))})"
        if agree
        else NA
    )
    gold_txt = (
        f"{report.get('gold_clean_passed', NA)}/{report.get('gold_tests', '?')} "
        f"({_pct(report.get('gold_clean_pass_rate'))})"
    )
    can_txt = str(can.get("status", NA)).upper() if can else NA
    rows: list[dict[str, str]] = []

    def independent(metric: str, text: str) -> None:
        r = {"Metric": metric}
        first = True
        for m in MODES:
            if not blocks.get(m):
                r[m] = NA
            elif first:
                r[m] = text
                first = False
            else:
                r[m] = "same (LLM-independent)"
        rows.append(r)

    def dependent(metric: str, fn: Callable[[dict], str]) -> None:
        r = {"Metric": metric}
        for m in MODES:
            r[m] = fn(blocks[m]) if blocks.get(m) else NA
        rows.append(r)

    independent("1. Simulator <-> rules-engine agreement", agree_txt)
    independent("2. Gold tests passing on bug-free simulator", gold_txt)
    independent("3. udsoncan virtual-CAN sequence", can_txt)
    dependent(
        "4. Held-out v1 bug detection (12 bugs; SEEN: templates designed against these misses)"
        if v3
        else "4. Held-out bug detection (12 bugs)",
        (lambda b: _heldout_text(b, tag=False)) if v3 else _heldout_text,
    )
    dependent(
        "5. Requirement understanding (natural v1 test split; SEEN)"
        if v3
        else "5. Requirement understanding (natural requirements)",
        _understanding_text,
    )
    dependent("6. Coverage (seed requirements, tests per category)", _coverage_text)
    dependent("7. Citation validity", _citation_text)
    return rows


PREDATES = "n/a — report predates Part C"
NOT_RUN = "not run yet"


def _report_version(report: dict) -> int:
    v = report.get("report_version", 1)
    return v if isinstance(v, int) else 1


def _v2_cell(report: dict, blocks: dict[str, dict], mode: str, fn: Callable[[dict], str]) -> str:
    """One cell of a v2 row: predates-Part-C, not-run-yet, or the value."""
    if _report_version(report) < 3:
        return PREDATES
    blk = blocks.get(mode)
    if not blk:
        return NOT_RUN
    return fn(blk)


def _supp_text(block: dict, name: str) -> str:
    supp = _get(block, "heldout_v2_bug_detection", "supplementary", name, default=None)
    if not isinstance(supp, dict) or "detected" not in supp:
        return NA
    return f"{supp['detected']}/{supp.get('bugs', '?')} ({_pct(supp.get('rate'))})"


def _v2_headline_rows(report: dict, blocks: dict[str, dict]) -> list[dict[str, str]]:
    """The fresh (blind, written after the freeze) headline rows, one column per mode."""
    spec: list[tuple[str, Callable[[dict], str]]] = [
        (
            "A. Held-out v2 bug detection, FRESH (15 bugs): generated / gold / union",
            lambda b: _heldout_text(b, "heldout_v2_bug_detection"),
        ),
        (
            "B. Natural v2 requirement understanding, FRESH (test2, 16 requirements)",
            lambda b: _understanding_text(b, "requirement_understanding_v2", "test2"),
        ),
        (
            "   supplementary: v2 bugs detected by all generated tests (seed + natural)",
            lambda b: _supp_text(b, "all_generated"),
        ),
        (
            "   supplementary: v2 bugs detected by the natural-v2 tests alone",
            lambda b: _supp_text(b, "natural_v2_generated"),
        ),
    ]
    return [
        {"Metric": label, **{m: _v2_cell(report, blocks, m, fn) for m in MODES}}
        for label, fn in spec
    ]


def _freeze_section(report: dict) -> None:
    fr = report.get("freeze")
    if not isinstance(fr, dict) or "paths" not in fr:
        st.caption(f"Freeze status: {PREDATES}.")
        return
    st.subheader("Freeze status (templates, prompts, planner, gold unchanged since the freeze)")
    if fr.get("error"):
        st.error(f"Freeze check could not run: {fr['error']}")
    elif fr.get("all_ok"):
        st.success("Freeze status: all recorded hashes MATCH and the worktree is clean.")
    else:
        st.error(
            "Freeze status: MISMATCH (a frozen path changed, is dirty, or the commit is not "
            "an ancestor of HEAD)."
        )
    rows = [
        {
            "path": path,
            "recorded": str(v.get("expected", ""))[:12],
            "current": str(v.get("head", ""))[:12],
            "result": "match" if v.get("matches") else "MISMATCH",
            "worktree clean": str(v.get("worktree_clean")),
        }
        for path, v in (fr.get("paths") or {}).items()
    ]
    if rows:
        st.dataframe(rows, use_container_width=True)
    commit = fr.get("commit") or {}
    if commit.get("recorded"):
        anc = commit.get("recorded_is_ancestor_of_head")
        st.caption(
            f"Freeze commit {str(commit['recorded'])[:12]} is "
            + ("an ancestor of HEAD." if anc else "NOT confirmed as an ancestor of HEAD.")
        )


def _noise_section(report: dict, blocks: dict[str, dict]) -> None:
    st.subheader("Noise check (natural v2, repeated runs)")
    if _report_version(report) < 3:
        st.caption(f"Noise check: {PREDATES}.")
        return
    shown = False
    for m in MODES:
        nc = (blocks.get(m) or {}).get("noise_check")
        if not isinstance(nc, dict) or nc.get("status") != "completed":
            st.caption(f"{m}: noise check {NOT_RUN}.")
            continue
        shown = True
        n_runs = len(nc.get("runs") or [])
        st.markdown(
            f"**{m}**: {'deterministic' if nc.get('deterministic') else 'sampled'}, "
            f"{n_runs} run(s) (requested {nc.get('requested_runs', '?')})."
        )
        runs = [
            {
                "run": r.get("run"),
                "used for main tables": r.get("used_for_main_tables"),
                "parsed P": r.get("parsed_precision"),
                "parsed R": r.get("parsed_recall"),
                "parsed F1": r.get("parsed_f1"),
                "exercised F1": r.get("exercised_f1"),
                "category recall": r.get("category_recall_micro"),
                "precondition recall": r.get("precondition_recall_micro"),
                "tests kept": r.get("tests_kept"),
                "rejected": r.get("rejected"),
                "fallback events": r.get("fallback_events"),
                "wall s": r.get("wall_total_s"),
            }
            for r in nc.get("runs") or []
        ]
        if runs:
            st.dataframe(runs, use_container_width=True)
        lines = [
            f"{k}: mean {v['mean']} (range {v.get('min')} to {v.get('max')}, n={v.get('n')})"
            for k, v in (nc.get("summary") or {}).items()
            if isinstance(v, dict) and v.get("mean") is not None
        ]
        if lines:
            st.caption("Mean and min-max range over all runs: " + "; ".join(lines))
        det = nc.get("determinism_check")
        if isinstance(det, dict):
            st.caption(f"Second run identical: {det.get('second_run_identical')}.")
        if nc.get("note"):
            st.caption(str(nc["note"]))
    if not shown:
        st.caption("No completed noise check in this report.")


def _before_after_path() -> Path:
    return Path(
        os.environ.get("UDS_BEFORE_AFTER") or REPO_ROOT / "outputs" / "partC" / "before_after.md"
    )


def _before_after_section() -> None:
    st.subheader("Before / after Part C")
    path = _before_after_path()
    if not path.exists():
        st.caption(
            f"Before/after table not generated yet ({path}). It is written by "
            "`python -m uds_assistant.eval.run_eval --mode ollama --before-after` or "
            "`python -m uds_assistant.eval.before_after`."
        )
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].startswith("# "):  # the page already has a subheader
        lines = lines[1:]
    st.markdown("\n".join(lines))


def _sum_pipeline(block: dict, key: str) -> object:
    vals = [_get(block, p, key, default=None) for p in ("pipeline", "pipeline_natural")]
    if any(not isinstance(v, (int, float)) for v in vals):
        return NA
    return int(sum(vals))  # type: ignore[arg-type]


def _latency_text(block: dict) -> str:
    w = _get(block, "latency", "per_requirement_wall_s", "all", default=None)
    if not isinstance(w, dict):
        return NA
    return f"mean {w.get('mean', '?')} s / p95 {w.get('p95', '?')} s (max {w.get('max', '?')} s)"


def _provenance_text(block: dict) -> str:
    prov = block.get("provenance") or {}
    if "passed" not in prov:
        return NA
    return f"{prov.get('passed')}/{prov.get('checked')} passed"


def _events_text(block: dict, kind: str) -> str:
    ev = _get(block, "events", kind, default=None)
    return str(len(ev)) if isinstance(ev, list) else NA


def _comparison_rows(blocks: dict[str, dict], v3: bool = False) -> list[dict[str, str]]:
    """Side-by-side rows for the mock vs ollama comparison."""
    spec: list[tuple[str, Callable[[dict], str]]] = []
    if v3:
        spec += [
            (
                "Held-out v2 bug detection, FRESH (15 bugs)",
                lambda b: _heldout_text(b, "heldout_v2_bug_detection"),
            ),
            (
                "Natural v2 understanding, FRESH (test2)",
                lambda b: _understanding_text(b, "requirement_understanding_v2", "test2"),
            ),
        ]
    seen = " (SEEN)" if v3 else ""
    spec += [
        ("Requirement understanding, v1 TEST split" + seen, _understanding_text),
        (
            "Held-out v1 bug detection (12 bugs)" + seen,
            (lambda b: _heldout_text(b, tag=False)) if v3 else _heldout_text,
        ),
        ("Generated tests (seed requirements)", lambda b: str(_get(b, "generated_tests", "count"))),
        (
            "In-sample detection, generated (26 bugs; tuned on)",
            lambda b: _frac(_get(b, "bug_detection", "generated", default=None)),
        ),
        ("Planner choices rejected (35 requirements)", lambda b: str(_sum_pipeline(b, "rejected"))),
        ("Re-plans / retries", lambda b: str(_sum_pipeline(b, "retries"))),
        ("Fallback-to-mock events", lambda b: _events_text(b, "fallback")),
        ("Prompt truncation events", lambda b: _events_text(b, "truncation")),
        ("Wall-clock per requirement", _latency_text),
        ("Byte provenance (all generated tests)", _provenance_text),
        ("Citation validity", _citation_text),
    ]
    rows = []
    for label, fn in spec:
        r = {"Metric": label}
        for m in MODES:
            r[m] = fn(blocks[m]) if blocks.get(m) else NA
        rows.append(r)
    return rows


def _retrieval_rows(report: dict) -> list[dict[str, object]]:
    backends = _get(report, "retrieval_comparison", "backends", default=None)
    if not isinstance(backends, dict):
        return []
    rows: list[dict[str, object]] = []
    for split in ("dev", "test", "all"):
        for name, be in backends.items():
            sp = _get(be, "splits", split, default=None)
            if not isinstance(sp, dict):
                continue
            rows.append(
                {
                    "split": split,
                    "backend": name,
                    "queries": sp.get("queries"),
                    "hit@1": _pct(sp.get("hit_at_1")),
                    "hit@3": _pct(sp.get("hit_at_3")),
                    "MRR": sp.get("mrr"),
                    "citation validity (top 3)": _pct(sp.get("citation_validity")),
                }
            )
    return rows


def _heldout_section(
    blocks: dict[str, dict], key: str = "heldout_bug_detection", title: str | None = None
) -> None:
    present = {m: b[key] for m, b in blocks.items() if b.get(key)}
    if not present:
        st.caption("Held-out results not in this report (older report).")
        return
    st.subheader(title or "Held-out bug detection (bugs not seen when templates/gold were written)")
    first = next(iter(present.values()))
    st.caption(first.get("scope", ""))
    analysis = first.get("analysis", {})
    triggers = analysis.get("triggers", {})
    reasons_gold = {m["bug_id"]: m["reason"] for m in analysis.get("gold", {}).get("missed", [])}
    gold_by_id = {b["bug_id"]: b for b in first.get("gold", {}).get("per_bug", [])}
    per_mode = {
        m: {b["bug_id"]: b for b in h.get("generated", {}).get("per_bug", [])}
        for m, h in present.items()
    }
    reasons_gen = {
        m: {
            x["bug_id"]: x["reason"]
            for x in h.get("analysis", {}).get("generated", {}).get("missed", [])
        }
        for m, h in present.items()
    }
    rows = []
    for b in first.get("generated", {}).get("per_bug", []):
        bid = b["bug_id"]
        row: dict[str, object] = {"bug": bid, "category": b.get("category", "")}
        for m in MODES:
            if m in per_mode:
                row[f"{m} generated"] = "yes" if per_mode[m].get(bid, {}).get("detected") else "NO"
            else:
                row[f"{m} generated"] = NA
        row["gold"] = "yes" if gold_by_id.get(bid, {}).get("detected") else "NO"
        row["trigger needed"] = triggers.get(bid, "")
        for m in per_mode:
            row[f"{m} missed because"] = reasons_gen[m].get(bid, "")
        row["gold missed because"] = reasons_gold.get(bid, "")
        rows.append(row)
    st.dataframe(rows, use_container_width=True)
    st.caption(
        " ; ".join(
            f"{m}: generated {_frac(h.get('generated'))}, gold {_frac(h.get('gold'))}, "
            f"union {_frac(h.get('union'))}"
            for m, h in present.items()
        )
        + ". Reasons come from a static trigger analysis (reporting only)."
    )


def _split_rows(und: dict, mode: str) -> list[dict[str, object]]:
    rows = []
    for name, sp in (und.get("splits") or {}).items():
        tp, te = sp.get("targets_parsed", {}), sp.get("targets_exercised", {})
        cat, pre, fb = sp.get("categories", {}), sp.get("preconditions", {}), sp.get("fallback", {})
        rows.append(
            {
                "mode": mode,
                "split": name,
                "n": sp.get("requirements"),
                "parsed exact": f"{tp.get('exact')}/{sp.get('requirements')}",
                "parsed P": tp.get("precision"),
                "parsed R": tp.get("recall"),
                "parsed F1": tp.get("f1"),
                "exercised exact": f"{te.get('exact')}/{sp.get('requirements')}",
                "exercised F1": te.get("f1"),
                "category recall (micro)": cat.get("micro_recall"),
                "precondition recall (micro)": pre.get("micro_recall"),
                "fallback / nothing": fb.get("count"),
            }
        )
    return rows


def _understanding_section(
    blocks: dict[str, dict], key: str = "requirement_understanding", title: str | None = None
) -> None:
    present = {
        m: b[key] for m, b in blocks.items() if isinstance(b.get(key), dict) and b[key].get("splits")
    }
    if not present:
        st.caption("Requirement-understanding results not in this report (older report).")
        return
    st.subheader(title or "Requirement understanding (natural-language requirements)")
    first = next(iter(present.values()))
    st.caption(f"Source: {first.get('source', '?')}. The TEST split is the main number.")
    split_rows: list[dict[str, object]] = []
    for m, und in present.items():
        split_rows.extend(_split_rows(und, m))
    st.dataframe(split_rows, use_container_width=True)
    by_mode = {m: {r.get("id"): r for r in u.get("per_requirement", [])} for m, u in present.items()}
    req_rows = []
    for r in first.get("per_requirement", []):
        rid = r.get("id")
        row: dict[str, object] = {
            "req": rid,
            "split": f"{r.get('split')}" + (" (ambiguous)" if r.get("ambiguous") else ""),
            "label targets": ", ".join(r.get("label_targets", [])),
        }
        for m in present:
            x = by_mode[m].get(rid, {})
            pa = x.get("parsed", {})
            row[f"{m} parsed exact"] = pa.get("exact")
            row[f"{m} parsed missed"] = ", ".join(pa.get("missed", []))
            row[f"{m} parsed extra"] = ", ".join(pa.get("extra", []))
            row[f"{m} tests"] = x.get("tests")
            row[f"{m} categories missed"] = ", ".join(x.get("categories", {}).get("missed", []))
        req_rows.append(row)
    st.dataframe(req_rows, use_container_width=True)


def _comparison_section(report: dict, blocks: dict[str, dict]) -> None:
    st.subheader("Mock vs Ollama: side by side")
    if not blocks.get("ollama") or not blocks.get("mock"):
        st.caption(
            "This report does not hold both modes (older report); the comparison is n/a. "
            "Regenerate with `python -m uds_assistant.eval.run_eval --mode ollama` "
            "(needs a local Ollama)."
        )
    elif _report_version(report) < 3:
        st.info(HEADLINE_NOTE)
    else:
        st.info(
            "Read the FRESH v2 rows first. The v1 rows are SEEN (the Part C templates were "
            "designed against the v1 misses), so they are not independent evidence; see "
            "docs/RESULTS.md for the interpretation of the run."
        )
    st.table(_comparison_rows(blocks, _report_version(report) >= 3))
    st.caption(
        f"Model: {_get(report, 'llm_settings', 'model')}, num_ctx "
        f"{_get(report, 'llm_settings', 'num_ctx')}. Prompts were tuned on the 8 dev rows only; "
        "the test split has n=12 and GPU decoding is nondeterministic (about +-0.05 F1), "
        "so small gaps are within noise."
    )
    st.subheader("Retrieval comparison: BM25 vs Chroma (bge-small-en-v1.5 via fastembed)")
    rrows = _retrieval_rows(report)
    if rrows:
        st.dataframe(rrows, use_container_width=True)
        st.caption(
            "19 of 20 natural requirements scored. Neither backend is clearly better; "
            "the default stays BM25."
        )
    else:
        st.caption("Retrieval comparison not in this report (n/a; older report).")


def _eval_section() -> None:
    st.header("4. Evaluation report (mock vs ollama)")
    path = Path(os.environ.get("UDS_EVAL_REPORT") or REPO_ROOT / "outputs" / "eval_report.json")
    if not path.exists():
        st.caption(f"No report yet at {path}. Run `python -m uds_assistant.eval.run_eval`.")
        _before_after_section()
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    version = _report_version(report)
    v3 = version >= 3
    blocks = _mode_blocks(report)
    st.caption(
        f"Report version {version}"
        + ("" if v3 else f" ({PREDATES}: v2 rows are n/a, v1 sections are shown as measured)")
    )
    _freeze_section(report)
    st.subheader("Fresh v2 headline (written blind after the Part C freeze)")
    st.dataframe(_v2_headline_rows(report, blocks), use_container_width=True)
    st.caption(
        "FRESH = nothing was changed after seeing these results. HEADLINE for bug detection is the "
        "generated suite (tests generated from the 15 seed requirements)."
    )
    st.subheader("Headline metrics")
    st.table(_headline_rows(report, blocks, v3))
    st.caption(
        "Both columns come from one invocation on the same inputs, templates and retriever. "
        "The oracle self-consistency check is circular and lives in the report appendix."
        + (" Held-out v1 and natural v1 rows are SEEN: " + "templates were designed against them."
           if v3 else "")
    )
    _noise_section(report, blocks)
    _before_after_section()
    _comparison_section(report, blocks)
    base = blocks.get("mock") or next((b for b in blocks.values() if b), {})
    det = base.get("bug_detection", {})
    col1, col2, col3 = st.columns(3)
    col1.metric("Generated tests (mock)", base.get("generated_tests", {}).get("count", "?"))
    col2.metric("In-sample bugs (generated, mock; tuned on)", _frac(det.get("generated")))
    col3.metric("In-sample bugs (gold)", _frac(det.get("gold")))
    if v3:
        _heldout_section(
            blocks, "heldout_v2_bug_detection", "Held-out v2 bug detection (FRESH, 15 bugs)"
        )
        _understanding_section(
            blocks, "requirement_understanding_v2", "Natural v2 requirement understanding (FRESH)"
        )
        _heldout_section(
            blocks,
            "heldout_bug_detection",
            "Held-out v1 bug detection — seen (templates designed against these misses)",
        )
        _understanding_section(
            blocks,
            "requirement_understanding",
            "Natural v1 requirement understanding (test split SEEN; dev split tuned on)",
        )
    else:
        _heldout_section(blocks)
        _understanding_section(blocks)
    st.caption(f"Report timestamp: {report.get('timestamp')}; spec is synthetic.")
    with st.expander("Full report JSON"):
        st.json(report)


def _export_section() -> None:
    st.header("5. Export")
    tests = st.session_state.tests
    if not tests:
        st.caption("Generate tests first.")
        return
    pytest_src = render_pytest(tests, filename="generated_tests_test.py")
    capl_src = render_capl(tests)
    col1, col2 = st.columns(2)
    col1.download_button(
        "Download pytest file", pytest_src, file_name="generated_tests_test.py", mime="text/x-python"
    )
    col2.download_button(
        "Download CAPL template (unverified)", capl_src, file_name="generated_tests.can", mime="text/plain"
    )


def main() -> None:
    st.set_page_config(page_title="UDS Diagnostics Assistant", layout="wide")
    st.title("UDS Diagnostics & Automated Test Generation Assistant")
    st.caption(
        "Local, offline-capable. ECU spec is SYNTHETIC. " + GOVERNANCE_BANNER
    )
    backend = _load_backend()
    _init_state()
    _generate_section(backend)
    _tests_table(backend)
    _run_section(backend)
    _eval_section()
    _export_section()


main()
