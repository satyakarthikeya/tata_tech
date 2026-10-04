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

### C4 (fresh evaluation data, written blind)

Both agents were launched after the Part C freeze. Their exact prompts are recorded in PROGRESS.md.

- **[PC4-BUGS]** Held-out bugs v2: 15 new defects in `data/bugs/heldout_v2_catalog.yaml`, each tagged `heldout_v2: true`.
  - The agent could read only the spec, the behaviour contract, protocol, simulator and the two existing bug catalogs (to avoid duplicates). It could not see the testgen, agent, llm, eval, gold or outputs.
  - It is a third, separate set. `IMPLEMENTED_BUG_IDS` and `HELDOUT_BUG_IDS` are unchanged, and only `ALL_BUG_IDS` is widened.
  - The 15 ids, by category:
    - Security (4): `seed_request_keeps_stale_pending_seed`, `key_compare_prefix_only`, `lockout_counter_pooled_across_levels`, `suppressed_seed_request_not_stored`.
    - Session and state after reset or timeout (4): `session_reentry_keeps_unlock`, `s3_timeout_resets_lockout_counters`, `ecu_reset_keeps_session`, plus the timing one below.
    - Timing (1): `s3_restart_skipped_on_negative_response`.
    - NRC order (2): `nrc_order_range_before_security`, `nrc_order_nvm_fault_before_group_check`.
    - Length and format (2): `read_dtc_trailing_bytes_accepted`, `routine_option_record_overlong_accepted`.
    - DID and routine (3): `write_range_upper_bound_exclusive`, `multi_did_read_dedups_repeats`, `routine_restart_after_stop_blocked`.
  - Limits the agent reported:
    - Every session in the spec has the same timing values, so no bug could be built on per-session P2 or S3 values. The timing bug is about S3 restart behaviour instead.
    - Every positive 0x10 re-locks security and 0x27 is not allowed in the default session, so "S3 timeout keeps the unlock" cannot be observed. The S3-state bug is about lockout counters instead.
  - A unit test per bug asserts the exact differing bytes with the bug on and off.
  - With all bugs off the simulator is unchanged: the agreement tests still pass.
- **[PC4-REQS]** Natural requirements v2: 16 requirements in `data/requirements_natural_v2.csv`, all `split=test2`.
  - The agent could read only the spec and the seed requirements. It could not see the v1 natural set.
  - Only 2 contain a hex id (NAT2-011 and NAT2-012).
  - The 2 ambiguous rows are NAT2-014 (which door lock, and what "unauthorised" means) and NAT2-015 (when the fault memory may not be cleared).
  - NAT2-016 asks for freeze-frame snapshots, which the spec does not define. It has empty targets, empty categories and the precondition `none`.
  - NAT2-004 lists `routine_started` as a precondition.
  - NAT2-006 (lockout) lists `extended_session` and `lockout_active` but not `security_level_1`.
  - NAT2-010 is about state being lost after a reset, because the spec does not define whether written values survive.
- **[PC4-FREEZE]** I verified after C4 that the testgen, llm and agent trees, the prompts file and `data/gold` still match the recorded freeze hashes. The working tree has no changes to any of them.

### C5a (evaluation extension, built without the GPU)

- **[PC5-V2-HEADLINE]** The held-out v2 "generated suite" is the tests generated from the 15 seed requirements, the same definition as the earlier headline, so the numbers are comparable.
  - Detection by all generated tests (seed, natural v1 and natural v2) and by the natural-v2 tests alone are reported as supplementary lines.
- **[PC5-TRIGGERS-V2]** The 15 v2 trigger predicates (`uds_assistant/eval/heldout_v2.py`) were written from the bug descriptions and the behaviour contract before any v2 result was seen.
  - Afterwards only behaviour-preserving edits were made: one lint-driven refactor and some wording in the reason text. No logic was changed.
  - The predicates are necessary, not sufficient. A bug whose stimulus is applied but whose expected responses do not differ is reported with that reason.
- **[PC5-NOISE]** `--noise-runs N` runs natural v2 N times in ollama mode. Run 1 feeds the tables, and the report lists every run with mean and min–max. Mock runs once plus a second run that must be identical.
- **[PC5-PROV]** Byte provenance also covers natural v2 and every extra noise run. Any failure still gives exit code 2 after the report is written.
- **[PC5-FREEZE]** The report now parses the freeze hashes from the "Part C freeze" table in PROGRESS.md, and the freeze commit must be an ancestor of HEAD. The old hard-coded expected hashes were removed.
- **[PC5-BASELINE]** `outputs/partC/baseline_before_partC.json` is frozen from commit 38aa719, and a test re-extracts it from git and compares.
  - Explain calls in the baseline are derived from tests kept, because explain made one call per kept test: 9.80 per requirement for mock, 4.51 for ollama.
