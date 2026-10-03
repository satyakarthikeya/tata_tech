# DECISIONS.md

- Python 3.13.6 used instead of 3.11 (only interpreter available); code stays 3.11-compatible (no 3.12+ syntax).
- docs/, data/bcm_spec.yaml, data/requirements_seed.csv did not exist; synthetic BCM spec and requirements seed authored from scratch per PROJECT.md/SCOPE.md.
- Package root is `uds_assistant/` (implied by `python -m uds_assistant.eval.run_eval`); component dirs from PROJECT.md (protocol/, rules/, ...) live inside it.
- Owner asked for subagents ("sonnet 5.5"): no such model exists; Sonnet 5 used for routine phases, Opus for correctness-critical phases.
- Synthetic SecurityAccess algorithm: key = rotl8(seed_byte XOR (0xA5+level mod 256), 3) + level (mod 256), applied per byte; chosen to be simple, deterministic, and independently reproducible without copying any real algorithm.
- YAML spec authoring convention: `default_value` is a hex string (e.g. "F190" bytes as "f190"), converted to raw bytes by `_parse_spec_dict` before pydantic validation, since pydantic's `bytes` field otherwise treats a YAML string as UTF-8 text.
- `EcuSpec` cross-reference validation (sessions referenced by security levels/DIDs/routines, security levels referenced by DIDs/routines, SIDs referenced by sessions) is enforced in one `model_validator(mode="after")` so a malformed spec fails fast at `load_spec()` time rather than later in the rules engine.
- SecurityAccess seed/key subfunctions are constrained odd=seed / even=key via field validators, matching the udsoncan `Mode.RequestSeed`/`Mode.SendKey` convention used for cross-checking.
- `tester_present()` defaults `suppress_positive=True` since that is how it is used operationally (periodic keep-alive with no need for a response); callers that want a response pass `suppress_positive=False`.
- [R-SWS] (superseded in Part A — see [PA-SWS] below) Originally: no AUTOSAR Dcm SWS document available offline, so no SWS_Dcm IDs were cited; each check cited "udsoncan behaviour" or "design decision — see DECISIONS.md [tag]".
- [R-ORDER] Generic NRC order follows PROJECT.md §5 exactly: supported service (0x11; supported = listed in any session) → service in session (0x7F) → length (0x13) → subfunction supported (0x12) → subfunction in session (0x7E) → service-specific → response length (0x14) → response pending (0x78).
- [R-EMPTY] An empty request (no SID byte) gets no response at all and does not restart the S3 timer.
- [R-LEN] Length checked in two stages: generic min/exact length per service at step 3, then subfunction/identifier-specific exact length (0x19/02 = 3 bytes, 0x27 seed = 2, key = 2+seed_length, 0x2E data = DID length, 0x31 start = 4+option_record_length, stop/results = 4) right after the identifier/subfunction is known; 0x2E length precedes security.
- [R-SPRMIB] Suppress bit honoured only for 0x10/0x11/0x31/0x3E (Phase 1 SERVICES_WITH_SUPPRESS_BIT); for 0x19 and 0x27 the full subfunction byte is used, so e.g. 27 81 or 19 82 → 0x12.
- [R-SUPPRESS-NEG] Negative responses are never suppressed (physical addressing only); a suppressed positive outcome still applies its state change.
- [R-SUB-SESSION] 0x7E is produced only for SecurityAccess seed/key subfunctions whose level's allowed_sessions excludes the active session; all session transitions (0x10) and reset types (0x11) are allowed from every session because the spec defines no restrictions.
- [R-CLEAR] 0x14 group 0xFFFFFF clears all DTC statuses to 0x00; a 3-byte value equal to a spec DTC clears that one; anything else → 0x31.
- [R-0x72] NRC 0x72 is driven by an injectable environment flag `nvm_write_fault`: a 0x2E write or 0x14 clear that passes every other check returns 0x72 and changes nothing.
- [R-0x14] max_response_length (spec field, default/BCM value 4095 = ISO-TP classic limit) bounds positive 0x22/0x19 responses; checked after all identifier checks pass.
- [R-MULTI-DID] Strict multi-DID read: if any requested DID is unknown or not readable in the active session the whole request gets 0x31 (instead of silently skipping DIDs); duplicates are allowed and echoed.
- [R-READONLY] Writing a DID with empty write_sessions (read-only) → 0x31 (checked before session/length/security), since the identifier is not supported for writing.
- [R-SEC-EXACT] Security levels are independent: a DID/routine needing level N requires unlocked_level == N exactly (no hierarchy).
- [R-COND] Conditions (only `vehicle_stationary` = speed 0 km/h; unknown condition names are treated as not met) are checked after security, before value range; for routines they gate start only (stop/results are allowed while moving).
- [R-RANGE] 0x2E value range compares the data record as a big-endian unsigned integer against the inclusive spec range; routine option records have no range check (spec defines none).
- [R-SEC-LOCKOUT] SecurityAccess: delay check (0x37) precedes everything else in step 6 for both seed and key; an invalid key gives 0x35, and the attempt that reaches max_attempts gives 0x36 and arms delay_ms; after expiry the counter stays at max so the next invalid key immediately gives 0x36 again; only a valid key resets the counter; lockout state survives session change, S3 timeout and ECU reset.
- [R-SEC-SEQ] sendKey without an outstanding seed for that level → 0x24; any verified key (valid or invalid) consumes the pending seed; a session change, S3 timeout or reset discards pending seeds.
- [R-SEED] Seeds are deterministic: derive_seed(level, counter, len) byte i = (0x5A + 0x3B·level + 0x9D·counter + 0x71·i) mod 256 with an ECU-wide counter of non-zero seeds issued (never reset); each requestSeed issues a fresh seed (replacing any pending one); requesting the seed of the already-unlocked level returns an all-zero seed (udsoncan treats that as "already unlocked") and does not advance the counter.
- [R-ROUTINE-SUB] A RoutineControl type valid for the service (01/02/03) but not in the routine's allowed_subfunctions → 0x12, checked after routine id/session (0x31).
- [R-ROUTINE-SEQ] Routine sequence: start while RUNNING → 0x24; stop when not RUNNING → 0x24 (if stop_requires_start); results when never started since last session change → 0x24 (if results_requires_start); restart after STOPPED/COMPLETED allowed.
- [R-ROUTINE-STATUS] Routine responses carry one status byte: 0x01 running, 0x02 completed, 0x03 stopped, 0x00 never started; start of a long_running routine completes synchronously (status 0x02).
- [R-0x78] Spec field RoutineDef.long_running (true for nvm_factory_restore): start answers `7F 31 78` then the final positive; the final positive is sent even if the suppress bit was set; exactly one 0x78 is emitted.
- [R-NO-0x10] NRC 0x10 generalReject is never produced by the oracle (reserved for simulator bug injection); 0x10/0x11/0x3E have no service-specific negative checks.
- [R-S3] S3 check runs before evaluation: in a non-default session, if now − last_request > the active session's s3_ms (strictly greater) the ECU returns to default session, locks security, clears pending seeds and routine status; every non-empty request (even one answered negatively) restarts S3.
- [R-SESSION-RESET] Any positive 0x10 (including re-entering the same session) and any positive 0x11 lock security and clear pending seeds and routine status; DID values, DTC statuses, lockout counters and seed counter persist (NVM-like).
- [R-DYN-DID] DIDs named active_diagnostic_session (0xF186) and vehicle_speed_kph (0x0140) are read live from state (current session byte / environment speed clamped to 255) rather than from stored values.
- [R-RESP-BYTES] RuleResult.responses is a list of raw bytes rather than UdsResponse, because codec.UdsResponse cannot represent a 7F response for an unsupported SID; the rules engine parses requests leniently (rules/request.py) for the same reason.
- [S-INDEP] The simulator (`uds_assistant/simulator/`) is written from `docs/behaviour_contract.md` + `data/bcm_spec.yaml` only and never imports `uds_assistant.rules` (AST + fresh-interpreter test in `tests/simulator/test_independence.py`). It may share the lower layers `uds_assistant.protocol` (wire constants, `derive_seed`/`compute_key`) and `uds_assistant.spec` (spec loader), because those are the wire format and the input data, not the oracle; sharing them cannot hide an NRC-order/state disagreement.
- [S-STRUCT] Simulator structure deliberately differs from the rules engine: mutable `EcuMemory` dataclass, a generic gate + per-service handler classes in a SID dispatch table, negatives raised as `Reject` exceptions (no single ordered NRC function).
- [S-CLOCK] `SimulatedEcu.handle(request, now_ms=None)`: explicit `now_ms` wins, else the injected `clock()`, else the last time seen (moved by `advance()`); only `EcuCanServer` uses the wall clock (monotonic ms).
- [S-ENV] Simulator environment inputs: `set_vehicle_speed`, `set_nvm_write_fault`, `set_dtc_status` (DTC fault injection, needed so 0x19/0x14 behaviour is observable); `reset_state()` restores power-on memory but keeps environment and injected bugs.
- [S-BUGS] 26 injectable bugs in `data/bugs/bug_catalog.yaml`, each implemented by an explicit `ctx.bug(<ID>)` hook; `enable_bug` rejects ids not in `IMPLEMENTED_BUG_IDS`. `missing_response_pending` keeps the "final response sent even if suppressed" rule so it only removes the 0x78.
- [S-AGREE] Agreement test compares the bug-free simulator and `RulesSession` byte-for-byte on hypothesis sequences (300 examples, <=30 steps incl. multi-step macros for unlock/lockout/routines/writes) plus deterministic seeded walks/fuzz; DTC injection on the rules side uses the public helper `rules.state.with_dtc_status`. No disagreements were found, so the rules engine was not modified.
- [S-CAN] Virtual CAN uses python-can `interface="virtual"` with can-isotp 2.x `NotifierBasedCanStack`, normal 11-bit addressing tester 0x7E0 -> ECU 0x7E8, stmin 0, blocksize 0, padding 0x00; udsoncan test disables `use_server_timing` (server P2 = 50 ms is too tight for Windows thread scheduling) and uses generous timeouts.
- [T-STEP-MODEL] `TestStep` is a pydantic discriminated union on `kind` (`send`/`advance_time`/`set_environment`/`set_dtc_status`); `SendStep.expected_responses_hex` is the *ordered* list of frames the ECU is expected to send for that one request (0, 1, or 2 for a response-pending sequence), matching `RuleResult.responses` directly, rather than a set of alternative single responses.
- [T-BUILDER] `templates.py`'s internal `_Builder` steps a `RulesSession` while recording `TestStep`s, so every byte in a generated `TestCase` is produced by the rules engine oracle, never guessed; `applicable_params` enumerates combinations by scanning the loaded `EcuSpec` (DIDs/sessions/routines/security levels), not by hardcoding ids, so it stays valid if the spec changes.
- [T-GOLD] The 60 gold tests in `data/gold/gold_tests.yaml` were authored by `scripts/gen_gold.py` (not part of the package): request bytes come from `uds_assistant.protocol.builders` (wire encoding only, no rules-engine call), expected response bytes were hand-derived from `docs/behaviour_contract.md`; seed/key bytes for levels 1/0 and 3/0 were computed once via a `derive_seed`/`compute_key` one-liner and hardcoded. One authoring mistake (`gold_write_unknown_did` sent in the default session, where 0x2E itself is unsupported, so the service-in-session check wins over the DID lookup) was found by `validate_test`/`run_test_on_simulator` and fixed by moving the request into extended session.
- [T-DTC-STEP] `SetDtcStatusStep.code` carries the DTC code string (e.g. "B10101") rather than its integer, so the same step model drives both the rules-engine builder (via `rules.state.dtc_code_to_int`) and `SimulatedEcu.set_dtc_status`, which accepts either form.
- [RAG-SRC] `data/sources/` was empty; `data/sources/uds_reference_notes.md` was authored from scratch in our own words (no ISO 14229 text copied), with one `### 0xNN <ServiceName> {#svc-0xnn}` section per in-scope service so citations can point at a specific service's explanation.
- [RAG-CHUNK-MD] Markdown chunking splits on every heading line (`#` through `######`), not just top-level sections, so nested `###` service/NRC subsections become individually citable chunks; `ref` is the heading's explicit `{#anchor}` if present, else a slug of the heading text.
- [RAG-CHUNK-SPEC] `ecu_spec` chunks are built directly from `data/bcm_spec.yaml` (one per session/security level/DID/routine/DTC), with `identifiers` set to the union of every hex id mentioned in the generated text plus the entry's own id, so a citation's quote (any substring of that text) always finds its identifiers present.
- [RAG-HEX-TOK] BM25 tokenization normalizes a hex-looking token (has a `0x` prefix, or is <=8 chars with at least one a-f letter and one digit) to `hex:<lowercase-digits>`, so `"0xF190"`, `"F190"` and `"f190"` collide into one token; a bare all-decimal token like `"90"` is left as a plain word since it's ambiguous with an ordinary number.
- [RAG-BM25-FALLBACK] `rank-bm25` is installed in this environment, so `Bm25Retriever` uses the real `BM25Okapi`; a hand-written `HandBM25` (same Okapi formula) is included and used automatically if the `rank_bm25` import fails, verified to produce an identical top-k ranking order to `rank_bm25` on a fixed corpus.
- [RAG-CITATION] `citation_is_valid` requires the cited `(source_path, ref)` pair to match a real corpus chunk, and if a `quote` is present, that quote must appear verbatim in the chunk's text and any hex identifier it mentions must be in the chunk's `identifiers` — this catches both a dangling reference and a fabricated/mismatched quote, which is what the "citation validity" eval metric needs.
- [RAG-CHROMA-LAZY] `uds_assistant/rag/chroma.py` imports `chromadb`/`sentence_transformers` only inside `ChromaRetriever.__init__`/`chroma_available`, never at module scope, so the module (and the whole package) imports cleanly without either installed; verified by a subprocess import test and an AST check for top-level imports. The one test that instantiates `ChromaRetriever` is marked `needs_model`.
- [L-NO-BYTES] LLM schemas (`ParsedRequirement`, `PlannedTest`, `TestPlan`) have no byte/payload/parameter fields and use `extra="ignore"`. The planner chooses `(template_id, option_index)`, where the index points into `applicable_params(spec, template_id)` as enumerated by the agent. `plan` re-validates the LLM object from a plain dict (dropping subclass/extra fields), `instantiate` builds steps only via `TEMPLATES[...].instantiate`, and `validate` rejects any test whose steps differ from a fresh template instantiation (byte-provenance check).
- [L-CONTEXT] Prompts end with `CONTEXT_JSON:` + a JSON object holding the structured context (requirement, spec index, option catalog, rejected choices). A real LLM reads it as prompt text and `MockLLM` parses it, so mock and Ollama see the same prompt.
- [L-MOCK-RULES] MockLLM classifies each hex token by the nearest preceding keyword within 40 chars (DID/routine/session/level/service; sub-function/reset values are ignored). Keyword tables use word-start regexes (`read(?!dtc)` so "ReadDTCInformation" is not 0x22). The planner caps 6 options per template and, for per-session templates, narrows to the sessions the requirement names.
- [L-OLLAMA] OllamaClient uses `/api/chat` with `format` = the pydantic JSON schema (Ollama structured outputs), `temperature 0`, `stream false`. Transport errors/5xx are retried with backoff `backoff_s * 2**attempt` (default 2 retries); invalid JSON/schema is re-prompted immediately with the error text appended as a user turn; 4xx raises at once. Model/base URL come from `OLLAMA_MODEL`/`OLLAMA_HOST`.
- [L-FALLBACK] `get_llm` probes `GET /api/tags` (2 s timeout) for `LLM_MODE=ollama`; unreachable -> `warnings.warn` + `MockLLM`. LLM errors inside the pipeline are logged as node decisions and yield an empty parse/plan (the run still completes) rather than crashing.
- [A-ENGINE] The LangGraph graph uses a single-channel TypedDict state holding the pydantic `PipelineState`, and every graph node calls the same `run_node()` wrapper as the plain loop (which also flushes new decisions to the audit store), so both engines give identical results. Engine = argument, else `UDS_AGENT_ENGINE` (auto|langgraph|plain); auto = LangGraph if importable.
- [A-RETRY] A test failing validation is dropped immediately and its choice is added to `rejected` + `feedback`; `validate` routes back to `plan` while failures occurred and `plan_attempts - 1 < max_retries` (2). A re-proposed failed choice is rejected in `plan` ("previously failed validation").
- [A-CITATIONS] Template placeholder citations (e.g. `bcm_spec.yaml`/`dids.VIN`) are not corpus refs, so generated tests carry citations built from retrieval hits only: ECU-spec chunks for the option's DID/routine/DTC/security level/session (exact `did:<name>`-style refs as built by `rag.ingest`), the standard-notes and behaviour-contract sections for the template's primary service (heading match preferred), and the requirement row. Quotes are verbatim lines checked with `citation_is_valid`. Entities missing from the initial retrieval are fetched by a logged "evidence top-up" search in `instantiate`.
- [A-IDS] Generated test ids are `<requirement id lower-cased, hyphen -> underscore>__<template test id>` (e.g. `req_005__tpl_write_secured_0100`): unique per requirement and identifier-safe for exports.
- [A-LOCKOUT-FIX] Deviation from Phase 4: `security_invalid_key_lockout` advanced `delay_ms + 1` (10001 ms), which also exceeds S3 (5000 ms), so the final "seed after delay expiry" request actually hit 0x7F in the default session and never exercised delay expiry (bug `lockout_delay_never_expires` went undetected). The template now re-enters the level's session before that request; bytes still come from the rules engine.
- [S-STORE] AuditStore uses one sqlite3 connection with `check_same_thread=False` guarded by a lock (for later FastAPI use); timestamps are UTC ISO-8601; `results.bug_id` NULL = clean ECU; `runs` also stores `finished_at`.
- [RUN-TIMING] `runner.run_suite` wraps every `SimulatedEcu.handle` call with a wall-clock timer (via a proxy ECU, still executing through `testgen.execute.run_test_on_simulator`, fresh ECU per test). A step's explicit `max_response_time_ms` is enforced (overrun fails the test); otherwise the active session's P2 (P2* when the first frame is `7F xx 78`) is checked and an overrun is only a `timing_warning`, because in-process wall-clock time on a desktop OS reflects scheduler/GC noise, not ECU logic.
- [RUN-MATRIX] Bug detection: each bug is enabled alone on a fresh simulator per test; a bug is detected only by tests that pass on the clean simulator. Tests failing on the clean simulator are reported as invalid and never get detection credit, even if they also fail with the bug on.
- [EVAL-VALIDITY] "Request validity" = request decodes via `protocol.codec.decode_request` AND the oracle (replayed in sequence) does not answer a format NRC 0x11/0x12/0x13, unless the template declares that NRC in its new `Template.intended_nrcs` field (deliberate malformed-request probes). The unadjusted rate (no exemption) is reported too. This metric found a real v1 template defect (see [EVAL-TPL-V2]).
- [EVAL-ACCURACY] "Expected-response accuracy" is reported three ways: vs a fresh oracle re-run (a consistency check, since expected bytes come from the oracle), vs the independent simulator (clean pass rate), and vs the gold set via (1) exact overlap = identical step sequences ignoring expectations and (2) shared prefix = distinct send steps reached by an identical step prefix from power-on in both suites (deduplicated by prefix, so a shared `10 03` opener counts once).
- [EVAL-MODES] The report has a `modes` block with `mock` and `ollama` entries; only the mode actually used is filled, the other is `{"status": "not run"}`. `--mode ollama` with an unreachable server falls back to mock and records `requested_mode=ollama, actual_mode=mock, mode_fallback=true` plus the warning text.
- [EVAL-BASELINE] Before/after comparison: the first (template set v1) eval report was copied verbatim to `outputs/eval_report_baseline_v1.{json,md}`; `run_eval` reads that file (never hardcoded numbers) and renders a before/after table when it exists.
- [EVAL-TPL-V2] Deviation from PROJECT.md "8–12 templates": template set v2 has 23 templates (the Phase-4 registry-size test bound was raised from 20 to 30). The 9 new templates (templates_v2.py) are generic engineer checks (multi-DID read, write to read-only DID, session change re-locks security, key replay -> 0x24, DTC clear specific keeps others + undefined group -> 0x31, NRC still sent with suppress bit, TesterPresent at exactly S3, NRC priority 0x7F-before-0x31 with an unknown identifier, routine start+results incl. 0x78), enumerated from the spec and planned by generic MockLLM keyword/identifier rules; nothing reads the bug catalog. They were, however, chosen AFTER seeing which bugs v1 missed, and the same author wrote the catalog, so the v2 detection rate is optimistic and not an independent measurement; this is stated in the report (`template_set_note`).
- [EVAL-ROUTINE-FIX] v1 defect found by the request-validity metric: `routine_sequence` and `condition_not_met` sent RoutineControl start without the spec'd option record, so routine 0x0202 (option_record_length 1) only ever saw NRC 0x13 and its sequencing/condition checks were never exercised. Start requests now carry `bytes(option_record_length)`.
- [EXP-PYTEST] `to_pytest` writes one test function per TestCase calling `run_steps([...])` with the literal step bytes copied from the TestCase; the file locates `uds_assistant` by import / `UDS_REPO_ROOT` / its parent dirs (no absolute paths embedded). Default transport is in-process with an injected clock; `UDS_EXPORT_TRANSPORT=can` serves the ECU with `EcuCanServer` on a python-can virtual bus and sends raw bytes through udsoncan's `PythonIsoTpConnection` (`send`/`wait_frame`, following 0x78 pending; 0.3 s silence wait when no response is expected). Tests with an `advance_time` step are skipped in CAN mode (the server uses the wall clock; really sleeping through S3/lockout delays would cost >10 s per test).
- [EXP-CAPL] `to_capl` emits one `testcase` per TestCase using raw `diagRequest` bytes (`diagResize`/`diagSetPrimitiveByte`/`diagSendRequest`/`testWaitForDiagResponse`/`diagGetPrimitiveByte`) and a shared `SendAndCheck` helper; only the final frame of a 0x78 sequence is compared (the interim frame is noted in a comment); time steps -> `testWaitForTimeout`; simulator-only set-up steps -> `TODO` comments. Banner: "UNVERIFIED TEMPLATE — not compiled or run in CANoe".
- [EVAL-AUDIT] `run_eval` records every pipeline run in `<out>/audit.sqlite` and adds one `EVAL` run whose `results` rows hold the clean + per-bug execution of the generated suite (`bug_id` set). The DB accumulates across runs and is git-ignored.
- [API-RUNID] `/run` and `/export` accept either `run_id` (tests fetched from `AuditStore.get_tests`) or inline `tests` in the body; audit `results` rows are only written when `run_id` is given (ad-hoc inline-test runs have nothing to attach them to).
- [API-REVIEW-PATH] The review endpoint is `POST /tests/{run_id}/{test_id}/review`, not `/tests/{id}/review` as sketched in the task, because `AuditStore.set_review_status(run_id, test_id, status)` needs the run id to find the row (generated test ids are unique per run, not globally).
- [API-EVAL-OUTDIR] `POST /eval` defaults `out_dir` to a fresh `tempfile.mkdtemp()` (not `outputs/`) so API calls can never overwrite the Phase-7 committed `outputs/eval_report*.json`; callers can still pass an explicit `out_dir` to write into `outputs/` on purpose.
- [API-DB] The module-level `app = create_app()` uses `outputs/api_audit.sqlite` (git-ignored by the existing `*.sqlite` pattern); the Streamlit UI uses a separate `outputs/ui_audit.sqlite` so the two front-ends don't contend for the same SQLite file under concurrent dev use. Tests always pass an explicit `db_path=tmp_path/...`.
- [UI-NO-HTTP] The Streamlit UI calls `agent.run_pipeline`/`runner.run_suite`/`export.render_*` directly rather than going over HTTP to the FastAPI service, to avoid requiring both processes to be running for the UI to work; it shares the same `AuditStore` class (different file) so both front-ends keep an audit trail.
- [UI-STREAMLIT-INSTALL] `pip install streamlit` was attempted once (no retry loop, per AGENT.md) and succeeded (1.64.0). It is declared as an optional extra (`uds-assistant[ui]`) rather than a hard dependency, and `uds_assistant/ui/__init__.py` imports nothing from `streamlit_app.py`, so the rest of the package stays importable without it (verified by a subprocess test that blocks the `streamlit` import and still imports `uds_assistant` and `uds_assistant.api.app`).

