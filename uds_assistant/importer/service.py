"""Validate parsed imported tests against the rules engine and record them in the audit trail.

Per test, one of three outcomes:

- ``accepted``: schema valid and every expected response equals what the deterministic rules
  engine predicts. Stored with ``review_status="validated"`` (never approved: a human still has to
  approve before run or export) and ``origin="imported"``.
- ``oracle_mismatch``: schema valid but the author's expected bytes differ from the rules engine
  (the legacy test disagrees with the spec, or the spec changed). Reported with the differing steps,
  not stored as a runnable test, not counted in coverage.
- ``invalid``: the file's entry does not fit the format / the ``TestCase`` schema.

The audit trail gets one run (``llm_mode="import"``, requirement id ``import:<suite>``), one
``import`` decision per test and one ``import_result`` decision holding the full outcome list.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from uds_assistant.eval.trace import request_did_ids, request_routine_id, trace_test
from uds_assistant.importer.format import ParsedImport
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.store.audit import AuditStore
from uds_assistant.testgen.criteria import annotate_test
from uds_assistant.testgen.model import Citation, TestCase
from uds_assistant.testgen.templates import validate_test

IMPORT_LLM_MODE = "import"
IMPORT_NODE = "import"
RESULT_NODE = "import_result"
Status = Literal["accepted", "oracle_mismatch", "invalid"]


class ImportOutcome(BaseModel):
    source_id: str
    title: str = ""
    status: Status
    category: str | None = None
    steps: int = 0
    errors: list[str] = Field(default_factory=list)
    """Format/schema problems (``invalid``) or the rules-engine differences (``oracle_mismatch``)."""


class ImportResult(BaseModel):
    run_id: int
    suite: str
    description: str = ""
    source_file: str
    sha256: str
    total: int
    accepted: int
    oracle_mismatch: int
    invalid: int
    outcomes: list[ImportOutcome]


def spec_citations(spec: EcuSpec, test: TestCase) -> list[Citation]:
    """Spec items the test touches, as ``bcm_spec.yaml`` citations (derived, never invented)."""
    refs: list[str] = []

    def add(ref: str) -> None:
        if ref not in refs:
            refs.append(ref)

    key_to_level = {lvl.key_subfunction: lvl for lvl in spec.security_levels}
    seed_to_level = {lvl.seed_subfunction: lvl for lvl in spec.security_levels}
    for ev in trace_test(spec, test).sends:
        for did in request_did_ids(ev.request):
            d = spec.get_did(did)
            if d is not None:
                add(f"dids.{d.name}")
        rid = request_routine_id(ev.request)
        r = spec.get_routine(rid) if rid is not None else None
        if r is not None:
            add(f"routines.{r.name}")
        s = spec.get_session(ev.session)
        if s is not None:
            add(f"sessions.{s.name}")
        if ev.sid == 0x27 and ev.subfunction is not None:
            lvl = seed_to_level.get(ev.subfunction) or key_to_level.get(ev.subfunction)
            if lvl is not None:
                add(f"security_levels.{lvl.name}")
    return [Citation(source="bcm_spec.yaml", ref=r) for r in refs]


def _prepare(spec: EcuSpec, test: TestCase) -> TestCase:
    """Fill empty preconditions / pass criteria deterministically and add spec citations."""
    out = annotate_test(spec, test)
    return out.model_copy(update={
        "citations": [*out.citations, *spec_citations(spec, out)],
        "review_status": "validated",
    })


def import_tests(parsed: ParsedImport, spec: EcuSpec, store: AuditStore) -> ImportResult:
    """Validate every parsed test and record the import (see module docstring)."""
    run_id = store.start_run(
        requirement_id=f"import:{parsed.suite}",
        requirement_text=f"Imported from {parsed.source_file} (sha256 {parsed.sha256})",
        llm_mode=IMPORT_LLM_MODE,
        retriever="none",
    )
    outcomes: list[ImportOutcome] = []
    try:
        for pt in parsed.tests:
            if pt.test is None:
                outcomes.append(ImportOutcome(source_id=pt.source_id, status="invalid",
                                              errors=pt.errors))
                continue
            report = validate_test(spec, pt.test)
            base = {"source_id": pt.source_id, "title": pt.test.title,
                    "category": pt.test.category, "steps": len(pt.test.steps)}
            if report.ok:
                store.record_test(run_id, _prepare(spec, pt.test))
                outcomes.append(ImportOutcome(status="accepted", **base))
            else:
                outcomes.append(ImportOutcome(status="oracle_mismatch", errors=report.mismatches,
                                              **base))
        for o in outcomes:
            detail = "; ".join(o.errors) if o.errors else "matches the rules engine; awaiting review"
            store.record_decision(run_id, IMPORT_NODE, f"{o.source_id} | {o.status} | {detail}")
        result = ImportResult(
            run_id=run_id, suite=parsed.suite, description=parsed.description,
            source_file=parsed.source_file, sha256=parsed.sha256, total=len(outcomes),
            accepted=sum(o.status == "accepted" for o in outcomes),
            oracle_mismatch=sum(o.status == "oracle_mismatch" for o in outcomes),
            invalid=sum(o.status == "invalid" for o in outcomes), outcomes=outcomes)
        store.record_decision(run_id, RESULT_NODE, result.model_dump_json())
    except Exception:
        store.finish_run(run_id, "failed")
        raise
    store.finish_run(run_id, "completed")
    return result


def load_import_result(store: AuditStore, run_id: int) -> ImportResult | None:
    """The stored outcome list of an import run (None if ``run_id`` is not an import run)."""
    run = store.get_run(run_id)
    if run is None or run.llm_mode != IMPORT_LLM_MODE:
        return None
    rows = store.get_decisions(run_id, RESULT_NODE)
    return ImportResult.model_validate_json(rows[-1].message) if rows else None
