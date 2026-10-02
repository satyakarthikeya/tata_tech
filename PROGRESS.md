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
