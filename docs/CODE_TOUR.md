# Code tour

A guided walk through `uds_assistant/` for someone presenting the project. Plain English; every term is explained the first time it appears.

Quick glossary:

- **UDS** (Unified Diagnostic Services, ISO 14229): the request/response language a diagnostic tester uses to talk to a car ECU. A request starts with a service byte (for example `22` = read data, `2E` = write data). A good answer starts with that byte plus `0x40`. A refusal is always `7F <service> <reason code>`; the reason code is an **NRC** (negative response code).
- **ECU**: a car computer. Here it is a fictional Body Control Module (BCM).
- **Oracle**: the thing that decides what the correct answer is. Here it is the rules engine.
- **Simulator**: a second, separately written fake ECU that the generated tests run against.
- **Mock LLM**: a deterministic keyword-based stand-in for a language model, so everything runs offline and repeatably. It is the default. A real local model (Qwen2.5-3B via Ollama) was evaluated in Part B and again in Part C; see `docs/RESULTS.md`.
- **Behaviour class**: the kind of ECU behaviour a template probes (for example "what happens to a written value after an S3 timeout"). A template is written for the class and filled in from the spec for every DID, routine or level it applies to. It is never written for one bug.
- **Held-out / fresh / seen**: held-out bugs and requirements were written by a subagent that could not see the templates, gold tests, evaluation or LLM code. Once the templates were designed against the v1 misses, v1 became **seen**. The **v2** sets were written blind after the Part C freeze and are the only independent evidence.
- **Freeze**: from the end of Part C step C3, templates, prompts, planner and gold tests were not allowed to change until the v2 data had been written and measured. See the freeze table below.

## The whole system in one breath

1. A person writes a plain-English requirement ("Writing brightness DID 0x0100 shall require extended session and security level 0x01").
2. The agent pipeline (`agent/`) asks the LLM layer (`llm/`) to extract what the requirement is about: which services, data identifiers (DIDs), routines. A grounding check then drops any identifier that is neither written in the requirement nor supported by the retrieved spec text.
3. It retrieves matching passages from the spec and notes (`rag/`), so every test can carry citations.
4. The LLM picks from a fixed menu of test templates (`testgen/`; for a small-context model the menu is first cut to a ranked shortlist). It never writes bytes. Template ids it returns are normalised, never fuzzy-matched.
5. Templates generate the actual request bytes; the rules engine (`rules/`) computes the expected response bytes.
6. A validator re-checks every test (schema, byte provenance, oracle agreement, citations) and sends bad ones back for a retry (at most 2 retries). Explanations are then written by one batched LLM call per requirement.
7. Validated tests run on an independent simulator (`simulator/`) via the runner (`runner/`); bugs from three catalogs (in-sample, held-out v1, held-out v2) can be switched on to see which tests fail.
8. The evaluation (`eval/`) measures this honestly: simulator-vs-rules agreement, gold tests, a udsoncan cross-check, detection of the 15 fresh held-out v2 bugs (the headline), requirement understanding on 16 fresh natural v2 requirements, a noise check, and the older v1 and in-sample numbers labelled as seen.
9. Results and decisions are stored in SQLite (`store/`), and tests export to pytest and CAPL (`export/`).
10. A FastAPI service (`api/`) and a Streamlit page (`ui/`) wrap all of it; `config.py` holds the two switches (`LLM_MODE`, `RETRIEVER`).

---

## protocol/

**What it does.** The byte-level vocabulary of UDS: service and NRC enums, request/response encoding, request builders, and the project-invented seed/key algorithm for SecurityAccess (0x27). It has no logic about the ECU itself.

**Key code**
- [codec.py](../uds_assistant/protocol/codec.py): `UdsRequest`, `UdsResponse`, `decode_request`, `negative_response`
- [constants.py](../uds_assistant/protocol/constants.py): `ServiceId`, `Nrc` enums (cross-checked against udsoncan)
- [security.py](../uds_assistant/protocol/security.py): `compute_key`, `derive_seed`, lockout state functions
- [builders.py](../uds_assistant/protocol/builders.py): `write_did`, `security_send_key`, `session_control`, ...

**Data in/out.** In: ints and bytes. Out: `bytes` frames and pydantic request/response objects.

**Likely questions**
1. *Is the seed/key algorithm a real OEM one?* No. It is invented for the synthetic spec (a rotate-and-add on each seed byte); it is documented at the top of `security.py`.
2. *Where do the NRC numbers come from?* `constants.py`, cross-checked against the `udsoncan` library wherever it defines them.
3. *Does the clock use real time?* No. Time is always passed in (`now_ms`), so tests are repeatable.

## spec/

**What it does.** Loads `data/bcm_spec.yaml`, the description of the fictional BCM (sessions, security levels, DIDs, routines, DTCs), into validated pydantic objects and cross-checks references (for example a DID may not point at a security level that does not exist).

