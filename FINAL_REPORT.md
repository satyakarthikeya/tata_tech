# FINAL_REPORT.md

Honest status of the UDS Diagnostics & Automated Test Generation Assistant at
the end of Part E (results consistency, cited Q&A, confidence indicators, OEM
retrieval layer, Docker files, tabbed UI, compliance matrix), which follows
Part D (conformance sweep, service grounding, constrained planner, fresh v3
blind evaluation), Part C (fixes and a fresh v2 evaluation), Part B
(real-model evaluation), Part A (honest evaluation) and the Phase 9 wrap-up. Eval numbers are copied exactly from
`outputs/eval_report.md` / `.json` (report version 5), `outputs/partD/before_after.md`,
`outputs/partD/interpretation.md` and `PROGRESS.md`; test counts come from a
fresh `python -m pytest -q` run (Python 3.13.6, Windows, git repo at
`tata_tech`); none are estimated or rounded up.

**Run labels.** Unless a heading or bullet names another run, every evaluation number in this report is from the **Main eval run: 2026-10-04, git `1f0c293`** (recorded with uncommitted phase files; generator bytes verified unchanged since, DECISIONS E32/E33). The diagnostic Q&A run (2026-10-04, git `9e66f7a`) and the tool-side timing run (2026-10-04, git `8357ec0`) are reported in `docs/RESULTS.md`, `outputs/eval_report.md` and the "Part E changes" section below. Earlier-run tables (Part C and Part D before/after) are under **History** at the end and are historical. `docs/RESULTS.md` is the one-page summary; this report must not contradict it.

**Headline (fresh v3 data: written blind after the Part D freeze, nothing tuned
on it; Main eval run 2026-10-04, git `1f0c293`).**

- **Correctness (LLM-independent):** the simulator and the rules engine agree on
  5000/5000 seeded random requests, all 60 gold tests pass on the bug-free
  simulator, and a udsoncan client completes a session/seed-key/read/write
  sequence over a virtual CAN bus (one happy path). The sweep's 1200 tests also
  all pass on the clean simulator. These share one author and one contract.
- **Held-out v3 bug detection by the system's full output (requirement-driven
  tests plus the conformance sweep) is 10/15 (66.7%) with mock and 9/15
  (60.0%) with ollama.** Almost all of it comes from the sweep: the
  requirement-driven tests alone catch 4/15 (mock) and 2/15 (ollama), the
  sweep alone 9/15 in both modes, gold 3/15. Part C's 2/15 was on a different
  bug set, so it is a reference point, not a before/after pair. The sweep also
  caught 9/15 on the seen v2 bugs. Five bugs are missed in both modes; in each
  case no test applies the stimulus (ollama also misses a sixth).
- **Requirement understanding on natural v3 (n=16) is better with the model
  than with the mock**: parsed F1 0.609 vs 0.407, category recall 70.0% vs
  42.0%, precondition recall 89.7% vs 48.3% (ollama; parsed, category and
  precondition numbers identical in all three runs). But ollama's precision is
  0.596 with 19 false positives (15 services, 4 DIDs); the mock's precision is
  0.857 but its recall is 0.267.
- **Rejected planner choices fell to 0** on every set (15 on the old 35
  requirements and 12 on v2 in Part C), and 0 truncation events. The likely
  cause is the constrained planner schema; no ablation was run.
- **Service precision is reduced on seen sets, not shown to be solved.** v2
  false positives went from 30 to 9 and the v1 test split from 21 to 9, but the
  grounding was designed after reading those errors. On fresh v3 precision is
  0.596 (0.565 on v2 in Part C, a different set), and recall is 0.622 (0.796 on
  v2).
- v1 and v2 results (held-out v1 full output mock 12/12, ollama 11/12; v2 full
  output 9/15 in both modes) are **SEEN**, and the 26-bug in-sample numbers
  (26/26 in both modes) are **tuned on**; none is evidence.
- **Diagnostic Q&A (Part E; 25 blind questions, 21 answerable and 4
  unanswerable; Q&A run 2026-10-04, git `9e66f7a`):** answer accuracy 90.5%
  (19/21) in both mock and ollama, citation correctness 95.2% (20/21) mock and
  90.5% (19/21) ollama, correct not-found 3/4 in both. Misses: QA-018 (answered
  instead of refusing), QA-022 and QA-023 (retrieval misses). Twenty-five
  questions is a small sample: one question is 4 to 5 points.
- **UI (Part E):** five tabs (Ask, Generate & Review, Run on Simulator,
  Export, Results) with headless AppTest coverage; never clicked through in a
  real browser. The natural door-lock requirement did not yield the intended
  test pair (see Known limitations).
- **Status of the remaining Part E items:** Docker files are **written, not
  built here**; the manual-vs-tool test-design-time comparison is **pending
  owner measurement** (tool side only: mock mean 0.217 s, ollama mean 19.36 s
  per requirement, timing run `8357ec0`).
- **The mock stays the default.**

## ✅ Done and tested

- Protocol core (`protocol/`): SIDs, NRC table, codec, seed/key security math,
  request builders — cross-checked against `udsoncan`'s own encoding (including
  the suppress-positive cases for 0x19 and 0x27 added in Part C).
- Synthetic BCM ECU spec (`data/bcm_spec.yaml`) + pydantic schema with
  cross-reference validation.
- Rules engine oracle (`rules/`), single NRC-evaluation-order function with a
  citation on every check (`udsoncan behaviour` or a `DECISIONS.md` tag).
- Independent ECU simulator (`simulator/`) — verified by AST check to never
  import `uds_assistant.rules` — with 26 in-sample + 12 held-out v1 + 15
  held-out v2 + 15 held-out v3 injectable bugs (68 in all), in-process and virtual-CAN/ISO-TP transports.
- Simulator/rules-engine agreement: **5000/5000 (100.0%)** requests over 89
  seeded walks in the eval (seed 20261003), plus 100% on two seeds with more
  than 13,000 requests each after the Part C fixes (13,487 and 13,556), plus
  the hypothesis property test.
- 60 hand-authored gold tests (`data/gold/gold_tests.yaml`), all passing on the
  bug-free simulator (60/60). One was updated by hand in Part C
  (`gold_multi_did_read_one_bad`).
- `udsoncan` client full request/response sequence over a virtual CAN / ISO-TP
  bus (PASS in the eval too).
- 27 test templates (template set `v3`: v1 14 + v2 9 + 4 new in Part C),
  templates frozen at the Part C freeze (testgen tree `a4b6491fc2d01421c4cff10143aabd3c75017df1`; the Part D
  freeze, which adds the sweep, is in "Part D changes"); byte
  provenance re-checked against a fresh instantiation on every generated test
  (Part D run: 613/613 mock, 552/552 ollama, 1200/1200 sweep, including all noise runs).
- BM25 retrieval with citations (`rag/`), mock LLM (`llm/mock.py`), agent
  pipeline (LangGraph + plain-Python fallback, identical results by
  construction), runner, SQLite audit store, pytest/udsoncan and CAPL
  exporters, FastAPI service.
- **Ollama run on the real model (execution evidence).** `OllamaClient` ran
  against Ollama 0.35.1 with `qwen2.5:3b-instruct-q4_K_M`: the Part B smoke and
  full runs, and the Part C run
  (`python -m uds_assistant.eval.run_eval --mode ollama --noise-runs 3
  --before-after`, about 31 minutes: total 1854.37 s, ollama 1782.2 s, mock
  45.7 s; log `outputs/partC/eval_run.log`). All 83 pipeline runs completed (35
  seed + natural v1 requirements, 16 natural v2 requirements, 2 extra noise
  runs of 16), no truncation events, no JSON failures.