- **[PC5-LATENCY]** The latency and rejected-choice rows in before/after use the 35 seed and natural-v1 requirements, so they stay comparable with the baseline. The v2 rows are reported separately.
- **[PC5-DRYRUN]** A mock-only dry run into a temporary folder gave these v2 numbers:
  - Held-out v2 bugs: generated 2/15, gold 5/15, union 5/15.
  - Natural v2: parsed exact 0/16, parsed P/R/F1 1.0 / 0.2245 / 0.3667, category recall 24/50, precondition recall 15/27.
  - These are the mock numbers on fresh data, recorded before any Ollama run.

### C6a (UI, checklist, code tour and demo, built without the GPU)

- **[PC6-UI]** The Streamlit evaluation section renders `outputs/eval_report.json` (version 2 or 3) and `outputs/partC/before_after.md`, and never computes metrics.
  - v1 rows are labelled SEEN.
  - The "did NOT beat" note shows only for version 2 reports.
  - A mode that was not run shows "not run yet"; a missing before/after file shows "not generated yet".
- **[PC6-UI-BUGS]** The bug dropdown now offers three sets: `[in-sample]`, `[held-out v1, seen]` and `[held-out v2, fresh]`.
- **[PC6-UI-LLM]** After generating, the UI shows which LLM backend ran and any fallback warning. This addition was not in the brief.
- **[PC6-DEMO]** `scripts/demo.py --bug` accepts any bug id from all three sets, and reads the version 3 headline, falling back gracefully to the older layout. It hard-codes no verdict or numbers for version 3.
- **[PC6-DOCS]** `docs/DEMO_SCRIPT.md` and `docs/CODE_TOUR.md` carry no final v2 numbers, only placeholders. The mock counts in them come from real runs.
- **[PC6-CHECKLIST]** `docs/UI_CHECKLIST.md` has 10 steps. Steps 1 to 8 are checked against the real widget labels through the headless UI test, and step 6 is pinned by a test.
  - Not verified: launching `streamlit run` in a real browser (the checklist notes it may need `PYTHONPATH=.`), and the human-review button in a live browser.

### C5b and C6b (real evaluation, final docs)

- **[PC5B-RESULT]** The real run found, on fresh v2 data:
  - Held-out bug detection by the generated suite is 2/15 in both modes (gold 5/15, union 5/15). The templates written in C3 did not transfer from the seen v1 bugs.
  - On natural v2 the model beats the mock on understanding (parsed F1 0.661 vs 0.367, category recall 74.0% vs 48.0%), but its precision is 0.565 with 30 false positives, 25 of them services.
  - The identifier grounding did not fix precision because it does not cover services, and the template-id normalisation fired 0 times.
  - Rejected planner choices went up: 15 across the 35 old requirements (10 before), and 12 on v2.
  - Explain batching worked: 1.00 call per requirement, mean latency 21.37 s (30.79 s before).
  - Mock stays the default.
- **[PC5B-FALLBACKS]** The 62 "fallback events" in the ollama report are not fallbacks to the mock. They are batched-explain replies that left out some tests, where a deterministic text was used. There were no truncation events and no JSON failures.
- **[PC6B-DOCS]** The final docs lead with the fresh v2 numbers. v1 results are labelled SEEN, in-sample results are labelled "tuned on", and all numbers come from report version 3.
- **[PC6B-STALE-TESTS]** Two tests asserted the old version 2 report layout and failed against the committed version 3 report. I updated them to the version 3 layout. They are not code regressions. One UI test that only applies to a version 2 report now skips.
- **[PC6B-BM25-DRIFT]** The BM25 retrieval numbers differ from Part B (test split hit@1 27.3% against 36.4%). A likely cause, not confirmed by an ablation: the behaviour contract in the `project` search collection grew from about 10,000 to 17,500 characters in Part C, with the same 24 sections, so each chunk is longer and BM25 rankings shift.

## Part D

### D1a (parse precision and constrained planner decoding, built with fake models only)

