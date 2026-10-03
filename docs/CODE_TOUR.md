# Code tour

A guided walk through `uds_assistant/` for someone presenting the project. Plain English; every term is explained the first time it appears.

Quick glossary:

- **UDS** (Unified Diagnostic Services, ISO 14229): the request/response language a diagnostic tester uses to talk to a car ECU. A request starts with a service byte (for example `22` = read data, `2E` = write data). A good answer starts with that byte plus `0x40`. A refusal is always `7F <service> <reason code>`; the reason code is an **NRC** (negative response code).
- **ECU**: a car computer. Here it is a fictional Body Control Module (BCM).
- **Oracle**: the thing that decides what the correct answer is. Here it is the rules engine.
- **Simulator**: a second, separately written fake ECU that the generated tests run against.
- **Mock LLM**: a deterministic keyword-based stand-in for a language model, so everything runs offline and repeatably. No real model has been run yet (that is "Part B").

## The whole system in one breath

1. A person writes a plain-English requirement ("Writing brightness DID 0x0100 shall require extended session and security level 0x01").
2. The agent pipeline (`agent/`) asks the LLM layer (`llm/`) to extract what the requirement is about: which services, data identifiers (DIDs), routines.
3. It retrieves matching passages from the spec and notes (`rag/`), so every test can carry citations.
4. The LLM picks from a fixed menu of test templates (`testgen/`). It never writes bytes.
5. Templates generate the actual request bytes; the rules engine (`rules/`) computes the expected response bytes.
6. A validator re-checks every test (schema, byte provenance, oracle agreement, citations) and sends bad ones back for a retry (at most 2 retries).
7. Validated tests run on an independent simulator (`simulator/`) via the runner (`runner/`); bugs from a catalog can be switched on to see which tests fail.
8. The evaluation (`eval/`) measures this honestly: simulator-vs-rules agreement, gold tests, a udsoncan cross-check, and detection of 12 held-out bugs.
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
1. *Who checks the oracle?* Three things: a separately written simulator (5000/5000 agreement), 60 hand-written gold tests, and a udsoncan cross-check.
2. *Does it follow the AUTOSAR standard exactly?* Not everywhere. Nine disagreements (D1 to D9) are documented in [SWS_DISAGREEMENTS.md](SWS_DISAGREEMENTS.md) and deliberately not fixed.
3. *Why one function for the order?* So a reviewer can read the whole priority list in one place and every line has a cited source.

## simulator/

**What it does.** A second implementation of the ECU, written from [behaviour_contract.md](behaviour_contract.md) and never importing `rules/` (a test enforces this). It can also have named bugs switched on.

**Key code**
- [ecu.py](../uds_assistant/simulator/ecu.py): `SimulatedEcu.handle(request, now_ms)`, `enable_bug`
- [services.py](../uds_assistant/simulator/services.py): one handler class per UDS service
- [bugs.py](../uds_assistant/simulator/bugs.py): `load_bug_catalog`, `IMPLEMENTED_BUG_IDS`, `HELDOUT_BUG_IDS`
- [transport.py](../uds_assistant/simulator/transport.py): in-process and virtual-CAN (ISO-TP) access

**Data in/out.** In: request bytes + injected time. Out: list of response frames (empty, one, or `7F xx 78` "response pending" then the final answer).

**Likely questions**
1. *Why two implementations?* If one program both produced and checked answers, a shared mistake would be invisible. Two independent ones that agree 5000/5000 on random walks are much stronger evidence. Caveat: the same author wrote both from the same contract, so they can share a misreading.
2. *How are bugs injected?* Each bug id is an explicit `if self.bug("...")` hook in the simulator; catalogs are in `data/bugs/`.
3. *Is there a real CAN path?* Yes, over python-can's virtual bus plus ISO-TP; it is used by the udsoncan check and optionally by exported tests.

## testgen/

**What it does.** The test case schema (steps are only hex bytes, time advances, environment changes), the registry of 23 reusable **templates** (each knows how to turn parameters into a concrete multi-step test), and a basic step executor.