- **Conformance sweep** (`testgen/conformance.py`, Part D): 1200
  requirement-independent tests (54 state setups x 215 stimuli, greedy covering
  from 11,610 candidates) with every expected byte from the rules engine; all
  1200 pass on the clean simulator and re-instantiate byte-identically; about 7 s
  to generate, 85 s for the bug matrix over all four catalogs. Not offered to the
  planner.
- **Part D parse and planner changes:** every parsed service needs evidence
  (a domain keyword in the text, an implied link from a kept identifier, or
  support from retrieved spec text); the planner schema is constrained to the
  offered template/option choices; the planner is skipped when nothing is
  offered; hex ids are padded to the spec's spelling.
- **Part D real-model run** (`python -m uds_assistant.eval.run_eval --mode ollama
  --noise-runs 3 --before-after`, about 39 minutes: total 2327.6 s, ollama
  2125.8 s, sweep 100.9 s, mock 73.0 s; log `outputs/partD/eval_run.log`). 0
  truncation events, 0 fallbacks to the mock; 123 fallback events, all the
  batched explain step omitting some test ids.
- **Chroma + embeddings backend.** `rag/chroma.py` with fastembed
  (`BAAI/bge-small-en-v1.5`, ONNX on CPU) ran for real; the BM25-vs-Chroma
  retrieval comparison is in the report (19 queries; no clear winner; default
  stays BM25).
- **Batched explain on the real model.** 1.00 LLM call per requirement (min 1,
  max 1) against 4.51 before; mean latency per requirement 21.37 s against
  30.79 s. Fallback events: 62 in the ollama report; none were fallbacks to
  the mock model; the inspected ones were the batched explain noticing that
  the reply left out some tests and substituting a short deterministic
  explanation.
- **Grounding on the real model.** In Part C it covered DIDs, routines and DTCs
  only; Part D added service evidence checks. Measured effect: on the seen sets
  ollama's parsed false positives fell (v2 30 to 9, v1 test split 21 to 9); on
  fresh v3 there are still 19 (15 services, 4 DIDs).
- **Ollama noise check.** Three ollama runs on natural v3 (and v2 in Part C), every run listed in
  the report with mean and range; mock re-run identical.
- **Mock vs ollama evaluation** in one report (version 5): fresh v3 headline,
  seen/tuned-on rows labelled, sweep rows, noise check, before/after table
  (`outputs/partD/before_after.md`), freeze verification, interpretation
  (`outputs/partD/interpretation.md`).
- **Streamlit UI, headless (rebuilt in Part E, E4).** Five tabs plus a sidebar
  (Ask, Generate & Review, Run on Simulator, Export, Results); the Results tab
  shows six headline cards from `outputs/eval_report.json`, each with its run
  date and git hash, and the detail tables in collapsed expanders. Covered by
  headless `streamlit.testing.v1.AppTest` runs per tab plus one `needs_model`
  test (natural requirement in ollama mode, then a v3 bug caught). This is not a
  human click-through (see "Written but not fully exercised").
- **Cited diagnostic Q&A (Part E, E3.1).** `qa/` and `POST /ask`; blind
  evaluation numbers are in the headline above and `docs/RESULTS.md`.
- **Confidence indicators (Part E, E3.2).** `agent/confidence.py`; every
  generated test and Q&A answer carries `confidence` and `confidence_reason`;
  each rule has a unit test.
- **Four retrieval layers (Part E, E3.3).** standard / OEM / ECU / project as
  separate collections with layer-tagged citations; the generator uses only the
  core layers, so generated bytes are unchanged.
- **Demo script.** `scripts/demo.py` was not updated after Part C: it still
  prints the v2 rows as "FRESH" and does not show v3, the sweep or Q&A (v2 is
  seen since Part D). `docs/DEMO_SCRIPT.md` was updated for the tabbed UI and
  the 7-minute demo path; the script itself was left alone (no new features
  in Part E5).
- Four SWS disagreements fixed (D2, D5, D6, D7), verified by the independent
  simulator agreeing on 100% of requests (see Part C changes).
- Test suite and lint: see "Test counts" below.

## ⚠️ Written but not fully exercised

- **Docker: written, not built here.** `Dockerfile`, `docker-compose.yml`,
  `.dockerignore`, `docker/entrypoint.sh` and `docs/DOCKER.md` were never built
  or run (limited network); nothing was pulled. The image does not copy the
  committed `outputs/` reports, so the Results tab shows "no report" in a fresh
  container until `run_eval` is run there.
- **`scripts/demo.py` is stale** (Part C headline layout; see above).
- **Streamlit UI in a real browser.** Only headless AppTest runs exist.
  Nobody has clicked through generate → review → run → export interactively.
  `docs/UI_CHECKLIST.md` (10 steps) is the manual procedure and has not been
  done by a human.
- **The human-review button in a live browser.** Marking a test
  `human_reviewed` in the UI is covered headlessly only. The UI's generate
  button was also not run live with `LLM_MODE=ollama` or `RETRIEVER=chroma`.
- **Chroma retrieval inside the generation pipeline.** The retrieval
  comparison measured Chroma against BM25 as a retriever. The mock-vs-ollama
  evaluation used BM25 for both modes; no end-to-end test-generation run used
  `RETRIEVER=chroma`, so its effect on generated tests was not measured.
- **`EMBEDDER=sentence-transformers`.** Implemented as an optional path;
  `sentence-transformers` and `torch` are not installed, so it was never run.
- **Only one model.** The ollama result is for `qwen2.5:3b-instruct-q4_K_M`
  on a 4 GB laptop GPU, with prompts tuned on 8 dev rows. The assistant was
  never run with a larger model or a larger context.
- **Noise.** Three ollama runs on natural v2 is a small sample; the parsed
  numbers were identical across them, but the earlier ±0.05 F1 seen on the dev
  split in Part B did not reproduce here, and the GPU is not guaranteed to
  repeat exactly.
- **No real ECU** was ever used; everything runs against the project's own
  simulator.
- **`MODEL_SETUP.md`** Windows installer steps in section 1 were not
  re-executed after B0; the owner's machine already had Ollama installed.
- CAPL exports (see Not done).

## ❌ Not done

- CAPL exports are unverified templates — no CANoe license available, per
  `SCOPE.md` ("out of scope: verifying CAPL in CANoe").
- SWS disagreements **D1, D3, D4, D8 and D9** remain documented and **not fixed**
  (`docs/SWS_DISAGREEMENTS.md`); D2, D5, D6 and D7 were fixed in Part C.
- No larger model than the 3B was tried.
- Parsed precision on fresh phrasing is not solved: 0.596 on v3 with 19 false
  positives (15 services). The service grounding helped on seen sets only.
- The sweep and the requirement-driven tests do not apply the stimuli behind 5
  of the 15 fresh v3 bugs (6 with ollama). Templates or sweep cases built
  against that list would make v3 seen; a v4 blind set would be needed.
- **Test design time: manual comparison pending owner measurement.** The protocol is
  `docs/TEST_DESIGN_TIME.md` and the results table is blank; only tool-side
  wall time exists.
- **Q&A misses left as they are:** QA-018, QA-022, QA-023 (no re-run, no tuning
  against the questions).
- DoIP, OBD-II, flashing (0x34/0x36/0x37 download), 0x29 authentication,
  real ECUs/vehicles, cloud/paid LLMs, fine-tuning — all explicitly out of
  scope per `SCOPE.md` and not attempted.

## Test counts

