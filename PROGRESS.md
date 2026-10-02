# PROGRESS.md

## Step 0 — Orientation & plan (2026-10-03T00:57:17+05:30)

**Environment:** Python 3.13.6 (docs specify 3.11 — see DECISIONS.md). Git initialised.
Pre-installed: pydantic 2.13, httpx 0.28. Installed in one pip attempt (succeeded): pyyaml, udsoncan 1.26.1, can-isotp 2.0.7, python-can 4.6.1, pytest, hypothesis, fastapi, uvicorn, langgraph, rank-bm25 (numpy present), ruff.
Heavy packages (torch, transformers, sentence-transformers, chromadb, onnxruntime, llama-cpp-python, vllm): all absent — not installed. streamlit absent (optional, try in Phase 8).
`docs/`, `data/bcm_spec.yaml`, `data/requirements_seed.csv` referenced by AGENT.md do **not exist** — authored from scratch (see DECISIONS.md).

**Plan** (package `uds_assistant/`, tests under `tests/` mirroring layout; commit `phase N: …` after each):
1. Protocol core + ECU spec (BCM yaml, seed/key + lockout), codec/udsoncan cross-check tests
2. Rules engine oracle, single NRC-order function with citations, 60+ table-driven tests
3. Independent simulator (no rules import), 15+ bug catalog, in-process + virtual CAN/ISO-TP transports, hypothesis agreement test, udsoncan client sequence
4. TestCase model, 8–12 templates, 40–60 gold tests verified on simulator
5. Layered BM25 retrieval with citations; Chroma backend lazy/needs_model
6. Mock LLM, Ollama client (monkeypatched tests), agent pipeline (LangGraph + plain fallback), SQLite store
7. Runner, mock-mode evaluation report (json+md), pytest/udsoncan + CAPL exports
8. FastAPI + TestClient tests, Streamlit UI
9. MODEL_SETUP.md, README.md, FINAL_REPORT.md, ruff, final pytest, commit

**Execution:** each phase delegated sequentially to a subagent (Sonnet for routine phases, Opus for oracle/simulator/agent), then verified by the orchestrator (pytest + ruff) before commit.

## Phase 1 — Protocol core, BCM spec, seed/key security (2026-10-03T01:14:02+05:30)

**Done:**
- `uds_assistant/config.py`: `get_config()` reads `LLM_MODE` (mock|ollama) and `RETRIEVER` (bm25|chroma) into a pydantic `Config`; invalid values fall back to default with a warning.
- `uds_assistant/protocol/constants.py`: `ServiceId` and `Nrc` IntEnums (0x10,0x11,0x14,0x19,0x22,0x27,0x2E,0x31,0x3E and the 16 scoped NRCs), `POSITIVE_RESPONSE_OFFSET`, `NEGATIVE_RESPONSE_SID`, `SUPPRESS_POS_RESP_BIT`, `SERVICES_WITH_SUBFUNCTION`, `SERVICES_WITH_SUPPRESS_BIT`, `NRC_DESCRIPTIONS`.
- `uds_assistant/protocol/codec.py`: `UdsRequest`/`UdsResponse` pydantic models with `to_bytes()`, `decode_request()`/`decode_response()`, `positive_response()`, `negative_response()`, `is_negative()`, `format_hex()`.
- `uds_assistant/protocol/builders.py`: typed builders for all 9 in-scope services (`session_control`, `ecu_reset`, `clear_dtc`, `read_dtc_by_status_mask`, `read_did`, `security_request_seed`, `security_send_key`, `write_did`, `routine_control`, `tester_present`).
- `uds_assistant/protocol/security.py`: documented synthetic seed/key algorithm (`generate_seed`, `compute_key`, `is_key_valid`) and a pure `SecurityLockoutState` model with `record_failed_attempt`, `record_successful_unlock`, `is_delay_active`, `clear_expired_lockout` — no wall-clock calls, clock is always injected.
- `uds_assistant/spec/schema.py`: `EcuSpec` pydantic model (sessions, security levels, DIDs, routines, DTCs, ECU reset subfunctions) with full cross-reference validation, plus `load_spec(path)`.
- `data/bcm_spec.yaml`: synthetic BCM spec — 3 sessions, 2 security levels, 14 DIDs (VIN, part number, serial, active session, lighting/door/wiper config, one condition-gated DID), 3 routines, 3 DTCs.
- `data/requirements_seed.csv`: 15 plain-English requirements referencing the spec.
- `pyproject.toml`, `tests/conftest.py` (auto-skip `needs_model` unless `RUN_MODEL_TESTS=1`).

