# FINAL_REPORT.md

Honest status of the UDS Diagnostics & Automated Test Generation Assistant at
the end of Part C (fixes, fresh blind evaluation, documentation), which follows
Part B (real-model evaluation), Part A (honest evaluation) and the Phase 9
wrap-up. Eval numbers are copied exactly from `outputs/eval_report.md` / `.json`
(report version 3), `outputs/partC/before_after.md` and `PROGRESS.md`; test
counts come from a fresh `python -m pytest -q` run (Python 3.13.6, Windows, git
repo at `tata_tech`); none are estimated or rounded up.

**Headline (fresh v2 data: written blind after the Part C freeze, nothing tuned
on it).**

- **Held-out v2 bug detection is 2/15 (13.3%) for the generated suite, in both
  modes** (mock and ollama). Gold catches 5/15 and the union is 5/15. The
  coverage templates added in Part C did not transfer from the seen v1 bugs
  (where the mock's generated suite went from 3/12 to 10/12) to 15 fresh bugs.
  Of the 13 misses, 11 have no generated test applying the stimulus and 2 apply
  it but cannot see the bug.
- **Requirement understanding on natural v2 (n=16) is clearly better with the
  model than with the mock**, which reverses the Part B result on the seen v1
  test split: parsed F1 0.661 vs 0.367, category recall 74.0% vs 48.0%,
  precondition recall 77.8% vs 55.6% (ollama run 1; 3-run mean category recall
  75.3%, range 74.0%-76.0%; precondition recall mean 82.7%, range 77.8%-85.2%;
  parsed F1 identical in all three runs). But ollama's precision is 0.565 with
  30 false positives (25 services, 5 DIDs); the mock's precision is 1.000 but
  its recall is 0.225.
- **The precision fix did not work** (services are not covered by the grounding
  check). The template-id normalisation fired 0 times, and rejected planner
  choices rose (15 on the 35 old requirements, up from 10; 12 on v2). **Explain
  batching worked**: 1.00 LLM call per requirement (4.51 before), mean latency
  21.37 s (30.79 s before).
- v1 results (held-out v1: mock 10/12, ollama 5/12 generated) are **SEEN**
  (templates were designed against those misses) and the 26-bug in-sample
  numbers (mock 25/26, ollama 19/26) are **tuned on**; neither is evidence.
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
  held-out v2 injectable bugs, in-process and virtual-CAN/ISO-TP transports.
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
  frozen at testgen tree hash `a4b6491fc2d01421c4cff10143aabd3c75017df1`; byte
  provenance re-checked against a fresh instantiation on every generated test
  (511/511 mock and 418/418 ollama in the final run, including all noise runs).
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
- **Grounding on the real model.** It ran in every ollama run. Its effect is
  small (the copied example DID 0x0140 appears once among the v1 test-split
  extras, against three requirements in Part B) and it does not cover
  services, which are 25 of the 30 v2 false positives.
- **Ollama noise check.** Three ollama runs on natural v2, every run listed in
  the report with mean and range; mock re-run identical.
- **Mock vs ollama evaluation** in one report (version 3): fresh v2 headline,
  seen/tuned-on rows labelled, noise check, before/after table
  (`outputs/partC/before_after.md`), freeze verification, interpretation
  (`outputs/partC/interpretation.md`).
- **Streamlit UI, headless.** The UI renders the freeze status, the fresh v2
  headline, the noise check, the before/after table, the mock | ollama
  comparison and the retrieval comparison from `outputs/eval_report.json`
  (versions 2 and 3), offers bugs from all three catalogs, and shows which LLM
  backend actually ran. Covered by headless `streamlit.testing.v1.AppTest` runs.
  This is not a human click-through (see "Written but not fully exercised").
- **Demo script.** `scripts/demo.py` prints the v3 headline (fresh v2 rows
  first, seen rows labelled), runs any bug id from the three catalogs, and has
  `--llm ollama` (falls back to the mock with a printed warning) and `--offline`.
  Its real output is quoted in `docs/DEMO_SCRIPT.md`.
- Four SWS disagreements fixed (D2, D5, D6, D7), verified by the independent
  simulator agreeing on 100% of requests (see Part C changes).
- Test suite and lint: see "Test counts" below.

## ⚠️ Written but not fully exercised

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
- The precision problem is not solved: no service-level grounding exists.
- Generated tests do not apply the stimuli behind 11 of the 15 fresh v2 bugs,
  and two applied stimuli are not checked at the response that exposes the bug.
  Templates built against that list would make the v2 set seen; a v3 blind set
  would be needed.
- DoIP, OBD-II, flashing (0x34/0x36/0x37 download), 0x29 authentication,
  real ECUs/vehicles, cloud/paid LLMs, fine-tuning — all explicitly out of
  scope per `SCOPE.md` and not attempted.

## Test counts

Full suite (default, model tests skipped): `python -m pytest -q` → **1167 passed, 14 skipped in 303.53s (0:05:03)**. The 14 skips are the 13 `needs_model` tests plus 1 UI test that only applies to a version 2 report (the committed report is now version 3). 1181 tests are collected in total.
`python -m ruff check .` → **All checks passed!**

`needs_model` tests with the real Ollama server and Chroma/fastembed (`RUN_MODEL_TESTS=1 python -m pytest -m needs_model -q`) → **13 passed, 1168 deselected in 123.61s (0:02:03)**, run after the Part C evaluation.

A first full run during C6b had 2 failures, `tests/scripts/test_demo.py::test_demo_headline_shows_both_modes` and `tests/ui/test_streamlit_app.py::test_app_shows_headline_heldout_and_understanding`. They were stale assertions for the old version 2 report layout, not code regressions. They were updated to the version 3 layout afterwards, and the run above is after that fix.

Per-directory collection counts (`python -m pytest --collect-only -q`):

| Directory | Tests |
|---|---|
| `tests/rules/` | 276 |
| `tests/testgen/` | 185 |
| `tests/simulator/` | 170 |
| `tests/agent/` | 168 |
| `tests/eval/` | 84 |
| `tests/protocol/` | 78 |
| `tests/llm/` | 70 |
| `tests/rag/` | 61 |
| `tests/ui/` | 21 |
| `tests/api/` | 18 |
| `tests/spec/` | 14 |
| `tests/runner/` | 11 |
| `tests/scripts/` | 9 |
| `tests/store/` | 7 |
| `tests/export/` | 6 |
| `tests/test_config.py` | 3 |
| **Total collected** | **1181** |

The skipped tests are the `needs_model` tests, skipped by design, not deleted.
AUTOSAR SWS tests skip without the local PDF; it was present on the machine
that produced these numbers.

## Evaluation numbers (mock and ollama)

From `outputs/eval_report.md` (generated 2026-10-03T20:49:18Z, git `c669e1e`,
report version 3, template set `v3`, 27 templates, Bm25Retriever, LangGraph
engine; ollama = `qwen2.5:3b-instruct-q4_K_M`, num_ctx 4096, temperature 0,
keep_alive 10m). Both columns come from one invocation on the same inputs. A
fuller walkthrough with the before/after table, the noise check and the missed
bug list is in `docs/RESULTS.md`.

### Headline table

| Metric | mock | ollama |
|---|---|---|
| **1. Held-out v2 bug detection, FRESH (15 bugs; HEADLINE = generated)** | **generated 2/15 (13.3%)** · gold 5/15 (33.3%) · union 5/15 (33.3%) | **generated 2/15 (13.3%)** · gold 5/15 (33.3%) · union 5/15 (33.3%) |
| **2. Natural v2, FRESH (test2, n=16)** | parsed exact 0/16, P/R/F1 1.000/0.225/0.367; exercised F1 0.450; category recall 48.0% micro; precondition recall 55.6% micro; fallback/nothing 7/16 (6 excl. empty-label rows) | parsed exact 4/16, P/R/F1 0.565/0.796/0.661; exercised F1 0.583; category recall 74.0% micro; precondition recall 77.8% micro; fallback/nothing 0/16 |
| 3. Simulator ↔ rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 4. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 5. udsoncan virtual-CAN sequence | PASS | same (LLM-independent) |
| 6. Coverage (seed requirements) | positive 43, negative 77, session 25, security 30, timing 31; 15/15 requirements with ≥1 test (100.0%) | positive 26, negative 18, session 9, security 9, timing 4; 15/15 requirements with ≥1 test (100.0%) |
| 7. Citation validity | 967/967 (100.0%) | 315/315 (100.0%) |
| **SEEN** 8. Held-out v1 bug detection (12 bugs) | generated 10/12 (83.3%) · gold 3/12 (25.0%) · union 11/12 (91.7%) | generated 5/12 (41.7%) · gold 3/12 (25.0%) · union 6/12 (50.0%) |
| **SEEN** 9. Natural v1 test split (n=12) | parsed exact 5/12, P/R/F1 0.933/0.560/0.700; exercised F1 0.425; category recall 67.9%; precondition recall 80.0% | parsed exact 3/12, P/R/F1 0.500/0.840/0.627; exercised F1 0.416; category recall 82.1%; precondition recall 73.3% |
| **In-sample (tuned on)** 10. 26-bug detection | generated 25/26 (96.2%) · gold 24/26 (92.3%) · union 26/26 (100.0%) | generated 19/26 (73.1%) · gold 24/26 (92.3%) · union 26/26 (100.0%) |

### Noise check (natural v2, ollama, 3 runs; mean and min–max)

| Metric | run 1 | mean (min–max) |
|---|---|---|
| Parsed P / R / F1 | 0.565 / 0.796 / 0.661 | 0.565 / 0.796 / 0.661 (0.661–0.661) |
| Exercised F1 | 0.583 | 0.602 (0.583–0.611) |
| Category recall (micro) | 74.0% | 75.3% (74.0%–76.0%) |
| Precondition recall (micro) | 77.8% | 82.7% (77.8%–85.2%) |
| Rejected choices | 12 | 9.33 (8–12) |
| Fallback events | 18 | 13.33 (11–18) |

The mock is deterministic; a second mock run was identical.

### Before / after Part C (`outputs/partC/before_after.md`)

| Metric | mock before | mock after | ollama before | ollama after |
|---|---|---|---|---|
| **Held-out v2, FRESH: generated / gold / union** | n/a | 2/15 / 5/15 / 5/15 | n/a | 2/15 / 5/15 / 5/15 |
| Held-out v1, SEEN: generated / gold / union | 3/12 / 3/12 / 5/12 | 10/12 / 3/12 / 11/12 | 3/12 / 3/12 / 5/12 | 5/12 / 3/12 / 6/12 |
| In-sample (tuned on): generated / gold / union | 25/26 / 24/26 / 26/26 | 25/26 / 24/26 / 26/26 | 21/26 / 24/26 / 26/26 | 19/26 / 24/26 / 26/26 |
| Natural v1 test split, SEEN: parsed P / R / F1 | 0.933 / 0.560 / 0.700 | 0.933 / 0.560 / 0.700 | 0.512 / 0.880 / 0.647 | 0.500 / 0.840 / 0.627 |
| Parsed precision / FP, v1 test split (SEEN) | 0.933 / 1 | 0.933 / 1 | 0.512 / 21 | 0.500 / 21 |
| **Parsed precision / FP, v2 (FRESH)** | n/a | 1.000 / 0 | n/a | 0.565 / 30 |
| Rejected planner choices (35 old requirements) | 0 | 0 | 10 | 15 |
| Rejected planner choices, natural v2 (FRESH) | n/a | 0 | n/a | 12 |
| Latency per requirement, mean / p95 (35) | 0.25 s / 0.45 s | 0.27 s / 0.46 s | 30.79 s / 43.41 s | 21.37 s / 28.52 s |
| Explain calls per requirement, mean | 9.80 (derived) | 0.89 | 4.51 (derived) | 1.00 |
| SWS disagreements open | 9 | 5 | 9 | 5 |

The v2 rows have no "before"; v1 "after" numbers are SEEN.

### Held-out v2 detail

- Both modes: generated 2/15, gold 5/15, union 5/15; invalid generated tests 0.
  Generated suites (both modes) detected `session_reentry_keeps_unlock` and
  `write_range_upper_bound_exclusive`. Gold also detected
  `ecu_reset_keeps_session`, `multi_did_read_dedups_repeats` and
  `routine_restart_after_stop_blocked`.
- 13 misses: 11 have no generated test applying the stimulus; 2
  (`s3_timeout_resets_lockout_counters`, `ecu_reset_keeps_session`) have tests
  that apply it but none of their expected responses differs when the bug is
  on. The full list with one-line reasons is in `docs/RESULTS.md`.
- The ollama suite is smaller (66 vs 206 tests) and catches the same two bugs.

### Interpretation (condensed from `outputs/partC/interpretation.md`)

- **Better:** requirement understanding on fresh natural v2 (recall 0.796 vs
  0.225, category recall 74.0% vs 48.0%, precondition recall 77.8% vs 55.6%);
  explain batching (1.00 call per requirement, 21.37 s vs 30.79 s mean).
- **Worse / unchanged:** precision (0.565 on v2, 30 false positives, 25 of them
  services, which the grounding check does not cover); rejected planner
  choices (15 on the old 35, 12 on v2; normalisation fired 0 times); detection
  (2/15, unchanged by the model).
- **Not evidence:** the v1 jump for the mock (3/12 to 10/12) and the in-sample
  numbers: templates were designed against those bugs.
- **Provenance:** 511/511 mock and 418/418 ollama; every Part C freeze hash
  matches and is clean.

### Retrieval: BM25 vs Chroma (19 of 20 natural requirements scored)

| split | backend | queries | hit@1 | hit@3 | MRR |
|---|---|---|---|---|---|
| dev | bm25 | 8 | 0.0% | 37.5% | 0.275 |
| dev | chroma | 8 | 0.0% | 75.0% | 0.374 |
| **test** | **bm25** | 11 | 27.3% | 63.6% | 0.506 |
| **test** | **chroma** | 11 | 18.2% | 63.6% | 0.458 |
| all | bm25 | 19 | 15.8% | 52.6% | 0.408 |
| all | chroma | 19 | 10.5% | 68.4% | 0.422 |

Citation validity over the top 3 hits is 100.0% for both. Neither backend is
clearly better; the default stays BM25. (These BM25 figures differ from the
Part B report. A likely cause, not confirmed by an ablation: the behaviour
contract, which is part of the `project` search collection, grew from about 10,000
to 17,500 characters in Part C (same 24 sections, so the chunk count is
unchanged but each chunk is longer), which shifts BM25 term statistics and
rankings.)

### Appendix: self-consistency (circular by construction)

Expected-response accuracy vs the oracle is 100% by construction: the expected
bytes are produced by the oracle itself, so this is not an independent accuracy
measure and is not a headline metric.

## Part A changes

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

- **Detection on fresh bugs is low: 2/15 (13.3%) generated, in both modes**
  (gold 5/15, union 5/15). 11 of 13 misses have no generated test applying the
  stimulus; 2 apply it but never check the response that exposes the bug.
- **The v1 and in-sample numbers are not evidence.** Held-out v1 is seen (the
  Part C templates were designed against its misses: mock 3/12 to 10/12), and
  the 26 in-sample bugs shaped templates v2 (and the same author wrote bug
  catalog and templates). The v2 sets are now also seen by anyone who reads
  the miss list: any template built from it needs a v3 blind set.
- **Small samples.** 15 bugs and 16 requirements: one item is 6.7 or 6.25
  points. Differences of one or two items are within what chance can produce.
- **Ollama precision is poor.** 0.565 on v2 with 30 false positives (25
  services, 5 DIDs) and 0.500 on the seen v1 test split. The grounding check
  does not cover services, so the precision fix did not work.
- **Rejected planner choices did not fall** (15 on the old 35, 12 on v2);
  normalisation fired 0 times.
- **Ollama noise is measured on three runs only.** Parsed numbers were
  identical; planning and explaining varied (exercised F1 0.583–0.611,
  category recall 74.0%–76.0%, precondition recall 77.8%–85.2%). The mock's
  keyword rules were written by the people who wrote the v1 requirements,
  which is the interpretation's explanation for its low recall (0.225) on the
  unfamiliar v2 phrasing.
- **One small model.** Only `qwen2.5:3b-instruct-q4_K_M` on one 4 GB laptop
  GPU, prompts tuned on 8 dev rows, a 30-option plan shortlist forced by the
  4096-token context. Nothing here says how a larger model or context would do.
- **Synthetic setting.** The ECU spec is synthetic, and the v2 bugs, though
  realistic, were written by a language model; none of the numbers say
  anything about a real vehicle ECU.
- **SWS traceability is partial:** 38 SWS IDs are cited; D1, D3, D4, D8 and
  D9 remain open, so the oracle is not SWS-conformant in those cases. The SWS
  PDF is not in the repo. The simulator, rules engine and gold tests share
  one prose contract, so shared misreadings are possible.
- **Self-consistency is circular.** The expected-response accuracy metric
  (100%) is circular by construction. The meaningful, independent checks are:
  (a) simulator↔oracle byte-for-byte agreement on randomized sequences
  (5000/5000), (b) all 60 gold tests passing against the independently-run
  simulator, and (c) the `udsoncan` client completing a real protocol exchange
  over a virtual CAN bus. Byte provenance (511/511, 418/418) shows that no LLM
  byte reaches a test; it does not show the bytes are right.
- CAPL export output is an unverified template — never compiled or run in
  CANoe (no license available).
- The UI has never been clicked through in a real browser.
- P2/P2* timing checks for the in-process transport are wall-clock on a
  general-purpose desktop OS and are `timing_warning`s rather than hard failures
  for anything but an explicit per-step `max_response_time_ms`
  (`DECISIONS.md [RUN-TIMING]`). CAN-mode timing is not tested for
  time-advance-dependent behaviour.
- Citation validity means a citation points at a retrieved chunk; it does not
  prove the chunk justifies the test.
- Template count (27) exceeds the original PROJECT.md target (8–12); template
  reuse (100% by construction) says nothing about whether 27 is the right size.

## Next steps

1. **Generate the stimuli behind the 11 unapplied v2 bugs**, and **write v3
   blind sets (bugs and requirements) before claiming any improvement**:
   anything built from the v2 miss list makes v2 seen.
2. **Make generated tests check the response that exposes a defect after the
   stimulus** (the two applied-but-undetected v2 bugs).
3. **Service-level grounding:** require each parsed service to be justified by
   a keyword or by the retrieved evidence, to attack the 25 service false
   positives. Not built or measured.
4. **Try a larger model** (or a larger context window on bigger hardware),
   which would also lift the plan-shortlist limit. Re-run the whole comparison
   on a larger fresh requirement set; do not extrapolate from the 3B result.
5. **Fix SWS D1, D3, D4, D8 and D9 if wanted** (`docs/SWS_DISAGREEMENTS.md`),
   coordinated across `rules/`, `simulator/`, `docs/behaviour_contract.md` and
   the gold tests, and evaluate with a fresh bug set.
6. Click through the Streamlit UI in a real browser following
   `docs/UI_CHECKLIST.md` (including the human-review button, `LLM_MODE=ollama`
   and `RETRIEVER=chroma`).
7. Evaluate end-to-end test generation with `RETRIEVER=chroma` (only the
   retrieval step itself was compared so far).
8. Justify or trim the 27-template design size against the original 8–12
   target.
