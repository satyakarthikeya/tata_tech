"""Prompt constants live in one module and the agent nodes use them."""

from __future__ import annotations

from uds_assistant.agent import nodes
from uds_assistant.llm import prompts


def test_nodes_use_the_prompts_module_constants() -> None:
    for name in ("SYSTEM_PROMPT", "PARSE_INSTRUCTION", "PLAN_INSTRUCTION", "EXPLAIN_INSTRUCTION"):
        assert getattr(nodes, name) is getattr(prompts, name)
        assert getattr(prompts, name).strip()


def test_prompts_never_ask_for_bytes() -> None:
    assert "never write request or response bytes" in prompts.SYSTEM_PROMPT
    assert "{error}" in prompts.SCHEMA_RETRY_INSTRUCTION