**Tests:** 90 passed, 0 failed (`python -m pytest -q`). Includes hypothesis round-trip properties for request/response encode-decode and seed/key, table-driven builder/NRC/spec-validation tests, and a full cross-check of every SID/NRC constant plus 12 request-encoding comparisons against `udsoncan` 1.26.1.

**Ruff:** clean (`python -m ruff check .` → "All checks passed!").

**Key design notes logged to DECISIONS.md:** synthetic seed/key formula, DID/session/security cross-ref validation rules, bytes-field hex-string convention for YAML spec authoring.

## Phase 2 — Rules engine oracle with cited NRC order (2026-10-03T01:27:53+05:30)

**Done:**
- `uds_assistant/rules/state.py`: immutable pydantic `EcuState` (session, unlocked level, per-level `SecurityLockoutState`, pending seeds, ECU-wide seed counter, routine status, DTC statuses, DID values, `EnvironmentConditions` with vehicle speed / NVM-fault flag, S3 last-request timestamp, now_ms), `initial_state(spec, now_ms)`, `with_environment`, `with_dtc_status`, `RoutineStatus`.
- `uds_assistant/rules/request.py`: lenient `ParsedRequest` so the oracle answers any byte string.
- `uds_assistant/rules/nrc_order.py`: the single `evaluate_nrc()` implementing PROJECT.md §5 order plus SecurityAccess (0x37/0x24/0x35/0x36), 0x14, 0x72, 0x78; every check has a `Source:` comment tagged to a DECISIONS.md line (no SWS IDs cited — document unavailable offline).
- `uds_assistant/rules/engine.py`: pure `evaluate(spec, state, request, now_ms) -> RuleResult` (S3 timeout + lockout expiry first, positive payloads for all 9 services, suppress-bit, 0x78+final sequence, new state), `explain()`, stateful `RulesSession`.
- `protocol/security.py`: added deterministic `derive_seed(level, counter, length)`.
- `spec/schema.py` + `data/bcm_spec.yaml`: added `RoutineDef.long_running` (nvm_factory_restore) and `EcuSpec.max_response_length` (4095).

**Tests:** 276 passed, 0 failed overall (`python -m pytest -q`); 186 in `tests/rules/` — 155 table-driven cases (every NRC path per service, every positive path, S3/lockout timing), hypothesis properties (never raises, well-formed responses, input not mutated, determinism, sequence invariants), AST checks that only `evaluate_nrc` names NRCs and every NRC is cited, unit tests.

**Ruff:** clean.

## Phase 3 — Independent ECU simulator, bug catalog, virtual CAN transport (2026-10-03T01:41:40+05:30)

