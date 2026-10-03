# FINAL_REPORT.md

Honest status of the UDS Diagnostics & Automated Test Generation Assistant at
the end of Part A (which follows the Phase 9 wrap-up). Eval numbers are copied
exactly from `outputs/eval_report.md` / `.json`; test counts come from a fresh
`python -m pytest -q` run (Python 3.13.6, Windows, git repo at `tata_tech`);
none are estimated or rounded up.

**Headline:** on 12 held-out bugs (not seen when templates and gold tests were
written) the generated suite detects **3/12 (25.0%)**; gold 3/12 (25.0%);
union 5/12 (41.7%). The earlier 25/26 (96.2%) figure is in-sample (templates
tuned on those bugs) and is secondary. All LLM-dependent numbers are `mock`
mode; `ollama` is pending Part B.

## ✅ Done and tested

- Protocol core (`protocol/`): SIDs, NRC table, codec, seed/key security math,
  request builders — cross-checked against `udsoncan`'s own encoding.
- Synthetic BCM ECU spec (`data/bcm_spec.yaml`) + pydantic schema with
  cross-reference validation.
- Rules engine oracle (`rules/`), single NRC-evaluation-order function with a
  citation on every check (`udsoncan behaviour` or a `DECISIONS.md` tag).
- Independent ECU simulator (`simulator/`) — verified by AST check to never
  import `uds_assistant.rules` — with 26 in-sample + 12 held-out injectable bugs, in-process and
  virtual-CAN/ISO-TP transports.
- Simulator/rules-engine agreement property test
  (`tests/simulator/test_agreement.py`, hypothesis, 300 examples + deterministic
  walks): **passed**, no disagreement found. The eval also computes it live:
  5000/5000 (100.0%) requests agreed over 89 seeded walks.
- 60 hand-authored gold tests (`data/gold/gold_tests.yaml`), all passing on the
  bug-free simulator: `python -m pytest tests/testgen/test_gold.py` →
  **126 passed** (126 pytest cases cover the 60 gold tests, each run on the
  in-process simulator plus related structural checks).
- `udsoncan` client full request/response sequence over a virtual CAN / ISO-TP
  bus: `tests/simulator/test_transport.py::test_udsoncan_full_sequence` →
  **1 passed**.
- 23 test templates (`testgen/templates.py` + `templates_v2.py`; v1 14 + v2 9),
  frozen at testgen tree hash `9a121b2742c5f85fa48fd4f5340caf3b85979c67`; byte
  provenance re-checked against a fresh instantiation on every generated test.
- BM25 retrieval with citations (`rag/`), mock LLM (`llm/mock.py`), agent
  pipeline (LangGraph + plain-Python fallback, identical results by
  construction), runner, SQLite audit store, mock-mode evaluation
  (`eval/run_eval.py`), pytest/udsoncan and CAPL exporters, FastAPI service,
  Streamlit UI (headline table, held-out per-bug table, requirement-understanding
  results, held-out bugs in the bug picker) with headless AppTest runs.
- Full test suite: **834 passed, 2 skipped in 124.00s (0:02:04)**
  (`python -m pytest -q`). The 2 skips are `needs_model` tests, skipped by
  design, not deleted.
- `python -m ruff check .` → **All checks passed!**
- `outputs/eval_report.{json,md}` from `python -m uds_assistant.eval.run_eval
  --mode mock` (171 generated tests, see numbers below).

## ⚠️ Written but untested (needs model)

- `uds_assistant/llm/client.py` (`OllamaClient`) — real HTTP behaviour against
  a live Ollama server was never exercised; all tests drive it through
  `httpx.MockTransport` (monkeypatched request/response bodies), not a real
  model.
- `uds_assistant/rag/chroma.py` (`ChromaRetriever`, `BAAI/bge-small-en-v1.5`)
  — `chromadb` and `sentence-transformers` are not installed in this
  environment (`pip show` confirms both absent); the one test that
  instantiates it is marked `@pytest.mark.needs_model` and was skipped, both
  in the full run above and in a targeted `RUN_MODEL_TESTS` check that was not
  run this session (no model stack installed to run it against).
- Evaluation in `mode=ollama` — never run; `outputs/eval_report.md`'s `ollama`
  column reads "not run" for every metric. No mock-vs-ollama comparison exists
  yet.
- Streamlit UI "end to end" with a human — only a headless
  `streamlit run --server.headless` smoke test ran in CI
  (`tests/ui/test_streamlit_app.py::test_app_runs_headless_without_exceptions`);
  nobody has clicked through it interactively.
- `MODEL_SETUP.md` steps 1–6 (installing Ollama, pulling the model,
  installing `chromadb`/`sentence-transformers`, running `needs_model` tests,
  running the ollama eval, running the UI live) were written and
  cross-checked against the source but **not executed** this phase — doing so
  would require installing Ollama, downloading a ~2 GB model and pulling
  `torch`, all explicitly disallowed by `AGENT.md`/`SCOPE.md` for the offline
  build.

