"""Prompt constants live in one module and the agent nodes use them."""

from __future__ import annotations

import re

from uds_assistant.agent import nodes
from uds_assistant.llm import prompts


def test_nodes_use_the_prompts_module_constants() -> None:
    for name in ("SYSTEM_PROMPT", "PARSE_INSTRUCTION", "PLAN_INSTRUCTION", "EXPLAIN_BATCH_INSTRUCTION"):
        assert getattr(nodes, name) is getattr(prompts, name)
        assert getattr(prompts, name).strip()


def test_prompts_never_ask_for_bytes() -> None:
    assert "never write request or response bytes" in prompts.SYSTEM_PROMPT
    assert "{error}" in prompts.SCHEMA_RETRY_INSTRUCTION


def test_parse_examples_do_not_contain_spec_identifiers() -> None:
    """Concrete example ids were copied into unrelated requirements (Part B finding)."""
    from pathlib import Path

    spec_text = (Path(__file__).resolve().parents[2] / "data" / "bcm_spec.yaml").read_text()
    spec_ids = {m.upper() for m in re.findall(r"id: 0x([0-9A-Fa-f]{4})(?![0-9A-Fa-f])", spec_text)}
    prompt_ids = {m.upper() for m in re.findall(r"0x([0-9A-Fa-f]{4})(?![0-9A-Fa-f])", prompts.PARSE_INSTRUCTION)}
    assert not (spec_ids & prompt_ids)