**Done:**
- `uds_assistant/simulator/memory.py`: mutable `EcuMemory` (session, unlocked level, per-level lockouts, pending seeds, seed counter, routine status, DTC statuses, DID store, environment, S3 timestamp).
- `uds_assistant/simulator/services.py`: per-service handler classes (0x10/0x11/0x14/0x19/0x22/0x27/0x2E/0x31/0x3E) in a SID dispatch table; negatives raised as `Reject`; explicit bug hooks.
- `uds_assistant/simulator/ecu.py`: `SimulatedEcu(spec, bugs=None, clock=None)` with `handle(request, now_ms=None) -> list[bytes]`, `set_vehicle_speed`, `set_nvm_write_fault`, `set_environment`, `set_dtc_status`, `reset_state`, `advance`, `enable_bug`/`disable_bug`/`active_bugs`; thread-safe (RLock).
- `uds_assistant/simulator/bugs.py` + `data/bugs/bug_catalog.yaml`: 26 injectable bugs (pydantic `BugCatalog`, `load_bug_catalog`).
- `uds_assistant/simulator/transport.py`: `InProcessTransport`, `EcuCanServer` (ECU behind ISO-TP on a python-can virtual bus, background thread, context manager), `IsoTpClientTransport` (tester side, follows 0x78 pending), `make_isotp_stack`.
- Simulator never imports the rules engine (AST + subprocess test).

**Tests:** 367 passed, 0 failed overall (`python -m pytest -q`, ~19 s); 91 in `tests/simulator/`:
- Agreement simulator vs rules engine: hypothesis (300 sequences, up to 30 steps), 40 seeded walks x 100 steps, 3000 single-request fuzz cases from random prefixes, 60 directed unlocked walks — ~26,800 requests compared per run (hypothesis part varies, ~4,000), **100% byte-identical, 0 discrepancies**; generators reach every NRC used by the contract (0x11/12/13/22/24/31/33/35/36/37/72/78/7E/7F) and every positive SID.
- Bugs: catalog == implemented set, every bug has a dedicated scenario whose output differs bug-on vs bug-off, toggling restores clean behaviour.
- Transport: in-process, ISO-TP round trip incl. multi-frame VIN and 0x78+final over CAN, udsoncan client (extended session -> seed -> compute_key -> key -> read 0x0100 -> write 0x50 -> read back) and NegativeResponseException 0x33.
- 20 direct contract-example tests.

**Ruff:** clean.

## Phase 4 — Test-case model, reusable templates, and a hand-authored gold set (2026-10-03T02:09:32+05:30)

**Done:**
- `uds_assistant/testgen/model.py`: pydantic `TestCase` (id, title, requirement_ids, category, template_id, parameters, preconditions, steps, citations, review_status, explanation, origin) and a discriminated-union `TestStep`: `SendStep` (request_hex, expected_responses_hex — the ordered frame sequence, description, max_response_time_ms), `AdvanceTimeStep`, `SetEnvironmentStep`, `SetDtcStatusStep`; hex helpers; `load_tests`/`dump_tests` for YAML/JSON.
- `uds_assistant/testgen/templates.py`: 14 templates (read_did_positive, read_did_wrong_session_or_unknown, write_did_secured_positive, write_did_without_security, write_did_out_of_range, write_did_invalid_length, service_not_in_session, unsupported_subfunction, security_invalid_key_lockout, s3_timeout_reverts_session, routine_sequence, condition_not_met, suppress_positive_response, dtc_read_clear) in a `TEMPLATES` registry; each has a pydantic params model, `instantiate(spec, params) -> TestCase` that builds every expected response by stepping a `RulesSession` (incl. seed->key via `protocol.security.compute_key`), and an `applicable_params_fn` that scans the loaded spec; `applicable_params(spec, template_id)` and `validate_test(spec, test) -> ValidationReport` (re-runs steps through the oracle) are public.
- `uds_assistant/testgen/execute.py`: `run_test_on_simulator(test, ecu_factory) -> TestOutcome` (injected time starting at 0, per-step pass/fail, exact-bytes comparison).
- `data/gold/gold_tests.yaml`: 60 hand-authored tests (not using templates.py), generated once by `scripts/gen_gold.py` from `docs/behaviour_contract.md` + builder-encoded request bytes; category breakdown positive 22 / negative 21 / session 7 / security 7 / timing 3; covers all 9 services, NRCs 0x11/12/13/22/24/31/33/35/36/37/72/78/7E/7F, S3 timing (incl. the exactly-5000ms boundary), suppress bit (positive and "negative never suppressed"), ECU reset (incl. suppressed), DTC read/clear with injected statuses, and multi/duplicate-DID reads.