## ❌ Not done

- No comparison of mock-mode vs ollama-mode evaluation numbers (blocked on the
  above).
- CAPL exports are unverified templates — no CANoe license available, per
  `SCOPE.md` ("out of scope: verifying CAPL in CANoe").
- The 9 rules-engine vs AUTOSAR Dcm SWS disagreements (D1-D9,
  `docs/SWS_DISAGREEMENTS.md`) are documented, **not fixed** (see Part A
  changes).
- Ollama-mode evaluation numbers (every `ollama` cell reads "pending Part B").
- DoIP, OBD-II, flashing (0x34/0x36/0x37 download), 0x29 authentication,
  real ECUs/vehicles, cloud/paid LLMs, fine-tuning — all explicitly out of
  scope per `SCOPE.md` and not attempted.

## Test counts

Full suite: `python -m pytest -q` → **834 passed, 2 skipped in 124.00s (0:02:04)**.
`ruff check .` → clean. Per-directory collection counts
(`python -m pytest --collect-only -q tests/<dir>`):

| Directory | Tests |
|---|---|
| `tests/rules/` | 216 |
| `tests/testgen/` | 160 |
| `tests/simulator/` | 120 |
| `tests/protocol/` | 73 |
| `tests/agent/` | 64 |
| `tests/llm/` | 56 |
| `tests/rag/` | 50 |
| `tests/eval/` | 29 |
| `tests/api/` | 18 |
| `tests/spec/` | 14 |
| `tests/runner/` | 11 |
| `tests/ui/` | 8 |
| `tests/store/` | 7 |
| `tests/export/` | 6 |
| `tests/test_config.py` | 3 |
| `tests/scripts/` | 1 |
| **Total collected** | **836** |

(836 collected = passed + skipped, consistent with the full-suite run.)
AUTOSAR SWS tests skip without the local PDF; it was present on the machine
that produced these numbers.

## Evaluation numbers (mock mode)

From `outputs/eval_report.md` (mode `mock`, template set v2, 23 templates;
inputs: 15 seed requirements, 20 natural requirements, 60 gold tests, 12
held-out + 26 in-sample bugs). **Ollama mode: pending Part B / not run.**

### Headline table

| Metric | mock | ollama |
|---|---|---|
| 1. Simulator ↔ rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 2. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 3. udsoncan virtual-CAN sequence | PASS | same (LLM-independent) |
| **4. Held-out bug detection (12 bugs; HEADLINE = generated)** | **generated 3/12 (25.0%)** · gold 3/12 (25.0%) · union 5/12 (41.7%) | pending Part B |
| 5. Requirement understanding (natural requirements, test split n=12) | target exact match parsed 5/12 (F1 0.700), exercised 2/12 (F1 0.449); category recall 67.9% micro / 69.7% macro; precondition recall 80.0% micro / 75.0% macro; fallback/nothing 3/12 (2 excl. NAT-020-style empty-label rows) | pending Part B |
| 6. Coverage (seed requirements) | positive 36, negative 70, session 21, security 18, timing 26; 15/15 requirements with ≥1 test (100.0%) | pending Part B |
| 7. Citation validity | 774/774 (100.0%) | pending Part B |

### Held-out detail

- Generated 3/12 (25.0%), gold 3/12 (25.0%), union 5/12 (41.7%); invalid
  tests (fail on the clean simulator): generated 0, gold 0.
- Generated suite detected: `failed_attempts_reset_by_seed_request`,
  `s3_not_refreshed_by_tester_present`, `session_suppress_bit_not_masked`.
  Gold detected: `failed_attempts_reset_by_seed_request`,
  `seed_returned_while_unlocked`, `uint16_did_stored_byte_swapped`.
- For each of the 9 bugs the generated suite missed, the static trigger
  analysis (`uds_assistant/eval/heldout.py`) shows no generated test even
  applies the stimulus the bug needs (for example no test reads a DID outside
  its read sessions, none writes a uint16 DID and reads it back). That is a
  template-coverage gap, not a validation problem.
- Per-bug table with reasons: `outputs/eval_report.md` and the Streamlit UI.

### Requirement understanding

The test split (n=12) is the main number (row 5 above). Dev split (n=8):
parsed exact 4/8 (F1 0.828), exercised exact 0/8 (F1 0.492). All 20: parsed
exact 9/20 (45.0%), exercised exact 2/20 (10.0%). Exercised-target precision
is low (0.312 on test) because generated suites touch many unrelated
DIDs/services. Per-requirement table: `outputs/eval_report.md`.

### Secondary: in-sample bug detection (templates tuned on these)

