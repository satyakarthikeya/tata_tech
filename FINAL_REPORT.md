# FINAL_REPORT.md

Honest status of the UDS Diagnostics & Automated Test Generation Assistant at
the end of Part B (real-model evaluation), which follows Part A (honest
evaluation) and the Phase 9 wrap-up. Eval numbers are copied exactly from
`outputs/eval_report.md` / `.json` (report version 2); test counts come from a
fresh `python -m pytest -q` run (Python 3.13.6, Windows, git repo at
`tata_tech`); none are estimated or rounded up.

**Headline.** On the held-out TEST split (n=12 natural requirements) the local
Qwen2.5-3B model (`ollama`) did **not** beat the deterministic mock on any
headline metric. Ollama has higher parsed-target recall (0.880 vs 0.560) but
much lower precision (0.512 vs 0.933; parsed F1 0.647 vs 0.700, exact match 4/12
vs 5/12). Held-out bug detection is **3/12 (25.0%) for both** (generated), gold
3/12, union 5/12, the same three bugs in both modes. Ollama is about 120x
slower (30.8 s vs 0.25 s mean wall-clock per requirement). **The mock stays the
default.** The earlier 25/26 (96.2%) in-sample figure is secondary (templates
were tuned on those bugs); in-sample ollama is 21/26 (80.8%).

## ✅ Done and tested

- Protocol core (`protocol/`): SIDs, NRC table, codec, seed/key security math,
  request builders — cross-checked against `udsoncan`'s own encoding.
- Synthetic BCM ECU spec (`data/bcm_spec.yaml`) + pydantic schema with
  cross-reference validation.
- Rules engine oracle (`rules/`), single NRC-evaluation-order function with a
  citation on every check (`udsoncan behaviour` or a `DECISIONS.md` tag).
- Independent ECU simulator (`simulator/`) — verified by AST check to never
  import `uds_assistant.rules` — with 26 in-sample + 12 held-out injectable
  bugs, in-process and virtual-CAN/ISO-TP transports.
- Simulator/rules-engine agreement property test
  (`tests/simulator/test_agreement.py`, hypothesis, 300 examples + deterministic
  walks): **passed**, no disagreement found. The eval also computes it live:
  5000/5000 (100.0%) requests agreed over 89 seeded walks.
- 60 hand-authored gold tests (`data/gold/gold_tests.yaml`), all passing on the
  bug-free simulator (60/60).
- `udsoncan` client full request/response sequence over a virtual CAN / ISO-TP
  bus: `tests/simulator/test_transport.py::test_udsoncan_full_sequence`
  (PASS in the eval too).
- 23 test templates (`testgen/templates.py` + `templates_v2.py`; v1 14 + v2 9),
  frozen at testgen tree hash `9a121b2742c5f85fa48fd4f5340caf3b85979c67`; byte
  provenance re-checked against a fresh instantiation on every generated test.
- BM25 retrieval with citations (`rag/`), mock LLM (`llm/mock.py`), agent
  pipeline (LangGraph + plain-Python fallback, identical results by
  construction), runner, SQLite audit store, pytest/udsoncan and CAPL
  exporters, FastAPI service.
- **Ollama client against a real server (new in Part B).** `OllamaClient`
  (`llm/client.py`) ran for real against Ollama 0.35.1 with
  `qwen2.5:3b-instruct-q4_K_M`: a 5-requirement smoke run (B2,
  `outputs/ollama_smoke.json`; all completed, 0 JSON failures, 0 retries, 0
  fallbacks) and the full 35-requirement evaluation (B4; 228 LLM calls, 0
  JSON/schema failures, 0 LLM errors, 0 failed runs, 0 fallback events, 0
  truncation events). Real-model smoke tests exist as `needs_model` tests.
- **Chroma + embeddings backend (new in Part B).** `rag/chroma.py` with
  fastembed (`BAAI/bge-small-en-v1.5`, ONNX on CPU) ran for real, and the
  BM25-vs-Chroma retrieval comparison is in the eval report (19 queries).
