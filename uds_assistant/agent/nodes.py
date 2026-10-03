"""Pipeline node functions: parse -> retrieve -> plan -> instantiate -> validate -> explain.

Each node takes the current :class:`PipelineState` plus :class:`PipelineDeps`
and returns a *new* state (the input is never mutated). Both the LangGraph
graph and the plain-Python loop call exactly these functions.

Byte provenance: only :func:`instantiate` creates test steps, and it does so
exclusively via ``TEMPLATES[template_id].instantiate(spec,
applicable_params(spec, template_id)[option_index])``. :func:`validate`
re-derives the steps the same way and rejects any test whose steps differ.
"""

from __future__ import annotations

import re
import string

from uds_assistant.agent.grounding import (
    apply_quote_check,
    ground_identifiers,
    ground_security_levels,
    ground_services,
    ground_sessions,
)
from uds_assistant.agent.options import (
    OptionRefs,
    ShortlistEntry,
    TemplateOptions,
    build_catalog,
    option_refs,
    plan_shortlist,
    primary_service,
    render_shortlist,
    spec_index,
)
from uds_assistant.agent.state import (
    DroppedTest,
    PipelineDeps,
    PipelineState,
    PlannedInstance,
    RejectedChoice,
)
from uds_assistant.llm.base import (
    ALL_INTENTS,
    ConstrainedPlan,
    ExplanationBatch,
    LLMError,
    ParsedRequirement,
    PlannedTest,
    TestPlan,
    build_prompt,
    constrained_plan_schema,
    context_budget,
    drain_truncation_events,
    estimate_tokens,
    truncation_mark,
)
from uds_assistant.llm.prompts import (
    EXPLAIN_BATCH_INSTRUCTION,
    PARSE_INSTRUCTION,
    PLAN_COMPACT_TEMPLATE,
    PLAN_CONSTRAINED_TEMPLATE,
    PLAN_INSTRUCTION,
    SYSTEM_PROMPT,
)
from uds_assistant.rag.citations import citation_is_valid
from uds_assistant.rag.model import Chunk, Hit
from uds_assistant.testgen.model import Citation, TestCase
from uds_assistant.testgen.templates import TEMPLATES, applicable_params, validate_test

COLLECTIONS = ("standard", "ecu_spec", "project")
MAX_CITATIONS = 6
PLAN_PROMPT_BUDGET = 0.6
"""Fraction of a limited context window the plan prompt (system + user) may use; the
rest is left for the JSON answer."""
PLAN_SHORTLIST_MAX = 30
"""Upper bound on options in a compact plan prompt (cut further to fit the budget). Raised
from 24 in Part C3: with template set v3 the full relevant list of a write requirement grew
to 26 and the old cap dropped a previously offered option; 30 options stay at ~1.7k of the
~2.4k-token plan budget for num_ctx 4096."""
EXPLAIN_TOKENS_PER_TEST = 90
"""Estimated answer tokens for one explanation (2-3 sentences plus JSON framing). A batch is
sized so that prompt tokens + this * tests stays inside the context window; with num_ctx
4096 a requirement's tests fit in one or two calls instead of one call per test."""
EXPLAIN_STEP_CHARS = 140
"""Characters of the one-line step summary sent per test."""

_TRAILING_GROUP_RE = re.compile(r"\s*\([^()]*\)\s*$")


def normalise_template_id(raw: str) -> str:
    """Canonical form of a planner ``template_id``: trailing ``(category)`` group removed,
    whitespace and quote characters trimmed, lower-cased. Never maps to a *different*
    template: the caller accepts the result only if it is an exact catalog id."""
    junk = string.whitespace + "\"'`"
    text = raw.strip(junk)
    text = _TRAILING_GROUP_RE.sub("", text).strip(junk)
    return text.lower()


def _record_truncations(s: PipelineState, deps: PipelineDeps, node: str, mark: int) -> None:
    """Copy truncation events the backend recorded since ``mark`` into the run (verbatim)."""
    for event in drain_truncation_events(deps.llm, mark):
        s.fallback_events.append(f"{node}: {event}")
        s.log(node, event)