## Part A

### Step 0 and A2 (natural-language requirements)

- **[PA-OLDDOCS]** No older 18-file doc set was found; the search is recorded in `docs/RECONCILIATION.md`. The current spec and requirements stay the source of truth, and nothing was ported.
- **[PA-SWS-FILE]** The Dcm SWS PDF is named `AUTOSAR_CP_SWS_DiagnosticCommunicationManager.pdf`. That doesn't match the brief's glob `*Dcm*`, but it is that document, so A4 was run.
- **[PA-A2-SPLIT]** The A2 subagent chose the dev/test split to balance topics:
  - dev: NAT-001, 003, 005, 007, 009, 011, 013, 015
  - test: the other 12
- **[PA-A2-LOCKOUT]** The labels for NAT-010 (lockout) list `extended_session` only. `lockout_active` is the state being tested, not a precondition for running the test.
- **[PA-A2-NAT017]** NAT-017 (DTC clear) has the precondition `none`, because the label format has no way to say "default or extended session". The note on the row explains this.
- **[PA-A2-AMBIG]** Three rows are deliberately ambiguous: NAT-004, NAT-006 and NAT-017.
- **[PA-A2-UNSUP]** NAT-020 (firmware rollback) is deliberately unsupported by the spec, so all its target columns are empty.
- **[PA-A2-HEX]** 5 of the 20 rows contain a literal hex ID: NAT-005, 010, 013, 016 and 019.

