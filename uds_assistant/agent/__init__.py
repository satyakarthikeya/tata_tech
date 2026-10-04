"""Agent pipeline: parse -> retrieve -> plan -> instantiate -> validate -> explain.

Entry point: :func:`run_pipeline` (LangGraph when importable, plain loop otherwise).
"""

from __future__ import annotations

from uds_assistant.agent.pipeline import (
    langgraph_available,
    resolve_engine,
    run_pipeline,
    run_plain,
)
from uds_assistant.agent.state import (
    Decision,
    DroppedTest,
    PipelineDeps,
    PipelineResult,
    PipelineState,
    RejectedChoice,
    TargetEvidence,
)

__all__ = [
    "Decision",
    "DroppedTest",
    "PipelineDeps",
    "PipelineResult",
    "PipelineState",
    "RejectedChoice",
    "TargetEvidence",
    "langgraph_available",
    "resolve_engine",
    "run_pipeline",
    "run_plain",
]
