"""Routes for the HTML front end: static files, config, examples, run views, review actions, report.

Everything here is a thin view over code that already exists (rules engine, runner, audit store,
review helpers, evaluation report); no new behaviour and no model calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from uds_assistant.llm.client import ollama_base_url, ollama_model, ollama_num_ctx, ollama_reachable
from uds_assistant.protocol.describe import decode_responses, decode_step
from uds_assistant.runner.suite import SuiteResult
from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.model import TestCase
from uds_assistant.ui import state as review
from uds_assistant.ui.bugs import bug_options
from uds_assistant.ui.env import REMOTE_OLLAMA_WARNING, ollama_is_local
from uds_assistant.ui.examples import ASK_EXAMPLES, requirement_examples

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
BANNER = "Synthetic ECU spec. Human review required before real-hardware use."

RAW_EXAMPLES = [
    {"label": "Write brightness, not unlocked (expect 7F 2E 33)", "hex": "2E 01 00 11",
     "session": 3, "unlocked_level": None},
    {"label": "Write brightness, level 1 unlocked (expect 6E 01 00)", "hex": "2E 01 00 11",
     "session": 3, "unlocked_level": 1},
    {"label": "Read the VIN in default session", "hex": "22 F1 90", "session": 1,
     "unlocked_level": None},
    {"label": "Unknown service 0x99 (expect 7F 99 11)", "hex": "99 99", "session": 1,
     "unlocked_level": None},
    {"label": "Truncated write (expect 7F 2E 13)", "hex": "2E 01 00", "session": 3,
     "unlocked_level": None},
]


class ReviewAction(BaseModel):
    action: Literal["approve", "reject", "comment"]
    comment: str = ""


class FailureView(BaseModel):
    index: int
    request_hex: str
    request_text: str
    expected: str
    actual: str
    detail: str = ""


class ResultView(BaseModel):
    test_id: str
    title: str
    category: str
    passed: bool
    clean_passed: bool | None = None
    caught: bool = False
    failure_detail: str = ""
    failure: FailureView | None = None


class RunView(BaseModel):
    bugs: list[str]
    total: int
    passed: int
    clean_passed: int | None = None
    caught_ids: list[str] = Field(default_factory=list)
    invalid_ids: list[str] = Field(default_factory=list)
    results: list[ResultView]


def did_names(spec: Any) -> dict[int, str]:
    return {int(d.id): d.name for d in spec.dids}


def step_views(test: TestCase, spec: Any) -> list[dict[str, Any]]:
    """Decoded steps: ``send`` steps get the arrow line and readable request / responses."""
    names = did_names(spec)
    out: list[dict[str, Any]] = []
    for i, step in enumerate(test.steps):
        if step.kind == "send":
            d = decode_step(step.request_hex, step.expected_responses_hex, names)
            out.append({"index": i, "kind": "send", "line": d.line, "request_text": d.request_text,
                        "response_texts": d.response_texts,
                        "max_response_time_ms": step.max_response_time_ms,
                        "description": step.description})
        else:
            out.append({"index": i, "kind": step.kind, "description": step.description,
                        "detail": step.model_dump(exclude={"kind", "description"})})
    return out


def test_view(store: AuditStore, run_id: int | None, test: TestCase, spec: Any) -> dict[str, Any]:
    log = review.review_log(store, run_id, test.id) if run_id is not None else []
    return {
        "test": test.model_dump(mode="json"),
        "steps": step_views(test, spec),
        "review_label": review.review_label(store, run_id, test),
        "review_log": [{"action": a, "comment": c} for a, c in log],
    }


def run_view(
    tests: list[TestCase], suite: SuiteResult, clean: SuiteResult | None, spec: Any
) -> RunView:
    by_id = {t.id: t for t in tests}
    names = did_names(spec)
    clean_ok = {r.test_id for r in clean.results if r.passed} if clean is not None else None
    results: list[ResultView] = []
    for r in suite.results:
        t = by_id[r.test_id]
        fv = None
        first = r.outcome.first_failure
        if first is not None and first.index < len(t.steps):
            req = getattr(t.steps[first.index], "request_hex", "")
            fv = FailureView(
                index=first.index,
                request_hex=req,
                request_text=(
                    decode_step(req, first.actual_responses_hex, names).request_text if req else ""
                ),
                expected=decode_responses(first.expected_responses_hex),
                actual=decode_responses(first.actual_responses_hex),
                detail=first.detail,
            )
        caught = bool(suite.bugs) and not r.passed and clean_ok is not None and r.test_id in clean_ok
        results.append(ResultView(
            test_id=r.test_id, title=t.title, category=t.category, passed=r.passed,
            clean_passed=(r.test_id in clean_ok) if clean_ok is not None else None,
            caught=caught, failure_detail=r.failure_detail, failure=fv))
    return RunView(
        bugs=suite.bugs, total=suite.total, passed=suite.passed_count,
        clean_passed=clean.passed_count if clean is not None else None,
        caught_ids=[x.test_id for x in results if x.caught],
        invalid_ids=[x.test_id for x in results if not x.passed and x.clean_passed is False],
        results=results)


def install(app: FastAPI) -> None:
    """Register the front-end routes on ``app`` (call after the API routes)."""

    @app.get("/config")
    def config() -> dict[str, Any]:
        base = ollama_base_url()
        up = ollama_reachable(base, timeout_s=1.0)
        return {
            "model": ollama_model(), "num_ctx": ollama_num_ctx(), "ollama_url": base,
            "ollama_reachable": up, "ollama_local": ollama_is_local(base),
            "remote_warning": None if ollama_is_local(base) else REMOTE_OLLAMA_WARNING,
            "banner": BANNER, "ecu_name": app.state.spec.ecu_name,
            "retriever": "ChromaDB + BAAI/bge-small-en-v1.5",
            "standard_source": app.state.standard_source,
        }

    @app.get("/examples")
    def examples() -> dict[str, Any]:
        spec = app.state.spec
        return {
            "requirements": [{"label": k, "id": v[0], "text": v[1]}
                             for k, v in requirement_examples().items()],
            "questions": list(ASK_EXAMPLES),
            "raw_requests": RAW_EXAMPLES,
            "bugs": [{"id": b.id, "group": b.group, "title": b.title, "description": b.description}
                     for b in bug_options()],
            "sessions": [{"id": s.id, "name": s.name} for s in spec.sessions],
            "security_levels": [{"level": lv.level, "name": lv.name}
                                for lv in spec.security_levels],
        }

    @app.get("/runs/{run_id}/tests")
    def run_tests(run_id: int) -> dict[str, Any]:
        store: AuditStore = app.state.store
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"no run {run_id}")
        tests = store.get_tests(run_id)
        return {"run_id": run_id,
                "tests": [test_view(store, run_id, t, app.state.spec) for t in tests]}

    @app.post("/runs/{run_id}/tests/{test_id}/review")
    def review_action(run_id: int, test_id: str, req: ReviewAction) -> dict[str, Any]:
        store: AuditStore = app.state.store
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"no run {run_id}")
        if req.action == "comment" and not req.comment.strip():
            raise HTTPException(status_code=422, detail="a comment needs text")
        fn = {"approve": review.approve, "reject": review.reject, "comment": review.add_comment}
        try:
            fn[req.action](store, run_id, test_id, req.comment)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        test = next(t for t in store.get_tests(run_id) if t.id == test_id)
        return test_view(store, run_id, test, app.state.spec)

    @app.post("/runs/{run_id}/approve-validated")
    def approve_validated(run_id: int) -> dict[str, Any]:
        """Bulk approve: every ``validated`` test, one review-log entry each."""
        store: AuditStore = app.state.store
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"no run {run_id}")
        ids = review.bulk_approve_validated(store, run_id, store.get_tests(run_id))
        return {"run_id": run_id, "approved": ids}

    @app.get("/report")
    def report() -> dict[str, Any]:
        path = app.state.repo_root / "outputs" / "eval_report.json"
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="No evaluation report yet. Run: python -m uds_assistant.eval.run_eval",
            )
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/report.md", response_class=PlainTextResponse)
    def report_md() -> str:
        path = app.state.repo_root / "outputs" / "eval_report.md"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No evaluation report yet.")
        return path.read_text(encoding="utf-8")

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")