### A1 (held-out bugs)

- **[PA-A1-IDS]** The 12 held-out bugs are kept in a separate `HELDOUT_BUG_IDS` set, not in `IMPLEMENTED_BUG_IDS`.
  - `SimulatedEcu` accepts any id in `ALL_BUG_IDS`, which is the union of the two sets; unknown ids still raise `ValueError`.
  - Code that loops over the original catalog is unchanged.
- **[PA-A1-SCHEMA]** `BugDef` gained an optional `heldout: bool = False`, so the original catalog loads unchanged.
  - `HELDOUT_BUG_CATALOG_PATH` points to `data/bugs/heldout_catalog.yaml`.
  - No new category values were added. Bugs about state after reset or S3 are filed under security or timing, and suppress-bit bugs under format.
- **[PA-A1-AUTHOR]** The held-out bugs were written by a subagent under the read restrictions recorded in PROGRESS.md. It could not see testgen, gold, eval, llm or agent code.

### A4 (AUTOSAR SWS citations)

- **[PA-SWS]** `rules/nrc_order.py` and `rules/engine.py` now cite 38 distinct AUTOSAR CP R24-11 Dcm SWS IDs.
  - An ID is cited only where the requirement text states the same behaviour, and each comes with a one-line paraphrase.
  - The existing DECISIONS.md tags are kept alongside.
  - The PDF and its extracted-text cache are git-ignored for licensing reasons.
  - `tests/rules/test_sws_citations.py` checks every cited ID against the local PDF and is skipped if the PDF is absent.