**Tests:** 518 passed, 0 failed (`python -m pytest -q`). New in `tests/testgen/` (151 cases): schema round-trip (YAML/JSON/discriminator), every template's every `applicable_params` entry instantiates + `validate_test`s clean + passes on the bug-free simulator (108 generated cases across 14 templates), every one of the 60 gold tests passes on the clean simulator and validates against the oracle, gold count/category/citation checks, and a bug-detection sanity check.

**Gold-set bug detection:** the 60 gold tests alone catch **24 of 26** catalog bugs when run against the simulator with each bug enabled one at a time (undetected: `lockout_delay_never_expires`, `seed_not_consumed` — both need a longer multi-step sequence than any single gold test currently exercises; left as a known gap for the Phase-6 planner/generated tests to cover).

**Ruff:** clean (`python -m ruff check .` → "All checks passed!").

**Key design notes logged to DECISIONS.md:** `SendStep.expected_responses_hex` as an ordered frame sequence (not alternatives); the `_Builder` pattern that makes every generated byte come from `RulesSession`; gold-authoring method and the one authoring mistake caught by `validate_test`; `SetDtcStatusStep.code` kept as a string to feed both the rules engine and the simulator.

## Phase 5 — Layered BM25 retrieval with citations, lazy Chroma backend (2026-10-03T02:21:16+05:30)

**Done:**
- `data/sources/uds_reference_notes.md`: own-words UDS reference notes (NRC evaluation order, all 16 in-scope NRCs, P2/P2*/S3 timing, security seed/key + lockout concept, and one `### 0xNN Service {#svc-0xnn}` section per in-scope service: 0x10, 0x11, 0x14, 0x19, 0x22, 0x27, 0x2E, 0x31, 0x3E) — no ISO 14229 text copied.
- `uds_assistant/rag/model.py`: pydantic `Chunk(id, collection, source_path, ref, text, identifiers)`, `Hit(chunk, score)` with `to_citation(quote=None) -> testgen.model.Citation`, and a `Retriever` protocol (`search(query, k=5, collections=None) -> list[Hit]`).
- `uds_assistant/rag/ingest.py`: `build_corpus(repo_root) -> list[Chunk]` — markdown chunker (`chunk_markdown`, splits on any `#`-level heading, uses `{#anchor}` or a slugified heading as `ref`), `chunk_ecu_spec` (one human-readable chunk per session/security level/DID/routine/DTC from `data/bcm_spec.yaml`, each line like `"DID 0xF190 VIN: length 17 bytes, ..."`), `chunk_requirements_csv` (one chunk per `data/requirements_seed.csv` row); `normalize_identifier`/`extract_identifiers` for hex-id normalization. Produces 80 chunks: 15 `standard`, 25 `ecu_spec`, 40 `project` (25 `docs/behaviour_contract.md` sections + 15 `data/requirements_seed.csv` rows).
- `uds_assistant/rag/bm25.py`: `tokenize()` normalizes hex tokens (`0xF190`/`F190`/`f190` -> the same `hex:f190` token) while leaving plain words and ambiguous bare numbers alone; `HandBM25` (hand-written pure-Python Okapi BM25) used automatically via `Bm25Retriever` whenever `rank_bm25` fails to import; `Bm25Retriever.search(query, k=5, collections=None) -> list[Hit]` with per-collection filtering; `Bm25Retriever.uses_rank_bm25` exposes which backend is active.
- `uds_assistant/rag/chroma.py`: `ChromaRetriever` (ChromaDB `PersistentClient` + `sentence_transformers` `BAAI/bge-small-en-v1.5`, persist dir defaults to `outputs/chroma`) and `chroma_available()`; every `chromadb`/`sentence_transformers` import is inside a function/method body, so the module imports cleanly without either package installed.
- `uds_assistant/rag/factory.py`: `get_retriever(config=None, repo_root=None, chunks=None) -> Retriever` reads `RETRIEVER` via `uds_assistant.config.get_config()`; `bm25` is the default; `chroma` falls back to `Bm25Retriever` with a `warnings.warn` if `chroma_available()` is false.
- `uds_assistant/rag/citations.py`: `citation_is_valid(citation, corpus) -> bool` — the cited `(source, ref)` must match a real chunk, and if the citation carries a `quote`, that quote must appear verbatim in the chunk's text with every hex identifier it mentions present in the chunk's `identifiers`.
- `tests/rag/`: `test_ingest.py` (chunk counts per collection: 14 DIDs / 3 routines / 3 DTCs / 3 sessions / 2 security levels, uniqueness, hex normalization), `test_bm25.py` (tokenizer incl. hex-form equivalence, the 4-row relevance table — "read VIN"->ecu_spec DID 0xF190, "security access invalid key"->standard 0x27, "NRC 0x7F"->relevant chunk, "wiper sensitivity"->DID 0x0130 — collection filtering, `HandBM25` vs `rank_bm25` identical top-k ordering on a fixed corpus plus a monkeypatched-absent-rank_bm25 path), `test_chroma.py` (subprocess import-cleanliness check with chromadb absent, AST check for no top-level heavy imports, one `@pytest.mark.needs_model` round-trip test), `test_factory.py` (bm25 default, chroma unavailable -> bm25 + warning, chroma available -> chroma via monkeypatch), `test_citations.py` (valid/fabricated/unknown-source/unknown-ref/identifier-mismatch cases).