- **`needs_model` tests: 13 passed** with `RUN_MODEL_TESTS=1` (recorded in
  PROGRESS B4 with Ollama and the embedding stack live; not re-run in B5,
  because the GPU was in use by the owner).
- **Mock vs ollama evaluation** (`python -m uds_assistant.eval.run_eval --mode
  ollama`, 19.2 minutes, exit 0): both modes in one report, byte provenance
  343/343 (mock) and 158/158 (ollama), written interpretation in
  `outputs/eval_interpretation.md`.
- **Streamlit UI, headless.** The UI renders the mock | ollama comparison from
  `outputs/eval_report.json` (side-by-side headline table, understanding per
  mode, held-out per mode, latency, rejections/retries, fallback/truncation
  events, byte provenance, retrieval comparison) and degrades to "n/a" for
  older reports. Covered by headless `streamlit.testing.v1.AppTest` runs. This
  is not a human click-through (see "Written but not fully exercised").
- **Demo script.** `scripts/demo.py` prints both modes' recorded numbers and
  has `--llm ollama`, which falls back to the mock with a printed warning (the
  fallback path is tested against a closed port, so no Ollama or GPU is
  touched in tests).
- Full test suite (default, model tests skipped): **912 passed, 13 skipped in
  218.26s (0:03:38)** (`python -m pytest -q`). The 13 skips are `needs_model`
  tests, skipped by design, not deleted.
- `python -m ruff check .` → **All checks passed!**
- `outputs/eval_report.{json,md}` from `python -m uds_assistant.eval.run_eval
  --mode ollama` (which also ran mock), template set v2, 15 seed requirements,
  20 natural requirements, 60 gold tests, 12 held-out + 26 in-sample bugs.

## ⚠️ Written but not fully exercised

- **Streamlit UI with a human.** Only headless AppTest runs exist (including
  the new comparison tests). Nobody has clicked through generate → review → run
  → export interactively, and the UI's generate button was not run live with
  `LLM_MODE=ollama` or `RETRIEVER=chroma`.
- **Chroma retrieval inside the generation pipeline.** The retrieval
  comparison measured Chroma against BM25 as a retriever. The mock-vs-ollama
  evaluation used BM25 for both modes; no end-to-end test-generation run used
  `RETRIEVER=chroma`, so its effect on generated tests was not measured.
- **`EMBEDDER=sentence-transformers`.** Implemented as an optional path;
  `sentence-transformers` and `torch` are not installed, so it was never run.
- **Ollama run-to-run variability.** The ollama column is a single full run.
  Greedy decoding on the GPU is not bit-reproducible (about ±0.05 F1 between
  identical runs, measured in B3), and no repeat of the full evaluation was done.
- **`MODEL_SETUP.md`** was updated to match what was actually run (Ollama,
  fastembed, chromadb, 4 GB settings), but the Windows installer steps in
  section 1 were not re-executed in B5; the owner's machine already had Ollama
  installed (B0).
- CAPL exports (see Not done).

## ❌ Not done

- CAPL exports are unverified templates — no CANoe license available, per
  `SCOPE.md` ("out of scope: verifying CAPL in CANoe").
- The 9 rules-engine vs AUTOSAR Dcm SWS disagreements (D1-D9,
  `docs/SWS_DISAGREEMENTS.md`) are documented, **not fixed**.
- No larger model than the 3B was tried, and no model beat the mock: the LLM
  path is viable and safe but not an improvement.
- The two known fixable failure modes of the 3B model (the copied "(category)"
  suffix in `template_id`, the copied example DID 0x0140) were identified but
  deliberately not fixed, because prompts and agent code were frozen before the
  test split was run.
- Template improvements against the 9 missed held-out bugs (would need a new
  held-out bug set).
- DoIP, OBD-II, flashing (0x34/0x36/0x37 download), 0x29 authentication,
  real ECUs/vehicles, cloud/paid LLMs, fine-tuning — all explicitly out of
  scope per `SCOPE.md` and not attempted.

## Test counts