- **[PA-SWS-DIFF]** Nine differences from the SWS (D1–D9) are documented in `docs/SWS_DISAGREEMENTS.md`, not fixed.
  - Fixing them needs coordinated changes to the simulator, the behaviour contract and the gold tests and templates, which are frozen during Part A.
  - The high-impact ones are D2, D5, D6 and D7.
- **[PA-RESPOND-ALL]** SIDs in 0x40–0x7F and 0xC0–0xFF are answered with 0x11. In SWS terms this matches DcmRespondAllRequest = TRUE (SWS_Dcm_00084).

### A3 (evaluation extension)

This subagent was interrupted when the session ended before it could report back. The orchestrator reviewed its on-disk work instead: 830 tests passed, ruff was clean, and the freeze diff was empty.

- **[PA-A3-HEADLINE]** The headline table in `outputs/eval_report.md` has 7 rows, in the order the brief sets.
  - The headline bug-detection number is the generated suite's held-out detection.
  - The in-sample 26-bug numbers are a secondary section, labelled "in-sample (templates tuned on these)".
  - "Expected-response accuracy vs oracle" moved to an appendix titled "Self-consistency check (circular by construction)".
- **[PA-A3-AGREE]** Simulator ↔ rules-engine agreement is computed live in the eval by `uds_assistant/eval/agreement.py`.
  - It uses a deterministic seeded random sample of 5000 requests and does not import from `tests/`.