- **[PD-SVC-EVID]** For real-model backends, every parsed service needs evidence, or it is dropped and recorded. Evidence is any of:
  - a lexical hit, from a regex lexicon in `agent/service_lexicon.py` written only from protocol constants, the spec and general UDS vocabulary;
  - implied by a kept identifier plus an intent (a kept DID with a read intent implies 0x22, with a write intent 0x2E; a kept routine implies 0x31; a kept DTC implies 0x14 or 0x19 depending on the verb);
  - retrieval support from the `standard` collection **plus** a weak word of that service in the text. Retrieval alone never counts.

  The mock is exempt, as with the identifier check.
- **[PD-SESS-LVL]** Sessions must be named or implied in the text. Security levels are kept only when an unlock, security, seed or key word is present. 0x10 and 0x27 are never kept just because a session or level was parsed.
- **[PD-QUOTE]** The parse output can carry optional evidence quotes, as `evidence` entries keyed like `service:0x2E`.
  - A quote that is not found in the requirement text drops that item.
  - A valid quote is never sufficient evidence by itself.
  - The schema still has no byte or hex request fields.
- **[PD-ENUM]** On Ollama, planner choices are constrained by a per-call schema in which each choice is one string from an enum of exactly the offered `template_id#option_index` pairs, with a limit of 12.
  - The existing normalisation and validation stay as defence in depth, and the mock path is unchanged.
  - Whether Ollama's decoder honours the enum is untested: no real call was made in this step. D1b must smoke-test it.
- **[PD-RISK]** The evidence rules can drop a true service when the text uses a synonym outside the lexicon (for example "flip to diagnostics" for 0x10). The notes make every drop visible.
  - The lexicon may be extended during D1b dev tuning only, using the 8 dev rows and the seed requirements.
  - The agent built and tested it with its own made-up sentences and never opened any natural-requirements file.
- **[PD-MOCK-EQ]** Mock output on the 15 seed requirements is unchanged across 30 runs (two engines), recorded in `outputs/partD/mock_equivalence_D1a.json`. The "before" snapshot was taken from the working tree while another agent was editing, so I will re-check the final state.

### D2 (requirement-independent conformance sweep)

- **[PD2-SWEEP]** The conformance sweep is built only from the spec and the behaviour contract, with no bug catalog, no trigger lists and no simulator bug imports (a test checks this).
  - A case is a setup, then one stimulus, then a fixed probe set.
  - There are 54 setups, 215 stimuli and one probe set called `state_v1`.
  - Every expected byte comes from the rules engine. Keys use the seed actually observed on the wire, and a suppressed seed counts as unseen.
  - The probes read every DID, request every routine's results, request a seed per level, wait past S3 and read every DID again, then read DTCs.
- **[PD2-SELECT]** The full cross product is 11,610 candidates. Selection is a deterministic lazy-greedy cover, in four priority phases, capped at 1200 tests. Phase 1 (every stimulus and response class, and every setup and service pair) is fully covered, and the cap is reached during phase 2.
  - Phase 2 covered 1336 of 2038 transition items, so coverage is incomplete by design.
  - Generation takes 4.7 s. The bug matrices for all 53 seen bugs take 44.8 s.
- **[PD2-REGISTRY]** The sweep template is in a separate registry outside `TEMPLATES`, and provenance checks look in both. The planner and the mock are unchanged: the mock's 206 seed tests are identical in 206 of 206 cases (isolated worktree check, `outputs/partD/mock_equivalence_D2.json`).
- **[PD2-EVAL]** The eval is now report version 4. For each bug catalog it reports three rows: (a) requirement-driven tests, (b) the sweep alone, and (c) the full output, which is a per-bug union of the two. The sweep uses no LLM, so (b) is the same in every mode. A `--skip-conformance` flag exists for quick runs, and there is a hook for a v3 catalog.
- **[PD2-RESULT]** On the seen sets in mock mode (reported once, not tuned):
  - v2 (15 bugs): 2/15 requirement-driven, 9/15 for the sweep, 9/15 full output.
  - v1 (12 bugs): 10/12, 10/12, 12/12.
  - In-sample (26 bugs): 25/26, 26/26, 26/26.
  - Six v2 bugs are still missed, and no case was added for them.
  - These numbers are not evidence of improvement: the sets are seen. The sweep was designed without them, but v3 is the real test.
