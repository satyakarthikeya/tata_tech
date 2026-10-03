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
    "Extract the UDS identifiers in requirement_text, using only keys from spec_index. "
    "Work in this order and add nothing the text does not mention or clearly imply.\n"
    "1. services: the service for the main action (never empty). read/report a value -> "
    "0x22; write/set/change a value or calibration -> 0x2E; switch/enter/return to a "
    "session or mode -> 0x10; unlock/seed/key -> 0x27; ECU reset/reboot -> 0x11; "
    "keep-alive/tester present -> 0x3E; start/stop/results of a routine or self-test -> "
    "0x31; read fault memory/trouble codes -> 0x19; clear them -> 0x14.\n"
    "2. dids / routines: match the words of the text to the names in spec_index (a stored "
    "setting is a DID, something started or run is a routine). Only values the text names.\n"
    "3. sessions: default -> 0x01, programming/flash -> 0x02, extended/diagnostic mode -> "
    "0x03. Also add service 0x10 only if being in that session is a condition ('shall "
    "require extended mode', 'only in the flash session'); 'in any/every session' is not.\n"
    "4. security: only if the text mentions unlock, security access, seed/key or a level: "
    "add service 0x27 and the level (level 1 -> 0x01, programming-level -> 0x03). "
    "Otherwise leave security_levels empty and do not add 0x27.\n"
    "5. intents from allowed_intents, 2-4 keywords.\n"
    "Examples (other requirements; never copy their identifiers):\n"
    "'Vehicle speed shall be readable in every session.' -> services [0x22], dids [0x0140], "
    "sessions [0x01,0x02,0x03]\n"
    "'The door actuator calibration must give results only after it was started.' -> "
    "services [0x31], routines [0x0202]\n"
    "'Changing the ambient colour shall need extended mode and a level 1 unlock.' -> "
    "services [0x10,0x27,0x2E], dids [0x0101], sessions [0x03], security_levels [0x01]"
)

PLAN_INSTRUCTION = (
    "Choose a small, focused set of test cases (usually 4-8) that verify this "
    "requirement. Only pick options about the requirement's own DID, routine or service; "
    "skip options about other identifiers. Cover each category the requirement needs, one"
    " or two options each: positive (the behaviour works), negative (wrong value, length,"
    " sub-function or order is rejected), session (the service is refused in the wrong "
    "session), security (locked access, lockout or relock, whenever an unlock or security"
    " level is involved), timing (only for session timeout or keep-alive). Each choice is"
    " a template_id and one of its option_index values from the list, with a one-sentence"
    " rationale that names the part of the requirement it checks. Do not repeat a choice."
)

PLAN_COMPACT_TEMPLATE = (
    "OPTIONS (the only choices allowed; answer with a template_id and one of its "
    "option_index values):\n{options}\n\n{history}"
    "REQUIREMENT {requirement_id}: {requirement_text}\n"
    "PARSED: {parsed}\n\n"
    "TASK: {instruction}"
)
"""Layout of the budgeted plan prompt used when the backend has a context limit.

The option shortlist comes first and the requirement and instruction last, so that even
an unexpected truncation (which keeps the tail) would cut options rather than the task."""

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
    "PLAN_COMPACT_TEMPLATE",
    "PLAN_INSTRUCTION",
    "SCHEMA_RETRY_INSTRUCTION",
    "SYSTEM_PROMPT",
]
