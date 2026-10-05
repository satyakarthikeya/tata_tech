"""FastAPI service: requirement -> validated tests -> simulator run -> export, plus cited Q&A.

Factory: :func:`create_app(repo_root=None, db_path=None)`. A module-level ``app``
is also built (lazily-safe: building it only loads lightweight deps already
required by the package; the Chroma retriever is built on first use). Ollama is required:
endpoints that need the LLM answer HTTP 503 with a "Start Ollama" hint when it is down.

Governance (PROJECT.md §9): every ``/generate`` response carries a
``governance_banner`` reminding the engineer that generated tests require
human review before they run on real hardware, and every run is recorded in
the SQLite audit trail (:mod:`uds_assistant.store.audit`).
"""

from __future__ import annotations

import sys
import uuid
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from uds_assistant.agent import TargetEvidence, run_pipeline
from uds_assistant.eval.coverage import coverage_markdown, coverage_report
from uds_assistant.export import render_capl, render_pytest
from uds_assistant.llm.client import ollama_base_url, ollama_reachable
from uds_assistant.llm.factory import START_OLLAMA_HINT, OllamaUnavailableError, get_llm
from uds_assistant.qa import AskRequest, AskResponse, answer_question
from uds_assistant.qa.lookup import FactLookup
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.runner import run_suite
from uds_assistant.runner.suite import TestRunResult
from uds_assistant.simulator import load_bug_catalog
from uds_assistant.spec.schema import load_spec
from uds_assistant.store.audit import AuditStore, RunRecord
from uds_assistant.testgen.model import ReviewStatus, TestCase
from uds_assistant.testgen.review_gate import NoApprovedTestsError, select_for_run

REPO_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_BANNER = "Generated tests require human review before execution on real hardware"


# --------------------------------------------------------------------------------- models


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    ollama_reachable: bool
    ollama_hint: str | None = None
    retriever: str = "ChromaRetriever"
    versions: dict[str, str]


class SpecResponse(BaseModel):
    synthetic: bool = True
    spec: dict[str, Any]


class GenerateRequest(BaseModel):
    requirement_text: str = Field(min_length=1)
    requirement_id: str | None = None


class GenerateResponse(BaseModel):
    run_id: int | None
    requirement_id: str
    tests: list[TestCase]
    notes: list[str]
    dropped_count: int
    target_provenance: dict[str, list[TargetEvidence]] = Field(default_factory=dict)
    """Per test id: its service/DID/routine targets and whether the requirement text names them."""
    governance_banner: str = GOVERNANCE_BANNER


class RunRequest(BaseModel):
    run_id: int | None = None
    tests: list[TestCase] | None = None
    bugs: list[str] = Field(default_factory=list)
    include_unreviewed: bool = False
    """Default False: only human-approved tests run. True is a demo-only override."""


class RunResponse(BaseModel):
    run_id: int | None
    bugs: list[str]
    total: int
    passed: int
    results: list[TestRunResult]
    governance_banner: str = GOVERNANCE_BANNER


class ExportRequest(BaseModel):
    run_id: int | None = None
    tests: list[TestCase] | None = None
    format: Literal["pytest", "capl"]
    include_unreviewed: bool = False
    """Default False: only human-approved tests are exported. True is a demo-only override."""


class ExportResponse(BaseModel):
    format: Literal["pytest", "capl"]
    filename: str
    content: str


class CoverageRequest(BaseModel):
    run_id: int | None = None
    tests: list[TestCase] | None = None


class CoverageResponse(BaseModel):
    report: dict[str, Any]
    markdown: str


class ReviewRequest(BaseModel):
    review_status: ReviewStatus = "human_reviewed"


class BugInfo(BaseModel):
    id: str
    title: str
    category: str


# --------------------------------------------------------------------------------- helpers


def _versions() -> dict[str, str]:
    out = {"python": sys.version.split()[0]}
    for pkg in ("fastapi", "pydantic", "uvicorn", "httpx"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = "unknown"
    try:
        out["uds-assistant"] = metadata.version("uds-assistant")
    except metadata.PackageNotFoundError:
        out["uds-assistant"] = "0.1.0"
    return out


def _resolve_tests(app: FastAPI, run_id: int | None, tests: list[TestCase] | None) -> list[TestCase]:
    if tests is not None:
        return tests
    if run_id is not None:
        store: AuditStore = app.state.store
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"no run {run_id}")
        found = store.get_tests(run_id)
        if not found:
            raise HTTPException(status_code=404, detail=f"run {run_id} has no tests")
        return found
    raise HTTPException(status_code=400, detail="provide either 'run_id' or 'tests'")


def _approved(tests: list[TestCase], include_unreviewed: bool) -> list[TestCase]:
    try:
        return select_for_run(tests, include_unreviewed=include_unreviewed)
    except NoApprovedTestsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --------------------------------------------------------------------------------- factory