Full suite: `python -m pytest -q` → **912 passed, 13 skipped in 218.26s
(0:03:38)**. `ruff check .` → clean. Per-directory collection counts
(`python -m pytest --collect-only -q tests/<dir>`):

| Directory | Tests |
|---|---|
| `tests/rules/` | 216 |
| `tests/testgen/` | 160 |
| `tests/simulator/` | 120 |
| `tests/agent/` | 104 |
| `tests/protocol/` | 73 |
| `tests/llm/` | 69 |
| `tests/rag/` | 61 |
| `tests/eval/` | 50 |
| `tests/api/` | 18 |
| `tests/spec/` | 14 |
| `tests/runner/` | 11 |
| `tests/ui/` | 10 |
| `tests/store/` | 7 |
| `tests/export/` | 6 |
| `tests/test_config.py` | 3 |
| `tests/scripts/` | 3 |
| **Total collected** | **925** |

(925 collected = 912 passed + 13 skipped, consistent with the full-suite run.)
The 13 skipped are the `needs_model` tests; run with `RUN_MODEL_TESTS=1` they
gave 13 passed in B4 (not repeated in B5). AUTOSAR SWS tests skip without the
local PDF; it was present on the machine that produced these numbers.

## Evaluation numbers (mock and ollama)

From `outputs/eval_report.md` (generated 2026-10-03, git `a6a311f`, template set
v2, 23 templates, Bm25Retriever, LangGraph engine; ollama = `qwen2.5:3b-instruct-q4_K_M`,
num_ctx 4096, temperature 0, keep_alive 10m). Both columns come from one
invocation on the same inputs.

### Headline table

| Metric | mock | ollama |
|---|---|---|
| 1. Simulator ↔ rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 2. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 3. udsoncan virtual-CAN sequence | PASS | same (LLM-independent) |
| **4. Held-out bug detection (12 bugs; HEADLINE = generated)** | **generated 3/12 (25.0%)** · gold 3/12 (25.0%) · union 5/12 (41.7%) | **generated 3/12 (25.0%)** · gold 3/12 (25.0%) · union 5/12 (41.7%) |
| 5. Requirement understanding (natural requirements, test split n=12) | target exact match parsed 5/12 (F1 0.700), exercised 2/12 (F1 0.449); category recall 67.9% micro / 69.7% macro; precondition recall 80.0% micro / 75.0% macro; fallback/nothing 3/12 (2 excl. NAT-020-style empty-label rows) | target exact match parsed 4/12 (F1 0.647), exercised 0/12 (F1 0.435); category recall 64.3% micro / 64.4% macro; precondition recall 73.3% micro / 75.0% macro; fallback/nothing 1/12 (1 excl. NAT-020-style empty-label rows) |
| 6. Coverage (seed requirements) | positive 36, negative 70, session 21, security 18, timing 26; 15/15 requirements with ≥1 test (100.0%) | positive 29, negative 19, session 7, security 8, timing 5; 15/15 requirements with ≥1 test (100.0%) |
| 7. Citation validity | 774/774 (100.0%) | 335/335 (100.0%) |

### Mock vs ollama detail (test split n=12 unless stated)

| Metric | mock | ollama |
|---|---|---|
| Parsed targets P / R / F1 (micro) | 0.933 / 0.560 / 0.700 | 0.512 / 0.880 / 0.647 |
| Parsed targets tp / fp / fn | 14 / 1 / 11 | 22 / 21 / 3 |
| Exercised targets P / R / F1 | 0.312 / 0.800 / 0.449 | 0.298 / 0.800 / 0.435 |
| Category recall hit/required | 19/28 (67.9%) | 18/28 (64.3%) |
| Precondition recall hit/required | 12/15 (80.0%) | 11/15 (73.3%) |
| Dev split (n=8; prompts tuned on it, not evidence) parsed exact / F1 | 4/8 / 0.828 | 1/8 / 0.683 |
| Held-out generated / gold / union (12 bugs) | 3/12 / 3/12 / 5/12 | 3/12 / 3/12 / 5/12 |
| In-sample (26 bugs) generated / gold / union | 25/26 / 24/26 / 26/26 | 21/26 / 24/26 / 26/26 |
| Generated tests, seed requirements | 171 | 68 |
| Planner choices rejected (35 requirements) | 0 | 10 |
| Re-plans (retries) / JSON failures / LLM errors | 0 / 0 / 0 | 0 / 0 / 0 |
| Fallback-to-mock events / truncation events | 0 / 0 | 0 / 0 |
| LLM calls | 413 | 228 |
| Wall-clock per requirement, mean / p95 / max (35) | 0.254 s / 0.445 s / 0.510 s | 30.785 s / 43.405 s / 49.394 s |
| Byte provenance, all generated tests | 343/343 | 158/158 |