- **[PD2-FREEZE]** The Part C freeze table no longer matches, because D1a changed the agent and llm trees and the sweep adds a file under testgen. A Part D freeze table is needed.
- **[PD2-RUNTIME]** The full test suite now takes about 9.5 minutes, because the report fixture runs the sweep (about 55 s) and the conformance tests take about 40 s.

### D1b (dev-only tuning with the real model) and the robustness fixes

- **[PD-D1B-SELECT]** Revision 2 was selected by the pre-registered rule: parsed F1 + category recall + precondition recall on the 8 dev rows, with ties broken by fewer rejections.
  - Dev parsed precision / recall / F1 went from 0.583 / 0.824 / 0.683 (Part B, old code) to 0.929 / 0.765 / 0.839. Category recall is 0.682 and precondition recall 1.0.
  - Its lead over revision 5 (score 2.521 against 2.482) is within the run-to-run noise on 8 rows.
  - There were 0 planner rejections, 0 truncations and 0 JSON failures in every revision.
- **[PD-D1B-ENUM]** Ollama accepted the per-call enum schema with a limit of 12: no grammar errors, no JSON failures, and plan calls took about 6.5 s on average. The constrained plan calls returned only offered choices.
- **[PD-D1B-QUOTES]** The parse prompt no longer asks for evidence quotes. The 3B model copied instruction text into them, and the quote gate then dropped true services. The quote gate stays in code, but with no quotes supplied it has no effect.
- **[PD-D1B-GENERIC]** Generic words (`ecu`, `diagnostic`, `session`, `reset`) no longer count as a match between a DID name and the requirement text.
- **[PD-D1B-SEED]** On the 15 seed requirements, the untouched D1a code (revision 0) had 13 planner rejections, all "unknown template id". The model's evidence quotes dropped service 0x10, no service survived, the shortlist was empty, and the planner ran unconstrained. Revision 2 had 0 rejections.
- **[PD-FIX-EMPTY]** Fix (orchestrator): when nothing is on offer for a limited-context backend, the plan node now skips the model call instead of running unconstrained. This closes the path behind those 13 rejections.
- **[PD-FIX-HEX]** Fix (orchestrator): a parsed hex identifier is rewritten to the spec's spelling when its numeric value equals exactly one known identifier (`0x150` becomes `0x0150`, `0x2e` becomes `0x2E`). The value must be hex, and there is no nearest-match guessing. An unknown id is still dropped.
- **[PD-FIX-CHECK]** After the two fixes I re-ran the dev harness once as revision 6. It matches revision 2 (parsed F1 0.839, category recall 0.682, precondition recall 1.0, 0 rejections), so the fixes changed no dev outcome.
- **[PD-FIX-TEST]** `test_empty_shortlist_falls_back_to_the_unconstrained_schema` asserted the old behaviour. It is now `test_empty_shortlist_does_not_call_the_model`.

### D4 (fresh blind v3 sets, written after the Part D freeze)

Both agents were launched after the Part D freeze. Their exact prompts are recorded in PROGRESS.md.

- **[PD4-BUGS]** Held-out bugs v3: 15 new defects in `data/bugs/heldout_v3_catalog.yaml`, each tagged `heldout_v3: true`.
  - The agent could read the spec, the behaviour contract, protocol, simulator and the three existing catalogs. It could not read any generator, template, conformance module, prompt, eval code or report.
  - The ids, by category:
    - session: `session_switch_keeps_pending_seed`
    - security: `failed_key_keeps_pending_seed`, `lockout_expiry_resets_attempt_count`, `ecu_reset_resets_seed_counter`
    - NRC order: `nrc_order_subfunction_before_length`, `nrc_order_write_range_before_condition`
    - length and format: `routine_results_trailing_bytes_accepted`
    - DID and routine: `read_did_speed_not_clamped`, `write_stores_value_before_range_rejection`, `routine_stop_reports_completed_status`
    - DTC: `dtc_clear_single_clears_neighbour`, `dtc_read_reports_masked_status`
    - timing and state after S3 or reset: `session_response_p2_star_in_ms`, `s3_timeout_clears_dtc_status`, `suppressed_request_does_not_restart_s3`
  - Every bug is observable on the wire, and each has a unit test asserting the exact differing bytes.
  - DTC statuses cannot be changed over UDS, so the three DTC bugs (and the S3 one) are observed after setting statuses through the environment setter, in the same way as vehicle speed and the NVM fault. The S3 bug is only visible when a status is non-zero.
  - The agent dropped a candidate ("S3 timeout keeps the unlock") because every way of observing it goes through a 0x10 that clears that state anyway.
  - With all bugs off, behaviour is unchanged: the simulator and protocol tests pass (282).
