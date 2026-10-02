"""Pipeline runner: LangGraph when available, plain-Python loop otherwise.

Both engines call the same node functions from :mod:`.nodes` through the same
:func:`run_node` wrapper (which also streams each node's new decisions into the
audit store), so they produce identical results.

Engine choice: the ``engine`` argument, else the ``UDS_AGENT_ENGINE`` env var
(``auto`` | ``langgraph`` | ``plain``), default ``auto`` = LangGraph if it
imports, else plain.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Callable
from typing import Literal

from uds_assistant.agent import nodes
from uds_assistant.agent.state import PipelineDeps, PipelineResult, PipelineState
from uds_assistant.llm.base import LLMClient
from uds_assistant.rag.model import Retriever
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.store.audit import AuditStore

EngineChoice = Literal["auto", "langgraph", "plain"]
NodeFn = Callable[[PipelineState, PipelineDeps], PipelineState]

NODE_FUNCTIONS: dict[str, NodeFn] = {
    "parse": nodes.parse,
    "retrieve": nodes.retrieve,
    "plan": nodes.plan,
    "instantiate": nodes.instantiate,
    "validate": nodes.validate,
    "explain": nodes.explain,
}


def run_node(name: str, state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """Run one node and persist the decisions it added to the audit store."""
    before = len(state.decisions)
    new_state = NODE_FUNCTIONS[name](state, deps)
    if deps.store is not None and deps.run_id is not None:
        for d in new_state.decisions[before:]:
            deps.store.record_decision(deps.run_id, d.node, d.message)
    return new_state


def run_plain(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """Plain-Python loop over the node functions (LangGraph-free fallback)."""
    for name in ("parse", "retrieve", "plan", "instantiate", "validate"):
        state = run_node(name, state, deps)
    while nodes.route_after_validate(state) == "plan":
        for name in ("plan", "instantiate", "validate"):
            state = run_node(name, state, deps)
    return run_node("explain", state, deps)


def langgraph_available() -> bool:
    """True if :mod:`langgraph` can be imported."""
    try:
        import langgraph.graph  # noqa: F401
    except ImportError:
        return False
    return True


def resolve_engine(engine: EngineChoice | str | None = None) -> Literal["langgraph", "plain"]:
    """Pick the engine from the argument / ``UDS_AGENT_ENGINE`` / availability."""
    choice = (engine or os.environ.get("UDS_AGENT_ENGINE", "auto") or "auto").strip().lower()
    if choice == "plain":
        return "plain"
    if choice not in ("auto", "langgraph"):
        warnings.warn(f"Unknown agent engine {choice!r}; using auto.", stacklevel=2)
    if langgraph_available():
        return "langgraph"
    if choice == "langgraph":
        warnings.warn("langgraph is not importable; using the plain pipeline.", stacklevel=2)
    return "plain"


def run_pipeline(
    requirement_text: str,
    requirement_id: str,
    spec: EcuSpec,
    llm: LLMClient,
    retriever: Retriever,
    store: AuditStore | None = None,
    *,
    engine: EngineChoice | str | None = None,
    max_retries: int = 2,
) -> PipelineResult:
    """Turn one requirement into validated, cited test cases.

    Runs parse -> retrieve -> plan -> instantiate -> validate (-> plan on failure,
    at most ``max_retries`` times) -> explain. When ``store`` is given, the run,
    every node decision, and every kept test are recorded in the audit trail.
    """
    chosen = resolve_engine(engine)
    llm_name = str(getattr(llm, "name", type(llm).__name__))
    run_id: int | None = None
    if store is not None:
        run_id = store.start_run(
            requirement_id, requirement_text, llm_name, type(retriever).__name__
        )
        store.record_decision(run_id, "pipeline", f"engine={chosen} llm={llm_name}")
    deps = PipelineDeps(spec=spec, llm=llm, retriever=retriever, store=store, run_id=run_id)
    state = PipelineState(
        requirement_id=requirement_id, requirement_text=requirement_text, max_retries=max_retries
    )
    try:
        if chosen == "langgraph":
            from uds_assistant.agent.graph import run_graph

            final = run_graph(state, deps)
        else:
            final = run_plain(state, deps)
    except Exception:
        if store is not None and run_id is not None:
            store.finish_run(run_id, "failed")
        raise

    tests = [inst.test for inst in final.validated]
    if store is not None and run_id is not None:
        for t in tests:
            store.record_test(run_id, t)
        store.finish_run(run_id, "completed")
    return PipelineResult(
        run_id=run_id,
        requirement_id=requirement_id,
        requirement_text=requirement_text,
        engine=chosen,
        llm=llm_name,
        parsed=final.parsed,
        tests=tests,
        dropped=final.dropped,
        rejected=final.rejected,
        notes=final.notes,
        decisions=final.decisions,
        plan_attempts=final.plan_attempts,
    )