**Key code**
- [schema.py](../uds_assistant/spec/schema.py): `EcuSpec`, `DidDef`, `RoutineDef`, `load_spec`

**Data in/out.** In: `data/bcm_spec.yaml`. Out: an `EcuSpec` object used by almost everything.

**Likely questions**
1. *Is this a real ECU spec?* No, it is synthetic, written for this project in an OEM-like style. All numbers are against our own simulator.
2. *What happens with a malformed spec?* Pydantic validators fail loudly at load time.
3. *Could a real OEM spec be dropped in?* The schema would need to be mapped; the pipeline downstream only reads `EcuSpec`.

## rules/

**What it does.** The **oracle**: a pure function that, given the spec, the ECU state and a request, says exactly what the response bytes must be and why. The order in which error checks are applied (the "NRC order") lives in exactly one function.

**Key code**
- [nrc_order.py](../uds_assistant/rules/nrc_order.py): `evaluate_nrc`, the single place that decides which error wins; each check carries a comment naming its source (AUTOSAR SWS ID, udsoncan behaviour, or a design decision)
- [engine.py](../uds_assistant/rules/engine.py): `evaluate` (pure), `RulesSession` (stateful wrapper), `explain` (human-readable trace)
- [state.py](../uds_assistant/rules/state.py): `EcuState`, `initial_state`

**Data in/out.** In: spec + state + request bytes + `now_ms`. Out: `RuleResult` (response frames, trace, next state).