- 26 bugs: generated **25/26 (96.2%)**, gold 24/26 (92.3%), union 26/26
  (100.0%). Optimistic and non-independent (see Known limitations).
- Baseline (template set v1, 14 templates): generated 17/26 (65.4%); rose to
  25/26 after the 9 v2 templates were added in Phase 7.
- 171 generated tests (94 unique template instantiations); 171/171 (100.0%)
  pass on the clean simulator.
- Request validity: 445/445 (100.0%, after exempting 41 intentional
  format-NRC probes; unadjusted 404/445 = 90.8%).
- Template reuse: 171/171 (100.0%) (true by construction).

### Appendix: self-consistency (circular by construction)

Expected-response accuracy vs the oracle: 445/445 (100.0%) steps; vs gold
(exact overlap) 25/25; vs gold (shared prefix) 18/18. The expected bytes are
produced by the oracle itself, so this is not an independent accuracy measure
and is no longer a headline metric.

## Part A changes

Part A (A1-A6) was done after the Phase 9 wrap-up to make the evaluation less
circular. Templates and gold tests were not changed after the held-out results
were seen (testgen tree hash `9a121b2742c5f85fa48fd4f5340caf3b85979c67`).

- **A1: held-out bugs.** 12 new simulator bugs
  (`data/bugs/heldout_catalog.yaml`, `HELDOUT_BUG_IDS`) written by a subagent
  restricted from reading testgen, gold, eval, llm and agent code. Result:
  generated 3/12.
- **A2: natural requirements + understanding metric.** 20 labelled
  requirements (`data/requirements_natural.csv`; 8 dev / 12 test; 3
  deliberately ambiguous, 1 unsupported by the spec, 5 with literal hex IDs)
  written under similar restrictions. New metric (`eval/understanding.py`):
  target identification (parsed and exercised), category recall, precondition
  recall, fallback.
- **A3: metrics cleanup.** The headline is now a 7-row table. The oracle
  self-consistency number moved to an appendix (circular); simulator↔rules
  agreement and the udsoncan virtual-CAN sequence are computed live in the eval
  (`--skip-can` skips the latter, for fast runs); in-sample numbers are
  labelled.
- **A4: SWS citations + disagreements.** The rules engine now cites 38
  distinct AUTOSAR CP R24-11 Dcm SWS IDs. Nine differences from the SWS
  (D1-D9) are documented in `docs/SWS_DISAGREEMENTS.md` and **deliberately not
  fixed**: changing the oracle would require coordinated changes to the
  independent simulator, `docs/behaviour_contract.md`, and the frozen gold and
  template data. D2, D5, D6 and D7 are the ones to fix first. The AUTOSAR PDF
  is git-ignored (AUTOSAR terms do not allow redistribution); the owner keeps a
  local copy and the SWS tests skip without it.
- **A5: docs pack.** `docs/CODE_TOUR.md`, `docs/ARCHITECTURE.md`,
  `docs/RESULTS.md`, `docs/DEMO_SCRIPT.md`, `docs/SWS_DISAGREEMENTS.md`,
  `docs/RECONCILIATION.md`, plus `scripts/demo.py`.
- **A6: PROJECT.md, UI, this report.** PROJECT.md has a Status section and the
  new metrics; the Streamlit UI shows the headline table, the held-out
  evaluation, the requirement-understanding results, and offers held-out bugs
  in the bug picker.
- **Reconciliation result:** the owner's brief mentions an older 18-file doc
  set; none was found (`docs/RECONCILIATION.md`), so nothing was ported.

## Deviations from docs

- Python 3.13.6 used instead of the originally documented 3.11 (PROJECT.md now says 3.13) (only interpreter
  available); code kept 3.11-syntax-compatible.
- `docs/`, `data/bcm_spec.yaml`, `data/requirements_seed.csv` did not exist at
  project start and were authored from scratch, matching `PROJECT.md`/
  `SCOPE.md` intent (synthetic spec, no real OEM data).
- Template count is **23** (v1 14 + v2 9), not the 8–12 originally in
  `PROJECT.md` §4 (`DECISIONS.md [EVAL-TPL-V2]`); PROJECT.md now reflects 23.
  The registry-size test bound was raised from 20 to 30.
- Review endpoint is `POST /tests/{run_id}/{test_id}/review`, not
  `/tests/{id}/review`, because `AuditStore.set_review_status` needs the run
  id to locate the row (`DECISIONS.md [API-REVIEW-PATH]`).
- CAN-mode pytest export (`UDS_EXPORT_TRANSPORT=can`) skips tests containing
  an `advance_time` step, because that transport uses the wall clock and
  really sleeping through S3/lockout delays would cost >10 s per test
  (`DECISIONS.md [EXP-PYTEST]`).