**Tests:** 568 collected, 567 passed, 1 skipped (pre-existing `needs_model` skip plus one new `needs_model` Chroma test, both skipped without `RUN_MODEL_TESTS=1`) — `python -m pytest -q`. 49 of those tests are new, in `tests/rag/`.

**Ruff:** clean (`python -m ruff check .` -> "All checks passed!").

**Key design notes logged to DECISIONS.md:** citation validity defined via verbatim-quote + identifier-subset matching rather than source/ref existence alone; markdown chunker splits on every heading level so `###`-level service sections become individually citable chunks; `ChromaRetriever` returns `1 - distance` as its score to keep the same "higher is better" convention as BM25.

## Phase 6 — Mock + Ollama LLM layer, agent pipeline (LangGraph + plain), SQLite audit store (2026-10-03T02:40:07+05:30)

**Done:**
- `uds_assistant/llm/base.py`: `LLMClient` protocol (`name`, `complete_json(system, prompt, schema)`, `complete_text(system, prompt)`), `LLMError`, and the only schemas an LLM fills: `ParsedRequirement` (services/dids/routines/sessions/security_levels as validated `0x..` identifier strings, DTC codes, intents from a closed `Intent` vocabulary, keywords), `PlannedTest(template_id, option_index, rationale)`, `TestPlan(tests)`. No byte/hex/request/response/parameter fields anywhere; `extra="ignore"` drops anything else an LLM emits. `build_prompt`/`extract_context` put a `CONTEXT_JSON:` block at the end of every prompt.
- `uds_assistant/llm/mock.py`: `MockLLM` — deterministic keyword/regex parser (hex tokens classified by the nearest preceding keyword: DID/routine/session/level/service; sub-function/reset values ignored; DID/routine names matched as phrases; service and intent keyword tables), rule-based planner over the enumerated template options (identifier-driven first pass, then derived checks: lockout for implied security levels, S3 for implied non-default sessions, service-not-in-session for implied services, unsupported sub-function / suppress bit for named services; honours `rejected`), templated prose explanations.
- `uds_assistant/llm/client.py`: `OllamaClient` (httpx, `/api/chat`, `stream: false`, `temperature: 0`, `format` = pydantic JSON schema, default model `qwen2.5:3b-instruct-q4_K_M`, `OLLAMA_HOST`/`OLLAMA_MODEL` env, timeout, bounded exponential-backoff retries on transport errors/5xx, re-prompt with the validation error on invalid JSON/schema, `LLMError` after `max_retries`), `ollama_reachable()` (`GET /api/tags`).
- `uds_assistant/llm/factory.py`: `get_llm(config=None)` — mock by default; `ollama` probes reachability and falls back to `MockLLM` with a warning.
- `uds_assistant/agent/`: `options.py` (spec index + per-template enumerated options with summaries and identifier refs), `state.py` (`PipelineState`, `PipelineDeps`, `PipelineResult`, `Decision`, `RejectedChoice`, `DroppedTest`), `nodes.py` (`parse`, `retrieve`, `plan`, `instantiate`, `validate`, `explain`, `route_after_validate`), `pipeline.py` (`run_pipeline`, plain loop `run_plain`, engine selection via arg / `UDS_AGENT_ENGINE`), `graph.py` (LangGraph `StateGraph` with conditional edge validate -> plan). Validation = schema + byte provenance (steps must equal a fresh template instantiation) + rules-engine oracle (`validate_test`) + citation validity; failures are dropped and fed back to `plan` (max 2 retries).
- `uds_assistant/store/audit.py`: `AuditStore` (stdlib sqlite3; tables runs/tests/decisions/results); the pipeline records the run, every node decision, and every kept test.
- Fixed a Phase-4 template defect: `security_invalid_key_lockout` waited past the 10 s lockout delay, which also exceeds S3, so its "seed after delay expiry" step was really observing 0x7F in default session; it now re-enters the session before that request (DECISIONS.md [A-LOCKOUT-FIX]).