def _catalog(deps: PipelineDeps) -> list[TemplateOptions]:
    cached = deps.catalog_cache.get("catalog")
    if cached is None:
        cached = build_catalog(deps.spec)
        deps.catalog_cache["catalog"] = cached
    return cached  # type: ignore[return-value]


# -------------------------------------------------------------------------------- parse


def parse(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """LLM -> :class:`ParsedRequirement`; identifiers not in the spec are dropped + noted."""
    s = state.model_copy(deep=True)
    index = spec_index(deps.spec)
    prompt = build_prompt(
        PARSE_INSTRUCTION,
        {
            "task": "parse",
            "requirement_id": s.requirement_id,
            "requirement_text": s.requirement_text,
            "spec_index": index,
            "allowed_intents": list(ALL_INTENTS),
        },
    )
    mark = truncation_mark(deps.llm)
    try:
        raw = deps.llm.complete_json(SYSTEM_PROMPT, prompt, ParsedRequirement)
        parsed = ParsedRequirement.model_validate(raw.model_dump())
    except (LLMError, ValueError) as exc:
        s.log("parse", f"LLM parse failed ({exc}); continuing with an empty parse.")
        s.fallback_events.append(f"parse: LLM call failed ({exc}); used an empty parse")
        parsed = ParsedRequirement(intents=["positive"])
    _record_truncations(s, deps, "parse", mark)

    kept: dict[str, list[str]] = {}
    for field_name in ("services", "dids", "routines", "sessions", "security_levels", "dtcs"):
        values: list[str] = getattr(parsed, field_name)
        known = index[field_name]
        kept[field_name] = [v for v in values if v in known]
        for v in values:
            if v not in known:
                note = f"Dropped unknown {field_name[:-1]} identifier {v} (not in spec)."
                s.notes.append(note)
                s.log("parse", note)
    if getattr(deps.llm, "applies_grounding", True):
        # Grounding is for models that hallucinate identifiers. The mock sets
        # applies_grounding = False: it only emits ids written in the text or matched by a
        # name phrase, so the check is a no-op there and is skipped to keep its output
        # identical by construction.
        text = s.requirement_text
        drops = []
        kept, quote_drops, valid_quotes = apply_quote_check(kept, parsed.evidence, text)
        drops += quote_drops
        kept, id_drops = ground_identifiers(kept, text, index, deps.retriever)
        drops += id_drops
        kept["sessions"], session_drops = ground_sessions(kept["sessions"], text, index)
        kept["security_levels"], level_drops = ground_security_levels(
            kept["security_levels"], text
        )
        drops += session_drops + level_drops
        kept["services"], service_drops, reasons = ground_services(
            kept["services"], text, kept, list(parsed.intents), deps.retriever
        )
        drops += service_drops
        for drop in drops:
            note = f"Dropped ungrounded {drop.field[:-1]} identifier {drop.identifier}: {drop.reason}."
            s.notes.append(note)
            s.log("parse", note)
        for sid, why in reasons.items():
            s.log("parse", f"service {sid} kept: {why}.")
        if parsed.services and not kept["services"]:
            note = "No parsed service had evidence in the requirement; continuing with none."
            s.notes.append(note)
            s.log("parse", note)
        kept_items = {
            f"{field[:-1] if field != 'security_levels' else 'security_level'}:{v}"
            for field, values in kept.items()
            for v in values
        }
        evidence = {k: q for k, q in valid_quotes.items() if k in kept_items}
        kept_all: dict[str, object] = {**kept, "evidence": evidence}
    else:
        kept_all = dict(kept)
    s.parsed = parsed.model_copy(update=kept_all)
    p = s.parsed
    s.log(
        "parse",
        f"services={p.services} dids={p.dids} routines={p.routines} sessions={p.sessions} "
        f"levels={p.security_levels} dtcs={p.dtcs} intents={list(p.intents)}",
    )
    return s


# ----------------------------------------------------------------------------- retrieve


def _retrieval_queries(state: PipelineState, deps: PipelineDeps) -> list[tuple[str, list[str], int]]:
    queries: list[tuple[str, list[str], int]] = [
        (state.requirement_text, [c], 3) for c in COLLECTIONS
    ]
    queries.append((f"{state.requirement_id} {state.requirement_text}", ["project"], 1))
    p = state.parsed or ParsedRequirement()
    index = spec_index(deps.spec)
    for did in p.dids:
        queries.append((f"DID {did} {index['dids'][did]}", ["ecu_spec"], 1))
    for rid in p.routines:
        queries.append((f"Routine {rid} {index['routines'][rid]}", ["ecu_spec"], 1))
    for lvl in p.security_levels:
        queries.append((f"Security level {lvl} {index['security_levels'][lvl]}", ["ecu_spec"], 1))
    for sess in p.sessions:
        queries.append((f"Session {sess} {index['sessions'][sess]}", ["ecu_spec"], 1))
    for code in p.dtcs:
        queries.append((f"DTC {code} {index['dtcs'][code]}", ["ecu_spec"], 1))
    for sid in p.services:
        queries.append((f"{sid} {index['services'][sid]}", ["standard", "project"], 2))
    return queries


def retrieve(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """Search the layered collections with the requirement text and its identifiers."""
    s = state.model_copy(deep=True)
    seen: set[str] = set()
    hits: list[Hit] = []
    for query, collections, k in _retrieval_queries(s, deps):
        for hit in deps.retriever.search(query, k=k, collections=collections):
            if hit.score <= 0 or hit.chunk.id in seen:
                continue
            seen.add(hit.chunk.id)
            hits.append(hit)
    s.hits = hits
    per_collection = {c: sum(1 for h in hits if h.chunk.collection == c) for c in COLLECTIONS}
    s.log("retrieve", f"{len(hits)} evidence chunks kept: {per_collection}")
    return s


# --------------------------------------------------------------------------------- plan


def _choice_key(template_id: str, index: int) -> tuple[str, int]:
    return (template_id, index)


def _parsed_lists(parsed: ParsedRequirement) -> dict[str, list[str]]:
    data = parsed.model_dump()
    return {k: [str(v) for v in data[k]] for k in
            ("services", "dids", "routines", "sessions", "security_levels", "dtcs", "intents")}


def _parsed_line(parsed: dict[str, list[str]]) -> str:
    return "; ".join(f"{k} {', '.join(v) if v else '-'}" for k, v in parsed.items())


def compact_plan_prompt(
    state: PipelineState,
    deps: PipelineDeps,
    catalog: list[TemplateOptions],
    exclude: set[tuple[str, int]],
    budget_tokens: int,
    *,
    constrained: bool = False,
) -> tuple[str, list[ShortlistEntry]]:
    """Budgeted plan prompt for a backend with a context limit.

    Options are shortlisted by relevance to the parsed requirement
    (:func:`~uds_assistant.agent.options.plan_shortlist`) and shown with their real
    catalog ``option_index``, so validation, instantiation and byte provenance are
    unchanged. The list is cut (lowest-ranked first) until system + prompt fit
    :data:`PLAN_PROMPT_BUDGET` of the window; the requirement and the instruction come
    after the options.
    """
    parsed = _parsed_lists(state.parsed or ParsedRequirement())
    ranked = plan_shortlist(deps.spec, catalog, parsed, exclude=exclude)[:PLAN_SHORTLIST_MAX]
    limit = int(budget_tokens * PLAN_PROMPT_BUDGET)
    kept = len(state.validated)

    def render(entries: list[ShortlistEntry], fb: list[str]) -> str:
        history = ""
        if kept:
            history += f"Already kept: {kept} test(s); offer only new ones.\n"
        if fb:
            history += "Validation feedback: " + " | ".join(fb) + "\n"
        if history:
            history += "\n"
        template = PLAN_CONSTRAINED_TEMPLATE if constrained else PLAN_COMPACT_TEMPLATE
        return template.format(
            options=render_shortlist(catalog, entries) if entries else "(none left)",
            history=history,
            requirement_id=state.requirement_id,
            requirement_text=state.requirement_text,
            parsed=_parsed_line(parsed),
            instruction=PLAN_INSTRUCTION,
        )

    feedback = [f[:160] for f in state.feedback[-3:]]
    entries = ranked
    prompt = render(entries, feedback)
    while entries and estimate_tokens(SYSTEM_PROMPT, prompt) > limit:
        entries = entries[:-1]
        prompt = render(entries, feedback)
    if estimate_tokens(SYSTEM_PROMPT, prompt) > limit:
        prompt = render(entries, [])
    return prompt, entries


def plan(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """LLM -> :class:`TestPlan`, restricted to registered templates and enumerated options."""
    s = state.model_copy(deep=True)
    s.plan_attempts += 1
    s.needs_replan = False
    catalog = _catalog(deps)
    kept_keys = {_choice_key(v.choice.template_id, v.choice.option_index) for v in s.validated}
    rejected_keys = {_choice_key(r.template_id, r.option_index) for r in s.rejected}
    budget = context_budget(deps.llm)
    shortlist: set[tuple[str, int]] | None = None
    constrained = False
    plan_schema: dict[str, object] = {}
    if budget is None:
        # Unlimited backend (mock): the full catalog as JSON context, unchanged.
        prompt = build_prompt(
            PLAN_INSTRUCTION,
            {
                "task": "plan",
                "requirement_id": s.requirement_id,
                "requirement_text": s.requirement_text,
                "requirement": (s.parsed or ParsedRequirement()).model_dump(),
                "templates": [t.model_dump() for t in catalog],
                "rejected": [r.model_dump() for r in s.rejected],
                "already_kept": [
                    {"template_id": k[0], "option_index": k[1]} for k in sorted(kept_keys)
                ],
                "feedback": s.feedback,
            },
        )
    else:
        exclude = kept_keys | rejected_keys
        constrained = bool(getattr(deps.llm, "supports_json_schema", False))
        prompt, entries = compact_plan_prompt(
            s, deps, catalog, exclude, budget, constrained=constrained
        )
        if constrained and not entries:  # nothing to enumerate: an empty enum is not a schema
            constrained = False
            prompt, entries = compact_plan_prompt(s, deps, catalog, exclude, budget)
        shortlist = {(e.template_id, e.option_index) for e in entries}
        if constrained:
            plan_schema = constrained_plan_schema(
                [(e.template_id, e.option_index) for e in entries]
            )
        s.log(
            "plan",
            f"compact prompt: {len(entries)} shortlisted options, ~"
            f"{estimate_tokens(SYSTEM_PROMPT, prompt)} of {budget} context tokens"
            + (", constrained decoding (enum of offered choices)" if constrained else ""),
        )
    mark = truncation_mark(deps.llm)
    try:
        if constrained:
            reply = deps.llm.complete_json(  # type: ignore[call-arg]
                SYSTEM_PROMPT, prompt, ConstrainedPlan, json_schema=plan_schema
            )
            test_plan = ConstrainedPlan.model_validate(reply.model_dump()).to_test_plan()
        else:
            raw = deps.llm.complete_json(SYSTEM_PROMPT, prompt, TestPlan)
            # Re-validate from a plain dict: drops any extra (e.g. byte) fields a
            # misbehaving backend might have attached.
            test_plan = TestPlan.model_validate(raw.model_dump())
    except (LLMError, ValueError) as exc:
        s.log("plan", f"LLM plan failed ({exc}); no new choices this round.")
        s.fallback_events.append(f"plan: LLM call failed ({exc}); no new choices this round")
        test_plan = TestPlan()
    _record_truncations(s, deps, "plan", mark)
    s.plan = test_plan

    offered = {t.template_id: len(t.options) for t in catalog}
    accepted: list[PlannedTest] = []
    accepted_keys: set[tuple[str, int]] = set()
    choices: list[PlannedTest] = []
    for choice in test_plan.tests:
        norm = normalise_template_id(choice.template_id)
        if norm != choice.template_id and norm in offered:
            note = f"Normalised planner template_id {choice.template_id!r} -> {norm!r}."
            s.notes.append(note)
            s.log("plan", note)
            choice = choice.model_copy(update={"template_id": norm})
        choices.append(choice)
    for choice in choices:
        key = _choice_key(choice.template_id, choice.option_index)
        reason: str | None = None
        if choice.template_id not in TEMPLATES or choice.template_id not in offered:
            reason = f"unknown template id {choice.template_id!r}"
        elif choice.option_index >= offered[choice.template_id]:
            reason = (
                f"option_index {choice.option_index} out of range for {choice.template_id} "
                f"({offered[choice.template_id]} options)"
            )
        elif key in rejected_keys:
            reason = "choice previously failed validation"
        elif shortlist is not None and key not in shortlist and key not in kept_keys:
            reason = "option was not in the offered shortlist"
        if reason is not None:
            s.rejected.append(
                RejectedChoice(
                    template_id=choice.template_id,
                    option_index=choice.option_index,
                    reason=reason,
                    node="plan",
                )
            )
            rejected_keys.add(key)
            s.log("plan", f"Rejected {choice.template_id}[{choice.option_index}]: {reason}")
            continue
        if key in kept_keys or key in accepted_keys:
            s.log("plan", f"Skipped duplicate {choice.template_id}[{choice.option_index}].")
            continue
        accepted_keys.add(key)
        accepted.append(choice)
    s.accepted = accepted
    s.log(
        "plan",
        f"attempt {s.plan_attempts}: {len(test_plan.tests)} choices proposed, "
        f"{len(accepted)} accepted: "
        + ", ".join(f"{c.template_id}[{c.option_index}]" for c in accepted),
    )
    return s


# -------------------------------------------------------------------------- instantiate


def _best_quote(chunk: Chunk, ids: list[str]) -> str | None:
    """A verbatim line of ``chunk`` that mentions one of ``ids`` (else its first line)."""
    lines = [ln.strip() for ln in chunk.text.splitlines() if ln.strip()]
    candidates = [ln for ident in ids for ln in lines if ident.lower() in ln.lower()]
    candidates += lines[:1]
    for line in candidates:
        cand = Citation(source=chunk.source_path, ref=chunk.ref, quote=line)
        if citation_is_valid(cand, [chunk]):
            return line
    return None


_ENTITY_GROUPS: tuple[tuple[str, str, str, int], ...] = (
    # (OptionRefs field, ecu_spec ref prefix, query label, max entries cited)
    ("dids", "did:", "DID", 3),
    ("routines", "routine:", "Routine", 2),
    ("dtcs", "dtc:", "DTC", 1),
    ("security_levels", "security_level:", "Security level", 1),
    ("sessions", "session:", "Session", 1),
)


def evidence_targets(
    refs: OptionRefs, primary_sid: str, index: dict[str, dict[str, str]]
) -> list[tuple[str, str, str, list[str]]]:
    """What one test should cite: ``(collection, ref_or_prefix, ident, query)`` tuples.

    For ECU-spec entities the ref is exact (``did:<name>``, as built by
    :func:`uds_assistant.rag.ingest.chunk_ecu_spec`); for the service the
    standard notes and the behaviour contract are searched by identifier.
    """
    targets: list[tuple[str, str, str, list[str]]] = []
    for group, prefix, label, limit in _ENTITY_GROUPS:
        for ident in getattr(refs, group)[:limit]:
            name = index[group].get(ident)
            if name is None:
                continue
            targets.append(("ecu_spec", f"{prefix}{name}", ident, [f"{label} {ident} {name}"]))
    svc_name = index["services"].get(primary_sid, "")
    for collection in ("standard", "project"):
        targets.append((collection, "", primary_sid, [f"{primary_sid} {svc_name}"]))
    return targets


def _match(hit: Hit, collection: str, ref: str, ident: str) -> bool:
    c = hit.chunk
    if c.collection != collection:
        return False
    if ref:
        return c.ref == ref
    return ident in c.identifiers


def _rank_service_hit(hit: Hit, ident: str) -> int:
    """Prefer chunks whose heading (first line) names the service."""
    first = hit.chunk.text.splitlines()[0] if hit.chunk.text else ""
    return 0 if ident.lower() in first.lower() else 1


def select_citations(
    hits: list[Hit],
    targets: list[tuple[str, str, str, list[str]]],
    requirement_id: str,
) -> list[Citation]:
    """Turn retrieval hits relevant to one test into citations.

    Order: ECU-spec chunks for the test's entities, the standard notes section
    for its main service, the requirement row itself, the behaviour-contract
    section for the service. Only chunks that were actually retrieved are cited.
    """
    chosen: list[tuple[Hit, str]] = []
    used: set[str] = set()
    req_hits = [h for h in hits if h.chunk.collection == "project" and h.chunk.ref == requirement_id]
    for collection, ref, ident, _query in targets:
        if collection == "project" and req_hits and req_hits[0].chunk.id not in used:
            used.add(req_hits[0].chunk.id)
            chosen.append((req_hits[0], ""))
        matches = [h for h in hits if h.chunk.id not in used and _match(h, collection, ref, ident)]
        if not ref:
            matches.sort(key=lambda h: _rank_service_hit(h, ident))
        if matches:
            used.add(matches[0].chunk.id)
            chosen.append((matches[0], ident))
    return [
        Citation(
            source=h.chunk.source_path,
            ref=h.chunk.ref,
            quote=_best_quote(h.chunk, [ident] if ident else []),
        )
        for h, ident in chosen[:MAX_CITATIONS]
    ]


def _top_up_evidence(
    s: PipelineState, deps: PipelineDeps, targets: list[tuple[str, str, str, list[str]]]
) -> None:
    """Retrieve evidence for a test's identifiers that ``retrieve`` did not cover."""
    for collection, ref, ident, queries in targets:
        if any(_match(h, collection, ref, ident) for h in s.hits):
            continue
        for query in queries:
            found = [
                h
                for h in deps.retriever.search(query, k=5, collections=[collection])
                if h.score > 0 and _match(h, collection, ref, ident)
            ]
            if found:
                s.hits.append(found[0])
                s.log("instantiate", f"evidence top-up: {found[0].chunk.id} for {ident}")
                break


def instantiate(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """Build :class:`TestCase` objects from accepted choices via the templates only."""
    s = state.model_copy(deep=True)
    pending: list[PlannedInstance] = []
    req_slug = s.requirement_id.lower().replace("-", "_")
    index = spec_index(deps.spec)
    for choice in s.accepted:
        tid, idx = choice.template_id, choice.option_index
        try:
            params = applicable_params(deps.spec, tid)[idx]
            base = TEMPLATES[tid].instantiate(deps.spec, params)
        except Exception as exc:  # noqa: BLE001 - recorded as a rejection, never fatal
            reason = f"instantiation failed: {exc}"
            s.rejected.append(
                RejectedChoice(template_id=tid, option_index=idx, reason=reason, node="instantiate")
            )
            s.log("instantiate", f"{tid}[{idx}]: {reason}")
            continue
        targets = evidence_targets(
            option_refs(deps.spec, tid, idx), primary_service(tid, params), index
        )
        _top_up_evidence(s, deps, targets)
        test = base.model_copy(
            update={
                "id": f"{req_slug}__{base.id}",
                "requirement_ids": [s.requirement_id],
                "citations": select_citations(s.hits, targets, s.requirement_id),
                "origin": "generated",
                "review_status": "draft",
            }
        )
        pending.append(PlannedInstance(choice=choice, test=test))
        s.log(
            "instantiate",
            f"{test.id} from {tid}[{idx}] ({test.category}, {len(test.steps)} steps, "
            f"{len(test.citations)} citations)",
        )
    s.accepted = []
    s.pending = pending
    return s


# ----------------------------------------------------------------------------- validate


def check_test(deps: PipelineDeps, inst: PlannedInstance, hits: list[Hit],
               requirement_id: str) -> list[str]:
    """Return every problem with one instantiated test (empty list = valid)."""
    problems: list[str] = []
    test = inst.test
    tid, idx = inst.choice.template_id, inst.choice.option_index
    try:
        TestCase.model_validate(test.model_dump())
    except ValueError as exc:
        problems.append(f"schema: {exc}")
    if test.template_id != tid or tid not in TEMPLATES:
        problems.append(f"schema: template_id {test.template_id!r} does not match plan {tid!r}")
    if not any(step.kind == "send" for step in test.steps):
        problems.append("schema: test has no send step")
    if test.origin != "generated" or requirement_id not in test.requirement_ids:
        problems.append("schema: origin/requirement link missing")

    # Byte provenance: steps must equal a fresh template instantiation.
    try:
        reference = TEMPLATES[tid].instantiate(deps.spec, applicable_params(deps.spec, tid)[idx])
        if [st.model_dump() for st in reference.steps] != [st.model_dump() for st in test.steps]:
            problems.append("provenance: steps differ from the template instantiation")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"provenance: cannot re-instantiate template ({exc})")

    report = validate_test(deps.spec, test)
    problems += [f"oracle: {m}" for m in report.mismatches]

    corpus: list[Chunk] = [h.chunk for h in hits]
    if not test.citations:
        problems.append("citations: none attached")
    for c in test.citations:
        if not citation_is_valid(c, corpus):
            problems.append(f"citations: invalid citation {c.source}#{c.ref}")
    return problems


def validate(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """Check pending tests against the oracle, the schema, provenance and citations."""
    s = state.model_copy(deep=True)
    failures = 0
    for inst in s.pending:
        problems = check_test(deps, inst, s.hits, s.requirement_id)
        tid, idx = inst.choice.template_id, inst.choice.option_index
        if not problems:
            s.validated.append(inst)
            s.log("validate", f"{inst.test.id}: OK")
            continue
        failures += 1
        reason = "; ".join(problems)
        s.rejected.append(
            RejectedChoice(template_id=tid, option_index=idx, reason=reason, node="validate")
        )
        s.dropped.append(
            DroppedTest(test_id=inst.test.id, template_id=tid, option_index=idx, reasons=problems)
        )
        s.feedback.append(f"{tid}[{idx}] failed validation: {reason}")
        s.log("validate", f"{inst.test.id}: FAILED -> dropped ({reason})")
    s.pending = []
    retries_used = max(0, s.plan_attempts - 1)
    s.needs_replan = failures > 0 and retries_used < s.max_retries
    if failures:
        s.log(
            "validate",
            f"{failures} test(s) failed; "
            + ("re-planning with feedback." if s.needs_replan else "retry budget exhausted."),
        )
    return s


def route_after_validate(state: PipelineState) -> str:
    """Conditional edge: back to ``plan`` on failure while retries remain, else ``explain``."""
    return "plan" if state.needs_replan else "explain"


# ------------------------------------------------------------------------------ explain


def _test_summary(inst: PlannedInstance) -> dict[str, object]:
    """Compact per-test facts for the batched explain prompt (no byte values)."""
    test = inst.test
    steps = "; ".join(st.description for st in test.steps)
    if len(steps) > EXPLAIN_STEP_CHARS:
        steps = steps[: EXPLAIN_STEP_CHARS - 3].rstrip() + "..."
    return {
        "test_id": test.id,
        "title": test.title,
        "category": test.category,
        "rationale": inst.choice.rationale[:160],
        "steps": f"{len(test.steps)} steps: {steps}",
        "citation_refs": [f"{c.source}#{c.ref}" for c in test.citations[:3]],
    }


def _explain_prompt(s: PipelineState, summaries: list[dict[str, object]]) -> str:
    return build_prompt(
        EXPLAIN_BATCH_INSTRUCTION,
        {
            "task": "explain_batch",
            "requirement_id": s.requirement_id,
            "requirement_text": s.requirement_text,
            "tests": summaries,
        },
    )


def explain_batches(
    s: PipelineState, summaries: list[dict[str, object]], budget: int | None
) -> list[list[dict[str, object]]]:
    """Split ``summaries`` into as few batches as fit the context window.

    No limit (mock) -> one batch. Otherwise tests are added greedily while
    ``estimate_tokens(system, prompt) + EXPLAIN_TOKENS_PER_TEST * tests <= budget``; a batch
    always holds at least one test.
    """
    if budget is None or not summaries:
        return [summaries] if summaries else []
    batches: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    for item in summaries:
        trial = current + [item]
        need = (
            estimate_tokens(SYSTEM_PROMPT, _explain_prompt(s, trial))
            + EXPLAIN_TOKENS_PER_TEST * len(trial)
        )
        if current and need > budget:
            batches.append(current)
            current = [item]
        else:
            current = trial
    batches.append(current)
    return batches


def fallback_explanation(inst: PlannedInstance) -> str:
    """Deterministic short explanation from the test title, category and template."""
    tpl = TEMPLATES[inst.choice.template_id]
    test = inst.test
    return (
        f"{test.title} ({test.category} test, template {tpl.id}). "
        f"{tpl.description.rstrip('.')}. Expected responses come from the rules engine."
    )


def explain(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """LLM prose for all kept tests in one batched call; mark kept tests ``validated``.

    One call returns ``{explanations: [{test_id, explanation}]}`` for the whole requirement
    (several calls only if the prompt would not fit the context window, see
    :func:`explain_batches`). A test the reply omits, or a batch that fails after the
    client's retries, gets :func:`fallback_explanation` and a trace entry. Explanations are
    prose stored in ``TestCase.explanation`` only; test steps are never touched here.
    """
    s = state.model_copy(deep=True)
    summaries = [_test_summary(inst) for inst in s.validated]
    batches = explain_batches(s, summaries, context_budget(deps.llm))
    texts: dict[str, str] = {}
    for n, batch in enumerate(batches, start=1):
        ids = [str(item["test_id"]) for item in batch]
        mark = truncation_mark(deps.llm)
        try:
            raw = deps.llm.complete_json(SYSTEM_PROMPT, _explain_prompt(s, batch), ExplanationBatch)
            result = ExplanationBatch.model_validate(raw.model_dump())
        except (LLMError, ValueError) as exc:
            s.log("explain", f"batch {n}/{len(batches)} failed ({exc}); using fallback text.")
            s.fallback_events.append(
                f"explain: batch {n}/{len(batches)} LLM call failed ({exc}); used fallback text"
            )
            result = ExplanationBatch()
        _record_truncations(s, deps, "explain", mark)
        for item in result.explanations:
            text = item.explanation.strip()
            if item.test_id in ids and text and item.test_id not in texts:
                texts[item.test_id] = text
    if len(batches) > 1:
        s.log("explain", f"{len(summaries)} tests explained in {len(batches)} batched LLM calls.")
    out: list[PlannedInstance] = []
    for inst in s.validated:
        test = inst.test
        explanation = texts.get(test.id)
        if explanation is None:
            explanation = fallback_explanation(inst)
            s.log("explain", f"{test.id}: no explanation from the LLM; used deterministic text.")
            s.fallback_events.append(f"explain: {test.id}: missing in LLM reply; used fallback text")
        out.append(
            PlannedInstance(
                choice=inst.choice,
                test=test.model_copy(
                    update={"explanation": explanation, "review_status": "validated"}
                ),
            )
        )
    s.validated = out
    s.log("explain", f"{len(out)} test(s) explained and marked validated (human review pending).")
    return s


__all__ = [
    "check_test",
    "explain",
    "instantiate",
    "parse",
    "plan",
    "retrieve",
    "route_after_validate",
    "select_citations",
    "validate",
]