### Held-out detail

- Both modes: generated 3/12 (25.0%), gold 3/12 (25.0%), union 5/12 (41.7%);
  invalid tests (fail on the clean simulator): generated 0, gold 0.
- Generated suites (both modes) detected: `failed_attempts_reset_by_seed_request`,
  `s3_not_refreshed_by_tester_present`, `session_suppress_bit_not_masked`. Gold
  detected: `failed_attempts_reset_by_seed_request`,
  `seed_returned_while_unlocked`, `uint16_did_stored_byte_swapped`.
- For each of the 9 bugs the generated suite missed, the static trigger
  analysis (`uds_assistant/eval/heldout.py`) shows no generated test even
  applies the stimulus the bug needs. That is a template-coverage gap, not a
  validation problem, and it is shared by both modes because they share the
  templates. The ollama suite is 2.5x smaller (68 vs 171 tests) and lost no
  held-out detection, but gained none.

### Interpretation (condensed from `outputs/eval_interpretation.md`)

- **Better:** parsed-target recall (0.880 vs 0.560); exact parses on NAT-002,
  NAT-006, NAT-008, NAT-016 where the keyword mock missed implied session or
  security services; fewer empty runs (1 vs 3 on the test split).
- **Worse:** parsed precision (21 false positives vs 1) because the model
  invents identifiers (example DID 0x0140 copied into NAT-012/014/017;
  0x10/0x27/0x2E added to rows that never name them; 5 tests on the empty-label
  NAT-020 where the mock correctly made none); exact match, F1, category and
  precondition recall; exercised exact match 0/12 vs 2/12; in-sample detection
  (also missed `routine_stop_without_start`, `dtc_clear_ignores_group`,
  `dtc_clear_noop`, `dtc_read_ignores_mask`).
- **Equal:** held-out detection, request validity, clean-simulator pass rate,
  citation validity, byte provenance (all 100% where applicable).
- **Validation evidence:** all 10 rejected planner choices were template ids not
  in the catalog (invented names, and the "(category)" suffix copied into
  `template_id`; NAT-012 lost all 4 choices this way and produced the run's only
  zero-test requirement). The validator caught every one.
- **Context budget:** no prompt was truncated. The cost is the 24-option
  shortlist (at most 4 per template, against the 154-option catalog the mock
  sees) and the selective rev-8 plan instruction.
- **Latency:** explain dominates at 19.4 s mean per requirement (one call per
  kept test); plan 7.0 s, parse 4.2 s; the ollama run took about 18 minutes.

### Retrieval: BM25 vs Chroma (19 of 20 natural requirements scored)

| split | backend | queries | hit@1 | hit@3 | MRR |
|---|---|---|---|---|---|
| dev | bm25 | 8 | 0.0% | 37.5% | 0.271 |
| dev | chroma | 8 | 0.0% | 75.0% | 0.374 |
| **test** | **bm25** | 11 | 36.4% | 63.6% | 0.552 |
| **test** | **chroma** | 11 | 18.2% | 63.6% | 0.462 |
| all | bm25 | 19 | 21.1% | 52.6% | 0.434 |
| all | chroma | 19 | 10.5% | 68.4% | 0.425 |

Citation validity over the top 3 hits is 100.0% for both. Neither backend is
clearly better; the default stays BM25.

### Secondary: in-sample bug detection (templates tuned on these)