- **[PA-A3-CAN]** The udsoncan virtual-CAN sequence runs live in the eval (`uds_assistant/eval/can_check.py`). `--skip-can` exists for fast tests only.
- **[PA-A3-HELDOUT]** `runner.run_bug_matrix` gained an optional `catalog=` parameter, so it can run against the held-out catalog. The default behaviour is unchanged.
  - The reason given for each missed held-out bug comes from a static "trigger" check in `uds_assistant/eval/heldout.py`: does any test apply the stimulus the bug needs?
  - That analysis is for reporting only and changes nothing.
- **[PA-A3-UNDERSTAND]** Requirement understanding is scored in `uds_assistant/eval/understanding.py`, with the TEST split as the main number. Targets are scored two ways:
  - "parsed": the identifiers in `ParsedRequirement`
  - "exercised": the identifiers the generated tests actually send

  Precondition recall uses preconditions worked out from concrete test steps (`uds_assistant/eval/trace.py`); the mapping is documented in the report.

### A5 and A6 (docs pack, UI and final touches)

- **[PA-UI-REPORT-ENV]** The Streamlit UI reads the eval report from `UDS_EVAL_REPORT` if it is set, otherwise from `outputs/eval_report.json`. Tests use this to supply an old-format report without touching `outputs/`.
- **[PA-UI-BUGLABELS]** The bug picker labels each option `[in-sample]` or `[held-out]`. If the held-out catalog can't be loaded, the UI falls back to in-sample bugs only.
- **[PA-DOCS-HEADLINE]** PROJECT.md, README.md, FINAL_REPORT.md and docs/RESULTS.md all lead with the held-out generated-suite number (3/12), shown with gold 3/12 and union 5/12.
  - In-sample 25/26 is a secondary number, labelled "templates tuned on these".