**Likely questions**
1. *Who checks the oracle?* Three things: a separately written simulator (the report's random-walk agreement check, plus two further seeds of more than 13,000 requests each after the Part C fixes), 60 hand-written gold tests, and a udsoncan cross-check.
2. *Does it follow the AUTOSAR standard exactly?* Not everywhere. Nine disagreements (D1 to D9) were documented in [SWS_DISAGREEMENTS.md](SWS_DISAGREEMENTS.md). In Part C, four were fixed (D2, D5, D6, D7); D1, D3, D4, D8 and D9 are still documented and open.
3. *Why one function for the order?* So a reviewer can read the whole priority list in one place and every line has a cited source.
4. *Why did you fix SWS D2, D5, D6 and D7 and not D1, D3 and D4?* The four fixed ones are "high" confidence: a normative SWS requirement contradicts what we did (a key during the lockout delay is not a 0x37 case; the suppress-positive bit applies to every subfunction service; a multi-DID read skips an unsupported DID; RoutineControl has no generic 0x12 check ahead of the routine lookup). D1, D3 and D4 are "medium": the SWS order comes from the listing order of checks, not from an explicit ordering rule, so changing them would be a guess. D8 has no observable effect with this spec, and D9 is a configuration choice. Each fixed check now cites the SWS ids it matches.
5. *What did the four fixes change in behaviour?* D2: an unknown routine or wrong session answers 0x31 before any 0x12. D5: a key sent during the delay answers 0x24, with no attempt counted. D6: bit 7 is the suppress-positive bit for all six subfunction services (so `27 81` is `27 01` with the positive reply withheld; negatives are still sent). D7: a multi-DID read answers the DIDs it can and skips unknown ones; 0x31 only if none remain.
6. *Did the fixes touch the tests?* One gold test changed, by hand (`gold_multi_did_read_one_bad`, now positive for the readable DID), and the other 59 passed unchanged. The decision log is in `DECISIONS.md` under [PC2-...].

## simulator/

**What it does.** A second implementation of the ECU, written from [behaviour_contract.md](behaviour_contract.md) and never importing `rules/` (a test enforces this). It can also have named bugs switched on, from three catalogs: 26 in-sample bugs, 12 held-out v1 bugs and 15 held-out v2 bugs. For the four Part C fixes it was changed by an agent that had not read the rules engine, working only from the contract and the SWS description.

**Key code**
- [ecu.py](../uds_assistant/simulator/ecu.py): `SimulatedEcu.handle(request, now_ms)`, `enable_bug`
- [services.py](../uds_assistant/simulator/services.py): one handler class per UDS service
- [bugs.py](../uds_assistant/simulator/bugs.py): `load_bug_catalog`, `IMPLEMENTED_BUG_IDS`, `HELDOUT_BUG_IDS`, `HELDOUT_V2_BUG_IDS`, `ALL_BUG_IDS`
- [transport.py](../uds_assistant/simulator/transport.py): in-process and virtual-CAN (ISO-TP) access

**Data in/out.** In: request bytes + injected time. Out: list of response frames (empty, one, or `7F xx 78` "response pending" then the final answer).

**Likely questions**
1. *Why two implementations?* If one program both produced and checked answers, a shared mistake would be invisible. Two independent ones that agree on every request of long random walks (with all bugs off) are much stronger evidence. Caveat: the same project wrote both from the same contract, so they can share a misreading; the Part C change used separate agents for the engine and the simulator to reduce that risk.
2. *How are bugs injected?* Each bug id is an explicit `if self.bug("...")` hook in the simulator; catalogs are in `data/bugs/` (`bug_catalog.yaml` for in-sample, `heldout_catalog.yaml`, `heldout_v2_catalog.yaml`).
3. *Is there a real CAN path?* Yes, over python-can's virtual bus plus ISO-TP; it is used by the udsoncan check and optionally by exported tests.
4. *How do you know the two implementations still agree after the Part C fixes?* The agreement generators were extended so each fixed path is exercised (for example key-during-delay requests), and the check ran on two seeds with more than 13,000 requests each: 100% agreement, no disagreement found. The simulator agent used different labels for two of the fixes (D6 and D7 swapped); only the labels differed.
5. *Who wrote the v2 bugs?* A subagent that could read the spec, protocol, simulator and behaviour contract but not the templates, agent, LLM, evaluation or gold code. Each of the 15 has a unit test that asserts the exact bytes that differ with the bug on and off.
6. *Are the v2 bugs realistic?* They are synthetic defects against a synthetic ECU. The subagent reported two limits: all sessions share the same timing values, and every positive 0x10 re-locks security, so "per-session timing" and "S3 timeout keeps the unlock" bugs could not be built.

## testgen/

**What it does.** The test case schema (steps are only hex bytes, time advances, environment changes), the registry of 27 reusable **templates** (template set `v3`; each knows how to turn parameters into a concrete multi-step test), and a basic step executor. The registry has a hard cap of 32.

**Key code**
- [model.py](../uds_assistant/testgen/model.py): `TestCase`, `SendStep`, `load_tests`, `dump_tests`
- [templates.py](../uds_assistant/testgen/templates.py): `TEMPLATES`, `applicable_params`, `validate_test`; the original templates
- [templates_v2.py](../uds_assistant/testgen/templates_v2.py): the generic templates added in v2
- [templates_v3.py](../uds_assistant/testgen/templates_v3.py): the four general templates added in Part C
- [execute.py](../uds_assistant/testgen/execute.py): `run_test_on_simulator`

**Data in/out.** In: spec + template parameters. Out: `TestCase` objects (request hex, expected-response hex, citations).

**The 27 templates, by what they probe.** Every template has a docstring starting "Behaviour class:" for the class of ECU behaviour it exercises, and every parameter (DID, routine, level, session) comes from `data/bcm_spec.yaml`. No template mentions a bug id, and a test scans the testgen source, the template metadata and every instantiated test for all 38 v1 and in-sample bug ids.

| Group | Templates |
|---|---|
| Read / write DIDs | `read_did_positive`, `read_did_wrong_session_or_unknown`, `read_multiple_dids`, `write_did_secured_positive`, `write_did_without_security`, `write_did_out_of_range`, `write_did_invalid_length`, `write_readonly_did` |
| Sessions, S3 timer | `service_not_in_session`, `s3_timeout_reverts_session`, `s3_keepalive_boundary`, `session_change_relocks_security` |
| Security | `security_invalid_key_lockout`, `seed_replay_rejected` |
| Routines | `routine_sequence`, `routine_start_results`, `condition_not_met` |
| DTCs | `dtc_read_clear`, `dtc_clear_specific_keeps_others` |
| Subfunctions, suppress bit, NRC order | `unsupported_subfunction`, `suppress_positive_response`, `negative_response_with_suppress_bit`, `nrc_priority_session_over_identifier` |

**What Part C added (template set v3: 23 to 27).** They were designed from the static list of stimuli that the nine "no template applies it" held-out v1 misses needed, grouped into general behaviour classes:

| New or extended | Behaviour class it probes | Spec-driven parameters |
|---|---|---|
| `read_did_invalid_length` (new) | 0x22 request-length validation: no identifier, a cut identifier, a dangling byte, each rejected as a whole; then a normal read still works | every readable DID, in a session where 0x22 is allowed |
| `seed_request_while_unlocked` (new) | security state once a level is unlocked: a second seed request answers an all-zero seed and does not lock the level | every security level |
| `session_change_resets_routine` (new) | routine status across a session change or an ECU reset: results must say "not started"; a fresh start is accepted | every routine, with a session-change and a reset variant |
| `write_did_value_retained` (new) | byte order of a stored value and its retention across an S3 timeout or an ECU reset | every writable DID, with a timeout and a reset variant |
| `security_invalid_key_lockout` (extended) | adds a variant that resets the ECU during the lockout delay: a reset must not skip the delay | per level |
| `condition_not_met` (extended) | adds a variant that violates the condition while security is still locked, so the answer shows which check the ECU evaluates first | per gated DID or routine |
| `routine_start_results` (extended) | adds a suppress-positive start: same state effect, no immediate positive reply | per routine |

Variants are appended after the base options, so earlier option indices and test ids did not change. The mock planner got generic keyword rules for the new templates, none keyed on a bug id.

**Likely questions**
1. *Where do expected bytes come from?* The rules engine, called inside the template. Never the LLM.
2. *Were templates tuned to the bug catalog?* Yes, the in-sample ones were, and the held-out v1 ones were used to design the Part C templates. That is why in-sample and v1 are labelled "tuned on" and "seen", and why only the v2 sets count as evidence.
3. *Why so few distinct tests per requirement?* Templates enumerate applicable parameters, so a requirement gets the instantiations relevant to its DIDs/services.
4. *How do you know the new templates aren't tuned to the bugs?* Three things. They were designed from stimulus classes (what an input sequence must contain), not from bug ids, and the test scan finds no bug id anywhere in the testgen code or generated tests. The templates were then frozen, with the tree hashes recorded, before the v2 bugs were written. And the v2 bugs were written by a subagent that could not read the templates. The honest limit: the stimulus classes came from the v1 misses, so the v1 recovery (3 of 12 up to 10 of 12 with the mock) is expected and is not evidence; only the v2 detection number is.
5. *Why 27 and not more?* A cap of 32 was set up front. Extending an existing template with a variant was preferred over adding one, so generated test ids stay stable and the planner menu stays short enough for a 3B model.
6. *What does a "behaviour class" docstring buy a reviewer?* It states the property being tested ("a written value is kept across an S3 timeout"), so a reviewer can check the template against the contract in a sentence instead of reading the step builder.

## rag/

**What it does.** Retrieval-augmented generation (RAG) = fetch relevant text before generating. It chunks the spec, UDS notes and requirements into a searchable corpus (BM25 keyword ranking by default; Chroma vectors optional and not installed) so tests can cite their evidence.

**Key code**
- [ingest.py](../uds_assistant/rag/ingest.py): `build_corpus`
- [bm25.py](../uds_assistant/rag/bm25.py): `Bm25Retriever`
- [citations.py](../uds_assistant/rag/citations.py): `citation_is_valid`
- [factory.py](../uds_assistant/rag/factory.py): `get_retriever` (falls back to BM25)

**Data in/out.** In: spec YAML, markdown notes, requirements CSV. Out: ranked chunks (`Hit`) and a yes/no on whether a citation points at a real chunk.

**Likely questions**
1. *Why BM25 and not embeddings?* Offline, tiny, no model downloads; embeddings are an optional switch.
2. *What does "citation validity" (all citations valid) mean?* Every citation attached to a generated test points at a chunk that exists in the retrieved corpus. It does not prove the cited text supports the test.
3. *Is real ISO text in the corpus?* No. Notes are written in our own words.

## llm/

**What it does.** A thin interface (`complete_json`, `complete_text`) with two backends: a deterministic mock and a local Ollama client. The LLM may only return structured choices (identifiers, template ids, option indices) and prose. The parse prompt's worked examples use `<id of ...>` placeholders, because the earlier examples contained real spec ids (0x0140, 0x0202, 0x0101) that a 3B model copied into unrelated requirements. The explain prompt asks for a JSON list of explanations keyed by test id (one call for all tests of a requirement).

**Key code**
- [base.py](../uds_assistant/llm/base.py): `LLMClient`, `ParsedRequirement`, `TestPlan`
- [mock.py](../uds_assistant/llm/mock.py): `MockLLM`
- [client.py](../uds_assistant/llm/client.py): `OllamaClient`
- [factory.py](../uds_assistant/llm/factory.py): `get_llm`

**Data in/out.** In: system prompt + JSON context + a pydantic schema. Out: a validated instance of that schema.

**Likely questions**
1. *Have you run a real model?* Yes: Qwen2.5-3B (Q4_K_M) via Ollama, compared with the mock on the same inputs in Part B and again after the Part C fixes. The Part B result was that it did not beat the mock on any headline metric. On the fresh v2 sets (Part C) it is better at requirement understanding (parsed F1 0.661 vs 0.367, category recall 74.0% vs 48.0%, precondition recall 77.8% vs 55.6%) but its precision is 0.565 with 30 false positives (the mock's is 1.000, recall 0.225), and held-out v2 bug detection is 2/15 in both modes. The mock stays the default.
2. *Can the LLM inject bytes?* No: its output is re-validated against a schema with no byte fields, and plan choices must be registered template ids.
3. *What if Ollama is down?* The config falls back to mock with a warning.
4. *Why placeholders in the prompt examples?* A small model copies concrete examples. The old examples named real DIDs and they showed up in unrelated parses; placeholders remove the thing to copy, and the grounding check in `agent/` catches the rest.
5. *Does the batched explain risk a missing or wrong explanation?* A test missing from the reply, or a failed batch, gets a short deterministic explanation and a trace entry, so a test is never left without one. Explanations are prose only; they cannot change a byte.
6. *Did Part C change what the mock produces?* No. Across 30 runs (15 seed requirements, two engines) before and after, everything was identical except explanation wording and call counts, and all 171 earlier tests had identical steps (evidence: `outputs/partC/mock_equivalence.json`).

## agent/

**What it does.** The six-node pipeline: parse, retrieve, plan, instantiate, validate, explain, with a retry loop from validate back to plan. Runs on LangGraph, or a plain Python loop with identical results. Part C added four guards around the LLM, all in this package:

- **Template-id normalisation** (`normalise_template_id` in `nodes.py`): a planner id has one trailing `(category)` group removed, quotes and spaces trimmed, and is lower-cased. It is accepted only if it then equals a catalog id exactly. There is no fuzzy matching, so `read_did` does not become `read_did_positive`. Each normalisation is logged in the run trace.
- **Identifier grounding** (`grounding.py`): a parsed DID, routine or DTC survives only if the requirement writes it (hex, any case, with or without `0x`) or a search of the spec chunks returns its chunk and a distinctive word of its name appears in the requirement. The reason is the copied example DIDs described under `llm/`. Services, sessions and levels are not checked. Every drop is recorded. The mock is exempt (`applies_grounding = False`), because it only emits identifiers written in the text.
- **Plan-context shortlist and budget** (`compact_plan_prompt`, `plan_shortlist`): for a backend with a context limit (Ollama, `num_ctx` 4096), the options shown to the planner are ranked by relevance to the parsed requirement and cut to at most `PLAN_SHORTLIST_MAX` = 30, then further until the prompt fits `PLAN_PROMPT_BUDGET` = 0.6 of the window. Options keep their real catalog index, so validation, instantiation and byte provenance are unchanged. The cap was raised from 24 to 30 when the catalog grew, so no previously offered option was dropped.
- **Batched explain** (`explain_batches`): one JSON call explains all kept tests, sent as compact summaries with no hex. It splits into more calls only if the estimated prompt plus `EXPLAIN_TOKENS_PER_TEST` (90) per test would exceed the window. A missing id or failed batch gets a deterministic fallback text.

**Key code**
- [pipeline.py](../uds_assistant/agent/pipeline.py): `run_pipeline`
- [nodes.py](../uds_assistant/agent/nodes.py): `parse`, `plan`, `instantiate`, `validate`, `check_test`
- [options.py](../uds_assistant/agent/options.py): the menu of template options shown to the LLM
- [graph.py](../uds_assistant/agent/graph.py): LangGraph wiring

**Data in/out.** In: requirement text and id. Out: `PipelineResult` (validated tests, dropped tests, decision log, parsed requirement).

**Likely questions**
1. *What is checked before a test is kept?* `check_test`: schema, "byte provenance" (steps must equal a fresh template instantiation), oracle agreement, and valid citations.
2. *What happens on failure?* The test is dropped, the reason is fed back as feedback, and the planner is re-run up to 2 times. In the seed run: 0 dropped, 0 re-plans.
3. *Is it deterministic?* With the mock LLM and BM25, yes.
4. *Why drop an identifier the model parsed?* A 3B model copied example DIDs into unrelated requirements, which then produced tests for the wrong DID. The check is deliberately blunt: if neither the text nor the evidence supports an identifier, it is dropped and the drop is logged. The known risk is a DID the requirement names only by an abbreviation; that has not been measured with the real model.
5. *Why a shortlist instead of the full menu?* A 3B model with a 4096-token window cannot take the full catalog (27 templates, many options) plus the requirement. The shortlist is deterministic and ranked, the real option index is kept, and the mock is unaffected (it has no context limit).
6. *Could normalisation let a wrong template through?* Only by exact match after removing a trailing parenthesis, quotes, whitespace and case. An invented name is still rejected and counted as a rejected choice.

## store/

**What it does.** A SQLite audit trail: each run, each node decision, each kept test, each run result, and human review status (draft, validated, human_reviewed).

**Key code**
- [audit.py](../uds_assistant/store/audit.py): `AuditStore.start_run`, `record_decision`, `record_test`, `set_review_status`

**Data in/out.** In: runs, decisions, tests, results. Out: records for the API/UI. Files live under `outputs/*.sqlite`.

**Likely questions**
1. *Why keep an audit trail?* So a reviewer can see why each test exists (which template, what evidence).
2. *Is it needed to run?* No, `store` is optional in `run_pipeline`.
3. *Can a human approve tests?* Yes, via `set_review_status` (API endpoint and UI).

## runner/

**What it does.** Runs a list of tests on a fresh simulator each, optionally with bugs on, checks timing against P2/P2* (the ECU's allowed response times; overruns are only warnings unless a step sets an explicit limit), and builds the bug-detection matrix.

**Key code**
- [suite.py](../uds_assistant/runner/suite.py): `run_test`, `run_suite`, `run_bug_matrix`

**Data in/out.** In: tests + spec + bug ids. Out: `SuiteResult` / `BugMatrix` (which tests failed, which bugs were detected).

**Likely questions**
1. *When does a bug count as detected?* Only if a test that passes on the clean simulator fails with the bug on. Tests failing on the clean simulator get no credit (reported as invalid; currently 0).
2. *Are timings real?* Wall-clock in-process; treated as warnings because a desktop OS adds jitter.
3. *Is state shared between tests?* No, each test gets a new ECU.

## eval/

**What it does.** The measurement harness that produces `outputs/eval_report.md` and `.json` (report version 3): simulator-vs-rules random-walk agreement, gold tests, udsoncan cross-check, bug detection with a static "why was it missed" analysis, requirement-understanding scoring, coverage and citation validity, byte provenance over every generated test (including every noise run), a noise check, the freeze check and a before/after table. It reports each data set under its own label:

| Data set | Size | Status |
|---|---|---|
| Held-out v2 bugs (`data/bugs/heldout_v2_catalog.yaml`) | 15 | FRESH: the headline. The generated suite is the tests from the 15 seed requirements; "all generated" and "natural-v2 tests only" are supplementary |
| Natural v2 requirements (`data/requirements_natural_v2.csv`, split `test2`) | 16 | FRESH: the headline for requirement understanding |
| Held-out v1 bugs | 12 | seen: templates were designed against these misses |
| Natural v1 test split | 12 | seen; the dev split (8) was tuned on |
| In-sample bugs | 26 | tuned on |

**Blind-authoring protocol.** Both v2 sets were written after the freeze by subagents with strict read limits, and their exact prompts are recorded in `PROGRESS.md`. The bug author could read the spec, protocol, simulator, behaviour contract and the two existing catalogs (to avoid duplicates), and could not read testgen, agent, llm, eval, gold, outputs or the project notes. The requirement author could read only the spec and the seed requirements. The static trigger predicates in `eval/heldout_v2.py` (used only to explain misses) were written from the bug descriptions before any v2 result existed.

**Noise check.** `--noise-runs N` repeats the natural-v2 run N times in ollama mode. Run 1 feeds every table; the report lists every run and the mean and min-max range, never the best run. The mock is deterministic: it runs once plus a second run that must be identical.

**Key code**
- [run_eval.py](../uds_assistant/eval/run_eval.py): `main` (the `python -m uds_assistant.eval.run_eval` entry)
- [agreement.py](../uds_assistant/eval/agreement.py): `simulator_rules_agreement`
- [heldout.py](../uds_assistant/eval/heldout.py): trigger predicates and `heldout_analysis`
- [heldout_v2.py](../uds_assistant/eval/heldout_v2.py): trigger predicates for the v2 bugs
- [before_after.py](../uds_assistant/eval/before_after.py): the before/after table from the frozen baseline (`outputs/partC/baseline_before_partC.json`) and the new report
- [understanding.py](../uds_assistant/eval/understanding.py): scoring against labelled natural requirements
- [can_check.py](../uds_assistant/eval/can_check.py): `run_udsoncan_sequence`

**Data in/out.** In: spec, requirements, gold tests, both bug catalogs. Out: JSON and Markdown reports.

**Likely questions**
1. *Why is the headline the v2 number and not 25/26?* The 26 in-sample bugs were known when templates were written, and the 12 v1 held-out bugs were used to design the Part C templates. Only the 15 v2 bugs were written blind, after the freeze, by a subagent that could not see templates, gold tests, eval, LLM or agent code.
2. *Why is "simulator and rules agree" not enough?* They were written from one contract by one author; it is a consistency check, not proof of correctness.
3. *Why were missed bugs missed?* See the per-bug reasons. The predicates are necessary, not sufficient: a bug whose stimulus is applied but whose expected response does not differ is reported with that reason.
4. *What is the freeze and how is it enforced?* After Part C step C3, nothing in `testgen/`, `llm/`, `agent/` (including the prompts file) or `data/gold/` was allowed to change until the v2 data had been written and measured. The git tree and blob hashes at that commit are recorded in `PROGRESS.md` (the freeze table below). Every evaluation run parses that table, compares it with `git rev-parse HEAD:<path>`, checks the paths have no uncommitted changes, and checks the freeze commit is an ancestor of HEAD. The result is in the report's `freeze` block and the UI shows it. Limits: it proves the frozen paths did not change, not that the data was chosen blind; that rests on the recorded prompts and read limits. It is a convention enforced by a check, not by git permissions.
5. *Why can v2 numbers still be noisy?* 15 bugs and 16 requirements are small, and ollama decoding is not deterministic, so small gaps are within noise; that is why the noise check lists every run.
6. *What does the before/after table compare?* The frozen pre-Part C report (commit `38aa719`) against the new report. v2 rows have no "before" (the data did not exist), v1 "after" numbers are seen, and latency and rejected-choice rows use the 35 seed and natural-v1 requirements so they stay comparable.

## export/

**What it does.** Turns tests into a runnable pytest file and a CAPL script (CAPL is Vector CANoe's scripting language).

**Key code**
- [pytest_export.py](../uds_assistant/export/pytest_export.py): `render_pytest`, `to_pytest`
- [capl_export.py](../uds_assistant/export/capl_export.py): `render_capl`, `to_capl`

**Data in/out.** In: `TestCase` list. Out: `.py` and `.can` files under `outputs/exports/`.

**Likely questions**
1. *Does the exported pytest run?* Yes; the eval run executes it in-process (the passed count is in the report's export section).
2. *Does the CAPL run in CANoe?* Unknown: it was never compiled or run in CANoe. It is labelled an unverified template.
3. *Does the pytest need this package?* The exported file imports the simulator from this repo.

## api/

**What it does.** A FastAPI service wrapping the same functions.

**Key code**
- [app.py](../uds_assistant/api/app.py): `create_app`, endpoints `/health`, `/spec`, `/generate`, `/run`, `/eval`, `/export`, `/bugs`, `/runs`, `/tests/{run_id}/{test_id}/review`
- [__main__.py](../uds_assistant/api/__main__.py): `python -m uds_assistant.api`

**Data in/out.** JSON over HTTP; audit trail in `outputs/api_audit.sqlite`.

**Likely questions**
1. *Is it needed for the demo?* No, the terminal demo and UI call Python directly.
2. *Authentication?* None; local demo service.
3. *How to try it?* Start with `python -m uds_assistant.api`, then open `/docs` for the interactive page.

## ui/

**What it does.** A Streamlit page: type a requirement, generate tests, review them (and mark one `human_reviewed`), run them with injected bugs from any of the three catalogs (labelled `[in-sample]`, `[held-out v1, seen]`, `[held-out v2, fresh]`), view the evaluation report, export. The evaluation section understands report versions 2 and 3: for v3 it shows the freeze status, the fresh v2 headline, the noise check, the before/after table (`outputs/partC/before_after.md`), the mock vs ollama comparison and the retrieval comparison, with the v1 rows labelled seen; a v2 report shows its v1 sections and "n/a" for the v2 rows. It calls the pipeline directly (no HTTP hop). Optional: needs `pip install -e ".[ui]"`.

**Key code**
- [streamlit_app.py](../uds_assistant/ui/streamlit_app.py): the whole page

**Data in/out.** In: requirement text and clicks. Out: on-screen tables and exports. Uses `outputs/ui_audit.sqlite`.

**Likely questions**
1. *Was the UI tested live?* It has headless Streamlit `AppTest` tests, including a generate, run and inject-a-bug click-through and synthetic report fixtures for report versions 2 and 3. A human click-through in a browser is the manual checklist in [UI_CHECKLIST.md](UI_CHECKLIST.md).
2. *Does importing the package need Streamlit?* No; nothing else imports `ui/`.
3. *Can reviewers approve tests there?* Yes, review status is stored in the audit trail.
4. *What happens when the report is old or only has one mode?* Missing pieces show "n/a" or "not run yet" instead of failing; the environment variables `UDS_EVAL_REPORT` and `UDS_BEFORE_AFTER` point the page at other files (the tests use this).
5. *Does the UI use the real model?* Only if `LLM_MODE=ollama` is set and the server is running; otherwise it uses the mock (and warns on fallback).
6. *Why does the page not show v2 numbers when there is no report for them?* It never computes metrics; it only renders `outputs/eval_report.json`. Until that file is a version-3 report, the v2 rows say the report predates Part C.

## config.py

**What it does.** The runtime switches: `LLM_MODE=mock|ollama`, `RETRIEVER=bm25|chroma` and `EMBEDDER=fastembed|sentence-transformers`, read from environment variables (the Ollama client also reads `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX`, `OLLAMA_KEEP_ALIVE`); invalid values fall back to defaults with a warning.

**Key code**
- [config.py](../uds_assistant/config.py): `Config`, `get_config`

**Data in/out.** In: environment variables. Out: a `Config` object.

**Likely questions**
1. *How do I switch to a real LLM?* See `MODEL_SETUP.md`; set `LLM_MODE=ollama`.
2. *Why fall back instead of erroring?* So a typo never crashes a demo.
3. *Any other config?* No; paths are repo-relative.

---

## Worked example: REQ-005, end to end with real bytes

All output below was produced by running the code (mock LLM, BM25, LangGraph engine, template set v3). Nothing is hand-edited.

**Requirement** (from `data/requirements_seed.csv`):
"Writing the interior lighting brightness DID (0x0100) shall require extended session and security level 0x01."

**Step 1. Parse (LLM layer, mock).** The LLM names things; it produces no bytes.

```
services=['0x27', '0x2E']  dids=['0x0100']  security_levels=['0x01']
intents=['positive', 'negative', 'session', 'security', 'write']
```

**Step 2. Retrieve.** `14 evidence chunks kept: {'standard': 5, 'ecu_spec': 4, 'project': 5}`.

**Step 3. Plan.** `attempt 1: 18 choices proposed, 18 accepted` (templates such as `write_did_secured_positive`, `write_did_out_of_range`, `write_did_value_retained`, `seed_request_while_unlocked`, ...).

**Step 4. Instantiate and validate.** 18 tests kept, 0 dropped, 0 re-plans. Pick `req_005__tpl_write_oor_0100` ("write an out-of-range value to DID 0x0100", brightness range is 0 to 100). Its steps, generated by the template with expected bytes from the rules engine:

| step | request | expected response | meaning |
|---|---|---|---|
| 0 | `10 03` | `50 03 00 32 01 F4` | switch to extended session (P2 = 0x0032 = 50 ms, P2* = 0x01F4 x 10 = 5000 ms) |
| 1 | `27 01` | `67 01 95 06 77 E8` | request a security seed |
| 2 | `27 02 9A 06 8F 73` | `67 02` | send the computed key, unlocked |
| 3 | `2E 01 00 65` | `7F 2E 31` | write value 0x65 = 101 to DID 0x0100: refused, NRC 0x31 (request out of range) |

Asking the oracle directly for step 3 returns this trace:

```
Request: 2E 01 00 65 at t=0 ms.
Step 1: SID 0x2E is supported.
Step 2: SID 0x2E allowed in session 0x03.
Step 3: length 4 acceptable for SID 0x2E.
Step 6e: value 101 outside [0, 100] -> NRC 0x31.
Response: 7F 2E 31 (negative responses are never suppressed).
Expected: 7F 2E 31
```

The test's parameter is `{'did': 256}` (256 = 0x0100) and its citations include `data/bcm_spec.yaml#did:interior_lighting_brightness_pct`.

**Step 5. Run on the clean simulator (independent code).**

```
passed=True
step 0 -> 5003003201f4   step 1 -> 6701950677e8   step 2 -> 6702   step 3 -> 7f2e31
```

All four actual responses equal the expected ones, so the test passes. All 18 REQ-005 tests pass on the clean simulator.

**Step 6. Enable bug `write_ignores_value_range`** (the simulator accepts any value, ignoring the DID's range):

```
passed=False
failure: step 3: expected ['7f2e31'], got ['6e0100']
```

- Request: `2E 01 00 65`
- Expected: `7F 2E 31` (refused: out of range)
- Actual: `6E 01 00` (positive: it wrote 101 into a 0 to 100 field)

With this bug on, 17 of the 18 REQ-005 tests still pass and exactly 1 fails, `req_005__tpl_write_oor_0100`. That is the point: a test either has a stimulus that exposes a bug or it does not.

Reproduce it:

```powershell
python scripts/demo.py
```

The same command with a fresh held-out v2 bug shows the difference between a bug the suite happens to expose and one it does not (the demo prints which set a bug belongs to):

```powershell
python scripts/demo.py --req REQ-006 --bug write_range_upper_bound_exclusive
```

---

## The Part C freeze

Templates, prompts, planner and gold tests were frozen at the end of Part C step C3 (commit `5a36eb4`), before the v2 bugs and requirements were written. The hashes are recorded in `PROGRESS.md` ("Part C freeze") and re-checked by every evaluation run (the report's `freeze` block; the UI and `docs/UI_CHECKLIST.md` step 9 show it).

| Frozen path | What it holds | Recorded hash (git object id) |
|---|---|---|
| `uds_assistant/testgen` (tree) | the 27 templates and test schema | `a4b6491fc2d01421c4cff10143aabd3c75017df1` |
| `uds_assistant/llm` (tree) | LLM clients, mock, prompts | `95ebf497e3e31a4d6d1377ca960b15e94e5cad66` |
| `uds_assistant/agent` (tree) | pipeline, grounding, shortlist | `9696c352234501d72ac54c18af5189317482321d` |
| `uds_assistant/llm/prompts.py` (blob) | the prompt text | `c0c6d5a6f0b64790beb13bf0179a6ef7877f31f7` |
| `data/gold` (tree) | the 60 hand-written gold tests | `778740195a3dc923ae2f6a34fd4b78e11d87b024` |

The only additions after the freeze were the v2 data (C4: 15 bug hooks in the simulator, off by default, so the clean simulator is unchanged, and the v2 requirement CSV) and the evaluation extension (C5a, written before any v2 result existed). If a hash ever mismatches, the report says so and the UI shows "MISMATCH"; that means a later change must be explained before any v2 number is trusted.

---

## Per-folder reading order for a first-time reader

1. [bcm_spec.yaml](../data/bcm_spec.yaml) and [behaviour_contract.md](behaviour_contract.md)
2. [nrc_order.py](../uds_assistant/rules/nrc_order.py)
3. [templates.py](../uds_assistant/testgen/templates.py)
4. [templates_v3.py](../uds_assistant/testgen/templates_v3.py) (the "Behaviour class" docstrings)
5. [nodes.py](../uds_assistant/agent/nodes.py) and [grounding.py](../uds_assistant/agent/grounding.py)
6. [suite.py](../uds_assistant/runner/suite.py)
7. [eval_report.md](../outputs/eval_report.md), then `outputs/partC/before_after.md` when it exists
