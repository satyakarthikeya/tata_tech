"""Rules engine: the deterministic oracle for expected UDS responses.

Public entry points:

- :func:`uds_assistant.rules.engine.evaluate` — pure ``(spec, state, request, now_ms)``
  to :class:`~uds_assistant.rules.engine.RuleResult`.
- :class:`uds_assistant.rules.engine.RulesSession` — the only stateful wrapper.
- :func:`uds_assistant.rules.state.initial_state` — power-on state factory.
"""

from __future__ import annotations

from uds_assistant.rules.engine import RuleResult, RulesSession, evaluate, explain
from uds_assistant.rules.nrc_order import NrcDecision, evaluate_nrc
from uds_assistant.rules.state import EcuState, EnvironmentConditions, RoutineStatus, initial_state

__all__ = [
    "EcuState",
    "EnvironmentConditions",
    "NrcDecision",
    "RoutineStatus",
    "RuleResult",
    "RulesSession",
    "evaluate",
    "evaluate_nrc",
    "explain",
    "initial_state",
]
