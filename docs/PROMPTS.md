# LLM prompts

Every LLM call in the app, with its purpose, inputs, output schema and the exact prompt text. The text below was extracted programmatically from `uds_assistant/llm/prompts.py` (parse, plan, explain) and from `uds_assistant/qa/answer.py` (Q&A phrasing, which keeps its two system prompts next to the verifier), so it cannot drift from the code. If you edit the prompts, regenerate this file.

**Settings for all calls:** Ollama `qwen2.5:3b-instruct-q4_K_M`, `temperature` 0, `seed` 0, `num_ctx` 4096, `stream` false; structured calls send the pydantic JSON schema as `format`. The model never produces request or response bytes (the schemas have no byte fields). An invalid JSON reply is re-prompted (up to 2 retries) with the retry text in section 5.

Prompt layout for the agent calls (`llm/base.py: build_prompt`): the instruction text, a blank line, `CONTEXT_JSON:` and a JSON object (keys sorted). The system prompt is `SYSTEM_PROMPT` for parse, plan and explain.

## 0. System prompt (parse, plan, explain)

```text
You are a UDS (ISO 14229) diagnostics test-planning assistant for an automotive ECU. You never write request or response bytes. You only reference identifiers that exist in the provided spec index, choose template ids and option indices from the provided catalog, and write short plain-English prose. Answer with JSON matching the schema when one is required.
```

## 1. Parse the requirement