- **[PA-DOCS-TEMPLATES]** PROJECT.md now documents 23 templates instead of the planned 8–12: 14 in v1, plus 9 added in Phase 7 after seeing the in-sample misses. It also states Python 3.13.
- **[PA-NEXT-SWS]** D2, D5, D6 and D7 are the first SWS disagreements to fix in Part B. The fix must be coordinated across the rules engine, simulator, behaviour contract and gold tests, and done with a new held-out set.

## Part B

- **[PB-INSTALL]** For Part B the owner lifted the offline rule for three things only: chromadb, fastembed and BAAI/bge-small-en-v1.5.
  - onnxruntime 1.30.0 came in as an unavoidable dependency of fastembed and chromadb. It is on AGENT.md's never-install list, but the owner explicitly allowed the packages that require it.
  - torch, transformers and sentence-transformers are still not installed.
- **[PB-EMBED]** Embeddings use fastembed, which runs ONNX on the CPU with no torch.
  - fastembed's `BAAI/bge-small-en-v1.5` resolves to Qdrant's ONNX export (`Qdrant/bge-small-en-v1.5-onnx-Q`), the same model exported to ONNX.
  - The sentence-transformers embedder stays as an optional code path and is not installed.
- **[PB-OLLAMA-CLI]** `ollama.exe` is not on Git Bash's PATH. Preconditions were checked with PowerShell `ollama list` and HTTP `/api/tags`.

### B1 (embeddings and retrieval comparison)

- **[PB-RAG-EMBED]** The embedder is chosen with `EMBEDDER=fastembed|sentence-transformers`; the default is fastembed running bge-small-en-v1.5 on ONNX.
  - sentence-transformers is an optional path that is only imported when selected.
  - The model cache lives at `~/.cache/uds_assistant/fastembed`, which `FASTEMBED_CACHE_PATH` overrides. It was seeded from the temporary cache so it survives Temp cleanup.
- **[PB-RAG-CHROMA]** The Chroma store is at `outputs/chroma` and is gitignored.
  - It uses cosine distance and one collection per embedder.
  - Only changed chunks are re-embedded, using a text hash.
  - The factory warns and falls back to BM25 if chromadb or the embedder is missing, or if building the store fails.
- **[PB-RETRIEVAL-CMP]** Relevance ground truth comes from the labelled targets in `requirements_natural.csv`.
  - A DID or routine target matches by identifier in the ecu_spec collection; a service-only target matches the standard `svc-<sid>` chunk.
  - NAT-020, which has no targets, is excluded. Search spans all collections.
  - Reported per split: hit@1, hit@3, MRR@10, and citation validity over the top 3 hits.
- **[PB-RETRIEVAL-RESULT]** Neither backend is clearly better on 19 queries, so the default stays BM25.
  - Test split (n=11): BM25 hit@1 36.4%, hit@3 63.6%, MRR 0.552. Chroma hit@1 18.2%, hit@3 63.6%, MRR 0.462.
  - All rows: Chroma hit@3 68.4% vs BM25 52.6%.

### B2 (Ollama settings and smoke test)

- **[PB-PROMPTS]** All agent prompt text now lives in `uds_assistant/llm/prompts.py`, moved there word for word in B2. Prompt tuning edits only that file.
- **[PB-OPTS]** `OllamaClient` always sends:
  - `num_ctx=4096`, overridable with `OLLAMA_NUM_CTX`
  - `temperature=0` and `seed=0`, for parse, plan and explain alike
  - `keep_alive=10m`, overridable with `OLLAMA_KEEP_ALIVE`
  - a JSON-schema `format` on structured calls

  Explain also runs at temperature 0 so results can be reproduced.
- **[PB-INSTR]** `PipelineResult` gained:
  - `node_timings` and `node_calls`
  - `llm_stats`: calls, JSON failures, retries, errors and latency for that run
  - `fallback_events`: the `get_llm` fallback warning quoted exactly, plus any failed LLM call the pipeline continued past

  Timing fields are left out of the engine-equality and determinism tests.
- **[PB-SMOKE]** Real-model smoke run on REQ-001 to REQ-005:
  - 0 JSON or schema failures, 0 retries, 0 fallbacks.
  - 18 to 19 tests kept per requirement; planning was not selective.
  - Parse output was weak: identifiers not in the requirement were added, and `sessions` came back empty every time.
  - Explain dominates the time, at about 80 s per requirement (one call per test). Total was 103 to 126 s per requirement.

### B3 (prompt tuning on the dev split)

- **[PB-B3-TRUNC]** B3 found that the plan prompt was about 16.2k tokens, mostly the 154-option template catalog, but `num_ctx` is 4096.
  - Ollama silently truncated the prompt to its last ~2k tokens, so the planner never saw the instruction or the requirement. It returned the same 18 tests for every requirement.
  - Decision: keep `num_ctx=4096`, the owner's explicit 4 GB setting, and fix the pipeline instead:
    - The plan node budgets its context only when the client declares a token limit. It sends a shortlist of relevant options, with the requirement placed after the options. Mock declares no limit, so its output is unchanged.
    - `OllamaClient` detects truncation from `prompt_eval_count` and reports it verbatim.
  - The fix is followed by more tuning on the dev split only.
- **[PB-B3-REV5]** The first tuning round kept revision 5, which changes only `PARSE_INSTRUCTION`.
  - Dev parsed F1 rose from 0.329 to 0.667.
  - Category and precondition recall did not move, because of the truncation above.
  - Each revision is a single run on 8 rows, so the scores are noisy.
