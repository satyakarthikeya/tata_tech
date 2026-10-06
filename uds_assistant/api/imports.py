"""Routes for importing an existing UDS test suite and comparing its coverage.

``POST /import`` parses and validates (schema + rules engine) and stores the valid tests in the audit
trail as ``validated`` and ``origin="imported"``. Review, run and export reuse the existing routes
(``/runs/{id}/tests``, ``/runs/{id}/tests/{test}/review``, ``/run``, ``/export``), so imported
tests pass through the same review gate and audit trail as generated ones. No model is called.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from uds_assistant.eval.coverage_compare import compare_coverage, comparison_markdown
from uds_assistant.importer import (
    FORMAT_VERSION,
    IMPORT_LLM_MODE,
    ImportFormatError,
    ImportResult,
    import_tests,
    load_import_result,
    parse_import,
)
from uds_assistant.importer.format import MAX_FILE_BYTES
from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.model import TestCase

IMPORT_BANNER = (
    "Imported tests are not AI-generated. They were checked against the rules engine, are "
    "'validated' only, and need human approval before any run or export. Simulator or approved "
    "lab bench only."
)


class ImportRequest(BaseModel):
    filename: str = Field(default="upload.yaml", min_length=1, max_length=200)
    content: str = Field(min_length=1)


class ImportResponse(ImportResult):
    governance_banner: str = IMPORT_BANNER


class CompareRequest(BaseModel):
    generated_run_id: int | None = None
    """One generated run to compare against; omitted = every generated run in the audit trail."""


class CompareResponse(BaseModel):
    import_run_id: int
    generated_source: str
    comparison: dict[str, Any]
    markdown: str


class ImportSummary(BaseModel):
    run_id: int
    suite: str
    source_file: str
    started_at: str
    total: int
    accepted: int
    oracle_mismatch: int
    invalid: int


def _import_run(store: AuditStore, run_id: int) -> ImportResult:
    result = load_import_result(store, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no import run {run_id}")
    return result


def _generated_tests(store: AuditStore, run_id: int | None) -> tuple[list[TestCase], str]:
    if run_id is not None:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"no run {run_id}")
        if run.llm_mode == IMPORT_LLM_MODE:
            raise HTTPException(status_code=422, detail=f"run {run_id} is an import, not generated")
        return store.get_tests(run_id), f"generated run #{run_id}"
    by_id: dict[str, TestCase] = {}
    runs = [r for r in store.list_runs() if r.llm_mode != IMPORT_LLM_MODE]
    for r in runs:
        for t in store.get_tests(r.id):
            by_id.setdefault(t.id, t)
    return list(by_id.values()), f"all generated runs in the audit trail ({len(runs)} runs)"


def install(app: FastAPI) -> None:
    """Register the import routes on ``app`` (needs ``app.state.store`` and ``.spec``)."""

    def compare(run_id: int, generated_run_id: int | None) -> CompareResponse:
        store: AuditStore = app.state.store
        _import_run(store, run_id)
        imported = store.get_tests(run_id)
        generated, source = _generated_tests(store, generated_run_id)
        cmp = compare_coverage(imported, generated, app.state.spec)
        md = comparison_markdown(
            cmp, f"# Imported-test baseline coverage (import run #{run_id} vs {source})")
        return CompareResponse(import_run_id=run_id, generated_source=source, comparison=cmp,
                               markdown=md)

    @app.get("/import/format")
    def import_format() -> dict[str, Any]:
        doc = app.state.repo_root / "docs" / "IMPORT_FORMAT.md"
        example = app.state.repo_root / "data" / "imports" / "legacy_bcm_regression.yaml"
        return {
            "format_version": FORMAT_VERSION, "max_file_bytes": MAX_FILE_BYTES,
            "documentation": doc.read_text(encoding="utf-8") if doc.exists() else "",
            "example_filename": example.name,
            "example": example.read_text(encoding="utf-8") if example.exists() else "",
        }

    @app.post("/import", response_model=ImportResponse)
    def import_suite(req: ImportRequest) -> ImportResponse:
        try:
            parsed = parse_import(req.content, req.filename)
        except ImportFormatError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ImportResponse(**import_tests(parsed, app.state.spec, app.state.store).model_dump())

    @app.get("/imports", response_model=list[ImportSummary])
    def list_imports() -> list[ImportSummary]:
        store: AuditStore = app.state.store
        out = []
        for run in store.list_runs():
            res = load_import_result(store, run.id)
            if res is not None:
                out.append(ImportSummary(
                    run_id=run.id, suite=res.suite, source_file=res.source_file,
                    started_at=run.started_at, total=res.total, accepted=res.accepted,
                    oracle_mismatch=res.oracle_mismatch, invalid=res.invalid))
        return out

    @app.get("/import/{run_id}", response_model=ImportResponse)
    def get_import(run_id: int) -> ImportResponse:
        return ImportResponse(**_import_run(app.state.store, run_id).model_dump())

    @app.post("/import/{run_id}/compare", response_model=CompareResponse)
    def compare_post(run_id: int, req: CompareRequest) -> CompareResponse:
        return compare(run_id, req.generated_run_id)

    @app.get("/import/{run_id}/compare.md", response_class=PlainTextResponse)
    def compare_md(run_id: int, generated_run_id: int | None = Query(default=None)) -> PlainTextResponse:
        md = compare(run_id, generated_run_id).markdown
        return PlainTextResponse(
            md, media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="import_coverage_{run_id}.md"'})