_Run: Part E final wrap-up (E5), 2026-10-04, on the tree at the E5 commit's parent (`52fdacc`) plus documentation edits only; no code changed in E5._

Full suite (default, model tests skipped): `python -m pytest -q` -> **1479 passed, 16 skipped in 787.51s (0:13:07)**. No failures (the known export flake did not occur). The 16 skips are the 15 `needs_model` tests plus 1 UI test that only applies to an older report version; 1495 tests are collected.
`RUN_MODEL_TESTS=1 python -m pytest -m needs_model -q` (Ollama reachable at `localhost:11434`, `qwen2.5:3b-instruct-q4_K_M`) -> **15 passed, 1480 deselected in 179.44s (0:02:59)**.
`python -m ruff check .` -> **All checks passed!**

Earlier Part D run for reference (historical): 1331 passed, 14 skipped, 1 failed in 888.33 s; the failure was the known `tests/export/test_export.py::test_gold_export_runs_and_passes` temp-file flake of the editor host (re-run alone: 6 passed).

The skips are `needs_model` tests plus tests that only apply to an older report version, skipped by design, not deleted. AUTOSAR SWS tests skip without the local PDF; it was present on the machine that produced these numbers.

Per-directory collection counts (`python -m pytest --collect-only -q`, 1495 collected):

| Directory | Tests |
|---|---|
| `tests/rules/` | 276 |
| `tests/agent/` | 266 |
| `tests/simulator/` | 204 |
| `tests/testgen/` | 201 |
| `tests/eval/` | 152 |
| `tests/llm/` | 83 |
| `tests/rag/` | 78 |
| `tests/protocol/` | 78 |
| `tests/ui/` | 58 |
| `tests/qa/` | 29 |
| `tests/api/` | 19 |
| `tests/spec/` | 14 |
| `tests/runner/` | 11 |
| `tests/scripts/` | 10 |
| `tests/store/` | 7 |
| `tests/export/` | 6 |
| `tests/test_config.py` | 3 |
| **Total collected** | **1495** |

## Evaluation numbers (mock and ollama)

From `outputs/eval_report.md` (generated 2026-10-04T08:15:23Z, git `1f0c293`,
report version 5, template set `v3`, 27 templates plus the conformance sweep,
Bm25Retriever, LangGraph engine; ollama = `qwen2.5:3b-instruct-q4_K_M`, num_ctx
4096, temperature 0, keep_alive 10m). Both columns come from one invocation on
the same inputs. The one-page summary (with the Q&A, timing and success-metric tables, each with its own run) is `docs/RESULTS.md`; the before/after table is under History at the end of this report.

### Headline table (Main eval run 2026-10-04, git `1f0c293`)

| Metric | mock | ollama |
|---|---|---|
| **1. Held-out v3 bugs, FRESH (15): FULL OUTPUT = requirement-driven + sweep** | **10/15 (66.7%)** | **9/15 (60.0%)** |
| 1a. requirement-driven only (the Part C "generated" suite) | 4/15 (26.7%) | 2/15 (13.3%) |
| 1b. conformance sweep alone (LLM-independent) | 9/15 (60.0%) | 9/15 (60.0%) |
| 1c. gold (LLM-independent) | 3/15 (20.0%) | 3/15 (20.0%) |
| Suite sizes (requirement-driven / sweep / full output) | 206 / 1200 / 1406 | 73 / 1200 / 1273 |
| **2. Natural v3, FRESH (test3, n=16)** | parsed exact 1/16, P/R/F1 0.857/0.267/0.407; exercised F1 0.342; category recall 42.0% micro; precondition recall 48.3% micro; fallback/nothing 7/16 | parsed exact 2/16, P/R/F1 0.596/0.622/0.609; exercised F1 0.472; category recall 70.0% micro; precondition recall 89.7% micro; fallback/nothing 0/16 |
| 2a. Natural v3: parsed FP / FN by kind | FP service 2; FN service 24, did 8, routine 1 | FP service 15, did 4; FN service 9, did 5, routine 3 |
| 2b. Natural v3: rejected planner choices | 0 | 0 |
| 3. Simulator <-> rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 4. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 5. udsoncan virtual-CAN sequence | PASS | same (LLM-independent) |
| 6. Conformance sweep: pass on the clean simulator; byte provenance | 1200/1200; 1200/1200 | same (LLM-independent) |
| 7. Coverage (seed requirements) | positive 43, negative 77, session 25, security 30, timing 31; 15/15 requirements with >=1 test | positive 26, negative 27, session 4, security 7, timing 9; 15/15 |
| 8. Citation validity | 967/967 (100.0%) | 353/353 (100.0%) |
| Byte provenance, all generated tests, all runs | 613/613 | 552/552 |
| **SEEN** Held-out v2 bugs (15): req-driven / sweep / full / gold | 2 / 9 / 9 / 5 | 2 / 9 / 9 / 5 |
| **SEEN** Natural v2 (n=16): parsed exact; P/R/F1 | 0/16; 1.000/0.225/0.367 | 4/16; 0.808/0.775/0.792 |
| **SEEN** Held-out v1 bugs (12): req-driven / sweep / full / gold | 10 / 10 / 12 / 3 | 8 / 10 / 11 / 3 |
| **SEEN** Natural v1 test split (n=12): parsed exact; P/R/F1 | 5/12; 0.933/0.560/0.700 | 5/12; 0.690/0.800/0.741 |
| **In-sample (tuned on)** 26 bugs: req-driven / sweep / full / gold | 25 / 26 / 26 / 24 | 21 / 26 / 26 / 24 |

### Noise check (natural v3, ollama, 3 runs; mean and min-max; Main eval run 2026-10-04, git `1f0c293`)

| Metric | run 1 | mean (min-max) |
|---|---|---|
| Parsed P / R / F1 | 0.596 / 0.622 / 0.609 | identical in all three runs |
| Exercised F1 | 0.472 | 0.465 (0.462-0.472) |
| Category recall (micro) | 70.0% | 70.0% (70.0%-70.0%) |
| Precondition recall (micro) | 89.7% | 89.7% (89.7%-89.7%) |
| Rejected choices | 0 | 0 |
| Fallback events | 44 | 37.7 (33-44) |

The mock is deterministic; a second mock run was identical.

The Part D before/after table is **historical** and lives under **History** at the end of this report.

### Held-out v3 detail (Main eval run 2026-10-04, git `1f0c293`)

- **Missed by the full output (5 with mock, 6 with ollama).** No test applies
  the stimulus: `session_switch_keeps_pending_seed`,
  `lockout_expiry_resets_attempt_count`, `nrc_order_subfunction_before_length`,
  `read_did_speed_not_clamped`, `dtc_read_reports_masked_status`; ollama also
  misses `dtc_clear_single_clears_neighbour` (the mock's larger
  requirement-driven suite catches it, the sweep does not).
- **Found only by the sweep:** 6 bugs with mock, 7 with ollama (for example
  `failed_key_keeps_pending_seed`, `nrc_order_write_range_before_condition`,
  `write_stores_value_before_range_rejection`, `s3_timeout_clears_dtc_status`).
- Invalid generated tests: 0 in every suite.

### Interpretation (condensed from `outputs/partD/interpretation.md`; Main eval run 2026-10-04, git `1f0c293`)

- **Better:** fresh bug detection (full output 9-10/15 against 2/15 in Part C on
  a different set), almost entirely from the sweep; rejected planner choices
  (0 against 15 and 12); requirement understanding with the model over the mock
  (recall 0.622 vs 0.267, category recall 70.0% vs 42.0%, precondition recall
  89.7% vs 48.3%).
