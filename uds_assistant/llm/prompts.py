"""All system/user prompt text used by the agent nodes, in one tunable place.

The agent nodes (:mod:`uds_assistant.agent.nodes`) build each user prompt as
``build_prompt(<INSTRUCTION>, <context dict>)``; the context block is JSON that
:class:`~uds_assistant.llm.mock.MockLLM` parses and a real LLM reads as part of
the prompt. The text here is the only natural-language prompt content; it must
never ask the model for bytes (see AGENT.md correctness rules).
"""

from __future__ import annotations

SYSTEM_PROMPT = (
    "You are a UDS (ISO 14229) diagnostics test-planning assistant for an automotive ECU. "
    "You never write request or response bytes. You only reference identifiers that exist "
    "in the provided spec index, choose template ids and option indices from the provided "
    "catalog, and write short plain-English prose. Answer with JSON matching the schema "
    "when one is required."
)

PARSE_INSTRUCTION = (
    "Read the requirement and list the UDS services, DIDs, routines, sessions, security "
    "levels and DTCs it refers to, using only identifiers from spec_index. Choose the test "
    "intents that apply from the allowed intents list and add a few keywords."
)

PLAN_INSTRUCTION = (
    "Choose test cases that verify the requirement thoroughly: positive behaviour plus "
    "negative, session, security and timing checks where relevant. Each choice is a "
    "template_id from the catalog and an option_index from that template's options, with a "
    "one-sentence rationale. Do not repeat choices listed under rejected or already_kept."
)

EXPLAIN_INSTRUCTION = (
    "Explain in 2-4 sentences, for a test engineer, what this test checks, why it matters "
    "for the requirement, and what outcome is expected. Do not invent byte values."
)

SCHEMA_RETRY_INSTRUCTION = (
    "Your previous reply was not valid JSON for the required schema. "
    "Error: {error}\nReply again with only a JSON object that matches the schema."
)
"""Re-prompt sent by :class:`~uds_assistant.llm.client.OllamaClient` after an invalid reply."""

__all__ = [
    "EXPLAIN_INSTRUCTION",
    "PARSE_INSTRUCTION",
    "PLAN_INSTRUCTION",
    "SCHEMA_RETRY_INSTRUCTION",
    "SYSTEM_PROMPT",
]