- `udsoncan`'s `use_server_timing` is disabled in the virtual-CAN test because
  the spec's 50 ms P2 is too tight for Windows thread scheduling
  (`DECISIONS.md [S-CAN]`); P2/P2* timing is otherwise checked only
  in-process, where wall-clock timing reflects scheduler/GC noise rather than
  ECU logic (`DECISIONS.md [RUN-TIMING]`) — see Known limitations.
- `streamlit` was installed (1.64.0) despite being in the "install only if pip
  is responsive" bucket of `SCOPE.md`; it succeeded on the first (non-retried)
  attempt (`DECISIONS.md [UI-STREAMLIT-INSTALL]`).

## Known limitations

- **The in-sample generated-suite bug-detection rate (25/26, 96.2%) is
  optimistic and not independent.** The 9 v2 templates were added in Phase 7
  specifically after inspecting which bugs the v1 templates (17/26, 65.4%)
  missed, and the same author wrote both the bug catalog and the templates.
  The held-out result (generated 3/12, 25.0%) is the honest number and shows
  the in-sample figure overstated generalisation. Gold is no better on
  held-out (3/12); the union is 5/12 (41.7%). The held-out set is small (12),
  so the rate is coarse, and it has now been seen once: further template work
  against it would make it in-sample too.
- **Requirement understanding is weak in mock mode** (test split: parsed
  exact 5/12, exercised exact 2/12). The mock LLM is a keyword stand-in, so
  this says nothing yet about the real model (pending Part B).
- **The rules-engine-vs-oracle "expected-response accuracy" metric (445/445,
  100%) is circular by construction**: expected bytes for every generated
  test are produced by the oracle itself, so re-running the oracle and
  diffing against its own earlier output can only ever agree. The
  meaningful, independent checks are: (a) simulator↔oracle byte-for-byte
  agreement on randomized sequences (`tests/simulator/test_agreement.py`,
  which found zero disagreements), (b) all 60 gold tests passing against the
  independently-run simulator, and (c) the `udsoncan` client completing a
  real protocol exchange over a virtual CAN bus
  (`test_udsoncan_full_sequence`). These three are the actual correctness
  evidence; the oracle self-consistency number is not.
- SWS traceability is partial: 38 SWS IDs are cited, but 9 documented
  disagreements (D1-D9) remain unfixed, so the oracle is not SWS-conformant in
  those cases. Checks with no SWS coverage cite "udsoncan behaviour" or a
  `DECISIONS.md` tag. The SWS PDF is not in the repo.
- The ECU spec is entirely synthetic; none of the numbers in this report say
  anything about a real vehicle ECU.
- CAPL export output is an unverified template — never compiled or run in
  CANoe (no license available).
- P2/P2* timing checks for the in-process transport are based on wall-clock
  measurement on a general-purpose desktop OS and are reported as
  `timing_warning`s rather than hard failures for anything but an explicit
  per-step `max_response_time_ms`, because scheduler/GC jitter can trigger
  false positives (`DECISIONS.md [RUN-TIMING]`). CAN-mode timing is not tested
  at all for time-advance-dependent behaviour (S3/lockout) — those tests are
  skipped in that transport.
- Ollama and ChromaDB code paths (`llm/client.py`, `rag/chroma.py`) have never
  been run against a real server or real embeddings — only
  monkeypatched/mocked. Correctness there rests on code review and the
  documented contract (JSON schema round-trip, `/api/tags` probe, lazy
  imports), not on execution evidence.
- Template count (23) exceeds the original PROJECT.md target (8–12); this makes
  template reuse look strong (171/171 = 100% by construction, since reuse is
  defined as "byte-identical to a fresh instantiation") but says nothing about
  whether 23 templates is the right design size.

## Next steps

**Part B**

1. Ollama evaluation: follow `MODEL_SETUP.md` in order (install Ollama, pull
   the 3B model, run `RUN_MODEL_TESTS=1 python -m pytest -m needs_model -v`),
   then `python -m uds_assistant.eval.run_eval --mode ollama --out
   outputs/ollama` and fill the `ollama` column of the headline table; report
   both, including any fallback-to-mock warnings verbatim.
2. Template improvements informed by the held-out misses (9 missed bugs, each
   with a stated missing stimulus) only with a NEW held-out bug set that nobody
   has seen; the current 12 are in-sample for any such change.
3. Fix the SWS disagreements D2, D5, D6 and D7 (`docs/SWS_DISAGREEMENTS.md`),
   coordinated across `rules/`, `simulator/`, `docs/behaviour_contract.md` and
   the gold tests, then re-run agreement and the full eval.

**Other**

4. Install `chromadb`/`sentence-transformers`, pre-download
   `BAAI/bge-small-en-v1.5`, and run the `needs_model` Chroma retrieval test.
5. Click through the Streamlit UI interactively end to end (generate → review
   → run → export) with a human watching, beyond the headless AppTest runs.
6. Justify or trim the 23-template design size against the original 8–12
   target.