- **Unchanged or not shown to be better:** the model's contribution to
  detection (requirement-driven 2/15 ollama, 4/15 mock); precision on fresh
  phrasing (0.596; 15 service false positives, mostly `0x10` and `0x27`);
  recall (0.622, lower than the 0.796 on v2).
- **Not evidence:** every v1, v2 and in-sample number (seen or tuned on),
  including the v2 precision gain (0.565 to 0.808) and v2 full output (2/15 to 9/15).
- **Provenance:** 613/613 mock, 552/552 ollama, 1200/1200 sweep; every Part D
  freeze hash matches and is clean.

### Retrieval: BM25 vs Chroma (19 of 20 natural requirements scored; Main eval run 2026-10-04, git `1f0c293`)

Re-run in this evaluation; the numbers are identical to Part C's.

| split | backend | queries | hit@1 | hit@3 | MRR |
|---|---|---|---|---|---|
| dev | bm25 | 8 | 0.0% | 37.5% | 0.275 |
| dev | chroma | 8 | 0.0% | 75.0% | 0.374 |
| **test** | **bm25** | 11 | 27.3% | 63.6% | 0.506 |
| **test** | **chroma** | 11 | 18.2% | 63.6% | 0.458 |
| all | bm25 | 19 | 15.8% | 52.6% | 0.408 |
| all | chroma | 19 | 10.5% | 68.4% | 0.422 |

Citation validity over the top 3 hits is 100.0% for both. Neither backend is
clearly better; the default stays BM25.

### Appendix: self-consistency (circular by construction; Main eval run 2026-10-04, git `1f0c293`)

Expected-response accuracy vs the oracle is 100% by construction: the expected
bytes are produced by the oracle itself, so this is not an independent accuracy
measure and is not a headline metric.

## Part A changes