**Mock-mode generation (seed requirements; LangGraph and plain identical):** REQ-001 6, REQ-002 9, REQ-003 5, REQ-004 3, REQ-005 10, REQ-006 10, REQ-007 8, REQ-008 8, REQ-009 10, REQ-010 4, REQ-011 4, REQ-012 6, REQ-013 3, REQ-014 7, REQ-015 8 = 101 tests, 0 dropped. Every test validates against the oracle, carries only valid citations, and passes on the bug-free simulator. All five categories are covered across the suite. Informal pre-check (the formal eval is Phase 7): the 101 generated tests catch 17/26 catalog bugs. The misses are template gaps (no multi-DID read, write-to-read-only DID, DTC group clear, 0x7F-vs-0x31 order probe, S3 exact-boundary, session-change relock, seed-reuse, or negative-with-suppress-bit templates), plus the long-running routine 0x0203 not being referenced by any seed requirement.

**Tests:** 693 passed, 2 skipped (`python -m pytest -q`); 126 new in `tests/llm`, `tests/agent`, `tests/store`, plus 1 new `needs_model` Ollama smoke test (skipped). Includes: no-byte-field schema checks, a malicious-LLM byte-injection test (both engines), a tampered-steps provenance test, LangGraph vs plain identical for all 15 seed requirements, a bounded retry loop (both engines), httpx.MockTransport client tests (body, parsing, invalid-JSON re-prompt, timeout/backoff, 5xx/4xx, max retries), factory fallback, and audit-store round trips.

**Ruff:** clean.

## Phase 7 — Runner, mock-mode evaluation, pytest/CAPL exports (2026-10-03T03:04:04+05:30)