**Key code**
- [model.py](../uds_assistant/testgen/model.py): `TestCase`, `SendStep`, `load_tests`, `dump_tests`
- [templates.py](../uds_assistant/testgen/templates.py): `TEMPLATES`, `applicable_params`, `validate_test`
- [templates_v2.py](../uds_assistant/testgen/templates_v2.py): the 9 generic templates added in v2
- [execute.py](../uds_assistant/testgen/execute.py): `run_test_on_simulator`

**Data in/out.** In: spec + template parameters. Out: `TestCase` objects (request hex, expected-response hex, citations).

**Likely questions**
1. *Where do expected bytes come from?* The rules engine, called inside the template. Never the LLM.
2. *Were templates tuned to the bug catalog?* Yes for v2, and the eval report says so. That is why the in-sample number is called optimistic and the held-out set exists.
3. *Why so few distinct tests per requirement?* Templates enumerate applicable parameters, so a requirement gets the instantiations relevant to its DIDs/services.

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
2. *What does "citation validity 774/774" mean?* Every citation attached to a generated test points at a chunk that exists in the retrieved corpus. It does not prove the cited text supports the test.
3. *Is real ISO text in the corpus?* No. Notes are written in our own words.

## llm/

**What it does.** A thin interface (`complete_json`, `complete_text`) with two backends: a deterministic mock and a local Ollama client. The LLM may only return structured choices (identifiers, template ids, option indices) and prose.

**Key code**
- [base.py](../uds_assistant/llm/base.py): `LLMClient`, `ParsedRequirement`, `TestPlan`
- [mock.py](../uds_assistant/llm/mock.py): `MockLLM`
- [client.py](../uds_assistant/llm/client.py): `OllamaClient`
- [factory.py](../uds_assistant/llm/factory.py): `get_llm`

**Data in/out.** In: system prompt + JSON context + a pydantic schema. Out: a validated instance of that schema.

**Likely questions**
1. *Have you run a real model?* No. Everything reported is `mode=mock`; Ollama (Qwen2.5-3B) is pending Part B.
2. *Can the LLM inject bytes?* No: its output is re-validated against a schema with no byte fields, and plan choices must be registered template ids.
3. *What if Ollama is down?* The config falls back to mock with a warning.

## agent/

**What it does.** The six-node pipeline: parse, retrieve, plan, instantiate, validate, explain, with a retry loop from validate back to plan. Runs on LangGraph, or a plain Python loop with identical results.

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

**What it does.** The measurement harness that produces `outputs/eval_report.md` and `.json`: simulator-vs-rules random-walk agreement, gold tests, udsoncan cross-check, held-out bug detection with a static "why was it missed" analysis, requirement-understanding scoring, coverage and citation validity.

**Key code**
- [run_eval.py](../uds_assistant/eval/run_eval.py): `main` (the `python -m uds_assistant.eval.run_eval` entry)
- [agreement.py](../uds_assistant/eval/agreement.py): `simulator_rules_agreement`
- [heldout.py](../uds_assistant/eval/heldout.py): trigger predicates and `heldout_analysis`
- [understanding.py](../uds_assistant/eval/understanding.py): scoring against labelled natural requirements
- [can_check.py](../uds_assistant/eval/can_check.py): `run_udsoncan_sequence`

**Data in/out.** In: spec, requirements, gold tests, both bug catalogs. Out: JSON and Markdown reports.

**Likely questions**
1. *Why is the headline 3/12 and not 25/26?* The 26 bugs were known when templates were written; the 12 held-out bugs were written by an independent subagent that could not see templates, gold tests, eval, LLM or agent code.
2. *Why is "simulator and rules agree" not enough?* They were written from one contract by one author; it is a consistency check, not proof of correctness.
3. *Why were missed bugs missed?* See the per-bug reasons, for example no generated test writes a uint16 DID and reads it back.

## export/