def create_app(repo_root: str | Path | None = None, db_path: str | Path | None = None) -> FastAPI:
    """Build the FastAPI app, loading the spec and corpus at startup (retriever/LLM on use)."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    if db_path is None:
        db_path = root / "outputs" / "api_audit.sqlite"

    app = FastAPI(
        title="UDS Diagnostics Assistant API",
        description="Requirement -> cited test cases -> simulator run -> export, plus cited Q&A. "
        "ECU spec is synthetic. " + GOVERNANCE_BANNER,
        version="0.1.0",
    )

    app.state.repo_root = root
    app.state.store = AuditStore(db_path)
    app.state.spec = load_spec(root / "data" / "bcm_spec.yaml")
    app.state.corpus = build_corpus(root)
    app.state.retriever = None
    app.state.bug_catalog = load_bug_catalog()
    app.state.qa_lookup = FactLookup(app.state.spec, app.state.corpus)

    def llm():
        try:
            return get_llm()
        except OllamaUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def retriever():
        if app.state.retriever is None:
            app.state.retriever = get_retriever(chunks=app.state.corpus)
        return app.state.retriever

    # ------------------------------------------------------------------------------- health

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        up = ollama_reachable(ollama_base_url(), timeout_s=1.0)
        return HealthResponse(
            ollama_reachable=up,
            ollama_hint=None if up else START_OLLAMA_HINT,
            versions=_versions(),
        )

    # --------------------------------------------------------------------------------- spec

    @app.get("/spec", response_model=SpecResponse)
    def get_spec() -> SpecResponse:
        dump = app.state.spec.model_dump(mode="json")
        dump["synthetic"] = True
        return SpecResponse(synthetic=True, spec=dump)

    # ----------------------------------------------------------------------------- generate

    @app.post("/generate", response_model=GenerateResponse)
    def generate(req: GenerateRequest) -> GenerateResponse:
        requirement_id = req.requirement_id or f"api-{uuid.uuid4().hex[:8]}"
        result = run_pipeline(
            req.requirement_text,
            requirement_id,
            app.state.spec,
            llm(),
            retriever(),
            app.state.store,
        )
        return GenerateResponse(
            run_id=result.run_id,
            requirement_id=result.requirement_id,
            tests=result.tests,
            notes=result.notes,
            dropped_count=len(result.dropped),
            target_provenance=result.target_provenance,
        )

    # ------------------------------------------------------------------------------- ask

    @app.post("/ask", response_model=AskResponse)
    def ask(req: AskRequest) -> AskResponse:
        """Cited diagnostic Q&A: answers only from the approved sources, or ``not_found``."""
        return answer_question(
            req.question,
            spec=app.state.spec,
            chunks=app.state.corpus,
            retriever=retriever(),
            llm=llm(),
            lookup=app.state.qa_lookup,
        )

    # ---------------------------------------------------------------------------------- run

    @app.post("/run", response_model=RunResponse)
    def run(req: RunRequest) -> RunResponse:
        tests = _approved(_resolve_tests(app, req.run_id, req.tests), req.include_unreviewed)
        known = set(app.state.bug_catalog.ids)
        unknown = [b for b in req.bugs if b not in known]
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown bug id(s): {unknown}")
        store = app.state.store if req.run_id is not None else None
        suite = run_suite(tests, app.state.spec, set(req.bugs), store=store, run_id=req.run_id)
        return RunResponse(
            run_id=req.run_id,
            bugs=suite.bugs,
            total=suite.total,
            passed=suite.passed_count,
            results=suite.results,
        )

    # ------------------------------------------------------------------------------- export

    @app.post("/export", response_model=ExportResponse)
    def export(req: ExportRequest) -> ExportResponse:
        tests = _approved(_resolve_tests(app, req.run_id, req.tests), req.include_unreviewed)
        if req.format == "pytest":
            filename = "generated_tests_test.py"
            content = render_pytest(tests, filename=filename)
        else:
            filename = "generated_tests.can"
            content = render_capl(tests)
        return ExportResponse(format=req.format, filename=filename, content=content)

    # ------------------------------------------------------------------------------ coverage

    @app.post("/coverage", response_model=CoverageResponse)
    def coverage(req: CoverageRequest) -> CoverageResponse:
        """Coverage of the given tests (all of them, no review filter) against the spec."""
        tests = _resolve_tests(app, req.run_id, req.tests)
        report = coverage_report(tests, app.state.spec)
        return CoverageResponse(report=report, markdown=coverage_markdown(report))

    # -------------------------------------------------------------------------- bugs / runs

    @app.get("/bugs", response_model=list[BugInfo])
    def list_bugs() -> list[BugInfo]:
        return [BugInfo(id=b.id, title=b.title, category=b.category) for b in app.state.bug_catalog.bugs]

    @app.get("/runs", response_model=list[RunRecord])
    def list_runs() -> list[RunRecord]:
        return app.state.store.list_runs()

    @app.post("/tests/{run_id}/{test_id}/review", response_model=TestCase)
    def review_test(run_id: int, test_id: str, req: ReviewRequest) -> TestCase:
        store: AuditStore = app.state.store
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"no run {run_id}")
        try:
            store.set_review_status(run_id, test_id, req.review_status)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return next(t for t in store.get_tests(run_id) if t.id == test_id)

    return app


app = create_app()
