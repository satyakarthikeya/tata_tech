"""Section 10 of the evaluation: the AUTOSAR SWS standard source and how the rules cite it.

Deterministic (no model):

- which source fed the ``standard`` layer this run (SWS PDF + notes, or the notes alone) and how
  many SWS requirement chunks it produced;
- ``rules/sws_map.py``: ids the rules cite, ids marked verified, and cited ids that are chunks
  of this run's corpus (0 without the PDF);
- NRC decisions backed by an SWS id: every negative or response-pending decision the rules
  engine makes while replaying a test suite (the conformance sweep and the generated tests),
  counted as backed when :func:`uds_assistant.rules.sws_map.refs_for_decision` returns at least
  one id, and as verified-backed when one of those ids is marked verified;
- citations of the generated tests that point at an SWS requirement chunk.
"""

from __future__ import annotations

from typing import Any

from uds_assistant.rag.model import Chunk
from uds_assistant.rules.engine import RulesSession
from uds_assistant.rules.state import dtc_code_to_int, with_dtc_status
from uds_assistant.rules.sws_map import SWS_RELEASE, SWS_REQUIREMENTS, refs_for_decision
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.model import TestCase


def nrc_backing(spec: EcuSpec, tests: list[TestCase]) -> dict[str, Any]:
    """Replay ``tests`` through the rules engine and count NRC decisions backed by SWS ids."""
    decisions = backed = verified = 0
    unbacked: dict[str, int] = {}
    for test in tests:
        rs = RulesSession(spec, now_ms=0)
        for step in test.steps:
            if step.kind == "send":
                res = rs.send(step.request_bytes)
                nrc = res.decision.nrc if res.decision.nrc is not None else res.decision.pending_nrc
                if nrc is None:
                    continue
                decisions += 1
                refs = refs_for_decision(res.decision.sid, int(nrc), res.trace)
                if refs:
                    backed += 1
                    verified += any(r.verified for r in refs)
                else:
                    sid = res.decision.sid
                    key = f"SID 0x{sid:02X} NRC 0x{int(nrc):02X}" if sid is not None else "empty"
                    unbacked[key] = unbacked.get(key, 0) + 1
            elif step.kind == "advance_time":
                rs.advance(step.ms)
            elif step.kind == "set_environment":
                rs.set_environment(vehicle_speed_kph=step.vehicle_speed_kph,
                                   nvm_write_fault=step.nvm_write_fault)
            elif step.kind == "set_dtc_status":
                rs.state = with_dtc_status(rs.state, dtc_code_to_int(step.code), step.status)
    return {"tests": len(tests), "nrc_decisions": decisions, "sws_backed": backed,
            "sws_backed_verified": verified, "unbacked": dict(sorted(unbacked.items()))}


def standard_sources_section(
    status: dict[str, Any], corpus: list[Chunk], spec: EcuSpec,
    sweep: list[TestCase], generated: list[TestCase],
) -> dict[str, Any]:
    """The report dict for section 10 (``status`` from :func:`rag.autosar.sws_status`)."""
    sws_chunks = {c.ref: c for c in corpus if c.id.startswith("standard:SWS_")}
    sws_sources = {c.source_path for c in sws_chunks.values()}
    cites = [c for t in generated for c in t.citations]
    cited_ids = set(SWS_REQUIREMENTS)
    return {
        "standard_source": status.get("mode"),
        "detail": status.get("detail"),
        "sws_release_expected": SWS_RELEASE,
        "sws_releases_in_corpus": sorted({c.release or "?" for c in sws_chunks.values()}),
        "sws_chunks": len(sws_chunks),
        "sws_ids_cited_by_rules": len(cited_ids),
        "sws_ids_verified": sum(1 for r in SWS_REQUIREMENTS.values() if r.verified),
        "sws_ids_in_corpus": len(cited_ids & set(sws_chunks)),
        "sweep": nrc_backing(spec, sweep),
        "generated": nrc_backing(spec, generated),
        "generated_citations": len(cites),
        "generated_citations_to_sws": sum(1 for c in cites if c.source in sws_sources),
    }


def section_rows(s: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    """Rows for the report table (empty for reports written before this section existed)."""
    if not s:
        return []
    sw, gen = s["sweep"], s["generated"]
    return [
        ("10", "Standard layer source", f"{s['standard_source']} ({s['sws_chunks']} SWS chunks)"),
        ("10", "SWS ids cited by the rules: verified / in this corpus",
         f"{s['sws_ids_verified']} / {s['sws_ids_in_corpus']} of {s['sws_ids_cited_by_rules']}"),
        ("10", "Sweep NRC decisions backed by an SWS id (verified)",
         f"{sw['sws_backed']}/{sw['nrc_decisions']} ({sw['sws_backed_verified']})"),
        ("10", "Generated-test NRC decisions backed by an SWS id (verified)",
         f"{gen['sws_backed']}/{gen['nrc_decisions']} ({gen['sws_backed_verified']})"),
        ("10", "Generated-test citations pointing at an SWS requirement",
         f"{s['generated_citations_to_sws']}/{s['generated_citations']}"),
    ]