- **[PD4-REQS]** Natural requirements v3: 16 requirements in `data/requirements_natural_v3.csv`, all `split=test3`.
  - The agent could read only the spec and the seed requirements. It could not read any natural set (v1 or v2) or any code.
  - Only 2 contain a hex id (NAT3-006 and NAT3-008).
  - The 2 ambiguous rows are NAT3-014 (which reset type, and what "clean" means) and NAT3-015 (which wiper setting, and which mode and unlock).
  - NAT3-016 asks for tyre pressure, which the spec does not define, so it has empty targets and the precondition `none`.
  - The agent wrote them in everyday engineering wording rather than the spec's field names.
- **[PD4-LABELS]** The labelling is not fully consistent about setup services. The agent reports that `target_services` lists every service a test must exercise, including setup steps such as 0x10 and 0x27 for a write requirement, but that some rows list only the main service. This adds some noise to service precision and recall on v3, and the interpretation will say so.
- **[PD4-CHECK]** After the agents finished I confirmed that the testgen, llm and agent trees, the prompts file and `data/gold` are unchanged, and that the test that scans the generator source and instantiated tests for bug ids passes with the new ids.

### D5a (evaluation extended for the v3 sets, built without the GPU)

- **[PD5-V3-HEADLINE]** The v3 bug headline is the system's full output: the requirement-driven tests for the 15 seed requirements plus the conformance sweep, as a per-bug union. This was pre-registered in PROGRESS.md before any v3 result. The requirement-driven only, sweep alone and gold numbers sit next to it in every table.
- **[PD5-TRIGGERS-V3]** The 15 trigger predicates (`uds_assistant/eval/heldout_v3.py`) were written from the bug descriptions and the behaviour contract before any v3 bug matrix was run, and none has been edited since.
- **[PD5-NOISE]** `--noise-runs N` now applies to natural v3 in ollama mode. Natural v1 and v2 keep a single run and are labelled SEEN. Mock runs once, plus a second run that must be identical.
- **[PD5-SEEN]** The v1 and v2 bug sets, the v1 and v2 natural sets, and the in-sample bugs are labelled SEEN or tuned-on everywhere in the report.
- **[PD5-BREAKDOWN]** False positives and false negatives by kind (service, DID, routine, DTC), and rejected planner choices by reason, come from one shared function over the per-requirement rows, so Part C and Part D numbers are comparable.
- **[PD5-BASELINE]** `outputs/partD/baseline_before_partD.json` is extracted from the Part C final report at commit 942f438. A test re-extracts it from git and checks equality.
- **[PD5-BEFOREAFTER]** `--before-after` now writes `outputs/partD/before_after.md` (the Part C mode is kept as `--part c`).
- **[PD5-LEAK]** Honest note on the blind v3 requirements: while checking the file format, the D5a agent ran a `head` command on `data/requirements_natural_v3.csv` and saw the text of NAT3-001 to NAT3-005. It had already written the predicates, changed nothing in response, and the code it could edit (eval only) cannot influence generation or parsing. The frozen code was not touched. I treat this as a minor deviation and it is stated in the final report.
- **[PD5-DRYRUN]** Mock-only dry run on the fresh v3 sets, reported before any model run (nothing may change in response):
  - v3 bugs: full output 10/15; requirement-driven 4/15; sweep alone 9/15; gold 3/15. The sweep has 1200 tests and the full output 1406.
  - Natural v3: parsed exact 1/16; parsed P/R/F1 0.857 / 0.267 / 0.407; exercised F1 0.342; category recall 0.42; precondition recall 0.483; 7 requirements produced nothing.
  - Five v3 bugs have no test that applies their stimulus: `session_switch_keeps_pending_seed`, `lockout_expiry_resets_attempt_count`, `nrc_order_subfunction_before_length`, `read_did_speed_not_clamped`, `dtc_read_reports_masked_status`.
- **[PD5-LABELS]** The UI and `scripts/demo.py` still label the v2 results as "fresh". That needs a label update in D6, because v2 is now seen.
- E1: explain fallback events are model omissions (valid JSON, fewer entries), not an id-matching, limit or schema bug; no code change, no re-run, because fixing it would be prompt tuning. Reason: decision rule fixes plain bugs only.