- **Purpose:** turn the plain-English requirement into identifiers (services, DIDs, routines, sessions, security levels, DTCs, intents) that exist in the spec. Node `parse` in `agent/nodes.py`; identifiers not in the spec are dropped and noted.
- **Inputs (context JSON):** `task` = "parse", `requirement_id`, `requirement_text`, `spec_index` (names of the spec's DIDs, routines, sessions, security levels, DTCs, services), `allowed_intents`.
- **Output schema:** `ParsedRequirement` (`llm/base.py`): `services`, `dids`, `routines`, `sessions`, `security_levels` (lists of hex-id strings such as `"0x2E"`), `dtcs` (e.g. `"B10101"`), `intents` (from `allowed_intents`), `keywords`, `evidence` (optional verbatim phrase per item).

Instruction text (`PARSE_INSTRUCTION`):

```text
Extract the UDS identifiers in requirement_text, using only keys from spec_index. Work in this order and add nothing the text does not mention or clearly imply.
1. services: the service for the main action (never empty). read/report a value -> 0x22; write/set/change a value or calibration -> 0x2E; switch/enter/return to a session or mode -> 0x10; unlock/seed/key -> 0x27; ECU reset/reboot -> 0x11; keep-alive/tester present -> 0x3E; start/stop/results of a routine or self-test -> 0x31; read fault memory/trouble codes -> 0x19; clear them -> 0x14.
2. dids / routines: match the words of the text to the names in spec_index (a stored setting is a DID, something started or run is a routine). Only values the text names.
3. sessions: default -> 0x01, programming/flash -> 0x02, extended/diagnostic mode -> 0x03. Also add service 0x10 only if being in that session is a condition ('shall require extended mode', 'only in the flash session'); 'in any/every session' is not.
4. security: only if the text mentions unlock, security access, seed/key or a level: add service 0x27 and the level (level 1 -> 0x01, programming-level -> 0x03). Otherwise leave security_levels empty and do not add 0x27.
5. intents from allowed_intents, 2-4 keywords.
Examples (made-up requirements; <id of X> stands for the key of the spec_index entry whose name matches X, never copy an identifier from an example):
'<X> shall be readable in every session.' -> services [0x22], dids [<id of X>], sessions [0x01,0x02,0x03]
'<Y> must give results only after it was started.' -> services [0x31], routines [<id of Y>]
'Changing <Z> shall need extended mode and a level 1 unlock.' -> services [0x10,0x27,0x2E], dids [<id of Z>], sessions [0x03], security_levels [0x01]
If the text names no matching entry for dids, routines or DTCs, leave that list empty.
```

## 2. Plan the tests

- **Purpose:** choose which approved templates (and which parameter option of each) to instantiate. Node `plan`. The model only picks from a shortlist; the rules engine then builds every byte.
- **Inputs:** the shortlisted `OPTIONS` (templates and their real option indices, ranked by relevance to the parsed requirement and cut to the context budget by `compact_plan_prompt`), a `history` block (`Already kept: N test(s)` and up to the last 3 validation-feedback lines of 160 characters each, on a re-plan), `requirement_id`, `requirement_text`, the `PARSED` line from step 1, and the task instruction below.
- **Output schema:** `TestPlan` = `{tests: [{template_id, option_index, rationale}]}`. When the backend supports it (Ollama does), decoding is constrained by a per-call JSON schema: `ConstrainedPlan` = `{tests: [{choice, rationale}]}` where `choice` is an enum of exactly the offered `template_id#option_index` strings (`constrained_plan_schema`).

Task instruction (`PLAN_INSTRUCTION`):

```text
Choose a small, focused set of test cases (usually 4-8) that verify this requirement. Only pick options about the requirement's own DID, routine or service; skip options about other identifiers. Cover each category the requirement needs, one or two options each: positive (the behaviour works), negative (wrong value, length, sub-function or order is rejected), session (the service is refused in the wrong session), security (locked access, lockout or relock, whenever an unlock or security level is involved), timing (only for session timeout or keep-alive). Each choice is a template_id and one of its option_index values from the list, with a one-sentence rationale that names the part of the requirement it checks. Do not repeat a choice.
```

Prompt layout used with constrained decoding (`PLAN_CONSTRAINED_TEMPLATE`; the placeholders `{options}`, `{history}`, `{requirement_id}`, `{requirement_text}`, `{parsed}`, `{instruction}` are filled in):

```text
OPTIONS (the only choices allowed). Write each choice as one string <template_id>#<option_index>, joining a template_id line with one of its option_index values:
{options}

{history}REQUIREMENT {requirement_id}: {requirement_text}
PARSED: {parsed}

TASK: {instruction}
```

Layout without constrained decoding (`PLAN_COMPACT_TEMPLATE`):

```text
OPTIONS (the only choices allowed; answer with a template_id and one of its option_index values):
{options}

{history}REQUIREMENT {requirement_id}: {requirement_text}
PARSED: {parsed}

TASK: {instruction}
```

## 3. Explain the kept tests

- **Purpose:** 2-3 sentences of prose per test for the reviewing engineer. Node `explain`. One batched call per requirement (split into several batches if the context window requires). The prose is stored in `TestCase.explanation`; it never feeds back into bytes.
- **Inputs (context JSON):** `task` = "explain_batch", `requirement_id`, `requirement_text`, `tests` = a list of `{test_id, title, category, rationale, steps (descriptions only), citation_refs}`.
- **Output schema:** `ExplanationBatch` = `{explanations: [{test_id, explanation}]}`.

Instruction text (`EXPLAIN_BATCH_INSTRUCTION`):

```text
For every test in tests, write 2-3 sentences for a test engineer: what the test checks, why it matters for the requirement, and the expected outcome. Answer with JSON {"explanations": [{"test_id": ..., "explanation": ...}]} containing exactly one entry per test, using the given test_id values. Plain prose only; do not write byte values.
```

## 4. Q&A phrasing

`qa/answer.py` first looks the answer up deterministically (spec / standard tables) or retrieves evidence sentences; the model only rephrases, and its output is verified (every looked-up value must survive, no new number or hex value, every claim's quote must be a substring of its chunk). On any failure the deterministic template answer is used and a fallback event is recorded. There are two variants.

### 4a. Phrasing looked-up facts

- **Inputs:** the question and the looked-up fact sentences (generated from the spec, not by the model).
- **Output schema:** `{answer: str}`.

System prompt (`_SYSTEM_FACTS`):

```text
You rewrite diagnostic facts as a short, clear answer to the question. Use ONLY the facts given. Keep every value (numbers, hex ids, session names) exactly as written. Do not add any information that is not in the facts.
```

User prompt (built in `_phrase_facts`):

```text
Question: <question>
Facts:
- <fact text>
- <fact text>
Write the answer in 1-3 sentences.
```

### 4b. Claims with quotes over retrieved evidence

- **Inputs:** the question and the numbered evidence sentences `[chunk_id] sentence` retrieved from all four layers.
- **Output schema:** `{claims: [{text, chunk_id, quote}]}`, at most 2 claims, `chunk_id` restricted to an enum of the offered chunk ids by a per-call JSON schema.

System prompt (`_SYSTEM_CLAIMS`):

```text
You answer a diagnostic question using ONLY the numbered evidence sentences. Return 1 or 2 claims; each claim has a short 'text', the 'chunk_id' of its evidence and a 'quote' copied word for word from that evidence sentence. Never state anything the evidence does not say.
```

User prompt (built in `_phrase_claims`):

```text
Question: <question>
Evidence:
[<chunk_id>] <evidence sentence>
[<chunk_id>] <evidence sentence>
```

## 5. Schema retry (any structured call)

Sent by `OllamaClient` (up to `max_retries` = 2 times) when a reply is not valid JSON for the schema (`SCHEMA_RETRY_INSTRUCTION`):

```text
Your previous reply was not valid JSON for the required schema. Error: {error}
Reply again with only a JSON object that matches the schema.
```

## Not LLM calls

The raw-request checker (`POST /validate`, the "Check a raw request" box), the coverage report, the preconditions and pass criteria, the exports and the bug-injection runs use no LLM at all.
