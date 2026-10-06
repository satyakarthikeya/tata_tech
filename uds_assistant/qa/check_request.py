"""Check a raw, user-supplied UDS request against the spec and rules engine (capability 3).

The user gives a hex request plus the ECU state (session, unlocked security level, vehicle speed).
This module decodes it (service, subfunction, DID / routine, via :mod:`protocol.describe`), runs it
through the same :func:`uds_assistant.rules.engine.evaluate` the test generator uses, and returns:
structurally valid or not, the expected response bytes or NRC with the engine's own reason
(its evaluation trace), and citations (deterministic spec / standard chunks, plus optional
retrieval over the project layer). No LLM is involved and no bytes are guessed.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from uds_assistant.protocol.constants import Nrc
from uds_assistant.protocol.describe import (
    decode_responses,
    describe_request,
    nrc_name,
    spaced_hex,
)
from uds_assistant.rag.model import Chunk, LayeredCitation, Retriever, citation_location
from uds_assistant.rules.engine import evaluate
from uds_assistant.rules.request import parse_request
from uds_assistant.rules.state import initial_state, with_environment
from uds_assistant.rules.sws_map import refs_for_decision
from uds_assistant.spec.schema import EcuSpec

#: NRCs that mean the request itself is malformed or unknown (not merely refused by state).
STRUCTURAL_NRCS = frozenset(
    {int(Nrc.SERVICE_NOT_SUPPORTED), int(Nrc.SUB_FUNCTION_NOT_SUPPORTED),
     int(Nrc.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT)}
)


class SwsRefView(BaseModel):
    """An AUTOSAR SWS requirement behind the decision (from :mod:`uds_assistant.rules.sws_map`)."""

    sws_id: str
    summary: str
    """Own-words paraphrase, not SWS text."""
    verified: bool
    """True only once ``verify_sws_map`` checked the id against the local PDF."""
    in_corpus: bool = False
    """True when the local SWS PDF is indexed and this requirement is one of its chunks."""
    page: int | None = None
    section: str | None = None


class RequestCheck(BaseModel):
    """Result of :func:`check_request`."""

    request_hex: str
    parse_error: str | None = None
    structurally_valid: bool
    decoded: str = ""
    state: dict[str, int | None] = Field(default_factory=dict)
    outcome: str
    """``positive``, ``negative``, ``no_response`` (suppressed) or ``invalid`` (not hex / empty)."""
    expected_responses_hex: list[str] = Field(default_factory=list)
    expected_text: str = ""
    nrc: int | None = None
    nrc_name: str | None = None
    reason: str = ""
    trace: list[str] = Field(default_factory=list)
    citations: list[LayeredCitation] = Field(default_factory=list)
    sws_refs: list[SwsRefView] = Field(default_factory=list)
    """AUTOSAR SWS ids the rules engine cites for this decision (see ``rules/sws_map.py``)."""
    comparison: str | None = None
    """``match`` / ``mismatch`` when an actual ECU response was supplied, else ``None``."""
    comparison_detail: str = ""


def parse_hex(text: str) -> bytes:
    """Parse ``"2E 01 00 11"`` / ``"0x2e010011"`` into bytes; ``ValueError`` if not hex."""
    cleaned = re.sub(r"0x|[\s,_]", "", text, flags=re.IGNORECASE)
    if not cleaned:
        raise ValueError("empty request")
    if len(cleaned) % 2:
        raise ValueError("odd number of hex digits")
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        raise ValueError("contains characters that are not hex digits") from None


def _citation(chunk: Chunk, quote: str | None = None) -> LayeredCitation:
    return LayeredCitation(
        source=chunk.source_path, ref=chunk.ref, quote=quote or chunk.text[:200], layer=chunk.layer,
        **citation_location(chunk),
    )


def _deterministic_chunk_ids(spec: EcuSpec, raw: bytes, session: int, nrc: int | None) -> list[str]:
    ids = [f"standard:svc-0x{raw[0]:02x}"]
    if nrc is not None:
        ids += ["standard:nrcs", "standard:nrc-order"]
    sess = spec.get_session(session)
    if sess is not None:
        ids.append(f"ecu:session:{sess.name}")
    did_ids: list[int] = []
    if raw[0] == 0x22:
        body = raw[1:]
        did_ids = [(body[i] << 8) | body[i + 1] for i in range(0, len(body) - 1, 2)]
    elif raw[0] == 0x2E and len(raw) >= 3:
        did_ids = [(raw[1] << 8) | raw[2]]
    for did in did_ids:
        d = spec.get_did(did)
        if d is not None:
            ids.append(f"ecu:did:{d.name}")
    if raw[0] == 0x31 and len(raw) >= 4:
        r = spec.get_routine((raw[2] << 8) | raw[3])
        if r is not None:
            ids.append(f"ecu:routine:{r.name}")
    if raw[0] == 0x27 and len(raw) >= 2:
        sub = raw[1] & 0x7F
        for lvl in spec.security_levels:
            if sub in (lvl.seed_subfunction, lvl.key_subfunction):
                ids.append(f"ecu:security_level:{lvl.name}")
    return list(dict.fromkeys(ids))


def _compare(actual: str | None, expected: list[str]) -> tuple[str | None, str]:
    """Compare an observed ECU response (frames separated by ``|``) with the predicted bytes."""
    if actual is None or not actual.strip():
        return None, ""
    try:
        frames = [parse_hex(part).hex() for part in actual.split("|") if part.strip()]
    except ValueError as exc:
        return "mismatch", f"The observed response is not valid hex: {exc}."
    want = decode_responses(expected)
    got = decode_responses(frames)
    if frames == expected:
        return "match", f"The observed response equals the predicted one: {got}."
    return "mismatch", f"Predicted {want}; observed {got}."


def check_request(
    spec: EcuSpec,
    chunks: list[Chunk],
    request: str,
    *,
    session: int = 0x01,
    unlocked_level: int | None = None,
    vehicle_speed_kph: int = 0,
    retriever: Retriever | None = None,
    actual_response: str | None = None,
) -> RequestCheck:
    """Decode ``request`` (hex text), evaluate it in the given ECU state, and cite the evidence."""
    state_info: dict[str, int | None] = {
        "session": session, "unlocked_level": unlocked_level, "vehicle_speed_kph": vehicle_speed_kph
    }
    try:
        raw = parse_hex(request)
    except ValueError as exc:
        return RequestCheck(
            request_hex=request.strip(), parse_error=str(exc), structurally_valid=False,
            state=state_info, outcome="invalid", reason=f"Not a hex request: {exc}.",
        )
    if spec.get_session(session) is None:
        return RequestCheck(
            request_hex=raw.hex(), parse_error=f"session {session:#04x} is not in the spec",
            structurally_valid=False, state=state_info, outcome="invalid",
            reason=f"Session {session:#04x} is not defined in the spec.",
        )
    if unlocked_level is not None and spec.get_security_level(unlocked_level) is None:
        return RequestCheck(
            request_hex=raw.hex(),
            parse_error=f"security level {unlocked_level:#04x} is not in the spec",
            structurally_valid=False, state=state_info, outcome="invalid",
            reason=f"Security level {unlocked_level:#04x} is not defined in the spec.",
        )

    state = initial_state(spec).model_copy(
        update={"active_session": session, "unlocked_level": unlocked_level}
    )
    state = with_environment(state, vehicle_speed_kph=vehicle_speed_kph)
    result = evaluate(spec, state, raw, now_ms=0)
    nrc = int(result.nrc) if result.nrc is not None else None
    structural = nrc not in STRUCTURAL_NRCS
    names = {d.id: d.name for d in spec.dids}
    decoded = describe_request(raw.hex(), names)
    parsed = parse_request(raw)
    if parsed.suppress_positive:
        decoded += " [suppress-positive-response bit set]"

    responses = [r.hex() for r in result.responses]
    if nrc is not None:
        outcome = "negative"
        expected = f"{spaced_hex(result.responses[-1])} (negative response: {nrc_name(nrc)})"
    elif result.responses:
        outcome = "positive"
        expected = " then ".join(spaced_hex(r) for r in result.responses)
    else:
        outcome = "no_response"
        expected = "no response (positive response suppressed)"
    final_trace = [t for t in result.decision.trace if not t.startswith("Result")]
    reason = (
        final_trace[-1]
        if nrc is not None and final_trace
        else "All checks of the NRC evaluation order passed."
    )

    cites: list[LayeredCitation] = []
    by_id = {c.id: c for c in chunks}
    for cid in _deterministic_chunk_ids(spec, raw, session, nrc):
        if cid in by_id:
            cites.append(_citation(by_id[cid]))
    sws_refs: list[SwsRefView] = []
    pending = result.decision.pending_nrc
    decided = nrc if nrc is not None else (int(pending) if pending is not None else None)
    for req in refs_for_decision(parsed.sid, decided, result.trace,
                                 suppressed=outcome == "no_response"):
        chunk = by_id.get(f"standard:{req.sws_id}")
        sws_refs.append(SwsRefView(
            sws_id=req.sws_id, summary=req.summary, verified=req.verified,
            in_corpus=chunk is not None, page=chunk.page if chunk else None,
            section=chunk.section if chunk else None))
        if chunk is not None:
            cites.append(_citation(chunk))
    if retriever is not None:
        query = f"{decoded} {nrc_name(nrc) if nrc is not None else ''}".strip()
        seen = {c.ref for c in cites}
        for hit in retriever.search(query, k=2, collections=["project"]):
            if hit.chunk.ref not in seen:
                cites.append(_citation(hit.chunk))
    comparison, detail = _compare(actual_response, responses)
    return RequestCheck(
        request_hex=raw.hex(),
        comparison=comparison,
        comparison_detail=detail,
        structurally_valid=structural,
        decoded=decoded,
        state=state_info,
        outcome=outcome,
        expected_responses_hex=responses,
        expected_text=expected,
        nrc=nrc,
        nrc_name=nrc_name(nrc) if nrc is not None else None,
        reason=reason,
        trace=result.trace,
        citations=cites,
        sws_refs=sws_refs,
    )