**What it does.** Turns tests into a runnable pytest file and a CAPL script (CAPL is Vector CANoe's scripting language).

**Key code**
- [pytest_export.py](../uds_assistant/export/pytest_export.py): `render_pytest`, `to_pytest`
- [capl_export.py](../uds_assistant/export/capl_export.py): `render_capl`, `to_capl`

**Data in/out.** In: `TestCase` list. Out: `.py` and `.can` files under `outputs/exports/`.

**Likely questions**
1. *Does the exported pytest run?* Yes; the eval run executed it in-process: 171 passed (see RESULTS.md).
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

**What it does.** A Streamlit page: type a requirement, generate tests, review them, run them with injected bugs, view the report, export. It calls the pipeline directly (no HTTP hop). Optional: needs `pip install -e ".[ui]"`.

**Key code**
- [streamlit_app.py](../uds_assistant/ui/streamlit_app.py): the whole page

**Data in/out.** In: requirement text and clicks. Out: on-screen tables and exports. Uses `outputs/ui_audit.sqlite`.

**Likely questions**
1. *Was the UI tested live?* Its logic has tests; running it live in a browser was not done in the build (see FINAL_REPORT.md).
2. *Does importing the package need Streamlit?* No; nothing else imports `ui/`.
3. *Can reviewers approve tests there?* Yes, review status is stored in the audit trail.

## config.py

**What it does.** The only runtime switches: `LLM_MODE=mock|ollama` and `RETRIEVER=bm25|chroma`, read from environment variables; invalid values fall back to defaults with a warning.

**Key code**
- [config.py](../uds_assistant/config.py): `Config`, `get_config`

**Data in/out.** In: environment variables. Out: a `Config` object.

**Likely questions**
1. *How do I switch to a real LLM?* See `MODEL_SETUP.md`; set `LLM_MODE=ollama`.
2. *Why fall back instead of erroring?* So a typo never crashes a demo.
3. *Any other config?* No; paths are repo-relative.

---

## Worked example: REQ-005, end to end with real bytes

All output below was produced by running the code (mock LLM, BM25, LangGraph engine). Nothing is hand-edited.

**Requirement** (from `data/requirements_seed.csv`):
"Writing the interior lighting brightness DID (0x0100) shall require extended session and security level 0x01."

**Step 1. Parse (LLM layer, mock).** The LLM names things; it produces no bytes.

```
services=['0x27', '0x2E']  dids=['0x0100']  security_levels=['0x01']
intents=['positive', 'negative', 'session', 'security', 'write']
```

**Step 2. Retrieve.** `14 evidence chunks kept: {'standard': 4, 'ecu_spec': 4, 'project': 6}`.

**Step 3. Plan.** `attempt 1: 14 choices proposed, 14 accepted` (templates such as `write_did_secured_positive`, `write_did_out_of_range`, ...).

**Step 4. Instantiate and validate.** 14 tests kept, 0 dropped, 0 re-plans. Pick `req_005__tpl_write_oor_0100` ("write an out-of-range value to DID 0x0100", brightness range is 0 to 100). Its steps, generated by the template with expected bytes from the rules engine:

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

All four actual responses equal the expected ones, so the test passes. All 14 REQ-005 tests pass on the clean simulator.

**Step 6. Enable bug `write_ignores_value_range`** (the simulator accepts any value, ignoring the DID's range):

```
passed=False
failure: step 3: expected ['7f2e31'], got ['6e0100']
```

- Request: `2E 01 00 65`
- Expected: `7F 2E 31` (refused: out of range)
- Actual: `6E 01 00` (positive: it wrote 101 into a 0 to 100 field)

With this bug on, 13 of the 14 REQ-005 tests still pass and exactly 1 fails, `req_005__tpl_write_oor_0100`. That is the point: a test either has a stimulus that exposes a bug or it does not.

Reproduce it:

```powershell
python scripts/demo.py
```

---

## Per-folder reading order for a first-time reader

1. [bcm_spec.yaml](../data/bcm_spec.yaml) and [behaviour_contract.md](behaviour_contract.md)
2. [nrc_order.py](../uds_assistant/rules/nrc_order.py)
3. [templates.py](../uds_assistant/testgen/templates.py)
4. [nodes.py](../uds_assistant/agent/nodes.py)
5. [suite.py](../uds_assistant/runner/suite.py)
6. [eval_report.md](../outputs/eval_report.md)