- 26 bugs, mock: generated **25/26 (96.2%)**, gold 24/26 (92.3%), union 26/26
  (100.0%). Optimistic and non-independent (see Known limitations). Ollama:
  generated 21/26 (80.8%).
- Baseline (template set v1, 14 templates): generated 17/26 (65.4%); rose to
  25/26 after the 9 v2 templates were added in Phase 7.
- Mock: 171 generated tests (94 unique template instantiations); 171/171
  (100.0%) pass on the clean simulator. Ollama: 68/68 (100.0%).
- Request validity: mock 445/445 (100.0%), ollama 192/192 (100.0%), after
  exempting intentional format-NRC probes.

### Appendix: self-consistency (circular by construction)

Expected-response accuracy vs the oracle is 100% by construction: the expected
bytes are produced by the oracle itself, so this is not an independent accuracy
measure and is not a headline metric.

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
- **A3: metrics cleanup.** The headline is a 7-row table. The oracle
  self-consistency number moved to an appendix (circular); simulator↔rules
  agreement and the udsoncan virtual-CAN sequence are computed live in the eval
  (`--skip-can` skips the latter, for fast runs); in-sample numbers are
  labelled.
- **A4: SWS citations + disagreements.** The rules engine cites 38 distinct
  AUTOSAR CP R24-11 Dcm SWS IDs. Nine differences from the SWS (D1-D9) are
  documented in `docs/SWS_DISAGREEMENTS.md` and **deliberately not fixed**:
  changing the oracle would require coordinated changes to the independent
  simulator, `docs/behaviour_contract.md`, and the frozen gold and template
  data. D2, D5, D6 and D7 are the ones to fix first. The AUTOSAR PDF is
  git-ignored (AUTOSAR terms do not allow redistribution); the owner keeps a
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

## Part B changes

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

## Deviations from docs

- Python 3.13.6 used instead of the originally documented 3.11 (PROJECT.md now
  says 3.13) (only interpreter available); code kept 3.11-syntax-compatible.
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
  in-process (`DECISIONS.md [RUN-TIMING]`) — see Known limitations.
- `streamlit` was installed (1.64.0) despite being in the "install only if pip
  is responsive" bucket of `SCOPE.md` (`DECISIONS.md [UI-STREAMLIT-INSTALL]`).