- **[PB-CTX-BUDGET]** When a backend declares `context_tokens` (Ollama does; mock does not), the plan node sends a compact plan prompt.
  - It contains a shortlist of options ranked by relevance to the parsed requirement: at most 24 options, at most 4 per template.
  - Each option keeps its real catalog index, so validation, instantiation and byte provenance are unchanged.
  - The task comes after the options, and the prompt fits within 60% of `num_ctx`, estimated at 3 characters per token.
  - A choice outside the shortlist is rejected.
  - The mock keeps the full-catalog prompt, byte for byte. Its output on all 15 seed requirements is identical before and after, recorded in `outputs/prompt_tuning/mock_equivalence.json`.
- **[PB-TRUNC-DETECT]** `OllamaClient` flags likely truncation in three cases:
  - `prompt_eval_count` is close to `num_ctx`;
  - `prompt_eval_count` sits at Ollama's cut point of `num_ctx`/2 while the estimated prompt is above 0.75 × `num_ctx`;
  - the estimated prompt is larger than `num_ctx`.

  Each flag is counted in `LLMStats.truncations` and quoted in the run's `fallback_events`.
- **[PB-B3-SELECT]** Revision 8 is selected and frozen: the revision-5 parse prompt with the revision-8 plan prompt.
  - It had the best dev score: 2.410 against 2.409 for revision 7, winning the tie-break with 5.38 tests per requirement against 6.62.
  - Dev results: parsed F1 0.683, category recall 0.727, precondition recall 1.0, 0 truncations.
  - Runs vary by about ±0.05 F1 because GPU decoding is not deterministic.
- **[PB-B3-RISK]** The 3B model sometimes copies "(category)" into `template_id`; this showed up in revision 9, which was rejected. A possible fix is to strip that suffix before validation. It is deliberately not done, because it would come after the freeze.

### B4 (full evaluation, mock vs ollama)

- **[PB-B4-PROV]** Byte provenance is checked after the run on every generated test in every mode (`uds_assistant/eval/provenance.py`).
  - Each test is rebuilt from its template using its stored parameters, and every step must match byte for byte.
  - Any failure makes `run_eval` exit with code 2 after the report is written.
  - Result: mock 343 of 343 passed, ollama 158 of 158 passed.
- **[PB-B4-COMBINED]** `--mode ollama` also runs mock in the same invocation, and `--no-mock-compare` turns that off.
  - `actual_mode` is the backend that really ran, after any fallback.
  - The LLM-dependent headline rows carry results for both modes, and the report version is now 2.
- **[PB-B4-EXPORTS]** Ollama exports go to `outputs/exports/ollama/` and `outputs/generated_tests_ollama.yaml`. The mock export paths are unchanged.
- **[PB-B4-LATENCY]** Latency is the wall-clock time of one pipeline run per requirement over all 35 requirements, with p95 by nearest rank. Per-node values come from `node_timings`.
- **[PB-B4-INTERP]** The interpretation was written after the numbers existed, in `outputs/eval_interpretation.md`, and was stored in the report with `--rerender`, which recomputes nothing.
- **[PB-B4-RESULT]** Test split, mock vs ollama:
  - Parsed F1: 0.700 vs 0.647 (precision 0.933 vs 0.512, recall 0.560 vs 0.880).
  - Category recall: 67.9% vs 64.3%.
  - Precondition recall: 80.0% vs 73.3%.
  - Held-out generated bug detection: 3/12 vs 3/12, the same three bugs.
  - In-sample generated detection: 25/26 vs 21/26. Generated tests on the seed requirements: 171 vs 68.
  - Mean latency per requirement: 0.25 s vs 30.8 s.
  - No truncations and no fallbacks in either mode.

  The model did not beat mock on any headline metric, so mock stays the default.

### B5 (docs, UI and final report)

- **[PB-DEMO-LLM]** `scripts/demo.py --llm ollama` is the only Ollama switch in the demo. It falls back to mock with a printed warning, and the default stays mock. The demo does not read `LLM_MODE`.
- **[PB-V2-READERS]** The demo's headline lines and the Streamlit UI now read the version 2 report, which has results for each mode. They show "n/a" when a mode or key is missing.
- **[PB-SMOKE-FALLBACK]** `outputs/ollama_smoke.json` is the early B2 run, from before the plan-context fix. The demo uses it only as an offline fallback, and the docs say so.
- **[PB-STALE-DOCS]** `MODEL_SETUP.md` and `docs/CODE_TOUR.md` were edited because they still described sentence-transformers and torch, and said no real model had been run.
- **[PB-DEFAULT-MOCK]** Mock stays the default LLM. On the held-out test split the 3B model did not beat it on any headline metric.

## Part C

### C1 (LLM pipeline fixes)

- **[PC-NORM]** Planner `template_id`s are normalised before validation:
  - one trailing `(...)` group removed, whitespace and quotes trimmed, lowercased;
  - the result is accepted only if it exactly matches a catalog id, with no fuzzy matching, so `read_did` does not match `read_did_positive`;
  - each normalisation is recorded in `notes` and in the plan trace.
- **[PC-GROUND]** DIDs, routines and DTCs from a real model survive parsing only if one of two things holds:
  - the requirement writes them out (`0x0100`, `0100` or `f190`, any case);
  - a search of the `ecu_spec` collection returns their chunk and a distinctive word of its name appears in the requirement.

  Services, sessions and security levels are not checked. Every drop is recorded in `notes` and the parse trace.
  - The mock is exempt through `applies_grounding = False`. Forcing grounding on the mock's parses would drop 0 identifiers on all 15 seed requirements, so the gate hides no difference.
  - Known risk: a real DID that the requirement refers to only by an abbreviation could be dropped. This has not been measured against the real model.
- **[PC-PROMPT]** The parse prompt examples use `<id of X>` placeholders. The old examples used the real spec ids 0x0140, 0x0202 and 0x0101, which is how they leaked into unrelated requirements.
- **[PC-EXPLAIN]** Explain makes one batched JSON call per requirement.
  - Tests are sent as compact summaries with no hex.
  - It splits into more calls only when the estimated prompt would exceed `num_ctx`.
  - A test missing from the reply, or a failed batch, gets a deterministic fallback text and a trace entry.
  - The mock's explanation wording changed; nothing else did.
  - `node_llm_calls` now shows calls per node.
