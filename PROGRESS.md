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
