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
    "Examples (made-up requirements; <id of X> stands for the key of the spec_index entry "
    "whose name matches X, never copy an identifier from an example):\n"
    "'<X> shall be readable in every session.' -> services [0x22], dids [<id of X>], "
    "sessions [0x01,0x02,0x03]\n"
    "'<Y> must give results only after it was started.' -> services [0x31], routines "
    "[<id of Y>]\n"
    "'Changing <Z> shall need extended mode and a level 1 unlock.' -> services "
    "[0x10,0x27,0x2E], dids [<id of Z>], sessions [0x03], security_levels [0x01]\n"
    "If the text names no matching entry for dids, routines or DTCs, leave that list empty."
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

PLAN_CONSTRAINED_TEMPLATE = (
    "OPTIONS (the only choices allowed). Write each choice as one string "
    "<template_id>#<option_index>, joining a template_id line with one of its "
    "option_index values:\n{options}\n\n{history}"
    "REQUIREMENT {requirement_id}: {requirement_text}\n"
    "PARSED: {parsed}\n\n"
    "TASK: {instruction}"
)
"""Same layout as :data:`PLAN_COMPACT_TEMPLATE` for a backend whose decoding is constrained to the
offered ``template_id#option_index`` strings (see ``nodes.plan``)."""

EXPLAIN_BATCH_INSTRUCTION = (
    "For every test in tests, write 2-3 sentences for a test engineer: what the test "
    "checks, why it matters for the requirement, and the expected outcome. Answer with "
    "JSON {\"explanations\": [{\"test_id\": ..., \"explanation\": ...}]} containing "
    "exactly one entry per test, using the given test_id values. Plain prose only; do "
    "not write byte values."
)
"""One call explains every kept test of a requirement (see ``nodes.explain``)."""

SCHEMA_RETRY_INSTRUCTION = (
    "Your previous reply was not valid JSON for the required schema. "
    "Error: {error}\nReply again with only a JSON object that matches the schema."
)
"""Re-prompt sent by :class:`~uds_assistant.llm.client.OllamaClient` after an invalid reply."""

__all__ = [
    "EXPLAIN_BATCH_INSTRUCTION",
    "PARSE_INSTRUCTION",
    "PLAN_COMPACT_TEMPLATE",
    "PLAN_CONSTRAINED_TEMPLATE",
    "PLAN_INSTRUCTION",
    "SCHEMA_RETRY_INSTRUCTION",
    "SYSTEM_PROMPT",
]