- **[PC-MOCK-EQ]** Mock output is unchanged.
  - The agent compared 30 runs (15 seed requirements, two engines) before and after: identical in everything except explanation text and call counts.
  - I separately compared the current mock tests with those committed before Part C: 171 of 171 have identical steps.
  - Evidence: `outputs/partC/mock_equivalence.json`.
- **[PC-FLAKE]** One earlier full run had a single failure: `tests/protocol/test_codec.py::test_request_roundtrip_with_subfunction`, a hypothesis `too_slow` health check. It passed in isolation and in the final full run, so it looks load-related rather than a code problem.

### C2 (fix SWS disagreements D2, D5, D6, D7)

- **[PC2-RULES]** The rules engine fixes four disagreements. Each was checked against the SWS text before changing behaviour, and each cites the SWS IDs it now matches.
  - D2: RoutineControl has no generic "subfunction supported" 0x12 check. An unknown routine or wrong session now answers 0x31 first, and the per-routine check is the only 0x12. Example: `31 04 FF FF` went from `7F 31 12` to `7F 31 31`.
  - D5: 0x37 applies to requestSeed only. A key sent during the delay takes the normal key path and answers 0x24, with no attempt counted and the deadline unchanged.
  - D6: bit 7 is the suppress-positive bit for all six subfunction services, including 0x19 and 0x27. `27 81` now behaves as `27 01` with the positive response suppressed, and negatives are still sent.
  - D7: multi-DID read skips unknown or unreadable DIDs, and answers 0x31 only if none remain. Duplicates are answered per occurrence, and 0x14 is computed on the answered DIDs only.
  - D1, D3, D4, D8 and D9 stay documented and open.
- **[PC2-SIM]** The simulator was changed in a separate step by an agent that never read the rules engine, working from `docs/behaviour_contract.md` and the SWS description. The two implementations agree on 100% of requests, with all bugs off:
  - seed 20261003: 13,487 requests
  - seed 777001: 13,556 requests
  - plus a 300-example hypothesis test and a 3,000-request fuzz

  The generators were extended so each new path is exercised (for example 824 key-during-delay requests answered 0x24 on one seed). No disagreement was found.
- **[PC2-LABELS]** The simulator agent referred to the suppress-bit fix as D7 and the multi-DID fix as D6, the opposite of `docs/SWS_DISAGREEMENTS.md`. Only the labels differ; the behaviour it implemented is correct.
- **[PC2-CODEC]** In the shared protocol layer, `SERVICES_WITH_SUPPRESS_BIT` now equals `SERVICES_WITH_SUBFUNCTION`.
  - The builders for 0x19 and 0x27 take `suppress_positive`.
  - A udsoncan cross-check covers the new suppress cases for 0x19 and 0x27, which udsoncan supports.
- **[PC2-GOLD]** One gold test changed, by hand:
  - `gold_multi_did_read_one_bad`: request `22 F1 90 99 99` now expects `62 F1 90` plus the 17-byte VIN, instead of `7F 22 31`.
  - Category changed from negative to positive, and the title and explanation were updated.
  - `scripts/gen_gold.py` was kept in sync.
  - The 59 other gold tests passed unchanged, so none of them exercised D2, D5 or D6. The set is still 60 tests.
  - The new expected bytes pass both on the clean simulator and against the rules engine.
- **[PC2-BUGS]** No bug needed changing. One catalog description changed: `lockout_delay_never_expires` now says "seed requests keep being answered 0x37", because keys now get 0x24 during the delay. Its behaviour and intent are unchanged, and every bug still differs from clean on its demonstrating sequence.

### C3 (coverage templates)

- **[PC3-TPL]** Template set v3: 27 templates, up from 23, with a cap of 32. They were designed from the static list of stimuli that the held-out v1 misses needed. Held-out v1 results are therefore labelled "seen" from now on.
  - 4 new general templates:
    - `read_did_invalid_length`: malformed 0x22 lengths (14 options)
    - `seed_request_while_unlocked` (2 options)
    - `session_change_resets_routine`: routine status across a session change or ECU reset (6 options)
    - `write_did_value_retained`: byte order and retention of a written value across S3 timeout or ECU reset (14 options)
  - Variants appended to 3 existing templates:
    - `security_invalid_key_lockout`: recovery by ECU reset
    - `condition_not_met`: security still locked
    - `routine_start_results`: suppress-positive start
  - Every parameter comes from the spec. Each new template has a "Behaviour class" docstring.
  - A test scans the testgen source, template metadata and every instantiated test for all 38 bug ids and fails on any hit. I ran the same scan myself: 0 hits.
- **[PC3-PARAMS]** Variants are appended after the base options, so existing option indices and test ids do not change. Base tests' stored parameters now include the default variant key, which the provenance round-trip needs.
- **[PC3-MOCK]** The mock planner has generic keyword rules for the new templates, none keyed on bug ids.
  - `read_did_wrong_session_or_unknown` is now chosen for any referenced DID.
  - All 171 earlier seed tests are still generated with identical steps; 35 new ones were added, for 206 in total.
- **[PC3-SHORTLIST]** `PLAN_SHORTLIST_MAX` went from 24 to 30, so the larger catalog drops no option that was offered before for any seed requirement. The compact plan prompt stays within the budget: about 1.6k of 2.46k estimated tokens.
- **[PC3-COVERAGE]** Of the 12 held-out v1 stimuli, the mock on the seed requirements now applies 10, up from 3.
  - The two still missing are the uint16 byte-order case and the suppressed long-running routine start. Templates for them exist, but no seed requirement names the DID or routine they need.
  - This is a coverage report only. It is not an optimisation target.
- **[PC3-HYPOTHESIS]** Hypothesis's `too_slow` health check is switched off for the whole suite in `tests/conftest.py`.
  - It measures how fast test data is generated, not correctness, and it failed twice under load: `test_request_roundtrip_with_subfunction`, plus a stale failure marker from an earlier step.
  - The test passes alone with the failing seed. No assertion or example count changed.