_Historical: figures here come from the Part A runs (see `PROGRESS.md` for each run's hash), not from the Main eval._

Part A (A1-A6) was done after the Phase 9 wrap-up to make the evaluation less
circular. Templates and gold tests were not changed after the held-out results
were seen (testgen tree hash `9a121b2742c5f85fa48fd4f5340caf3b85979c67` at the
time).

- **A1: held-out bugs.** 12 new simulator bugs
  (`data/bugs/heldout_catalog.yaml`, `HELDOUT_BUG_IDS`) written by a subagent
  restricted from reading testgen, gold, eval, llm and agent code. Result at
  the time: generated 3/12. (These are now "seen": see Part C.)
- **A2: natural requirements + understanding metric.** 20 labelled
  requirements (`data/requirements_natural.csv`; 8 dev / 12 test; 3
  deliberately ambiguous, 1 unsupported by the spec, 5 with literal hex IDs)
  written under similar restrictions. New metric (`eval/understanding.py`):
  target identification (parsed and exercised), category recall, precondition
  recall, fallback.
- **A3: metrics cleanup.** The headline is a table of independent rows. The
  oracle self-consistency number moved to an appendix (circular); simulator↔rules
  agreement and the udsoncan virtual-CAN sequence are computed live in the eval
  (`--skip-can` skips the latter, for fast runs); in-sample numbers are
  labelled.
- **A4: SWS citations + disagreements.** The rules engine cites 38 distinct
  AUTOSAR CP R24-11 Dcm SWS IDs. Nine differences from the SWS (D1-D9) were
  documented in `docs/SWS_DISAGREEMENTS.md`; four of them (D2, D5, D6, D7) were
  fixed in Part C. The AUTOSAR PDF is git-ignored (AUTOSAR terms do not allow
  redistribution); the owner keeps a local copy and the SWS tests skip without
  it.
- **A5: docs pack.** `docs/CODE_TOUR.md`, `docs/ARCHITECTURE.md`,
  `docs/RESULTS.md`, `docs/DEMO_SCRIPT.md`, `docs/SWS_DISAGREEMENTS.md`,
  `docs/RECONCILIATION.md`, plus `scripts/demo.py`.
- **A6: PROJECT.md, UI, this report.**
- **Reconciliation result:** the owner's brief mentions an older 18-file doc
  set; none was found (`docs/RECONCILIATION.md`), so nothing was ported.

## Part B changes

_Historical: figures here come from the Part B runs (see `PROGRESS.md` for each run's hash), not from the Main eval._

Historical: the figures quoted in this section (for example 343/343 and 158/158
provenance, 10 rejected choices, 19.2 minutes) are the Part B run on template
set v2, before Part C. The current numbers are in the headline and in Part C.

Part B (B0-B5) ran the real local model and the real embedding stack, and
compared them with the mock without changing templates, gold tests or the held-out
sets.

- **B0: preconditions and hardware.** `ollama list` showed
  `qwen2.5:3b-instruct-q4_K_M` (1.9 GB); `GET /api/tags` responded; Ollama
  0.35.1; GPU NVIDIA GeForce RTX 3050 Laptop, 4096 MiB VRAM, driver 581.15.
  `ollama.exe` is not on Git Bash's PATH, so checks used PowerShell and HTTP
  (`[PB-OLLAMA-CLI]`).
- **B1: fastembed + Chroma.** The owner lifted the offline rule for chromadb
  1.5.9, fastembed 0.8.1 and `BAAI/bge-small-en-v1.5` only (`[PB-INSTALL]`);
  onnxruntime 1.30.0 came in as a dependency, while torch, transformers and
  sentence-transformers stayed uninstalled. Embeddings run as ONNX on the CPU
  (`EMBEDDER=fastembed|sentence-transformers`, default fastembed). The Chroma
  store lives at `outputs/chroma` (git-ignored). A BM25-vs-Chroma comparison was
  added to the eval: neither is clearly better, default stays BM25
  (`[PB-RETRIEVAL-RESULT]`).
- **B2: instrumentation and smoke test.** All prompt text moved word for word
  into `uds_assistant/llm/prompts.py`. `OllamaClient` always sends `num_ctx`
  4096 (`OLLAMA_NUM_CTX`), temperature 0, seed 0, `keep_alive` 10m
  (`OLLAMA_KEEP_ALIVE`) and a JSON-schema `format`. Pipeline results gained
  per-node timings, LLM stats and fallback events. Smoke run on REQ-001 to
  REQ-005 (`outputs/ollama_smoke.json`): all completed, 0 JSON failures, 0
  retries, 0 fallbacks, but 18 to 19 tests per requirement (planning was not
  selective), weak parsing, and 103 to 126 s per requirement (about 80 s in
  explain). `MODEL_SETUP.md` section 2b documents the 4 GB server settings.
- **B3: bug found and fixed, then dev-only prompt tuning.** B3 found that the
  plan prompt was about 16.2k tokens (mostly the 154-option template catalog)
  while `num_ctx` is 4096, so Ollama silently truncated it to its last ~2k tokens
  (8 of 8 plan calls in every revision): the planner never saw the instruction
  or the requirement and returned the same 18 tests for every requirement
  (`[PB-B3-TRUNC]`). The owner kept `num_ctx` 4096, so the fix went into the
  pipeline (`[PB-CTX-BUDGET]`, `[PB-TRUNC-DETECT]`):
  - when a backend declares `context_tokens` (Ollama does, mock does not) the
    plan node sends a compact prompt: a deterministic shortlist of at most 24
    options (at most 4 per template, real catalog indices), the task placed
    after the options, fitted to 60% of the window; choices outside the
    shortlist are rejected;
  - `OllamaClient` flags likely truncation from `prompt_eval_count` and reports
    it verbatim; the mock's output on all 15 seed requirements is identical
    before and after (`outputs/prompt_tuning/mock_equivalence.json`).

  Tuning used only the 8 dev rows (harness `scripts/tune_dev.py`; selection
  rule fixed before revision 1: parsed F1 + category recall + precondition
  recall). Revision summary (dev split, n=8):

  | Rev | Change | Parsed F1 | Cat. recall | Precond. recall | Tests/req |
  |---|---|---|---|---|---|
  | 0 | Baseline (B2 prompts), truncated plan | 0.329 | 0.591 | 1.000 | 18.0 |
  | 1-4, 6 | Parse-prompt variants (precise extraction, examples, name matching) | 0.105 to 0.591 | 0.591 | 1.000 | 18.0 |
  | 5 | Parse: 5-step procedure (selected in round 1) | 0.667 | 0.591 | 1.000 | 18.0 |
  | 7 | Pipeline fix: budgeted compact plan prompt + truncation detection | 0.636 | 0.773 | 1.000 | 6.62 |
  | **8** | **Plan instruction: selective, own identifiers only (selected, frozen)** | **0.683** | **0.727** | **1.000** | **5.38** |
  | 9 | Rev 8 + per-category "when to include" (rejected: model copied `(negative)` into `template_id`) | 0.683 | 0.727 | 0.667 | 4.62 |
  | 10 | Rev 8 + re-rendered shortlist header (rejected: precondition recall fell) | 0.683 | 0.727 | 0.889 | 4.00 |

  Revision 8 (rev-5 parse prompt + rev-8 plan prompt) was selected on dev only,
  before the test split was run in ollama mode. Each revision is one greedy run
  on 8 rows, and runs vary by about ±0.05 F1. Freeze hashes: freeze commit
  `1008ebd1f5e321abd848993600f9f6382ffb789a`; `uds_assistant/llm/prompts.py` blob
  `98a4741604338c3a0ffc2b17dc433e9c90d47620`; `uds_assistant/llm` tree
  `3559f7e7e0e53b5d08212b5cbccd5aa06e6bba71`; `uds_assistant/agent` tree
  `1d678f0f41eb23962defd6c8ea387bea4fcffb59`; testgen tree unchanged
  (`9a121b2742c5f85fa48fd4f5340caf3b85979c67`). The eval report's freeze
  verification shows all four matching HEAD with a clean worktree.
- **B4: full comparison, provenance, interpretation.** `run_eval --mode ollama`
  (also runs mock; report version 2) took 19.2 minutes (ollama 18.2, mock 36 s),
  exit 0, with 0 fallbacks and 0 truncations. Byte provenance is asserted after
  the run on every generated test in every mode (343/343 mock, 158/158 ollama; a
  failure would exit with code 2). The interpretation was written after the
  numbers existed and stored with `--rerender`, which recomputes nothing
  (`outputs/eval_interpretation.md`). Result: see the headline above.
- **B5: docs, demo and UI.** `docs/RESULTS.md` rewritten around the combined
  table, the comparison, provenance, retrieval and the interpretation;
  `docs/DEMO_SCRIPT.md` got an ollama segment (about 2 extra minutes) with a
  recorded-results fallback; `scripts/demo.py` gained `--llm ollama` (falls back
  to the mock with a printed warning) and now prints both modes' headline;
  README, PROJECT.md, MODEL_SETUP.md, `docs/CODE_TOUR.md` and this report were
  brought up to date; the Streamlit UI shows the mock/ollama comparison, with
  new headless AppTest tests (full report, and a mock-only report degrading to
  "n/a"). No file under `uds_assistant/llm`, `agent`, `testgen`, `rules`,
  `simulator`, `rag`, `eval`, `data` or `outputs` was changed in B5. The GPU was
  not used in B5 (the owner was using it): the default pytest run only.

## Part C changes

_Historical: baseline git `38aa719` (2026-10-03T09:37Z) and final report git `c669e1e` (2026-10-03T20:49Z); not the Main eval._

Part C (C0-C6) fixed the problems Part B found, then measured on fresh data
whether the fixes worked. Order: change, freeze, write blind data, measure.
Details are in `PROGRESS.md` (Part C) and `DECISIONS.md` (`[PC-…]` to
`[PC6-…]`).

- **C0: baseline.** Frozen before any change: HEAD
  `38aa7197d0a330f6f2f8f550fb3796ea5ae9db20`, report stored as
  `outputs/partC/baseline_before_partC.json` (a test re-extracts it from git
  and compares). Baseline: held-out v1 generated 3/12 for both modes; ollama
  parsed precision 0.512 (21 false positives); 10 rejected planner choices;
  30.8 s mean latency; 9 SWS disagreements open.
- **C1: normalisation, grounding, batched explain.**
  - Template-id normalisation before validation (one trailing `(...)` removed,
    exact catalog match only, no fuzzy matching) `[PC-NORM]`.
  - Identifier grounding: DIDs, routines and DTCs from a real model survive
    parsing only if the requirement writes them out or a spec search plus a
    distinctive name word supports them. Services, sessions and security
    levels are deliberately not checked `[PC-GROUND]`. The parse prompt
    examples use `<id of X>` placeholders instead of real spec ids `[PC-PROMPT]`.
  - Explain makes one batched JSON call per requirement, with deterministic
    fallback text for any missing test `[PC-EXPLAIN]`.
  - **Mock output is byte-identical**: all 171 earlier tests have identical
    steps (171/171), and 30 runs (15 requirements, two engines) are identical
    except explanation wording and call counts
    (`outputs/partC/mock_equivalence.json`, `[PC-MOCK-EQ]`).
- **C2: SWS D2, D5, D6, D7 fixed.** In the rules engine (each checked against
  the SWS text), in `docs/behaviour_contract.md`, and in the simulator, which
  was changed by an agent that never read the rules engine. D2: no generic
  0x12 check for RoutineControl (unknown routine answers 0x31 first). D5: 0x37
  applies to requestSeed only (a key during the delay answers 0x24). D6:
  bit 7 is the suppress-positive bit for all six subfunction services (incl.
  0x19, 0x27). D7: multi-DID read skips unknown or unreadable DIDs. One gold
  test, `gold_multi_did_read_one_bad` (`22 F1 90 99 99`, now `62 F1 90` + VIN
  instead of `7F 22 31`), was hand-updated; the other 59 passed unchanged.
  Simulator and rules engine agree on 100% of requests on two seeds (13,487
  and 13,556 requests), plus a 300-example hypothesis test and a 3,000-request
  fuzz. **5 SWS disagreements remain open: D1, D3, D4, D8, D9.**
- **C3: coverage templates (27), v3 set, probes, freeze.** Template set v3 has
  27 templates (23 + 4 new generic ones: `read_did_invalid_length`,
  `seed_request_while_unlocked`, `session_change_resets_routine`,
  `write_did_value_retained`) plus parameter variants on 3 existing templates,
  cap 32. They were designed from the static list of stimuli that the held-out
  v1 misses needed, so **v1 is seen from here on**. General behaviour
  probes: the mock on the seed requirements applies 10 of the 12 held-out v1
  stimuli (up from 3). A test scans the testgen source, template metadata and
  every instantiated test for all 38 bug ids: 0 hits. Then the freeze.
- **Part C freeze** (no change to templates, prompts, planner or gold from
  here until the end of C6; every evaluation run re-checks it and all hashes
  matched and were clean):

  | What | Hash |
  |---|---|
  | Commit | `5a36eb432ed5aa05fb4a8ccb6776e8232a43d309` |
  | `uds_assistant/testgen` tree | `a4b6491fc2d01421c4cff10143aabd3c75017df1` |
  | `uds_assistant/llm` tree | `95ebf497e3e31a4d6d1377ca960b15e94e5cad66` |
  | `uds_assistant/agent` tree | `9696c352234501d72ac54c18af5189317482321d` |
  | `uds_assistant/llm/prompts.py` blob | `c0c6d5a6f0b64790beb13bf0179a6ef7877f31f7` |
  | `data/gold` tree | `778740195a3dc923ae2f6a34fd4b78e11d87b024` |

- **C4: blind v2 sets.** Two Sonnet subagents with strict read limits, after
  the freeze: **15 held-out v2 bugs** (`data/bugs/heldout_v2_catalog.yaml`,
  each with a unit test of the exact differing bytes) and **16 natural v2
  requirements** (`data/requirements_natural_v2.csv`, all `split=test2`). The
  exact prompts are recorded in `PROGRESS.md` ("C4 — subagent prompts"). The
  trigger predicates used to explain misses were written before any v2 result
  existed.
- **C5: v2 evaluation.** C5a extended the eval (report version 3: v2 headline,
  natural v2 understanding, `--noise-runs`, `--before-after`, freeze table,
  provenance on every run). C5b ran it for real
  (`python -m uds_assistant.eval.run_eval --mode ollama --noise-runs 3
  --before-after`, about 31 minutes). Results: see the headline. **Byte
  provenance: 511/511 mock and 418/418 ollama**, all three noise runs
  included. Before/after: `outputs/partC/before_after.md`. Interpretation
  written after the numbers existed: `outputs/partC/interpretation.md`.
- **C6: UI, UI_CHECKLIST, docs.** The Streamlit evaluation section renders
  report versions 2 and 3 and `before_after.md`; the bug dropdown offers
  `[in-sample]`, `[held-out v1, seen]` and `[held-out v2, fresh]`;
  `docs/UI_CHECKLIST.md` has 10 manual steps (steps 1 to 8 checked against
  real widget labels by a headless test). `scripts/demo.py`, README,
  PROJECT.md, `docs/RESULTS.md`, `docs/DEMO_SCRIPT.md`, `docs/CODE_TOUR.md` and
  this report were updated; every final number was copied from the report
  after the C5b run. No file under `uds_assistant/`, `data/`, `outputs/`,
  `tests/` or `scripts/` was changed in this documentation step (C6b).

## Part D changes

_Figures: Main eval run 2026-10-04, git `1f0c293` unless a bullet names another run._

Part D (D0-D6) went after the three Part C weaknesses: 2/15 fresh bug
detection, poor parsed precision (false positives mostly services), and rising
planner rejections. The plan and the metrics were written down in `PROGRESS.md`
before any v3 result existed. Details are in `PROGRESS.md` (Part D) and
`DECISIONS.md`.

- **D0: plan.** Start commit `9383d0bc6f129366e16d035a378809cddfb02648`.
  Pre-registered headline: bug detection is the system's full output
  (requirement-driven tests plus sweep), with the parts also reported
  separately; requirement understanding is natural v3 parsed P/R/F1, category
  and precondition recall. v1 and v2 are labelled seen.
- **D1a: parse and planner.** Service evidence grounding, optional evidence
  quotes (later removed from the prompt), constrained planner decoding. Built
  with fake models.
- **D2: conformance sweep.** 1200 requirement-independent tests, every
  expected byte from the rules engine, selected by greedy covering. The
  mock-mode output of the 15 seed requirements was checked against the earlier
  output (`outputs/partD/mock_equivalence_D1a.json`, `mock_equivalence_D2.json`).
- **D1b: dev-only tuning with the real model.** Revisions 0-5 on the 8 natural
  v1 dev rows (plus a robustness revision 6 with the same dev scores) under a selection rule written before revision 0; revision 2
  selected (parsed F1 0.839 on dev). Net change: one prompt step removed and
  four generic words added to the grounding's weak-word list. The planner now
  skips the model when nothing is offered, and hex ids are padded to the
  spec's spelling. No held-out set was run during tuning.
- **Part D freeze** (no change to templates, sweep, prompts, planner, service
  lexicon or gold from here until the end of D6; every evaluation run re-checks
  it and all hashes matched and were clean):

  | What | Hash |
  |---|---|
  | Commit | `4042f260527f76b781546cb39687b080d19ecb61` |
  | `uds_assistant/testgen` tree | `d990ef45a4f5f38c4ea59cc30e42011ccecf6ab9` |
  | `uds_assistant/llm` tree | `0dad8c4165842d10e7bf15c0c5554881d8db13d3` |
  | `uds_assistant/agent` tree | `5875c8629e01fe7dadab98d6f2de584aa0b4af05` |
  | `uds_assistant/llm/prompts.py` blob | `c117f993ef0d10657f36eaf2c08f132d02efbda4` |
  | `uds_assistant/testgen/conformance.py` blob | `edc143372c412ba65305231d6241eeacdc18b7d8` |
  | `uds_assistant/agent/service_lexicon.py` blob | `42ceae7509950189d69da8ce7516d15c2b1b1982` |
  | `data/gold` tree | `778740195a3dc923ae2f6a34fd4b78e11d87b024` |

- **D4: blind v3 sets.** Two Sonnet subagents with strict read limits, after
  the freeze: **15 held-out v3 bugs** (`data/bugs/heldout_v3_catalog.yaml`,
  each with a unit test of the exact differing bytes) and **16 natural v3
  requirements** (`data/requirements_natural_v3.csv`, all `split=test3`, two
  ambiguous, one with no supported target). The exact prompts are recorded in
  `PROGRESS.md` ("D4 - subagent prompts").
- **D5: v3 evaluation.** D5a extended the eval (report version 5: v3
  headline, full output with parts (a)/(b)/(c), FP/FN by kind, rejections by
  reason, `--before-after` for Part D). D5b ran it for real (about 39 minutes).
  Results: see the headline. Before/after: `outputs/partD/before_after.md`.
  Interpretation written after the numbers existed:
  `outputs/partD/interpretation.md`.
- **D6: documentation.** `docs/RESULTS.md` and this report were rewritten from
  the report. No file under `uds_assistant/`, `data/`, `tests/` or `scripts/`
  was changed in this step; the only code-side artifacts it adds are the
  regenerated `outputs/` files.

## Part D completion

_Figures: Main eval run 2026-10-04, git `1f0c293` unless named._

Part D was complete at its last commit (`482073e part D (D5b, D6)`); Part E began by verifying that and closing one open question.

- **v3 evaluation run.** `run_eval --mode ollama --noise-runs 3 --before-after`, about 39 minutes (log `outputs/partD/eval_run.log`), report version 5. Results are the headline of this report; before/after is `outputs/partD/before_after.md` (historical, under History below); interpretation `outputs/partD/interpretation.md` (commit `8357ec0 part D (D5b): v3 evaluation run, before/after, interpretation`).
- **Freeze hashes verified.** At the start of Part E (E0, git `04096ff`) the Part D freeze hashes still matched HEAD: testgen `d990ef45...`, llm `0dad8c41...`, agent `5875c862...`, gold `77874019...`. The freeze applied through D6 only; Part E legitimately changed code (Q&A, confidence, retrieval layers, UI), so the hashes are no longer expected to match HEAD. Generator bytes were verified unchanged in E3.2 (mock output for the 15 seeds identical, 206 tests) and E3.3 (core BM25 scores bit-identical, mock tests unchanged).
- **Fallback-events investigation (E1).** The report lists 123 Ollama events of the form `explain: <test_id>: missing in LLM reply; used fallback text` (33 to 44 per noise run). Cause: the 3B model returns valid JSON with fewer `explanations` entries than tests (often three). A reproduction over the 15 seed requirements (75 tests, 15 batches) gave 17 events with 0 id mismatches after normalisation, 0 invented ids, 0 invalid JSON or retries, 0 truncations, and `done_reason` `stop` (no token limit hit); replaying one request twice gives the same reply. **Model omissions, not a bug, and no score effect**: explain writes only the prose field `TestCase.explanation`, nothing in `eval/`, `export/` or the oracle reads it, so bytes, byte provenance and every score are independent of how many explanations fell back (what changes is a generic sentence instead of model prose for those tests). No code changed and the evaluation was not re-run, so there is no second run. Full write-up with verbatim events and raw replies: `outputs/partD/interpretation.md`, section "Ollama explain fallback events (Part E investigation)".

## Part E changes

_Commits from `git log --oneline`. Run labels: Main eval 2026-10-04 `1f0c293`; Q&A run 2026-10-04 `9e66f7a`; timing run 2026-10-04 `8357ec0`._

- **E0 orient (`04096ff`).** Findings and plan in `PROGRESS.md`: Part D was already complete; the case-study PDF is not in the repo, so Case 5 items come from the Part E brief, `PROJECT.md`, `SCOPE.md` and the docs.
- **E1 finish Part D (`8357ec0`, `482073e`).** v3 run, before/after and interpretation; the fallback-events investigation (above).
- **E3.4 Docker (`ffa813d`).** `Dockerfile` (python:3.13-slim, installs the project, runs FastAPI and Streamlit), `docker-compose.yml` (`app` and `ollama`, model volume, commented GPU block), `.dockerignore`, `docs/DOCKER.md`. **Written, not built here**; nothing was built or pulled.
- **E3.5 test design time (`cdcdfdf`).** `docs/TEST_DESIGN_TIME.md` (protocol, blank results table), `scripts/time_generation.py`. Tool-side time per requirement (mean of 5 requirement means, 3 repeats): mock 0.217 s, ollama 19.36 s. The manual comparison is **pending owner measurement**.
- **E3.6 spec provenance (`9445eb0`).** `PROJECT.md` states the ECU spec is hand-authored synthetic data, not extracted from a PDF; the same note is in `docs/RESULTS.md`.
- **E3.3 OEM layer (`7b5a6dd`, fix `3a8c4e3`).** Four layers standard / OEM / ECU / project; synthetic `data/oem_diagnostic_guidelines.md` in its own collection; layer in chunk metadata and citations. The generator uses only the core layers (`DECISIONS.md` E33-NO-OEM-IN-GEN), so generated output is unchanged.
- **E3.1 Q&A (`e9a4ca0`).** `qa/`, `POST /ask`, blind eval (`data/qa_eval.csv`, 21 answerable and 4 unanswerable written by a restricted subagent). Run `9e66f7a`: accuracy 90.5% / 90.5% (mock / ollama), citation correctness 95.2% / 90.5%, citation precision 80.6% / 79.3%, correct not-found 75% / 75%, ollama fallback events 13. Misses QA-018, QA-022, QA-023. Two earlier runs (plain-bug fixes in the claim verifier and the scorer) are kept under `outputs/qa/` and logged in `DECISIONS.md` E31-RERUNS.
- **E3.2 confidence (`9e66f7a`).** Shared rule in `agent/confidence.py` (`DECISIONS.md` E32-*); mock generation for the 15 seeds byte-identical before and after. Distribution on the 15 seeds in mock mode: 135 high / 71 medium / 0 low; `low` is only unit-tested.
- **E2 one results story (`d3d2fc3`).** Run provenance in `outputs/eval_report.*` (every section labelled with date and git hash), Part C/D before/after tables only under History (labelled historical), one-page `docs/RESULTS.md`, clean Q&A run.
- **E4 tabbed UI (`52fdacc`).** Five tabs, sidebar with reachability-aware mode selector, split `ui/` modules, AppTest per tab, door-lock sanity check (recorded in `PROGRESS.md`; limitation below).
- **E5 final wrap-up.** README, PROJECT.md, CODE_TOUR, ARCHITECTURE, this report, `docs/CASE_STUDY_COMPLIANCE.md`; final checks (Test counts).

Per-area headlines are at the top of this report (correctness, bug detection, requirement understanding, Q&A, UI).

## Deviations from docs

- Python 3.13.6 used instead of the originally documented 3.11 (PROJECT.md now
  says 3.13) (only interpreter available); code kept 3.11-syntax-compatible.
- `docs/`, `data/bcm_spec.yaml`, `data/requirements_seed.csv` did not exist at
  project start and were authored from scratch, matching `PROJECT.md`/
  `SCOPE.md` intent (synthetic spec, no real OEM data).
- Template count is **27** (v1 14 + v2 9 + v3 4), not the 8–12 originally in
  `PROJECT.md` §4 (`DECISIONS.md [EVAL-TPL-V2]`, `[PC3-TPL]`); the registry
  has a hard cap of 32.
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
  in-process (`DECISIONS.md [RUN-TIMING]`) — see Known limitations.
- `streamlit` was installed (1.64.0) despite being in the "install only if pip
  is responsive" bucket of `SCOPE.md` (`DECISIONS.md [UI-STREAMLIT-INSTALL]`).
- Part B: the owner lifted the offline rule for chromadb, fastembed and the
  embedding model only; `onnxruntime` (on `AGENT.md`'s never-install list) came
  in as a required dependency (`DECISIONS.md [PB-INSTALL]`).
- Part B: the ollama plan prompt differs from the mock's: it uses a compact
  shortlist because of the 4096-token window, while the mock keeps the
  full-catalog prompt (`DECISIONS.md [PB-CTX-BUDGET]`). In Part C the shortlist
  maximum went from 24 to 30 options because the catalog grew
  (`[PC3-SHORTLIST]`).
- Part C: Hypothesis's `too_slow` health check is switched off for the whole
  suite in `tests/conftest.py` (`[PC3-HYPOTHESIS]`).

## Known limitations

_Figures: Main eval run 2026-10-04, git `1f0c293` unless a bullet names another run._

- **Door-lock sanity check: the natural requirement did not produce the intended pair of tests (E4, 2026-10-04).**
  For "The door lock status must only be writable in extended session after
  security unlock." neither mode produced a negative write (expect 0x33, no
  unlock) together with a positive write after unlock. Mock: 5 tests, none
  writes a door-lock DID (it wrote DID 0x0100, interior lighting brightness,
  in the default session, and tested SecurityAccess subfunction errors).
  Ollama: 5 tests; one writes the read-only door-lock DID 0x0110 after
  switching to the programming session, with no unlock, and expects 0x31; one
  writes DID 0x0160 (coding variant id) and expects 0x33; none writes a
  door-lock DID after a successful unlock. In the
  synthetic spec the door-lock DIDs 0x0110/0x0111 are read-only (no write
  session), so a positive write after unlock cannot exist for them. Details:
  PROGRESS.md "Door-lock sanity check". Not tuned on.
- **Confidence is lightly validated.** On the 15 seed requirements in mock mode
  the distribution is 135 high / 71 medium / 0 low (206 tests; E3.2 run). `low`
  and the weak-retrieval signal (best cited BM25 score below 15.0; all seed
  hits score at least 23) never fire there, so they are covered by unit tests
  only. The signal weights and the 15.0 threshold were set by reasoning, not
  fitted, and the report has not measured whether `high` tests are actually
  more often right than `medium` ones.
- **Q&A is small and imperfect.** 25 questions (21 answerable); QA-018 shows the
  refusal rule can answer an unanswerable question when a retrieved sentence
  overlaps enough; QA-022 and QA-023 are retrieval misses. The OEM layer is
  synthetic, so Q&A over "OEM" content only shows the mechanism.
- **Detection on fresh bugs is 9-10/15 with the sweep and 2-4/15 without it.**
  The model does not change what can be found; both modes reach 9/15 through
  the sweep. Five bugs are missed in both modes because no test applies the
  stimulus.
- **The v1, v2 and in-sample numbers are not evidence.** v1 and v2 are seen
  (Part C templates were built from v1 misses; Part D was designed after v2
  results), and the 26 in-sample bugs shaped templates v2. The v3 sets are now
  also visible to anyone who reads the miss list: anything built from it needs
  a v4 blind set.
- **Small samples.** 15 bugs and 16 requirements: one item is 6.7 or 6.25
  points. A one-bug difference between modes (10 vs 9) is not evidence.
- **Ollama precision is poor on fresh phrasing.** 0.596 on v3 with 19 false
  positives (15 services, 4 DIDs). Recall (0.622) is lower than on v2 (0.796);
  the sets differ, so this may be set difficulty.
- **Ollama noise is measured on three runs only.** Parsed, category and
  precondition numbers were identical; exercised F1 varied by 0.01. The mock's
  keyword rules were written by the people who wrote the v1 requirements, which
  is the interpretation's explanation for its low recall (0.267) on the
  unfamiliar v3 phrasing.
- **The rejection fix has no ablation.** Planner rejections fell to 0, likely
  because of constrained decoding, but that was not isolated.
- **The sweep shares the oracle.** Its expected bytes come from the rules
  engine, so a misreading shared by the engine and the simulator is invisible
  to it. The prompt revision was chosen on 8 dev rows, and the gap between the
  selected revision and the runner-up was within noise (see `PROGRESS.md`).
- **One small model.** Only `qwen2.5:3b-instruct-q4_K_M` on one 4 GB laptop
  GPU, a 30-option plan shortlist forced by the 4096-token context. Nothing
  here says how a larger model or context would do.
- **Synthetic setting.** The ECU spec is synthetic, and the v3 bugs, though
  realistic, were written by a language model; none of the numbers say anything
  about a real vehicle ECU.
- **SWS traceability is partial:** D1, D3, D4, D8 and D9 remain open, so the
  oracle is not SWS-conformant in those cases. The SWS PDF is not in the repo.
  The simulator, rules engine and gold tests share one prose contract, so
  shared misreadings are possible.
- **Self-consistency is circular.** The expected-response accuracy metric
  (100%) is circular by construction. The meaningful, independent checks are:
  (a) simulator-oracle byte-for-byte agreement on randomized sequences
  (5000/5000), (b) all 60 gold tests passing against the independently-run
  simulator, and (c) the `udsoncan` client completing a real protocol exchange
  over a virtual CAN bus. Byte provenance (613/613, 552/552, 1200/1200) shows
  that no LLM byte reaches a test; it does not show the bytes are right.
- CAPL export output is an unverified template, never compiled or run in
  CANoe (no license available).
- The UI has never been clicked through in a real browser (AppTest only).
- Docker was never built; the test-design-time comparison was never measured by a human.
- P2/P2* timing checks for the in-process transport are wall-clock on a
  general-purpose desktop OS and are `timing_warning`s rather than hard failures
  for anything but an explicit per-step `max_response_time_ms`
  (`DECISIONS.md [RUN-TIMING]`). CAN-mode timing is not tested for
  time-advance-dependent behaviour.
- Citation validity means a citation points at a retrieved chunk; it does not
  prove the chunk justifies the test.
- Template count (27) exceeds the original PROJECT.md target (8-12); template
  reuse (100% by construction) says nothing about whether 27 is the right size.

## Next steps

1. **Close the five stimuli still missed** (seed, session switch, then key;
   lockout expiry then another wrong key; unsupported sub-function with wrong
   length; DID read above 255 kph; DTC mask with extra status bits), and
   **write v4 blind sets (bugs and requirements) before claiming any
   improvement.**
2. **Service precision on fresh phrasing:** the model still adds `0x10` and
   `0x27` where the text does not state them and misses `0x3E` in some
   requirements.
3. **Try a larger model** (or a larger context window on bigger hardware),
   which would also lift the plan-shortlist limit. Re-run the whole comparison
   on a larger fresh requirement set; do not extrapolate from the 3B result.
4. **Fix SWS D1, D3, D4, D8 and D9 if wanted** (`docs/SWS_DISAGREEMENTS.md`),
   coordinated across `rules/`, `simulator/`, `docs/behaviour_contract.md` and
   the gold tests, and evaluate with a fresh bug set.
5. Click through the Streamlit UI in a real browser following
   `docs/UI_CHECKLIST.md` (including the human-review button, `LLM_MODE=ollama`
   and `RETRIEVER=chroma`).
6. Evaluate end-to-end test generation with `RETRIEVER=chroma` (only the
   retrieval step itself was compared so far).
7. Justify or trim the 27-template design size against the original 8-12
   target.

## History

Historical tables from earlier runs, kept for the record. They are not the current headline; the current results are in `docs/RESULTS.md` and the first sections of this report. Part C's table is in `outputs/partC/before_after.md` (before = git `38aa719`, 2026-10-03T09:37Z; after = git `c669e1e`, 2026-10-03T20:49Z).

### Before / after Part D (**historical**; before = Part C final report, git `942f438`, 2026-10-03T20:49Z; after = Main eval, 2026-10-04, git `1f0c293`; source `outputs/partD/before_after.md`)

| Metric | mock before | mock after | ollama before | ollama after |
|---|---|---|---|---|
| **Held-out v3, FRESH: full output** | n/a | 10/15 | n/a | 9/15 |
| Held-out v3, FRESH: req-driven / sweep / gold | n/a | 4 / 9 / 3 | n/a | 2 / 9 / 3 |
| **Natural v3, FRESH: parsed P / R / F1** | n/a | 0.857 / 0.267 / 0.407 | n/a | 0.596 / 0.622 / 0.609 |
| Held-out v2, SEEN: req-driven | 2/15 | 2/15 | 2/15 | 2/15 |
| Held-out v2, SEEN: full output | 2/15 | 9/15 | 2/15 | 9/15 |
| Natural v2, SEEN: parsed P / R / F1 | 1.000 / 0.225 / 0.367 | 1.000 / 0.225 / 0.367 | 0.565 / 0.796 / 0.661 | 0.808 / 0.775 / 0.792 |
| Parsed FP, natural v2 (SEEN) | none | none | service 25, did 5 | service 6, did 3 |
| Parsed FP, natural v1 test split (SEEN) | service 1 | service 1 | service 17, did 4 | service 5, did 4 |
| Parsed FP, natural v3 (FRESH) | n/a | service 2 | n/a | service 15, did 4 |
| Rejected planner choices (35 old requirements) | 0 | 0 | 15 | 0 |
| Rejected planner choices, natural v2 (SEEN) | 0 | 0 | 12 | 0 |
| Latency per requirement, mean / p95 (35) | 0.27 s / 0.46 s | 0.38 s / 0.63 s | 21.37 s / 28.52 s | 21.85 s / 30.41 s |
| Explain calls per requirement, mean | 0.89 | 0.89 | 1.00 | 0.97 |
| SWS disagreements open | 5 | 5 | 5 | 5 |

The v3 rows have no "before". v1 and v2 "after" numbers are SEEN: Part D was
designed after their results were known.
