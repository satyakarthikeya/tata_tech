"""LangGraph ``StateGraph`` wiring of the agent nodes.

The graph state is a single channel holding the pydantic
:class:`PipelineState`; each graph node wraps the same function the plain loop
uses (:func:`uds_assistant.agent.pipeline.run_node`). ``validate`` has a
conditional edge back to ``plan`` while failures remain and retries are left.

``langgraph`` is imported inside :func:`build_graph` so this module imports
cleanly even without it.
"""

from __future__ import annotations

from typing import Any, TypedDict

from uds_assistant.agent.nodes import route_after_validate
from uds_assistant.agent.state import PipelineDeps, PipelineState


class GraphState(TypedDict):
    """LangGraph channel layout: one value, the whole pipeline state."""

    state: PipelineState


def build_graph(deps: PipelineDeps) -> Any:
    """Compile the parse→…→explain graph bound to ``deps``."""
    from langgraph.graph import END, START, StateGraph

    from uds_assistant.agent.pipeline import run_node

    def node(name: str) -> Any:
        def _run(gs: GraphState) -> dict[str, PipelineState]:
            return {"state": run_node(name, gs["state"], deps)}

        _run.__name__ = name
        return _run

    graph = StateGraph(GraphState)
    for name in ("parse", "retrieve", "plan", "instantiate", "validate", "explain"):
        graph.add_node(name, node(name))
    graph.add_edge(START, "parse")
    graph.add_edge("parse", "retrieve")
    graph.add_edge("retrieve", "plan")
    graph.add_edge("plan", "instantiate")
    graph.add_edge("instantiate", "validate")
    graph.add_conditional_edges(
        "validate",
        lambda gs: route_after_validate(gs["state"]),
        {"plan": "plan", "explain": "explain"},
    )
    graph.add_edge("explain", END)
    return graph.compile()


def run_graph(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """Run the compiled graph from ``state`` and return the final state."""
    app = build_graph(deps)
    out = app.invoke({"state": state}, config={"recursion_limit": 50})
    return out["state"]