**Done:**
- `uds_assistant/runner/`: `run_suite(tests, spec, bugs=None, store=None, run_id=None) -> SuiteResult` (fresh ECU per test via `testgen.execute.run_test_on_simulator`; wall-clock time of every `handle` call; explicit `max_response_time_ms` enforced, P2/P2* overruns recorded as warnings; optional AuditStore `results` rows with `bug_id`), `run_test`, `run_bug_matrix(tests, spec, bug_ids=None, store=None, run_id=None) -> BugMatrix` (each bug alone; tests failing on the clean simulator are reported invalid and get no detection credit).
- `uds_assistant/eval/`: `metrics.py` (request validity, expected-response accuracy vs oracle/simulator/gold, coverage, template reuse with an independent byte-provenance re-check, citation validity, bug detection, union), `report_md.py`, `run_eval.py` (`main(argv)`, `run_evaluation(mode, out_dir, engine, *, repo_root, requirement_ids, write_exports, run_exported) -> dict`). Writes `outputs/eval_report.{json,md}`, `outputs/generated_tests.yaml`, `outputs/exports/*`, `outputs/audit.sqlite` (git-ignored). JSON has mode (requested/actual/fallback), timestamp, git commit, metric definitions, per-mode blocks (ollama = "not run").
- `uds_assistant/export/`: `to_pytest(tests, path)` (standalone pytest file with raw bytes copied from the TestCase; in-process by default, `UDS_EXPORT_TRANSPORT=can` = EcuCanServer + udsoncan `PythonIsoTpConnection`, time-advance tests skipped in CAN mode), `to_capl(tests, path)` (CAPL testcase templates, banner "UNVERIFIED TEMPLATE — not compiled or run in CANoe").
- `Template.intended_nrcs`, `TEMPLATE_SET_VERSION`/`TEMPLATE_SET_NOTES` added; template set v2 (`testgen/templates_v2.py`, 9 generic templates, 23 total) + MockLLM generic planning rules for them; routine-start option-record fix (see DECISIONS.md [EVAL-TPL-V2], [EVAL-ROUTINE-FIX]).

**Eval, mock mode — baseline (template set v1, 14 templates; saved as outputs/eval_report_baseline_v1.{json,md}):** 101 generated tests; generated-suite bug detection **17/26 (65.4%)**; gold 24/26 (92.3%); union 25/26 (96.2%); request validity 265/268 (98.9%, the 3 failures were the real routine option-record defect: `31 01 02 02` -> 0x13); oracle agreement 268/268; gold exact overlap 22/22, shared prefix 15/15; clean-sim pass 101/101; coverage 15/15 requirements; template reuse 101/101; citations 460/460. Undetected: nrc_order_did_before_session, security_not_reset_on_session_change, s3_timeout_off_by_one, seed_not_consumed, readonly_did_writable, negative_response_suppressed, dtc_clear_ignores_group, multi_did_read_first_only, missing_response_pending.

**Eval, mock mode — after (template set v2, 23 templates):** 171 generated tests (94 unique); generated-suite bug detection **25/26 (96.2%)**; gold 24/26 (92.3%); union 26/26 (100%); request validity 445/445 (100%; unadjusted, no intent exemption, 90.8%); oracle agreement 445/445; gold exact overlap 25/25, shared prefix 18/18; clean-sim pass 171/171; coverage 15/15 (all 5 categories); template reuse 171/171; citations 774/774; 0 dropped/rejected/retries; ~28 s total. Only miss: `missing_response_pending` (no seed requirement references the long-running routine 0x0203, and the planner only tests referenced identifiers). Gold misses lockout_delay_never_expires and seed_not_consumed. **Caveat:** v2 was added after looking at the v1 misses, and the same author wrote the bug catalog, so the v2 number is optimistic and not an independent measurement (this is also stated in the report).

**Exports:** outputs/exports/generated_tests_test.py run via subprocess: 171 passed (in-process). Over virtual CAN, run once manually: 139 passed, 32 skipped (time-advance tests), ~48 s. Gold export over CAN: 58 passed, 2 skipped.

**Tests:** 730 passed, 2 skipped (needs_model) — `python -m pytest -q`, ~70 s. New: tests/runner (11), tests/export (6, including running exported files in subprocesses in-process + a CAN subset and a broken-expectation export that must fail), tests/eval (11, including an end-to-end `main()` into a tmp dir and an ollama->mock fallback run); template parametrized tests cover the 9 new templates.

**Ruff:** clean.
