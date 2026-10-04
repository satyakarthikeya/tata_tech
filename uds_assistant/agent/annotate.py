"""Attach ``confidence`` / ``confidence_reason`` and target provenance to the kept tests.

Runs after validate + explain; only reads the state and sets the two confidence fields on a
copy of each test, so steps, ids, citations and the choice of tests are untouched.
"""

from __future__ import annotations

from uds_assistant.agent.confidence import generated_test_confidence
from uds_assistant.agent.grounding import target_is_written
from uds_assistant.agent.options import applicable_params, option_refs, primary_service, spec_index
from uds_assistant.agent.state import PipelineDeps, PipelineState, PlannedInstance, TargetEvidence
from uds_assistant.testgen.model import TestCase


def target_evidence(deps: PipelineDeps, inst: PlannedInstance, text: str) -> list[TargetEvidence]:
    """Service (primary), DIDs and routines of one kept test, each marked written/inferred."""
    index = spec_index(deps.spec)
    tid, idx = inst.choice.template_id, inst.choice.option_index
    refs = option_refs(deps.spec, tid, idx)
    sid = primary_service(tid, applicable_params(deps.spec, tid)[idx])
    out: list[TargetEvidence] = []
    items = [("service", sid, index["services"].get(sid, ""))]
    items += [("did", d, index["dids"].get(d, "")) for d in refs.dids]
    items += [("routine", r, index["routines"].get(r, "")) for r in refs.routines]
    for kind, ident, name in items:
        out.append(TargetEvidence(kind=kind, id=ident, name=name,
                                  written=target_is_written(kind, ident, name, text)))
    return out


def annotate_tests(
    state: PipelineState, deps: PipelineDeps, extra_fallbacks: list[str]
) -> tuple[list[TestCase], dict[str, list[TargetEvidence]]]:
    """Return the kept tests with confidence set, and the per-test target provenance."""
    scores = {(h.chunk.source_path, h.chunk.ref): h.score for h in state.hits}
    rejections = len(state.rejected)
    retries = max(0, state.plan_attempts - 1)
    fallbacks = list(extra_fallbacks)
    tests: list[TestCase] = []
    provenance: dict[str, list[TargetEvidence]] = {}
    for inst in state.validated:
        t = inst.test
        targets = target_evidence(deps, inst, state.requirement_text)
        provenance[t.id] = targets
        cited = [scores[(c.source, c.ref)] for c in t.citations if (c.source, c.ref) in scores]
        # explain events name one test ("explain: <id>: ..."); all others are requirement-wide.
        own = [e for e in fallbacks
               if not e.startswith("explain: ")
               or e.startswith(("explain: batch", f"explain: {t.id}:"))]
        level, why = generated_test_confidence(
            inferred=[f"{e.id}" for e in targets if not e.written],
            top_score=max(cited) if cited else None,
            rejections=rejections,
            retries=retries,
            grounding_drops=len(state.grounding_drops),
            fallbacks=own,
        )
        tests.append(t.model_copy(update={"confidence": level, "confidence_reason": why}))
    return tests, provenance


__all__ = ["annotate_tests", "target_evidence"]