- Part B: the owner lifted the offline rule for chromadb, fastembed and the
  embedding model only; `onnxruntime` (on `AGENT.md`'s never-install list) came
  in as a required dependency (`DECISIONS.md [PB-INSTALL]`).
- Part B: the ollama plan prompt differs from the mock's: it uses a compact
  shortlist because of the 4096-token window, while the mock keeps the
  full-catalog prompt byte for byte (`DECISIONS.md [PB-CTX-BUDGET]`).

## Known limitations

- **The in-sample generated-suite bug-detection rate (25/26, 96.2%) is
  optimistic and not independent.** The 9 v2 templates were added in Phase 7
  specifically after inspecting which bugs the v1 templates (17/26, 65.4%)
  missed, and the same author wrote both the bug catalog and the templates.
  The held-out result (generated 3/12, 25.0%) is the honest number. Gold is no
  better on held-out (3/12); the union is 5/12 (41.7%). The held-out set is
  small (12), and it has been seen: further template work against it would make
  it in-sample too.
- **The ollama result is a small-sample, single-run result.** The test split has
  n=12 (one requirement moves exact match by 8.3 points); greedy GPU decoding is
  not bit-reproducible (about ±0.05 F1 between identical runs), so the
  parsed-F1 gap (0.647 vs 0.700, Δ 0.053) is at the edge of noise, while the
  precision gap (0.512 vs 0.933) is far outside it.
- **The prompts were tuned on only 8 dev rows**, so overfitting to them is
  plausible (dev exact match was only 1/8). The test split was run in ollama
  mode once, after the freeze.
- **The plan-context shortlist.** To fit 4096 tokens the planner sees at most 24
  options (4 per template) instead of all 154, so the ollama column measures "3B
  model with a shortlist", not "3B model with the full catalog".
- **One small model.** Only `qwen2.5:3b-instruct-q4_K_M` on one 4 GB laptop GPU
  was evaluated. Nothing here says how a larger model or a larger context would
  do.
- **Mock favoured on precision.** The mock's keyword rules were written by the
  author who also labelled the requirements; the synthetic phrasing of the 20
  natural requirements may favour them.
- **Held-out misses are template gaps in both modes.** Both modes share the
  templates, so a better planner cannot fix them; 9 of 12 held-out bugs have no
  generated test applying the needed stimulus.
- **Requirement understanding is weak in both modes** (test split: parsed exact
  5/12 mock, 4/12 ollama; exercised exact 2/12 and 0/12).
- **Self-consistency is circular.** The expected-response accuracy metric
  (100%) is circular by construction: expected bytes come from the oracle
  itself. The meaningful, independent checks are: (a) simulator↔oracle
  byte-for-byte agreement on randomized sequences (5000/5000, no
  disagreement), (b) all 60 gold tests passing against the independently-run
  simulator, and (c) the `udsoncan` client completing a real protocol exchange
  over a virtual CAN bus. Byte provenance (343/343, 158/158) shows that no LLM
  byte reaches a test; it does not show the bytes are right.
- SWS traceability is partial: 38 SWS IDs are cited, but 9 documented
  disagreements (D1-D9) remain unfixed, so the oracle is not SWS-conformant in
  those cases. The SWS PDF is not in the repo.
- The ECU spec is entirely synthetic; none of the numbers say anything about a
  real vehicle ECU.
- CAPL export output is an unverified template — never compiled or run in
  CANoe (no license available).
- P2/P2* timing checks for the in-process transport are wall-clock on a
  general-purpose desktop OS and are `timing_warning`s rather than hard failures
  for anything but an explicit per-step `max_response_time_ms`
  (`DECISIONS.md [RUN-TIMING]`). CAN-mode timing is not tested for
  time-advance-dependent behaviour.
- Citation validity means a citation points at a retrieved chunk; it does not
  prove the chunk justifies the test.
- Template count (23) exceeds the original PROJECT.md target (8–12); template
  reuse (100% by construction) says nothing about whether 23 is the right size.

## Next steps

1. **Strip the "(category)" suffix before validation.** The 3B model copies it
   into `template_id` (all 10 rejected choices were bad template ids; NAT-012
   lost all 4 and produced zero tests). This is a small, safe pipeline change
   (`[PB-B3-RISK]`), deliberately deferred because of the freeze.
2. **Suppress example DID copying.** The parse prompt's example DID 0x0140 shows
   up in unrelated requirements (NAT-012, NAT-014, NAT-017); remove or
   neutralise the example to attack the precision collapse.
3. **Batch the explain calls.** Explain is 19.4 s of the 30.8 s mean per
   requirement (one LLM call per kept test); batching would cut latency
   substantially.
4. **Consider a larger model** (or a larger context window on bigger hardware),
   which would also lift the 24-option shortlist limit. Re-run the whole
   comparison; do not extrapolate from the 3B result.
5. **Fix the SWS disagreements D2, D5, D6 and D7**
   (`docs/SWS_DISAGREEMENTS.md`), coordinated across `rules/`, `simulator/`,
   `docs/behaviour_contract.md` and the gold tests, and evaluate with a **new
   held-out bug set** that nobody has seen; then re-run agreement and the full
   eval.
6. **Template improvements** for the 9 missed held-out bugs only with that new
   held-out bug set; the current 12 are in-sample for any such change.
7. **A new held-out requirement set before claiming any improvement** from items
   1 to 4: the current test split (n=12) has been seen once, and after fixes
   targeting its failures it is no longer independent. Repeat runs to measure
   GPU noise.
8. Click through the Streamlit UI interactively with a human (generate → review
   → run → export), including with `LLM_MODE=ollama` and `RETRIEVER=chroma`.
9. Evaluate end-to-end test generation with `RETRIEVER=chroma` (only the
   retrieval step itself was compared so far).
10. Justify or trim the 23-template design size against the original 8–12
    target.
