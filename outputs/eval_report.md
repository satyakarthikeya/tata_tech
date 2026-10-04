# Evaluation report — UDS test generation assistant

- **Generated:** 2026-10-04T08:15:23.200078+00:00 (git `1f0c293a2033da0e4316197341c814d10aa16b1f`, uncommitted changes present)
- **LLM mode used:** `ollama` (requested `ollama`)
- **Modes evaluated in this invocation:** `mock`, `ollama`
- **Agent engine:** `langgraph` · **Retriever:** `Bm25Retriever`
- **Template set:** `v3` (27 templates)
- **Inputs:** 15 seed requirements, 16 natural v3 (FRESH) + 16 natural v2 (seen) + 20 natural v1 (seen) labelled requirements, 60 gold tests, 15 held-out v3 (FRESH) + 15 held-out v2 (seen) + 12 held-out v1 (seen) + 26 in-sample injectable simulator bugs
- **Ollama settings:** model `qwen2.5:3b-instruct-q4_K_M`, num_ctx 4096, temperature 0, keep_alive `10m`
- **Byte provenance:** all generated tests re-instantiate byte-identically from their templates

> **The ECU spec is synthetic.** `data/bcm_spec.yaml` describes a fictional Body Control Module written for this project in an OEM-like style; no real OEM document or ISO 14229 text is used. All numbers below are measured against the project's own simulator.
>
> **Modes:** `mock` is a deterministic keyword/rule stand-in; `ollama` is the local Qwen2.5-3B model. Both columns come from this single invocation, on the same inputs, templates and retriever. LLM-independent rows are identical for both.

> **Template set v3:** v2 + 4 generic templates (malformed 0x22 lengths, seed request while unlocked, routine status across session change / ECU reset, written DID value byte order + retention across S3 timeout / ECU reset) and new parameter variants of 3 templates (lockout + ECU reset, precondition failing while locked, routine start with the suppress bit). Added in Part C3 from the static stimulus analysis of the held-out v1 misses, so v1 held-out numbers after v3 are 'seen'; only fresh held-out sets measure v3 fairly.

## Headline metrics

| Metric | mock | ollama |
|---|---|---|
| **1. FRESH HEADLINE — Held-out v3 bugs (15 fresh bugs): detection by the system's FULL OUTPUT = requirement-driven tests ∪ conformance sweep** | **10/15 (66.7%)** | **9/15 (60.0%)** |
| 1a. (a) requirement-driven tests only (the Part C 'generated' suite) | 4/15 (26.7%) | 2/15 (13.3%) |
| 1b. (b) conformance sweep alone (LLM-independent) | 9/15 (60.0%) | 9/15 (60.0%) |
| 1c. gold tests (LLM-independent) | 3/15 (20.0%) | 3/15 (20.0%) |
| 1d. suite sizes (tests) | requirement-driven 206 · sweep 1200 · full output 1406 · gold 60 | requirement-driven 73 · sweep 1200 · full output 1273 · gold 60 |
| 1e. missed by the headline suite (the full output; requirement-driven if the sweep was skipped) | `session_switch_keeps_pending_seed`, `lockout_expiry_resets_attempt_count`, `nrc_order_subfunction_before_length`, `read_did_speed_not_clamped`, `dtc_read_reports_masked_status` | `session_switch_keeps_pending_seed`, `lockout_expiry_resets_attempt_count`, `nrc_order_subfunction_before_length`, `read_did_speed_not_clamped`, `dtc_clear_single_clears_neighbour`, `dtc_read_reports_masked_status` |
| 1f. supplementary: v3 bugs detected by other suites | all generated tests (seed + natural v1 + v2 + v3) 4/15 (26.7%), 613 tests; natural-v3 tests alone 4/15 (26.7%), 102 tests | all generated tests (seed + natural v1 + v2 + v3) 4/15 (26.7%), 368 tests; natural-v3 tests alone 2/15 (13.3%), 94 tests |
| **2. FRESH HEADLINE — Requirement understanding, natural v3 (split test3)** | test3 (n=16): parsed exact 1/16, P/R/F1 0.857/0.267/0.407; exercised exact 0/16, F1 0.342; category recall 42.0% micro / 39.6% macro; precondition recall 48.3% micro / 44.9% macro; fallback/nothing 7/16 (7 excl. empty-label rows) | test3 (n=16): parsed exact 2/16, P/R/F1 0.596/0.622/0.609; exercised exact 0/16, F1 0.472; category recall 70.0% micro / 72.2% macro; precondition recall 89.7% micro / 91.0% macro; fallback/nothing 0/16 (0 excl. empty-label rows) |
| 2a. natural v3: parsed false positives / false negatives by kind | FP [service 2]; FN [service 24, did 8, routine 1] | FP [service 15, did 4]; FN [service 9, did 5, routine 3] |
| 2b. natural v3: rejected planner choices by reason | 0 (none) | 0 (none) |
| 2c. natural v3: run-to-run noise check | deterministic: 1 run + equality re-run (identical = True) | 3 runs, mean (min–max) over ALL runs: parsed F1 0.609 (0.609–0.609); category recall 70.0% (70.0%–70.0%); precondition recall 89.7% (89.7%–89.7%) |
| 3. Simulator ↔ rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 4. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 5. udsoncan virtual-CAN sequence (session → seed/key → read → write → read-back) | PASS | same (LLM-independent) |
| 6. Coverage (seed requirements; tests per category) | positive 43, negative 77, session 25, security 30, timing 31; requirements with ≥1 test 15/15 (100.0%) | positive 26, negative 27, session 4, security 7, timing 9; requirements with ≥1 test 15/15 (100.0%) |
| 7. Citation validity | 967/967 (100.0%) | 353/353 (100.0%) |
| 8. Conformance sweep (size, time, runtime; no LLM) | 1200 tests (15722 steps), generated in 6.944 s, clean run 1.075 s, bug-matrix runtime 85.197 s over all catalogs; 1200/1200 pass on the clean simulator; byte provenance OK | same (LLM-independent) |
| 9. Held-out v2 bug detection (15 bugs) — **SEEN (Part C headline; its results were known before Part D)** | generated 2/15 (13.3%) · gold 5/15 (33.3%) · union 5/15 (33.3%) | generated 2/15 (13.3%) · gold 5/15 (33.3%) · union 5/15 (33.3%) |
| 9a. held-out v2 (SEEN): full output = requirement-driven ∪ sweep | 9/15 (60.0%) | 9/15 (60.0%) |
| 10. Requirement understanding, natural v2 (split test2) — **SEEN** | test2 (n=16): parsed exact 0/16, P/R/F1 1.000/0.225/0.367; exercised exact 0/16, F1 0.450; category recall 48.0% micro / 48.9% macro; precondition recall 55.6% micro / 53.8% macro; fallback/nothing 7/16 (6 excl. empty-label rows) | test2 (n=16): parsed exact 4/16, P/R/F1 0.808/0.775/0.792; exercised exact 0/16, F1 0.639; category recall 72.0% micro / 72.0% macro; precondition recall 92.6% micro / 95.5% macro; fallback/nothing 0/16 (0 excl. empty-label rows) |
| 11. Held-out v1 bug detection (12 bugs) — **SEEN (templates designed against these misses)** | generated 10/12 (83.3%) · gold 3/12 (25.0%) · union 11/12 (91.7%) | generated 8/12 (66.7%) · gold 3/12 (25.0%) · union 9/12 (75.0%) |
| 11a. held-out v1 (SEEN): full output | 12/12 (100.0%) | 11/12 (91.7%) |
| 12. Requirement understanding, natural v1 test split — **SEEN** | test split (n=12): parsed exact 5/12, P/R/F1 0.933/0.560/0.700; exercised exact 2/12, F1 0.425; category recall 67.9% micro / 69.7% macro; precondition recall 80.0% micro / 75.0% macro; fallback/nothing 3/12 (2 excl. empty-label rows) | test split (n=12): parsed exact 5/12, P/R/F1 0.690/0.800/0.741; exercised exact 1/12, F1 0.489; category recall 75.0% micro / 78.0% macro; precondition recall 93.3% micro / 87.5% macro; fallback/nothing 1/12 (0 excl. empty-label rows) |
| 13. Requirement understanding, natural v1 dev split — **dev (tuned on)** | dev split (n=8): parsed exact 4/8, P/R/F1 1.000/0.706/0.828; exercised exact 0/8, F1 0.471; category recall 68.2% micro / 63.5% macro; precondition recall 100.0% micro / 100.0% macro; fallback/nothing 1/8 (1 excl. empty-label rows) | dev split (n=8): parsed exact 5/8, P/R/F1 0.929/0.765/0.839; exercised exact 0/8, F1 0.576; category recall 68.2% micro / 67.7% macro; precondition recall 100.0% micro / 100.0% macro; fallback/nothing 0/8 (0 excl. empty-label rows) |
| 14. In-sample bug detection (26 bugs) — **in-sample (templates tuned on these)** | generated 25/26 (96.2%) · gold 24/26 (92.3%) · union 26/26 (100.0%) | generated 21/26 (80.8%) · gold 24/26 (92.3%) · union 25/26 (96.2%) |
| 14a. in-sample (tuned on): full output | 26/26 (100.0%) | 26/26 (100.0%) |

Rows 1-2 are the FRESH HEADLINE: both v3 data sets were written blind, after the Part D freeze, and nothing was tuned on them. The bug headline is the system's FULL OUTPUT (requirement-driven tests plus the conformance sweep, per bug); rows 1a-1c report its parts separately so Part C numbers stay comparable. Rows 3-5, 8 and the gold figures do not depend on the LLM; everything else is measured per mode. Rows 9-14 are SEEN or tuned-on sets (v1 and v2 results were known when Part D was designed; the natural v1 dev split shaped the prompts; the 26 in-sample bugs shaped the templates) and are not independent evidence. The self-consistency check (expected responses vs the oracle that produced them) is in the appendix.

## Part D — conformance sweep and full-output bug detection

_Part D rows. The existing headline above keeps its Part C meaning (requirement-driven suite). (a) = requirement-driven tests from the 15 seed requirements (the Part C 'generated' suite); (b) = the requirement-independent conformance sweep alone; (c) = the system's full output, (a) ∪ (b). The conformance sweep is generated from the spec alone, uses no LLM and is identical in every mode; only (a), and therefore (c), depend on the mode._

| Bug set | mock: (a) / (b) / (c) / gold | ollama: (a) / (b) / (c) / gold |
|---|---|---|
| heldout_v2: held-out v2 (15 bugs, SEEN: their Part C results were known before Part D) | 2/15 / 9/15 / **9/15** / 5/15 | 2/15 / 9/15 / **9/15** / 5/15 |
| heldout_v1: held-out v1 (12 bugs, SEEN) | 10/12 / 10/12 / **12/12** / 3/12 | 8/12 / 10/12 / **11/12** / 3/12 |
| in_sample: in-sample (26 bugs, templates tuned on these) | 25/26 / 26/26 / **26/26** / 24/26 | 21/26 / 26/26 / **26/26** / 24/26 |
| heldout_v3: held-out v3 (FRESH, written blind after the Part D freeze) | 4/15 / 9/15 / **10/15** / 3/15 | 2/15 / 9/15 / **9/15** / 3/15 |

- mock / heldout_v2: missed by the full output: `s3_restart_skipped_on_negative_response`, `s3_timeout_resets_lockout_counters`, `lockout_counter_pooled_across_levels`, `nrc_order_nvm_fault_before_group_check`, `routine_restart_after_stop_blocked`, `suppressed_seed_request_not_stored`; only the sweep: 7, only requirement-driven: 0.
- mock / heldout_v1: missed by the full output: none; only the sweep: 2, only requirement-driven: 2.
- mock / in_sample: missed by the full output: none; only the sweep: 1, only requirement-driven: 0.
- mock / heldout_v3: missed by the full output: `session_switch_keeps_pending_seed`, `lockout_expiry_resets_attempt_count`, `nrc_order_subfunction_before_length`, `read_did_speed_not_clamped`, `dtc_read_reports_masked_status`; only the sweep: 6, only requirement-driven: 1.
- ollama / heldout_v2: missed by the full output: `s3_restart_skipped_on_negative_response`, `s3_timeout_resets_lockout_counters`, `lockout_counter_pooled_across_levels`, `nrc_order_nvm_fault_before_group_check`, `routine_restart_after_stop_blocked`, `suppressed_seed_request_not_stored`; only the sweep: 7, only requirement-driven: 0.
- ollama / heldout_v1: missed by the full output: `nrc_order_condition_before_security`; only the sweep: 3, only requirement-driven: 1.
- ollama / in_sample: missed by the full output: none; only the sweep: 5, only requirement-driven: 0.
- ollama / heldout_v3: missed by the full output: `session_switch_keeps_pending_seed`, `lockout_expiry_resets_attempt_count`, `nrc_order_subfunction_before_length`, `read_did_speed_not_clamped`, `dtc_clear_single_clears_neighbour`, `dtc_read_reports_masked_status`; only the sweep: 7, only requirement-driven: 0.

- **Conformance sweep:** 1200 tests (15722 steps), template `conformance_case` (not offered to the planner); 54 setups x 215 stimuli = 11610 candidates, cap 1200.
- **Generation time:** 6.944 s (selection 2.251 s, instantiation + oracle validation 4.692 s).
- **Clean simulator:** 1200/1200 pass.
- **Byte provenance (conformance):** 1200/1200 OK.
- **Bug-matrix runtime (conformance sweep):** heldout_v2 19.091 s, heldout_v1 15.244 s, in_sample 31.624 s, heldout_v3 19.238 s; total 85.197 s.

Selection phases (greedy covering, see metric definitions):

| Phase | item kinds | items | covered | tests added |
|---|---|---|---|---|
| 1 | pair, stim_resp | 1034 | 1034 | 745 |
| 2 | effect, transition | 2038 | 1336 | 455 |
| 3 | stim_session | 1012 | 696 | 0 |
| 4 | fine_transition | 2694 | 921 | 0 |

Selected tests by stimulus family (service) and by setup dimension:

| family | tests |
|---|---|
| 10 | 107 |
| 11 | 91 |
| 14 | 84 |
| 19 | 103 |
| 22 | 120 |
| 23 | 8 |
| 24 | 1 |
| 27 | 190 |
| 2e | 215 |
| 31 | 184 |
| 3e | 89 |
| other | 8 |

| setup dimension | tests |
|---|---|
| did_value | 63 |
| dtc | 27 |
| environment | 81 |
| lockout | 106 |
| power_on | 134 |
| reset | 18 |
| routine | 57 |
| security | 145 |
| session | 190 |
| session_change | 18 |
| timing | 361 |

## Interpretation: where the LLM helped and where it didn't

### Summary (Part D, fresh v3 data)

All numbers come from one run of `python -m uds_assistant.eval.run_eval --mode ollama --noise-runs 3 --before-after` (mock and the local Qwen2.5-3B model on the same inputs). The v3 sets are fresh: 15 bugs and 16 requirements, each written blind by a subagent after the Part D freeze. Nothing was changed after their results were seen, and every freeze hash still matches. The v1 and v2 sets are seen and appear only as context.

1. **Bug detection on fresh bugs went up, and almost all of the gain comes from the conformance sweep.** The system's full output (requirement-driven tests plus the sweep) catches 10/15 (66.7%) with mock and 9/15 (60.0%) with ollama. The requirement-driven tests alone catch 4/15 (mock) and 2/15 (ollama), the sweep alone 9/15 in both modes, and the gold tests 3/15. The Part C headline on v2 was 2/15, but that was a different bug set, so it is a reference point and not a before/after pair.
2. **The sweep does not depend on the model, and it is cheap.** 1200 tests, generated from the spec in about 7 s, all 1200 pass on the clean simulator, and the bug matrix over all four catalogs took 85 s. It caught 9/15 on seen v2 and 9/15 on fresh v3, so the rate did not drop on bugs written after the freeze.
3. **The model still adds little to bug detection.** With the sweep included, mock is one bug ahead of ollama (10 against 9). The extra bug is `dtc_clear_single_clears_neighbour`, which only the mock's larger requirement-driven suite catches.
4. **Requirement understanding on fresh v3 is better with the model than with the mock, as in Part C, but precision is still poor.** Parsed P/R/F1 is 0.596/0.622/0.609 for ollama and 0.857/0.267/0.407 for mock; category recall is 70.0% against 42.0% and precondition recall 89.7% against 48.3%. Exact parsed match is 2/16 against 1/16. Ollama has 19 false positives (service 15, DID 4) and 17 false negatives (service 9, DID 5, routine 3).
5. **Rejected planner choices went to zero.** Ollama had 15 rejections on the 35 old requirements and 12 on v2 in Part C. It now has 0 on every set, including fresh v3. The likely cause is constrained decoding (the planner can only emit offered options); no ablation was run to confirm it.

### Held-out v3 bug detection (15 bugs, fresh): the headline

| Suite | mock | ollama |
|---|---|---|
| **Full output (requirement-driven + sweep)** | **10/15 (66.7%)** | **9/15 (60.0%)** |
| (a) requirement-driven only (the Part C "generated" suite) | 4/15 (26.7%) | 2/15 (13.3%) |
| (b) conformance sweep alone | 9/15 (60.0%) | 9/15 (60.0%) |
| Gold | 3/15 (20.0%) | 3/15 (20.0%) |
| Tests (requirement-driven / sweep / full) | 206 / 1200 / 1406 | 73 / 1200 / 1273 |

- **Missed by the full output (5 bugs with mock, 6 with ollama).** For each, no test applies the stimulus.
  - `session_switch_keeps_pending_seed`: no test requests a seed, switches session with a positive `10 xx`, then sends a key for that level.
  - `lockout_expiry_resets_attempt_count`: no test reaches a lockout, waits for the delay to expire, requests a seed and sends another wrong key.
  - `nrc_order_subfunction_before_length`: no test sends `10`, `11` or `3E` with an unsupported sub-function and a wrong total length.
  - `read_did_speed_not_clamped`: no test reads DID 0x0140 while the vehicle speed is above 255 kph.
  - `dtc_read_reports_masked_status`: no test reads DTCs where a listed DTC has status bits outside the request mask.
  - ollama only: `dtc_clear_single_clears_neighbour` (no test clears one DTC while the next one is stored and reads back with a mask that shows it).
- **Found by the sweep and not by the requirement-driven tests (6 bugs with mock, 7 with ollama).** For example `failed_key_keeps_pending_seed`, `nrc_order_write_range_before_condition`, `routine_results_trailing_bytes_accepted`, `write_stores_value_before_range_rejection`, `s3_timeout_clears_dtc_status`, `suppressed_request_does_not_restart_s3`. The seed requirements never ask for these stimuli; the sweep applies them without being asked.
- **Gold is lowest (3/15).** The hand-written gold set was written before any v3 bug existed and covers the seed requirements, not systematic state and mutation probing.
- **Caveats.** 15 bugs: one bug is 6.7 points, so a one-bug difference between modes is not evidence of a difference. The bugs were written by a language model. The sweep's expected bytes come from the rules engine, which is also what the simulator is checked against, so a shared misreading would be invisible to both.

### Requirement understanding on natural v3 (16 requirements, fresh): the headline

| Metric | mock | ollama (run 1) | ollama mean over 3 runs (min-max) |
|---|---|---|---|
| Parsed exact | 1/16 | 2/16 | - |
| Parsed P / R / F1 | 0.857 / 0.267 / 0.407 | 0.596 / 0.622 / 0.609 | 0.596 / 0.622 / 0.609 (identical) |
| Exercised F1 | 0.342 | 0.472 | 0.465 (0.462-0.472) |
| Category recall (micro) | 42.0% | 70.0% | 70.0% (70.0%-70.0%) |
| Precondition recall (micro) | 48.3% | 89.7% | 89.7% (89.7%-89.7%) |
| Fallback / nothing generated | 7 | 0 | - |

- **Where the model helps.** It finds far more targets than the mock (recall 0.622 against 0.267) and covers more required categories and preconditions. The mock's keyword rules produced nothing for 7 of 16 requirements. The mock again rarely invents a target (2 false positives), but finds about a quarter of them.
- **Precision is still the weak point.** 0.596 on fresh v3, against 0.565 on v2 in Part C. These are different sets, so this is not a measured improvement. The service-evidence grounding did cut false positives on the seen sets (v2 from 30 to 9, v1 test split from 21 to 9), but on fresh v3 the model still adds 15 services (5 times `0x10`, 5 times `0x27`, 2 times `0x2E` and `0x22`, once `0x11`) and 4 DIDs. The Part D changes were designed after reading the earlier false positives, so the fresh number is the honest one.
- **Recall is lower than Part C's v2 run** (0.622 against 0.796). The sets differ, so this may just be set difficulty (v3 avoids the spec's field names). `0x3E` is missed in 2 requirements (NAT3-011, NAT3-012), and the routine id and `0x31` in NAT3-006.
- **Ambiguous rows.** Both ambiguous requirements (NAT3-014, NAT3-015) are partly missed. NAT3-016 (the unsupported feature, no targets) still produces 8 tests and a spurious `0x22`.
- **Noise.** Parsed numbers, category recall and precondition recall were identical in all three runs. Exercised F1 varied by 0.01 (0.462-0.472). Three runs is a small sample.

### Seen sets (context only)

- Natural v2 (seen): ollama parsed P/R/F1 went from 0.565/0.796/0.661 to 0.808/0.775/0.792; precondition recall from 77.8% to 92.6%; category recall from 74.0% to 72.0%. Mock unchanged. The fixes targeted exactly these false positives, so this is not evidence.
- Held-out v1 (seen): full output 12/12 (mock) and 11/12 (ollama). Held-out v2 (seen): full output 9/15 in both modes (Part C: 2/15). In-sample: 26/26 in both modes.
- Latency: ollama mean 21.8 s per requirement over the 35 old ones (21.4 s before), 0.97 explain calls per requirement. Whole evaluation 2327.6 s (about 39 min): ollama 2125.8 s, sweep 100.9 s, mock 73.0 s.

### Provenance, errors, freeze

- Byte provenance passed on every generated test in all runs (mock 613/613, ollama 552/552, sweep 1200/1200): no model-written byte reached any test. This does not show the bytes are right, only where they came from.
- Ollama: 0 truncation events and 0 fallbacks to the mock model. 123 fallback events were all the batched explain step omitting some test ids, so a deterministic explanation was used. They do not affect any score.
- Every Part D freeze hash matches and the frozen paths are clean.

### What would help next

1. Close the five stimuli still missed (seed, session switch, then key; lockout expiry then another wrong key; unsupported sub-function with wrong length; DID read above 255 kph; DTC mask with extra status bits). They are known now, so any template built from them makes v3 seen, and a v4 blind set is needed to measure it.
2. Service precision on fresh phrasing: the model still adds `0x10`/`0x27` where the text does not state them, and still misses `0x3E` in some requirements.
3. Test a larger model or context. Only one 3B model on a 4 GB GPU was tried.


## Ollama explain fallback events (Part E investigation)

Investigated 2026-10-04 at git `ffa813d` (code under `uds_assistant/agent` and `uds_assistant/llm` unchanged since the Part D freeze). The report lists 123 `explain: <test_id>: missing in LLM reply; used fallback text` events for the Ollama run, and 33–44 per run in the natural-v3 noise table (44, 33, 36).

**Where it comes from.** `explain` in `uds_assistant/agent/nodes.py` sends one batched request per requirement (several only if the prompt would not fit `num_ctx` 4096) and asks for `{"explanations": [{"test_id": ..., "explanation": ...}]}`. A returned entry is used only if its `test_id` is exactly one of the batch ids. Any test with no usable entry gets `fallback_explanation` and the event above. The request carries no `num_predict`; the JSON schema is the plain `ExplanationBatch` model, so the model may return any number of entries (no required length or id list).

**Cause: the 3B model omits entries. It is a model limitation, not a code bug.** I re-ran all 15 seed requirements in ollama mode (`qwen2.5:3b-instruct-q4_K_M`, `num_ctx` 4096, temperature 0, seed 0) and recorded every raw explain reply next to the expected ids:

| Check | Result |
|---|---|
| Tests explained in the repro | 75 tests, 15 batches (one per requirement) |
| Fallback events | 17 |
| Missing ids that match a returned id after case / punctuation normalisation (an id-matching bug would show here) | 0 |
| Returned ids that are not in the batch (made-up or altered ids) | 0 |
| Replies that failed JSON or schema validation, retries, batch failures | 0 |
| Prompt truncation events | 0 (`prompt_eval_count` 1553–1584 of 4096) |
| Cut by a token limit | none: `done_reason` is `stop` in the replayed requests (`eval_count` 247 and 887, no `num_predict`) |
| Cause of every one of the 17 events | the model returned valid JSON that simply has fewer entries than tests |

Cases per requirement (returned / expected): REQ-001 3/5, REQ-002 6/8, REQ-003 3/4, REQ-004 3/4, REQ-007 2/4, REQ-008 3/8, REQ-010 2/3, REQ-012 3/4, REQ-013 3/5. The other six requirements got every entry. The model often stops at three entries; it does not take the first three (in one REQ-008 reply it explained tests 3, 4 and 5 of 6 and skipped 1, 2 and 6). Replaying the exact same request twice gives the exact same reply, so it is the model's decision, not noise in the transport. The repro set differs from the evaluation run (17 events over 75 tests here, 123 over the full run) because the planner's choices vary between Ollama runs; the cause is the same.

**Verbatim events from the report** (`outputs/eval_report.md`, section "Fallback-to-mock and truncation events"):

- REQ-001: `explain: req_001__tpl_read_badlen_f190_01: missing in LLM reply; used fallback text`
- REQ-001: `explain: req_001__tpl_write_readonly_f190: missing in LLM reply; used fallback text`
- REQ-008: `explain: req_008__tpl_read_did_positive_0100_01: missing in LLM reply; used fallback text`
- REQ-008: `explain: req_008__tpl_write_secured_0100: missing in LLM reply; used fallback text`
- REQ-009: `explain: req_009__tpl_condition_not_met_did_0150: missing in LLM reply; used fallback text`
- REQ-009: `explain: req_009__tpl_nrc_priority_2e_01: missing in LLM reply; used fallback text`

**Raw replies that explain them** (reproduction, REQ-001 with 5 tests): the reply held exactly three entries, with ids `req_001__tpl_read_did_positive_f190_01`, `..._f190_02` and `..._f190_03`. The expected ids were those three plus `req_001__tpl_read_badlen_f190_01` and `req_001__tpl_write_readonly_f190`, so the two events above are the two ids the reply never mentions. REQ-008 reply (6 tests): entries for `req_008__tpl_write_oor_0100`, `req_008__tpl_read_multi_0100_f190_01` and `req_008__tpl_write_retained_s3_0100` only; `req_008__tpl_read_did_positive_0100_01`, `req_008__tpl_write_secured_0100` and `req_008__tpl_write_retained_reset_0100` were never mentioned, which gives the three REQ-008 events. In the same session a REQ-009 reply with all 8 entries (887 tokens) was returned for another planner outcome, so the model can do the whole list; it just does not reliably do so.

**Fixed? No.** The decision rule was to fix only a plain bug (id matching, wrong limit, miscounting, a schema that fails to require ids the code intends to require). None applies: ids are matched correctly, nothing is cut by a limit, the events are counted once per missing test, and the code deliberately accepts an incomplete reply (docstring: "A test the reply omits ... gets `fallback_explanation` and a trace entry"). Making the model return every entry would mean prompt tuning or constrained-decoding changes, which were out of scope. No code was changed and the evaluation was not re-run, so there is no second run; the numbers in this report stand as measured (run at git `1f0c293`, report generated 2026-10-04T08:15:23Z).

**Effect on bytes and scores: none (checked in code).** `explain` only writes the prose field `TestCase.explanation` (and `review_status`) through `model_copy(update=...)`; test steps are not touched. A grep over `uds_assistant/` shows nothing in `eval/`, `export/` or the oracle reads `explanation`; the only consumers are the UI and the model definition. The fallback text is built from the test title, category and template description, and bytes only come from templates plus the rules engine. The bug-detection and natural-set scores, byte provenance and the exported tests are therefore independent of how many explanations fell back. What the fallback does change is the quality of the prose a human reviewer sees: for those tests it is a generic template sentence instead of a model-written one.

_Written after reading the measured numbers in this report (source `outputs/partD/interpretation.md`); no number was edited by hand._

## Noise check — natural v3 (FRESH), run-to-run variation

### mode=mock: 1 run(s) over the 16 natural-v3 requirements (requested 3)

| Run | Parsed P | Parsed R | Parsed F1 | Exercised F1 | Category recall (micro) | Precondition recall (micro) | Tests kept | Rejected choices | Fallback events | Byte provenance |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 (used for the main tables) | 0.857 | 0.267 | 0.407 | 0.342 | 42.0% | 48.3% | 102 | 0 | 0 | 102/102 |
| **mean (min–max) over all runs** | 0.857 (0.857–0.857) | 0.267 (0.267–0.267) | 0.407 (0.407–0.407) | 0.342 (0.342–0.342) | 42.0% (42.0%–42.0%) | 48.3% (48.3%–48.3%) | 102 (102–102) | 0 (0–0) | 0 (0–0) | - |

_mock is deterministic (keyword rules, no sampling), so it was run once for the tables; a second run was compared for equality as a check._

Determinism check: a second `mock` run over natural v3 was identical = **True** (compared: parsed requirement, status and every kept test's template, parameters and steps, over all natural-v3 requirements).

### mode=ollama: 3 run(s) over the 16 natural-v3 requirements (requested 3)

| Run | Parsed P | Parsed R | Parsed F1 | Exercised F1 | Category recall (micro) | Precondition recall (micro) | Tests kept | Rejected choices | Fallback events | Byte provenance |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 (used for the main tables) | 0.596 | 0.622 | 0.609 | 0.472 | 70.0% | 89.7% | 94 | 0 | 44 | 94/94 |
| 2 (extra) | 0.596 | 0.622 | 0.609 | 0.462 | 70.0% | 89.7% | 92 | 0 | 33 | 92/92 |
| 3 (extra) | 0.596 | 0.622 | 0.609 | 0.462 | 70.0% | 89.7% | 92 | 0 | 36 | 92/92 |
| **mean (min–max) over all runs** | 0.596 (0.596–0.596) | 0.622 (0.622–0.622) | 0.609 (0.609–0.609) | 0.465 (0.462–0.472) | 70.0% (70.0%–70.0%) | 89.7% (89.7%–89.7%) | 92.67 (92–94) | 0 (0–0) | 37.67 (33–44) | - |

_Run 1 is the run used for every main table. Every run is listed; the summary is the mean and the min-max range over ALL runs, never the best run._

## Mock vs Ollama — side by side

### Requirement understanding — natural v3 (split test3): FRESH HEADLINE

Natural requirements from `data/requirements_natural_v3.csv`: 16 rows written blind after the Part D freeze, by a subagent that could not see any natural set or any code. Nothing was tuned on them. Same label schema and scoring as v1 and v2.

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 16 | 16 |
| Target exact match — parsed | 1/16 (6.2%) | 2/16 (12.5%) |
| Target exact match — exercised by kept tests | 0/16 (0.0%) | 0/16 (0.0%) |
| Parsed targets P / R / F1 (micro) | 0.857 / 0.267 / 0.407 | 0.596 / 0.622 / 0.609 |
| Parsed targets tp / fp / fn | 12 / 2 / 33 | 28 / 19 / 17 |
| Exercised targets P / R / F1 (micro) | 0.278 / 0.444 / 0.342 | 0.343 / 0.756 / 0.472 |
| Category recall micro (hit/required) / macro | 21/50 (42.0%) / 39.6% | 35/50 (70.0%) / 72.2% |
| Precondition recall micro (hit/required) / macro | 14/29 (48.3%) / 44.9% | 26/29 (89.7%) / 91.0% |
| Fallback / nothing generated | 7 (7 excl. empty-label rows) | 0 (0 excl. empty-label rows) |

Per requirement, natural v3 (misses shown):

| Req | Label targets | mock parsed exact | mock parsed miss/extra | mock tests (categories missed) | mock preconds missed | ollama parsed exact | ollama parsed miss/extra | ollama tests (categories missed) | ollama preconds missed |
|---|---|---|---|---|---|---|---|---|---|
| NAT3-001 | did:0xF187, did:0xF18C, did:0xF190, service:0x22 | no | miss did:0xF187, service:0x22; extra - | 4 (positive missed) | - | no | miss did:0xF187, did:0xF190; extra - | 4 (session missed) | - |
| NAT3-002 | service:0x27 | no | miss service:0x27; extra - | 0 (negative, security, timing missed) | extended_session, lockout_active | no | miss -; extra service:0x10, service:0x2E | 4 (none missed) | - |
| NAT3-003 | did:0x0120, service:0x10, service:0x27, service:0x2E | no | miss did:0x0120, service:0x10, service:0x27, service:0x2E; extra - | 0 (negative, positive, security, session missed) | extended_session, security_level_1 | no | miss -; extra did:0x0110, did:0x0111, did:0x0131 | 5 (session missed) | - |
| NAT3-004 | did:0x0130, service:0x2E | no | miss service:0x2E; extra - | 14 (none missed) | - | no | miss -; extra service:0x10, service:0x27 | 8 (none missed) | - |
| NAT3-005 | routine:0x0201, service:0x31 | no | miss service:0x31; extra - | 15 (none missed) | - | no | miss routine:0x0201; extra service:0x10, service:0x27 | 7 (positive missed) | - |
| NAT3-006 | routine:0x0202, service:0x31 | no | miss service:0x31; extra - | 19 (none missed) | - | no | miss routine:0x0202, service:0x31; extra service:0x10, service:0x27 | 4 (positive, session missed) | security_level_1, vehicle_stationary |
| NAT3-007 | routine:0x0203, service:0x31 | no | miss routine:0x0203, service:0x31; extra - | 0 (negative, positive, security, session, timing missed) | programming_session, security_level_3 | no | miss routine:0x0203; extra did:0x0150, service:0x10, service:0x27 | 8 (session missed) | - |
| NAT3-008 | did:0x0150, service:0x2E | yes | miss -; extra - | 20 (none missed) | - | no | miss -; extra service:0x11, service:0x27 | 8 (session missed) | - |
| NAT3-009 | did:0x0160, service:0x10, service:0x11, service:0x22, service:0x27, service:0x2E | no | miss did:0x0160, service:0x10, service:0x27; extra - | 9 (positive, security missed) | security_level_3 | yes | miss -; extra - | 8 (session missed) | - |
| NAT3-010 | service:0x14, service:0x19 | no | miss service:0x14, service:0x19; extra service:0x22 | 9 (none missed) | - | no | miss service:0x14; extra service:0x2E | 8 (none missed) | - |
| NAT3-011 | did:0xF186, service:0x10, service:0x22, service:0x3E | no | miss did:0xF186, service:0x10, service:0x22, service:0x3E; extra - | 0 (positive, session, timing missed) | extended_session, s3_elapsed | no | miss did:0xF186, service:0x22, service:0x3E; extra - | 4 (session missed) | - |
| NAT3-012 | did:0x0100, service:0x10, service:0x27, service:0x2E, service:0x3E | no | miss did:0x0100, service:0x27, service:0x3E; extra - | 11 (security, timing missed) | s3_elapsed, security_level_1 | no | miss service:0x3E; extra - | 4 (security, session missed) | - |
| NAT3-013 | service:0x3E | no | miss service:0x3E; extra - | 0 (positive, timing missed) | - | yes | miss -; extra - | 4 (none missed) | - |
| NAT3-014 | did:0xF186, service:0x10, service:0x11, service:0x22, service:0x27 | no | miss did:0xF186, service:0x10, service:0x11, service:0x22, service:0x27; extra - | 0 (positive, security, session missed) | extended_session, security_level_1 | no | miss did:0xF186, service:0x10, service:0x22, service:0x27; extra - | 4 (positive, security, session missed) | security_level_1 |
| NAT3-015 | did:0x0130, did:0x0131, service:0x2E | no | miss did:0x0130, did:0x0131, service:0x2E; extra - | 0 (negative, positive, security missed) | extended_session, security_level_1 | no | miss did:0x0131, service:0x2E; extra service:0x22 | 6 (security missed) | - |
| NAT3-016 | (none) | no | miss -; extra service:0x22 | 1 (positive missed) | - | no | miss -; extra service:0x22 | 8 (none missed) | - |

### Requirement understanding — natural v2 (split test2): SEEN

Natural requirements from `data/requirements_natural_v2.csv`. Fresh in Part C; their Part C results were known before Part D, so they are SEEN. A single run per mode.

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 16 | 16 |
| Target exact match — parsed | 0/16 (0.0%) | 4/16 (25.0%) |
| Target exact match — exercised by kept tests | 0/16 (0.0%) | 0/16 (0.0%) |
| Parsed targets P / R / F1 (micro) | 1.000 / 0.225 / 0.367 | 0.808 / 0.775 / 0.792 |
| Parsed targets tp / fp / fn | 11 / 0 / 38 | 38 / 9 / 11 |
| Exercised targets P / R / F1 (micro) | 0.380 / 0.551 / 0.450 | 0.484 / 0.939 / 0.639 |
| Category recall micro (hit/required) / macro | 24/50 (48.0%) / 48.9% | 36/50 (72.0%) / 72.0% |
| Precondition recall micro (hit/required) / macro | 15/27 (55.6%) / 53.8% | 25/27 (92.6%) / 95.5% |
| Fallback / nothing generated | 7 (6 excl. empty-label rows) | 0 (0 excl. empty-label rows) |

Per requirement, natural v2 (misses shown):

| Req | Label targets | mock parsed exact | mock parsed miss/extra | mock tests (categories missed) | mock preconds missed | ollama parsed exact | ollama parsed miss/extra | ollama tests (categories missed) | ollama preconds missed |
|---|---|---|---|---|---|---|---|---|---|
| NAT2-001 | did:0xF187, did:0xF18C, did:0xF190, service:0x22 | no | miss did:0xF187, did:0xF18C; extra - | 18 (none missed) | - | no | miss did:0xF190; extra - | 7 (session missed) | - |
| NAT2-002 | did:0x0120, service:0x10, service:0x27, service:0x2E | no | miss service:0x10, service:0x27, service:0x2E; extra - | 14 (none missed) | - | no | miss did:0x0120; extra - | 4 (session missed) | - |
| NAT2-003 | did:0x0130, service:0x22, service:0x27, service:0x2E | no | miss service:0x22, service:0x27; extra - | 16 (none missed) | - | no | miss service:0x22; extra service:0x10 | 8 (none missed) | - |
| NAT2-004 | routine:0x0201, service:0x31 | no | miss service:0x31; extra - | 8 (security missed) | - | no | miss routine:0x0201; extra - | 4 (security missed) | - |
| NAT2-005 | routine:0x0203, service:0x10, service:0x27, service:0x31 | no | miss routine:0x0203, service:0x10, service:0x27, service:0x31; extra - | 0 (negative, positive, security, session, timing missed) | programming_session, security_level_3 | no | miss routine:0x0203, service:0x31; extra did:0x0150, service:0x22 | 5 (session missed) | - |
| NAT2-006 | service:0x27 | no | miss service:0x27; extra - | 0 (negative, security, timing missed) | extended_session, lockout_active | yes | miss -; extra - | 6 (negative, timing missed) | - |
| NAT2-007 | service:0x14, service:0x19 | no | miss service:0x14, service:0x19; extra - | 8 (negative missed) | - | no | miss service:0x14; extra service:0x22 | 6 (none missed) | - |
| NAT2-008 | service:0x10, service:0x22, service:0x3E | no | miss service:0x10, service:0x22, service:0x3E; extra - | 2 (negative, positive, session missed) | - | no | miss service:0x22; extra - | 6 (session missed) | - |
| NAT2-009 | did:0x0100, service:0x10, service:0x27, service:0x2E | no | miss did:0x0100, service:0x10, service:0x27; extra - | 2 (security, timing missed) | extended_session, s3_elapsed, security_level_1 | yes | miss -; extra - | 4 (session, timing missed) | s3_elapsed |
| NAT2-010 | did:0xF186, service:0x10, service:0x11, service:0x22, service:0x27 | no | miss did:0xF186, service:0x10, service:0x11, service:0x27; extra - | 1 (positive, security, session missed) | extended_session, security_level_1 | no | miss -; extra service:0x2E | 8 (session missed) | - |
| NAT2-011 | service:0x3E | no | miss service:0x3E; extra - | 2 (positive missed) | - | yes | miss -; extra - | 3 (none missed) | - |
| NAT2-012 | routine:0x0202, service:0x10, service:0x27, service:0x31 | no | miss service:0x10, service:0x27, service:0x31; extra - | 19 (none missed) | - | no | miss service:0x31; extra did:0x0110, did:0x0111 | 4 (negative missed) | vehicle_moving |
| NAT2-013 | did:0x0160, service:0x10, service:0x22, service:0x27, service:0x2E | no | miss did:0x0160, service:0x10, service:0x27, service:0x2E; extra - | 1 (positive, security, session missed) | programming_session, security_level_3 | yes | miss -; extra - | 4 (session missed) | - |
| NAT2-014 | did:0x0110, did:0x0111, service:0x22, service:0x2E | no | miss did:0x0110, did:0x0111, service:0x2E; extra - | 1 (positive, security missed) | - | no | miss service:0x2E; extra - | 6 (security missed) | - |
| NAT2-015 | service:0x10, service:0x14 | no | miss service:0x10, service:0x14; extra - | 0 (negative, session missed) | programming_session | no | miss service:0x10; extra - | 4 (negative missed) | - |
| NAT2-016 | (none) | no | miss -; extra - | 8 (none missed) | - | no | miss -; extra service:0x22, service:0x2E | 8 (none missed) | - |

### Requirement understanding — natural v1 TEST split: SEEN

Natural requirements from `data/requirements_natural.csv`. The template set was designed after these results, so they are no longer independent. The prompts were tuned on the 8 dev rows only.

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 12 | 12 |
| Target exact match — parsed | 5/12 (41.7%) | 5/12 (41.7%) |
| Target exact match — exercised by kept tests | 2/12 (16.7%) | 1/12 (8.3%) |
| Parsed targets P / R / F1 (micro) | 0.933 / 0.560 / 0.700 | 0.690 / 0.800 / 0.741 |
| Parsed targets tp / fp / fn | 14 / 1 / 11 | 20 / 9 / 5 |
| Exercised targets P / R / F1 (micro) | 0.290 / 0.800 / 0.425 | 0.339 / 0.880 / 0.489 |
| Category recall micro (hit/required) / macro | 19/28 (67.9%) / 69.7% | 21/28 (75.0%) / 78.0% |
| Precondition recall micro (hit/required) / macro | 12/15 (80.0%) / 75.0% | 14/15 (93.3%) / 87.5% |
| Fallback / nothing generated | 3 (2 excl. empty-label rows) | 1 (0 excl. empty-label rows) |

Per requirement, v1 test split:

| Req | Label targets | mock parsed exact | mock parsed miss/extra | mock tests (categories missed) | mock preconds missed | ollama parsed exact | ollama parsed miss/extra | ollama tests (categories missed) | ollama preconds missed |
|---|---|---|---|---|---|---|---|---|---|
| NAT-002 | did:0xF187, did:0xF18C, service:0x22 | no | miss did:0xF18C; extra - | 14 (none missed) | - | yes | miss -; extra - | 7 (none missed) | - |
| NAT-004 | service:0x10 | yes | miss -; extra - | 9 (session missed) | vehicle_stationary | yes | miss -; extra - | 4 (session missed) | vehicle_stationary |
| NAT-006 | did:0x0101, service:0x10, service:0x27, service:0x2E | no | miss service:0x10, service:0x27, service:0x2E; extra - | 14 (none missed) | - | no | miss service:0x10; extra - | 8 (none missed) | - |
| NAT-008 | did:0x0131, service:0x2E | no | miss service:0x2E; extra - | 0 (negative, security missed) | extended_session, security_level_1 | no | miss -; extra service:0x22 | 4 (security missed) | - |
| NAT-010 | service:0x27 | yes | miss -; extra - | 3 (security, timing missed) | - | yes | miss -; extra - | 4 (negative, timing missed) | - |
| NAT-012 | routine:0x0202, service:0x31 | yes | miss -; extra - | 16 (none missed) | - | no | miss service:0x31; extra did:0x0110, did:0x0111, did:0x0140 | 8 (none missed) | - |
| NAT-014 | service:0x19 | no | miss -; extra service:0x22 | 11 (none missed) | - | no | miss -; extra service:0x22 | 8 (none missed) | - |
| NAT-016 | did:0x0160, service:0x10, service:0x27, service:0x2E | no | miss service:0x10, service:0x27, service:0x2E; extra - | 13 (none missed) | - | yes | miss -; extra - | 8 (session missed) | - |
| NAT-017 | service:0x14, service:0x19 | no | miss service:0x14, service:0x19; extra - | 0 (negative, positive, session missed) | - | no | miss service:0x19; extra - | 4 (negative missed) | - |
| NAT-018 | did:0x0120, service:0x27, service:0x2E | no | miss service:0x27; extra - | 16 (none missed) | - | no | miss did:0x0120; extra service:0x10 | 8 (none missed) | - |
| NAT-019 | routine:0x0203, service:0x31 | yes | miss -; extra - | 19 (positive missed) | - | no | miss routine:0x0203; extra did:0x0150, service:0x10, service:0x27 | 4 (security missed) | - |
| NAT-020 | (none) | yes | miss -; extra - | 0 (none missed) | - | yes | miss -; extra - | 0 (none missed) | - |

### Requirement understanding — natural v1 dev split (dev: the rows the prompts were tuned on)

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 8 | 8 |
| Target exact match — parsed | 4/8 (50.0%) | 5/8 (62.5%) |
| Target exact match — exercised by kept tests | 0/8 (0.0%) | 0/8 (0.0%) |
| Parsed targets P / R / F1 (micro) | 1.000 / 0.706 / 0.828 | 0.929 / 0.765 / 0.839 |
| Parsed targets tp / fp / fn | 12 / 0 / 5 | 13 / 1 / 4 |
| Exercised targets P / R / F1 (micro) | 0.314 / 0.941 / 0.471 | 0.405 / 1.000 / 0.576 |
| Category recall micro (hit/required) / macro | 15/22 (68.2%) / 63.5% | 15/22 (68.2%) / 67.7% |
| Precondition recall micro (hit/required) / macro | 9/9 (100.0%) / 100.0% | 9/9 (100.0%) / 100.0% |
| Fallback / nothing generated | 1 (1 excl. empty-label rows) | 0 (0 excl. empty-label rows) |

### Requirement understanding — natural v1 all split

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 20 | 20 |
| Target exact match — parsed | 9/20 (45.0%) | 10/20 (50.0%) |
| Target exact match — exercised by kept tests | 2/20 (10.0%) | 1/20 (5.0%) |
| Parsed targets P / R / F1 (micro) | 0.963 / 0.619 / 0.754 | 0.767 / 0.786 / 0.776 |
| Parsed targets tp / fp / fn | 26 / 1 / 16 | 33 / 10 / 9 |
| Exercised targets P / R / F1 (micro) | 0.300 / 0.857 / 0.444 | 0.364 / 0.929 / 0.523 |
| Category recall micro (hit/required) / macro | 34/50 (68.0%) / 67.1% | 36/50 (72.0%) / 73.7% |
| Precondition recall micro (hit/required) / macro | 21/24 (87.5%) / 83.3% | 23/24 (95.8%) / 91.7% |
| Fallback / nothing generated | 4 (3 excl. empty-label rows) | 1 (0 excl. empty-label rows) |

Per requirement, v1 dev split:

| Req | Label targets | mock parsed exact | mock parsed miss/extra | mock tests (categories missed) | mock preconds missed | ollama parsed exact | ollama parsed miss/extra | ollama tests (categories missed) | ollama preconds missed |
|---|---|---|---|---|---|---|---|---|---|
| NAT-001 | did:0xF190, service:0x22 | yes | miss -; extra - | 18 (none missed) | - | no | miss did:0xF190; extra service:0x10 | 7 (none missed) | - |
| NAT-003 | service:0x10 | no | miss service:0x10; extra - | 0 (positive, session missed) | - | yes | miss -; extra - | 4 (session missed) | - |
| NAT-005 | did:0x0100, service:0x10, service:0x27, service:0x2E | no | miss service:0x10; extra - | 18 (none missed) | - | no | miss service:0x10, service:0x27; extra - | 7 (security missed) | - |
| NAT-007 | did:0x0130, service:0x2E | no | miss service:0x2E; extra - | 7 (security missed) | - | yes | miss -; extra - | 4 (security missed) | - |
| NAT-009 | did:0x0150, service:0x10, service:0x27, service:0x2E | no | miss service:0x10, service:0x27; extra - | 20 (none missed) | - | yes | miss -; extra - | 7 (session missed) | - |
| NAT-011 | routine:0x0201, service:0x31 | yes | miss -; extra - | 12 (security missed) | - | no | miss routine:0x0201; extra - | 8 (security missed) | - |
| NAT-013 | service:0x11 | yes | miss -; extra - | 6 (positive missed) | - | yes | miss -; extra - | 6 (positive missed) | - |
| NAT-015 | service:0x3E | yes | miss -; extra - | 9 (session, timing missed) | - | yes | miss -; extra - | 4 (session missed) | - |

### Parsed false positives and false negatives by kind (every set, every mode)

Kind = service / did / routine / dtc (no label or prediction names a DTC, so that row is zero). tp = label items of the kind minus the missed ones.

**natural v3 (FRESH, test3)**

| Kind | mock tp | mock FP | mock FN | ollama tp | ollama FP | ollama FN |
|---|---|---|---|---|---|---|
| service | 6 | 2 | 24 | 21 | 15 | 9 |
| did | 4 | 0 | 8 | 7 | 4 | 5 |
| routine | 2 | 0 | 1 | 0 | 0 | 3 |
| dtc | 0 | 0 | 0 | 0 | 0 | 0 |

**natural v2 (SEEN, test2)**

| Kind | mock tp | mock FP | mock FN | ollama tp | ollama FP | ollama FN |
|---|---|---|---|---|---|---|
| service | 6 | 0 | 30 | 29 | 6 | 7 |
| did | 3 | 0 | 7 | 8 | 3 | 2 |
| routine | 2 | 0 | 1 | 1 | 0 | 2 |
| dtc | 0 | 0 | 0 | 0 | 0 | 0 |

**natural v1 test split (SEEN)**

| Kind | mock tp | mock FP | mock FN | ollama tp | ollama FP | ollama FN |
|---|---|---|---|---|---|---|
| service | 7 | 1 | 10 | 14 | 5 | 3 |
| did | 5 | 0 | 1 | 5 | 4 | 1 |
| routine | 2 | 0 | 0 | 1 | 0 | 1 |
| dtc | 0 | 0 | 0 | 0 | 0 | 0 |

**natural v1 dev split (tuned on)**

| Kind | mock tp | mock FP | mock FN | ollama tp | ollama FP | ollama FN |
|---|---|---|---|---|---|---|
| service | 7 | 0 | 5 | 10 | 1 | 2 |
| did | 4 | 0 | 0 | 3 | 0 | 1 |
| routine | 1 | 0 | 0 | 0 | 0 | 1 |
| dtc | 0 | 0 | 0 | 0 | 0 | 0 |

### Rejected planner choices by reason (every set, every mode)

| Set | Reason | mock | ollama |
|---|---|---|---|
| 15 seed requirements | unknown template id | 0 | 0 |
|  | option index out of range | 0 | 0 |
|  | option not in the offered shortlist | 0 | 0 |
|  | duplicate / other | 0 | 0 |
|  | **total** | **0** | **0** |
| natural v1 (20 requirements, SEEN) | unknown template id | 0 | 0 |
|  | option index out of range | 0 | 0 |
|  | option not in the offered shortlist | 0 | 0 |
|  | duplicate / other | 0 | 0 |
|  | **total** | **0** | **0** |
| natural v2 (16, SEEN) | unknown template id | 0 | 0 |
|  | option index out of range | 0 | 0 |
|  | option not in the offered shortlist | 0 | 0 |
|  | duplicate / other | 0 | 0 |
|  | **total** | **0** | **0** |
| natural v3 (16, FRESH) | unknown template id | 0 | 0 |
|  | option index out of range | 0 | 0 |
|  | option not in the offered shortlist | 0 | 0 |
|  | duplicate / other | 0 | 0 |
|  | **total** | **0** | **0** |

### Held-out v3 bug detection (15 FRESH bugs) — FRESH HEADLINE: full output

15 bugs written blind after the Part D freeze by a subagent that could not see templates, the conformance sweep, prompts, eval code or any report; nothing was changed after seeing these results. The rows below split the headline into its parts. "Full output" is the per-bug union of (a) and (b).

| Suite | mock | ollama |
|---|---|---|
| **(c) Full output = (a) ∪ (b) — headline** | **10/15 (66.7%)** | **9/15 (60.0%)** |
| (a) Requirement-driven (seed requirements; Part C 'generated' suite) | 4/15 (26.7%) | 2/15 (13.3%) |
| (b) Conformance sweep alone (LLM-independent) | 9/15 (60.0%) | 9/15 (60.0%) |
| (d) Gold (LLM-independent) | 3/15 (20.0%) | 3/15 (20.0%) |
| Suite sizes (tests): requirement-driven / sweep / full output | 206 / 1200 / 1406 | 73 / 1200 / 1273 |
| Supplementary: union of ALL generated tests (seed + natural v1 + v2 + v3) | 4/15 (26.7%) (613 tests) | 4/15 (26.7%) (368 tests) |
| Supplementary: tests generated from natural v3 alone | 4/15 (26.7%) (102 tests) | 2/15 (13.3%) (94 tests) |

Per held-out v3 bug (which suite detected it):

| Bug | Category | mock (a) req-driven | mock (b) sweep | mock (c) full | ollama (a) req-driven | ollama (b) sweep | ollama (c) full | gold |
|---|---|---|---|---|---|---|---|---|
| `session_switch_keeps_pending_seed` | session | **no** | **no** | **no** | **no** | **no** | **no** | **no** |
| `session_response_p2_star_in_ms` | timing | yes | yes | yes | yes | yes | yes | yes |
| `failed_key_keeps_pending_seed` | security | **no** | yes | yes | **no** | yes | yes | **no** |
| `lockout_expiry_resets_attempt_count` | security | **no** | **no** | **no** | **no** | **no** | **no** | **no** |
| `nrc_order_subfunction_before_length` | nrc_order | **no** | **no** | **no** | **no** | **no** | **no** | **no** |
| `nrc_order_write_range_before_condition` | nrc_order | **no** | yes | yes | **no** | yes | yes | **no** |
| `routine_results_trailing_bytes_accepted` | format | **no** | yes | yes | **no** | yes | yes | **no** |
| `read_did_speed_not_clamped` | data | **no** | **no** | **no** | **no** | **no** | **no** | **no** |
| `write_stores_value_before_range_rejection` | data | **no** | yes | yes | **no** | yes | yes | **no** |
| `routine_stop_reports_completed_status` | data | yes | yes | yes | yes | yes | yes | yes |
| `dtc_clear_single_clears_neighbour` | data | yes | **no** | yes | **no** | **no** | **no** | yes |
| `dtc_read_reports_masked_status` | data | **no** | **no** | **no** | **no** | **no** | **no** | **no** |
| `ecu_reset_resets_seed_counter` | security | yes | yes | yes | **no** | yes | yes | **no** |
| `s3_timeout_clears_dtc_status` | timing | **no** | yes | yes | **no** | yes | yes | **no** |
| `suppressed_request_does_not_restart_s3` | timing | **no** | yes | yes | **no** | yes | yes | **no** |


### Held-out v2 bug detection (15 bugs) — SEEN: generated suite, gold, union

"Generated suite" = tests generated from the 15 seed requirements (the Part C headline definition). These 15 bugs were fresh in Part C and are SEEN now. The last rows are supplementary and use other test sets.

| Suite | mock | ollama |
|---|---|---|
| Generated (Part C headline definition) | 2/15 (13.3%) | 2/15 (13.3%) |
| Gold (LLM-independent) | 5/15 (33.3%) | 5/15 (33.3%) |
| Union generated ∪ gold | 5/15 (33.3%) | 5/15 (33.3%) |
| Generated tests (seed requirements) | 206 | 73 |
| Invalid generated tests (fail on clean simulator) | 0 | 0 |
| Supplementary: union of ALL generated tests (seed + natural v1 + natural v2) | 2/15 (13.3%) (511 tests) | 2/15 (13.3%) (274 tests) |
| Supplementary: tests generated from natural v2 alone | 2/15 (13.3%) (100 tests) | 2/15 (13.3%) (87 tests) |

Per held-out v2 bug (generated suite):

| Bug | Category | mock generated | ollama generated | gold |
|---|---|---|---|---|
| `session_reentry_keeps_unlock` | session | yes (8 tests) | yes (3 tests) | yes |
| `s3_restart_skipped_on_negative_response` | timing | **no** (0 tests) | **no** (0 tests) | **no** |
| `s3_timeout_resets_lockout_counters` | session | **no** (0 tests) | **no** (0 tests) | **no** |
| `ecu_reset_keeps_session` | session | **no** (0 tests) | **no** (0 tests) | yes |
| `seed_request_keeps_stale_pending_seed` | security | **no** (0 tests) | **no** (0 tests) | **no** |
| `key_compare_prefix_only` | security | **no** (0 tests) | **no** (0 tests) | **no** |
| `lockout_counter_pooled_across_levels` | security | **no** (0 tests) | **no** (0 tests) | **no** |
| `nrc_order_range_before_security` | nrc_order | **no** (0 tests) | **no** (0 tests) | **no** |
| `nrc_order_nvm_fault_before_group_check` | nrc_order | **no** (0 tests) | **no** (0 tests) | **no** |
| `read_dtc_trailing_bytes_accepted` | format | **no** (0 tests) | **no** (0 tests) | **no** |
| `routine_option_record_overlong_accepted` | format | **no** (0 tests) | **no** (0 tests) | **no** |
| `write_range_upper_bound_exclusive` | data | yes (6 tests) | yes (2 tests) | yes |
| `multi_did_read_dedups_repeats` | data | **no** (0 tests) | **no** (0 tests) | yes |
| `routine_restart_after_stop_blocked` | sequence | **no** (0 tests) | **no** (0 tests) | yes |
| `suppressed_seed_request_not_stored` | security | **no** (0 tests) | **no** (0 tests) | **no** |

### Held-out v1 bug detection (12 bugs) — SEEN (templates designed against these misses)

| Suite | mock | ollama |
|---|---|---|
| **Generated** | 10/12 (83.3%) | 8/12 (66.7%) |
| Gold (LLM-independent) | 3/12 (25.0%) | 3/12 (25.0%) |
| Union generated ∪ gold | 11/12 (91.7%) | 9/12 (75.0%) |
| Generated tests (seed requirements) | 206 | 73 |
| Invalid generated tests (fail on clean simulator) | 0 | 0 |

Per held-out v1 bug (generated suite):

| Bug | Category | mock generated | ollama generated | gold |
|---|---|---|---|---|
| `routine_state_survives_session_change` | session | yes (2 tests) | yes (1 tests) | **no** |
| `failed_attempts_reset_by_seed_request` | security | yes (12 tests) | yes (4 tests) | yes |
| `seed_returned_while_unlocked` | security | yes (6 tests) | yes (1 tests) | yes |
| `nrc_order_condition_before_security` | nrc_order | yes (1 tests) | **no** (0 tests) | **no** |
| `read_did_odd_length_truncated` | format | yes (3 tests) | yes (2 tests) | **no** |
| `read_did_session_restriction_ignored` | data | yes (2 tests) | yes (2 tests) | **no** |
| `uint16_did_stored_byte_swapped` | data | **no** (0 tests) | **no** (0 tests) | yes |
| `s3_not_refreshed_by_tester_present` | timing | yes (13 tests) | yes (1 tests) | **no** |
| `ecu_reset_clears_security_lockout` | security | yes (6 tests) | **no** (0 tests) | **no** |
| `s3_timeout_reverts_written_dids` | timing | yes (5 tests) | yes (3 tests) | **no** |
| `session_suppress_bit_not_masked` | format | yes (3 tests) | yes (2 tests) | **no** |
| `suppress_bit_echoed_in_response` | format | **no** (0 tests) | **no** (0 tests) | **no** |

### In-sample bug detection (26 bugs — in-sample, templates tuned on these)

| Suite | mock | ollama |
|---|---|---|
| Generated | 25/26 (96.2%) | 21/26 (80.8%) |
| Gold | 24/26 (92.3%) | 24/26 (92.3%) |
| Union | 26/26 (100.0%) | 25/26 (96.2%) |
| Undetected by the generated suite | missing_response_pending | nrc_order_security_before_length, seed_not_consumed, write_length_off_by_one, dtc_clear_ignores_group, missing_response_pending |

### Validation: rejections, re-plans (retries), plan attempts, dropped tests

Per requirement (15 seed + 20 natural v1 + 16 natural v2 + 16 natural v3). *rejected* = planner choices refused (unknown template/option, outside the shortlist, or failed validation); *retries* = re-plan rounds (plan attempts − 1); *dropped* = instantiated tests that failed validation.

| Req | Split | mock tests | mock rejected | mock retries | mock plan attempts | mock dropped | ollama tests | ollama rejected | ollama retries | ollama plan attempts | ollama dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| REQ-001 | seed | 18 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| REQ-002 | seed | 20 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| REQ-003 | seed | 8 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-004 | seed | 5 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-005 | seed | 18 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-006 | seed | 18 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| REQ-007 | seed | 16 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-008 | seed | 16 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| REQ-009 | seed | 22 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| REQ-010 | seed | 8 | 0 | 0 | 1 | 0 | 3 | 0 | 0 | 1 | 0 |
| REQ-011 | seed | 12 | 0 | 0 | 1 | 0 | 2 | 0 | 0 | 1 | 0 |
| REQ-012 | seed | 16 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-013 | seed | 6 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| REQ-014 | seed | 10 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-015 | seed | 13 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-001 | dev | 18 | 0 | 0 | 1 | 0 | 7 | 0 | 0 | 1 | 0 |
| NAT-002 | test | 14 | 0 | 0 | 1 | 0 | 7 | 0 | 0 | 1 | 0 |
| NAT-003 | dev | 0 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-004 | test | 9 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-005 | dev | 18 | 0 | 0 | 1 | 0 | 7 | 0 | 0 | 1 | 0 |
| NAT-006 | test | 14 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT-007 | dev | 7 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-008 | test | 0 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-009 | dev | 20 | 0 | 0 | 1 | 0 | 7 | 0 | 0 | 1 | 0 |
| NAT-010 | test | 3 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-011 | dev | 12 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT-012 | test | 16 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT-013 | dev | 6 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| NAT-014 | test | 11 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT-015 | dev | 9 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-016 | test | 13 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT-017 | test | 0 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-018 | test | 16 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT-019 | test | 19 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-020 | test | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0 |
| NAT2-001 | test2 | 18 | 0 | 0 | 1 | 0 | 7 | 0 | 0 | 1 | 0 |
| NAT2-002 | test2 | 14 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT2-003 | test2 | 16 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT2-004 | test2 | 8 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT2-005 | test2 | 0 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| NAT2-006 | test2 | 0 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| NAT2-007 | test2 | 8 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| NAT2-008 | test2 | 2 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| NAT2-009 | test2 | 2 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT2-010 | test2 | 1 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT2-011 | test2 | 2 | 0 | 0 | 1 | 0 | 3 | 0 | 0 | 1 | 0 |
| NAT2-012 | test2 | 19 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT2-013 | test2 | 1 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT2-014 | test2 | 1 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| NAT2-015 | test2 | 0 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT2-016 | test2 | 8 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT3-001 | test3 | 4 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT3-002 | test3 | 0 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT3-003 | test3 | 0 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| NAT3-004 | test3 | 14 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT3-005 | test3 | 15 | 0 | 0 | 1 | 0 | 7 | 0 | 0 | 1 | 0 |
| NAT3-006 | test3 | 19 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT3-007 | test3 | 0 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT3-008 | test3 | 20 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT3-009 | test3 | 9 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT3-010 | test3 | 9 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT3-011 | test3 | 0 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT3-012 | test3 | 11 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT3-013 | test3 | 0 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT3-014 | test3 | 0 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT3-015 | test3 | 0 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| NAT3-016 | test3 | 1 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| **total** |  | 613 | 0 | 0 | 67 | 0 | 368 | 0 | 0 | 67 | 0 |

LLM call counters (all 67 requirements):

| Counter | mock | ollama |
|---|---|---|
| LLM calls | 187 | 199 |
| Explain LLM calls | 53 | 66 |
| JSON/schema failures | 0 | 0 |
| LLM re-prompts/retries | 0 | 0 |
| LLM errors | 0 | 0 |
| Failed pipeline runs | 0 | 0 |

Rejection reasons — `mock` (0):

- none

Rejection reasons — `ollama` (0):

- none

### Fallback-to-mock and truncation events (verbatim)

**`mock` — fallback events (0):**

- none

**`mock` — truncation events (0):**

- none

**`ollama` — fallback events (123):**

- REQ-001: `explain: req_001__tpl_read_badlen_f190_01: missing in LLM reply; used fallback text`
- REQ-001: `explain: req_001__tpl_write_readonly_f190: missing in LLM reply; used fallback text`
- REQ-002: `explain: req_002__tpl_read_did_positive_f187_01: missing in LLM reply; used fallback text`
- REQ-002: `explain: req_002__tpl_read_badlen_f187_01: missing in LLM reply; used fallback text`
- REQ-003: `explain: req_003__tpl_suppress_positive_10_02: missing in LLM reply; used fallback text`
- REQ-004: `explain: req_004__tpl_suppress_positive_10_03: missing in LLM reply; used fallback text`
- REQ-007: `explain: req_007__tpl_read_did_positive_0130_01: missing in LLM reply; used fallback text`
- REQ-007: `explain: req_007__tpl_write_secured_0130: missing in LLM reply; used fallback text`
- REQ-008: `explain: req_008__tpl_read_did_positive_0100_01: missing in LLM reply; used fallback text`
- REQ-008: `explain: req_008__tpl_write_secured_0100: missing in LLM reply; used fallback text`
- REQ-008: `explain: req_008__tpl_write_retained_reset_0100: missing in LLM reply; used fallback text`
- REQ-009: `explain: req_009__tpl_condition_not_met_did_0150: missing in LLM reply; used fallback text`
- REQ-009: `explain: req_009__tpl_condition_not_met_did_0150_locked: missing in LLM reply; used fallback text`
- REQ-009: `explain: req_009__tpl_read_did_wrong_0150_02: missing in LLM reply; used fallback text`
- REQ-009: `explain: req_009__tpl_read_did_wrong_0150_01: missing in LLM reply; used fallback text`
- REQ-009: `explain: req_009__tpl_nrc_priority_2e_01: missing in LLM reply; used fallback text`
- REQ-010: `explain: req_010__tpl_session_relock_03: missing in LLM reply; used fallback text`
- REQ-012: `explain: req_012__tpl_routine_sequence_0202: missing in LLM reply; used fallback text`
- REQ-013: `explain: req_013__tpl_negative_suppress_11_01: missing in LLM reply; used fallback text`
- REQ-013: `explain: req_013__tpl_negative_suppress_11_03: missing in LLM reply; used fallback text`
- NAT-001: `explain: nat_001__tpl_read_did_wrong_dead_01: missing in LLM reply; used fallback text`
- NAT-001: `explain: nat_001__tpl_read_did_wrong_dead_02: missing in LLM reply; used fallback text`
- NAT-001: `explain: nat_001__tpl_read_did_wrong_dead_03: missing in LLM reply; used fallback text`
- NAT-001: `explain: nat_001__tpl_read_did_wrong_0150_01: missing in LLM reply; used fallback text`
- NAT-002: `explain: nat_002__tpl_read_badlen_f187_01: missing in LLM reply; used fallback text`
- NAT-002: `explain: nat_002__tpl_read_badlen_f18c_01: missing in LLM reply; used fallback text`
- NAT-002: `explain: nat_002__tpl_write_readonly_f187: missing in LLM reply; used fallback text`
- NAT-002: `explain: nat_002__tpl_write_readonly_f18c: missing in LLM reply; used fallback text`
- NAT-007: `explain: nat_007__tpl_write_secured_0130: missing in LLM reply; used fallback text`
- NAT-007: `explain: nat_007__tpl_write_retained_s3_0130: missing in LLM reply; used fallback text`
- NAT-007: `explain: nat_007__tpl_nrc_priority_2e_01: missing in LLM reply; used fallback text`
- NAT-008: `explain: nat_008__tpl_write_retained_s3_0131: missing in LLM reply; used fallback text`
- NAT-011: `explain: nat_011__tpl_service_not_in_session_31_01: missing in LLM reply; used fallback text`
- NAT-011: `explain: nat_011__tpl_routine_after_session_0201: missing in LLM reply; used fallback text`
- NAT-011: `explain: nat_011__tpl_routine_after_session_0202: missing in LLM reply; used fallback text`
- NAT-011: `explain: nat_011__tpl_routine_after_session_0203: missing in LLM reply; used fallback text`
- NAT-011: `explain: nat_011__tpl_routine_after_reset_0201: missing in LLM reply; used fallback text`
- NAT-012: `explain: nat_012__tpl_read_did_positive_0110_01: missing in LLM reply; used fallback text`
- NAT-012: `explain: nat_012__tpl_routine_sequence_0202: missing in LLM reply; used fallback text`
- NAT-012: `explain: nat_012__tpl_routine_after_session_0202: missing in LLM reply; used fallback text`
- NAT-012: `explain: nat_012__tpl_write_readonly_0110: missing in LLM reply; used fallback text`
- NAT-012: `explain: nat_012__tpl_condition_not_met_routine_0202_locked: missing in LLM reply; used fallback text`
- NAT-012: `explain: nat_012__tpl_routine_start_results_0202_suppress: missing in LLM reply; used fallback text`
- NAT-013: `explain: nat_013__tpl_negative_suppress_11_01: missing in LLM reply; used fallback text`
- NAT-013: `explain: nat_013__tpl_negative_suppress_11_03: missing in LLM reply; used fallback text`
- NAT-013: `explain: nat_013__tpl_negative_suppress_11_02: missing in LLM reply; used fallback text`
- NAT-015: `explain: nat_015__tpl_negative_suppress_3e_01: missing in LLM reply; used fallback text`
- NAT-018: `explain: nat_018__tpl_write_badlen_0100: missing in LLM reply; used fallback text`
- NAT-018: `explain: nat_018__tpl_security_lockout_01: missing in LLM reply; used fallback text`
- NAT-018: `explain: nat_018__tpl_session_relock_01: missing in LLM reply; used fallback text`
- NAT-018: `explain: nat_018__tpl_seed_replay_01: missing in LLM reply; used fallback text`
- NAT-018: `explain: nat_018__tpl_seed_while_unlocked_01: missing in LLM reply; used fallback text`
- NAT2-001: `explain: nat2_001__tpl_read_badlen_f187_01: missing in LLM reply; used fallback text`
- NAT2-001: `explain: nat2_001__tpl_read_badlen_f18c_01: missing in LLM reply; used fallback text`
- NAT2-001: `explain: nat2_001__tpl_write_readonly_f187: missing in LLM reply; used fallback text`
- NAT2-001: `explain: nat2_001__tpl_write_readonly_f18c: missing in LLM reply; used fallback text`
- NAT2-002: `explain: nat2_002__tpl_seed_while_unlocked_01: missing in LLM reply; used fallback text`
- NAT2-007: `explain: nat2_007__tpl_read_did_wrong_0150_01: missing in LLM reply; used fallback text`
- NAT2-007: `explain: nat2_007__tpl_service_not_in_session_19_02: missing in LLM reply; used fallback text`
- NAT2-007: `explain: nat2_007__tpl_read_badlen_f187_01: missing in LLM reply; used fallback text`
- NAT2-008: `explain: nat2_008__tpl_suppress_positive_3e_02: missing in LLM reply; used fallback text`
- NAT2-008: `explain: nat2_008__tpl_negative_suppress_10_01: missing in LLM reply; used fallback text`
- NAT2-010: `explain: nat2_010__tpl_read_did_positive_f186_01: missing in LLM reply; used fallback text`
- NAT2-010: `explain: nat2_010__tpl_write_readonly_f186: missing in LLM reply; used fallback text`
- NAT2-010: `explain: nat2_010__tpl_session_relock_01: missing in LLM reply; used fallback text`
- NAT2-010: `explain: nat2_010__tpl_seed_replay_01: missing in LLM reply; used fallback text`
- NAT2-010: `explain: nat2_010__tpl_negative_suppress_10_01: missing in LLM reply; used fallback text`
- NAT2-010: `explain: nat2_010__tpl_nrc_priority_2e_01: missing in LLM reply; used fallback text`
- NAT2-010: `explain: nat2_010__tpl_seed_while_unlocked_01: missing in LLM reply; used fallback text`
- NAT2-012: `explain: nat2_012__tpl_routine_after_reset_0202: missing in LLM reply; used fallback text`
- NAT2-012: `explain: nat2_012__tpl_security_lockout_01_reset: missing in LLM reply; used fallback text`
- NAT2-014: `explain: nat2_014__tpl_read_badlen_0110_01: missing in LLM reply; used fallback text`
- NAT2-014: `explain: nat2_014__tpl_write_readonly_0110: missing in LLM reply; used fallback text`
- NAT2-014: `explain: nat2_014__tpl_write_readonly_0111: missing in LLM reply; used fallback text`
- NAT2-015: `explain: nat2_015__tpl_dtc_clear_specific_B10101: missing in LLM reply; used fallback text`
- NAT2-015: `explain: nat2_015__tpl_dtc_clear_specific_B10205: missing in LLM reply; used fallback text`
- NAT2-015: `explain: nat2_015__tpl_dtc_clear_specific_B10310: missing in LLM reply; used fallback text`
- NAT2-016: `explain: nat2_016__tpl_read_did_positive_f190_01: missing in LLM reply; used fallback text`
- NAT2-016: `explain: nat2_016__tpl_write_secured_0100: missing in LLM reply; used fallback text`
- NAT3-002: `explain: nat3_002__tpl_write_secured_0130: missing in LLM reply; used fallback text`
- NAT3-002: `explain: nat3_002__tpl_write_retained_s3_0130: missing in LLM reply; used fallback text`
- NAT3-002: `explain: nat3_002__tpl_negative_suppress_10_03: missing in LLM reply; used fallback text`
- NAT3-004: `explain: nat3_004__tpl_read_badlen_0130_01: missing in LLM reply; used fallback text`
- NAT3-004: `explain: nat3_004__tpl_session_relock_01: missing in LLM reply; used fallback text`
- NAT3-004: `explain: nat3_004__tpl_seed_while_unlocked_01: missing in LLM reply; used fallback text`
- NAT3-004: `explain: nat3_004__tpl_s3_timeout_03: missing in LLM reply; used fallback text`
- NAT3-004: `explain: nat3_004__tpl_negative_suppress_10_03: missing in LLM reply; used fallback text`
- NAT3-006: `explain: nat3_006__tpl_negative_suppress_10_03: missing in LLM reply; used fallback text`
- NAT3-007: `explain: nat3_007__tpl_write_oor_0150: missing in LLM reply; used fallback text`
- NAT3-007: `explain: nat3_007__tpl_negative_suppress_31_02: missing in LLM reply; used fallback text`
- NAT3-007: `explain: nat3_007__tpl_read_multi_0150_f190_03: missing in LLM reply; used fallback text`
- NAT3-007: `explain: nat3_007__tpl_session_relock_03: missing in LLM reply; used fallback text`
- NAT3-007: `explain: nat3_007__tpl_seed_while_unlocked_03: missing in LLM reply; used fallback text`
- NAT3-008: `explain: nat3_008__tpl_write_oor_0150: missing in LLM reply; used fallback text`
- NAT3-008: `explain: nat3_008__tpl_write_retained_reset_0150: missing in LLM reply; used fallback text`
- NAT3-008: `explain: nat3_008__tpl_read_did_positive_0150_03: missing in LLM reply; used fallback text`
- NAT3-008: `explain: nat3_008__tpl_negative_suppress_11_01: missing in LLM reply; used fallback text`
- NAT3-008: `explain: nat3_008__tpl_security_lockout_03: missing in LLM reply; used fallback text`
- NAT3-008: `explain: nat3_008__tpl_seed_while_unlocked_03: missing in LLM reply; used fallback text`
- NAT3-008: `explain: nat3_008__tpl_session_relock_03: missing in LLM reply; used fallback text`
- NAT3-009: `explain: nat3_009__tpl_s3_timeout_02: missing in LLM reply; used fallback text`
- NAT3-009: `explain: nat3_009__tpl_security_lockout_01: missing in LLM reply; used fallback text`
- NAT3-009: `explain: nat3_009__tpl_seed_while_unlocked_01: missing in LLM reply; used fallback text`
- NAT3-009: `explain: nat3_009__tpl_seed_replay_01: missing in LLM reply; used fallback text`
- NAT3-010: `explain: nat3_010__tpl_service_not_in_session_2e_01: missing in LLM reply; used fallback text`
- NAT3-010: `explain: nat3_010__tpl_write_readonly_f190: missing in LLM reply; used fallback text`
- NAT3-010: `explain: nat3_010__tpl_write_oor_0100: missing in LLM reply; used fallback text`
- NAT3-010: `explain: nat3_010__tpl_write_badlen_0100: missing in LLM reply; used fallback text`
- NAT3-010: `explain: nat3_010__tpl_condition_not_met_did_0150: missing in LLM reply; used fallback text`
- NAT3-011: `explain: nat3_011__tpl_negative_suppress_10_03: missing in LLM reply; used fallback text`
- NAT3-011: `explain: nat3_011__tpl_suppress_positive_10_03: missing in LLM reply; used fallback text`
- NAT3-011: `explain: nat3_011__tpl_negative_suppress_10_01: missing in LLM reply; used fallback text`
- NAT3-012: `explain: nat3_012__tpl_negative_suppress_10_03: missing in LLM reply; used fallback text`
- NAT3-013: `explain: nat3_013__tpl_negative_suppress_3e_03: missing in LLM reply; used fallback text`
- NAT3-015: `explain: nat3_015__tpl_write_oor_0130: missing in LLM reply; used fallback text`
- NAT3-015: `explain: nat3_015__tpl_write_nosec_0130: missing in LLM reply; used fallback text`
- NAT3-015: `explain: nat3_015__tpl_read_multi_0130_f190_01: missing in LLM reply; used fallback text`
- NAT3-016: `explain: nat3_016__tpl_read_did_wrong_dead_01: missing in LLM reply; used fallback text`
- NAT3-016: `explain: nat3_016__tpl_read_badlen_f190_01: missing in LLM reply; used fallback text`
- NAT3-016: `explain: nat3_016__tpl_read_did_wrong_dead_02: missing in LLM reply; used fallback text`
- NAT3-016: `explain: nat3_016__tpl_read_did_wrong_dead_03: missing in LLM reply; used fallback text`
- NAT3-016: `explain: nat3_016__tpl_read_badlen_f187_01: missing in LLM reply; used fallback text`
- NAT3-016: `explain: nat3_016__tpl_read_badlen_f18c_01: missing in LLM reply; used fallback text`

**`ollama` — truncation events (0):**

- none

### Latency per requirement (wall clock)

| Scope | mock mean | ollama mean | mock p95 | ollama p95 | mock max | ollama max |
|---|---|---|---|---|---|---|
| seed (n=15) | 0.4 s | 22.5 s | 0.7 s | 30.5 s | 0.7 s | 30.5 s |
| natural (n=20) | 0.3 s | 21.3 s | 0.6 s | 29.2 s | 0.6 s | 30.1 s |
| all (n=35) | 0.4 s | 21.8 s | 0.6 s | 30.4 s | 0.7 s | 30.5 s |
| natural v2 (n=16) | 0.2 s | 21.8 s | 0.6 s | 30.1 s | 0.6 s | 30.1 s |
| natural v3 (n=16) | 0.3 s | 20.8 s | 0.6 s | 26.3 s | 0.6 s | 26.3 s |
| all with v2 (n=51) | 0.3 s | 21.8 s | 0.6 s | 30.1 s | 0.7 s | 30.5 s |
| all with v3 (n=67) | 0.3 s | 21.6 s | 0.6 s | 30.1 s | 0.7 s | 30.5 s |

Per-node mean latency per requirement (ms; p95 in brackets):

| Node | mock | ollama |
|---|---|---|
| parse | 2.3 [7.6] | 4649.8 [6376.6] |
| retrieve | 6.9 [11.1] | 7.1 [11.8] |
| plan | 16.6 [20.9] | 7409.0 [10934.2] |
| instantiate | 15.5 [29.5] | 8.6 [16.4] |
| validate | 21.9 [47.4] | 10.9 [21.5] |
| explain | 4.4 [7.7] | 9529.3 [16307.2] |
| time inside LLM calls | 0.0 [0.0] | 21554.9 [30081.8] |

_wall clock seconds of one run_pipeline call per requirement (parse through explain, including all LLM calls and re-plans); p95 is nearest-rank; per-node values are per requirement in milliseconds._

### Coverage, citations, request validity, byte provenance

| Metric | mock | ollama |
|---|---|---|
| Coverage: tests per category (positive, negative, session, security, timing) | 43 / 77 / 25 / 30 / 31 | 26 / 27 / 4 / 7 / 9 |
| Coverage: seed requirements with ≥1 test | 15/15 (100.0%) | 15/15 (100.0%) |
| Citation validity | 967/967 (100.0%) | 353/353 (100.0%) |
| Request validity (adjusted) | 691/691 (100.0%) | 226/226 (100.0%) |
| Generated tests passing on the clean simulator | 206/206 (100.0%) | 73/73 (100.0%) |
| Byte provenance — seed-requirement tests | 206/206 passed | 73/73 passed |
| Byte provenance — natural v1 requirement tests | 205/205 passed | 114/114 passed |
| Byte provenance — natural v2 requirement tests | 100/100 passed | 87/87 passed |
| Byte provenance — natural v3 requirement tests | 102/102 passed | 94/94 passed |
| Byte provenance — extra noise-check runs (natural v3) | none (no extra runs) | 184/184 passed over 2 run(s) |
| **Byte provenance — all generated tests, all runs** | 613/613 passed | 552/552 passed |

_Byte provenance: each generated test re-instantiated from TEMPLATES[template_id].instantiate(spec, params_model.model_validate(test.parameters)) (conformance-sweep tests: from the conformance registry, which the planner never sees); template_id must be registered, parameters must round-trip, and every step must be identical (request and expected-response bytes, time/environment/DTC steps, descriptions, timing limits)._

## Retrieval comparison (BM25 vs Chroma)

Queries are the `text` of each row of `data/requirements_natural.csv`; 19 of 20 scored (NAT-020 excluded: no target service/DID/routine). Relevant chunks: ecu_spec chunks carrying a target DID/routine identifier; for rows with no DID/routine, the standard-collection `svc-<sid>` chunk of each target service. Search spans all collections; MRR uses the first relevant rank in the top 10 (0 if none); citation validity is over the top 3 hits.

| split | backend | queries | hit@1 | hit@3 | MRR | citation validity (top 3) |
|---|---|---|---|---|---|---|
| dev | bm25 | 8 | 0.0% | 37.5% | 0.275 | 100.0% |
| dev | chroma | 8 | 0.0% | 75.0% | 0.374 | 100.0% |
| **test** | **bm25** | 11 | 27.3% | 63.6% | 0.506 | 100.0% |
| **test** | **chroma** | 11 | 18.2% | 63.6% | 0.458 | 100.0% |
| all | bm25 | 19 | 15.8% | 52.6% | 0.408 | 100.0% |
| all | chroma | 19 | 10.5% | 68.4% | 0.422 | 100.0% |

Rank of the first relevant chunk per query (0 = not in top 10):

| query | split | relevant chunks | BM25 rank | Chroma rank |
|---|---|---|---|---|
| NAT-001 | dev | 1 | 0 | 8 |
| NAT-002 | test | 2 | 2 | 4 |
| NAT-003 | dev | 1 | 6 | 5 |
| NAT-004 | test | 1 | 0 | 0 |
| NAT-005 | dev | 1 | 4 | 3 |
| NAT-006 | test | 1 | 2 | 4 |
| NAT-007 | dev | 1 | 2 | 2 |
| NAT-008 | test | 1 | 1 | 2 |
| NAT-009 | dev | 1 | 5 | 3 |
| NAT-010 | test | 1 | 5 | 2 |
| NAT-011 | dev | 1 | 4 | 2 |
| NAT-012 | test | 1 | 4 | 2 |
| NAT-013 | dev | 1 | 2 | 2 |
| NAT-014 | test | 1 | 2 | 1 |
| NAT-015 | dev | 1 | 3 | 2 |
| NAT-016 | test | 1 | 1 | 1 |
| NAT-017 | test | 2 | 2 | 3 |
| NAT-018 | test | 1 | 9 | 5 |
| NAT-019 | test | 1 | 1 | 2 |

## LLM-independent checks (details)

- Simulator ↔ rules engine: 5000/5000 requests agreed over 89 seeded walks (seed 20261003).
- Gold tests on the bug-free simulator: 60/60.
- udsoncan virtual-CAN sequence: **PASS**
  - 10 03 extended session: positive
  - 27 01 seed: 950677e8
  - 27 02 key: positive (unlocked)
  - 22 0100 read: 0x32
  - 2E 0100 write 0x50: positive
  - 22 0100 read-back: 0x50

## Freeze verification (Part D freeze: templates / sweep / prompts / agent / gold)

Recorded hashes are parsed from PROGRESS.md 'Part D freeze' table; current = `git rev-parse HEAD:<path>` when this report ran.

| Path | recorded (Part D freeze) | current | result | worktree clean |
|---|---|---|---|---|
| freeze commit | `4042f260527f76b781546cb39687b080d19ecb61` | `1f0c293a2033da0e4316197341c814d10aa16b1f` (HEAD) | ancestor of HEAD | - |
| `uds_assistant/testgen` | `d990ef45a4f5f38c4ea59cc30e42011ccecf6ab9` | `d990ef45a4f5f38c4ea59cc30e42011ccecf6ab9` | match | True |
| `uds_assistant/llm` | `0dad8c4165842d10e7bf15c0c5554881d8db13d3` | `0dad8c4165842d10e7bf15c0c5554881d8db13d3` | match | True |
| `uds_assistant/agent` | `5875c8629e01fe7dadab98d6f2de584aa0b4af05` | `5875c8629e01fe7dadab98d6f2de584aa0b4af05` | match | True |
| `uds_assistant/llm/prompts.py` | `c117f993ef0d10657f36eaf2c08f132d02efbda4` | `c117f993ef0d10657f36eaf2c08f132d02efbda4` | match | True |
| `uds_assistant/testgen/conformance.py` | `edc143372c412ba65305231d6241eeacdc18b7d8` | `edc143372c412ba65305231d6241eeacdc18b7d8` | match | True |
| `uds_assistant/agent/service_lexicon.py` | `42ceae7509950189d69da8ce7516d15c2b1b1982` | `42ceae7509950189d69da8ce7516d15c2b1b1982` | match | True |
| `data/gold` | `778740195a3dc923ae2f6a34fd4b78e11d87b024` | `778740195a3dc923ae2f6a34fd4b78e11d87b024` | match | True |

All recorded freeze hashes match and are clean: **True**.

# Details — mode=mock

Generated tests (seed requirements): **206** (119 unique template instantiations); 206/206 (100.0%) pass on the clean simulator; P2/P2* wall-clock warnings: 0.

## Held-out v3 bug detection (15 FRESH bugs) — FRESH HEADLINE — mode=mock

Scope: held-out v3 (FRESH): 15 bugs written blind by a subagent after the Part D freeze, which could not see templates, the conformance sweep, prompts, eval code or any report; nothing was changed after seeing these results. Catalog: `data/bugs/heldout_v3_catalog.yaml`.

15 bugs written blind after the Part D freeze by a subagent that could not see templates, the conformance sweep, prompts, eval code or any report; nothing was changed after seeing these results.

| Bug | Category | (a) req-driven | tests | (b) sweep | tests | (c) full output | gold | all generated (suppl.) | natural v3 (suppl.) | tests applying the trigger, per suite | reason if missed by the headline suite |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `session_switch_keeps_pending_seed` | session | **no** | 0 | **no** | 0 | **no** | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=0, full_output=0, all_generated=0, natural_v3_generated=0 | no full_output test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24) |
| `session_response_p2_star_in_ms` | timing | yes | 143 | yes | 1037 | yes | yes | yes | yes | requirement_driven=143, gold=35, conformance=1037, full_output=1180, all_generated=404, natural_v3_generated=65 | - |
| `failed_key_keeps_pending_seed` | security | **no** | 0 | yes | 6 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=6, full_output=6, all_generated=0, natural_v3_generated=0 | - |
| `lockout_expiry_resets_attempt_count` | security | **no** | 0 | **no** | 0 | **no** | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=0, full_output=0, all_generated=0, natural_v3_generated=0 | no full_output test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36) |
| `nrc_order_subfunction_before_length` | nrc_order | **no** | 0 | **no** | 0 | **no** | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=0, full_output=0, all_generated=0, natural_v3_generated=0 | no full_output test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13) |
| `nrc_order_write_range_before_condition` | nrc_order | **no** | 0 | yes | 1 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=1, full_output=1, all_generated=0, natural_v3_generated=0 | - |
| `routine_results_trailing_bytes_accepted` | format | **no** | 0 | yes | 3 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=3, full_output=3, all_generated=0, natural_v3_generated=0 | - |
| `read_did_speed_not_clamped` | data | **no** | 0 | **no** | 0 | **no** | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=0, full_output=0, all_generated=0, natural_v3_generated=0 | no full_output test reads DID 0x0140 while the vehicle speed is above 255 kph |
| `write_stores_value_before_range_rejection` | data | **no** | 0 | yes | 1 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=1, full_output=1, all_generated=0, natural_v3_generated=0 | - |
| `routine_stop_reports_completed_status` | data | yes | 2 | yes | 20 | yes | yes | yes | yes | requirement_driven=2, gold=1, conformance=20, full_output=22, all_generated=8, natural_v3_generated=2 | - |
| `dtc_clear_single_clears_neighbour` | data | yes | 2 | **no** | 0 | yes | yes | yes | yes | requirement_driven=2, gold=1, conformance=0, full_output=2, all_generated=10, natural_v3_generated=2 | - |
| `dtc_read_reports_masked_status` | data | **no** | 0 | **no** | 0 | **no** | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=0, full_output=0, all_generated=0, natural_v3_generated=0 | no full_output test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask |
| `ecu_reset_resets_seed_counter` | security | yes | 8 | yes | 15 | yes | **no** | yes | yes | requirement_driven=8, gold=0, conformance=15, full_output=23, all_generated=28, natural_v3_generated=6 | - |
| `s3_timeout_clears_dtc_status` | timing | **no** | 0 | yes | 6 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=6, full_output=6, all_generated=0, natural_v3_generated=0 | - |
| `suppressed_request_does_not_restart_s3` | timing | **no** | 0 | yes | 33 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=37, full_output=37, all_generated=0, natural_v3_generated=0 | - |

Totals: (a) requirement-driven 4/15 (26.7%), (b) sweep alone 9/15 (60.0%), (c) full output 10/15 (66.7%), gold 3/15 (20.0%). Invalid tests (fail on the clean simulator): requirement-driven 0, gold 0.

### Trigger coverage: how many bugs' stimuli each suite applies (coverage report only)

| Suite | bugs whose stimulus is applied | total stimulus applications |
|---|---|---|
| requirement_driven | 4/15 | 155 |
| gold | 3/15 | 37 |
| conformance | 9/15 | 1126 |
| full_output | 10/15 | 1281 |
| all_generated | 4/15 | 450 |
| natural_v3_generated | 4/15 | 75 |

### Missed v3 bugs — full_output (the headline suite, mode=mock)

- `session_switch_keeps_pending_seed`: no full_output test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no full_output test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no full_output test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `read_did_speed_not_clamped`: no full_output test reads DID 0x0140 while the vehicle speed is above 255 kph
- `dtc_read_reports_masked_status`: no full_output test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask

### Missed v3 bugs — requirement-driven suite

- `session_switch_keeps_pending_seed`: no requirement_driven test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `failed_key_keeps_pending_seed`: no requirement_driven test sends a wrong key and then a second key for the same seed (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no requirement_driven test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no requirement_driven test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `nrc_order_write_range_before_condition`: no requirement_driven test writes an out-of-range value to a conditioned DID while the condition fails (expected 0x22)
- `routine_results_trailing_bytes_accepted`: no requirement_driven test sends a requestResults (31 03 RID) with trailing bytes (expected 0x13)
- `read_did_speed_not_clamped`: no requirement_driven test reads DID 0x0140 while the vehicle speed is above 255 kph
- `write_stores_value_before_range_rejection`: no requirement_driven test has an out-of-range write refused (0x31) and later reads the same DID back
- `dtc_read_reports_masked_status`: no requirement_driven test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask
- `s3_timeout_clears_dtc_status`: no requirement_driven test stores a DTC status, lets an S3 timeout drop a session, then reads the DTCs
- `suppressed_request_does_not_restart_s3`: no requirement_driven test sends a suppressed request in a non-default session and then waits so that S3 is exceeded only when counted from the last answered request

### Missed v3 bugs — conformance suite

- `session_switch_keeps_pending_seed`: no conformance test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no conformance test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no conformance test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `read_did_speed_not_clamped`: no conformance test reads DID 0x0140 while the vehicle speed is above 255 kph
- `dtc_clear_single_clears_neighbour`: no conformance test clears one DTC while the next DTC in spec order is stored, then reads the DTCs back with a mask that shows it
- `dtc_read_reports_masked_status`: no conformance test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask

### Missed v3 bugs — gold suite

- `session_switch_keeps_pending_seed`: no gold test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `failed_key_keeps_pending_seed`: no gold test sends a wrong key and then a second key for the same seed (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no gold test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no gold test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `nrc_order_write_range_before_condition`: no gold test writes an out-of-range value to a conditioned DID while the condition fails (expected 0x22)
- `routine_results_trailing_bytes_accepted`: no gold test sends a requestResults (31 03 RID) with trailing bytes (expected 0x13)
- `read_did_speed_not_clamped`: no gold test reads DID 0x0140 while the vehicle speed is above 255 kph
- `write_stores_value_before_range_rejection`: no gold test has an out-of-range write refused (0x31) and later reads the same DID back
- `dtc_read_reports_masked_status`: no gold test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask
- `ecu_reset_resets_seed_counter`: no gold test issues a seed, resets the ECU, and then observes a newly issued seed
- `s3_timeout_clears_dtc_status`: no gold test stores a DTC status, lets an S3 timeout drop a session, then reads the DTCs
- `suppressed_request_does_not_restart_s3`: no gold test sends a suppressed request in a non-default session and then waits so that S3 is exceeded only when counted from the last answered request

### Missed v3 bugs — all generated tests (supplementary)

- `session_switch_keeps_pending_seed`: no all_generated test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `failed_key_keeps_pending_seed`: no all_generated test sends a wrong key and then a second key for the same seed (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no all_generated test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no all_generated test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `nrc_order_write_range_before_condition`: no all_generated test writes an out-of-range value to a conditioned DID while the condition fails (expected 0x22)
- `routine_results_trailing_bytes_accepted`: no all_generated test sends a requestResults (31 03 RID) with trailing bytes (expected 0x13)
- `read_did_speed_not_clamped`: no all_generated test reads DID 0x0140 while the vehicle speed is above 255 kph
- `write_stores_value_before_range_rejection`: no all_generated test has an out-of-range write refused (0x31) and later reads the same DID back
- `dtc_read_reports_masked_status`: no all_generated test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask
- `s3_timeout_clears_dtc_status`: no all_generated test stores a DTC status, lets an S3 timeout drop a session, then reads the DTCs
- `suppressed_request_does_not_restart_s3`: no all_generated test sends a suppressed request in a non-default session and then waits so that S3 is exceeded only when counted from the last answered request

### Missed v3 bugs — natural-v3 tests alone (supplementary)

- `session_switch_keeps_pending_seed`: no natural_v3_generated test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `failed_key_keeps_pending_seed`: no natural_v3_generated test sends a wrong key and then a second key for the same seed (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no natural_v3_generated test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no natural_v3_generated test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `nrc_order_write_range_before_condition`: no natural_v3_generated test writes an out-of-range value to a conditioned DID while the condition fails (expected 0x22)
- `routine_results_trailing_bytes_accepted`: no natural_v3_generated test sends a requestResults (31 03 RID) with trailing bytes (expected 0x13)
- `read_did_speed_not_clamped`: no natural_v3_generated test reads DID 0x0140 while the vehicle speed is above 255 kph
- `write_stores_value_before_range_rejection`: no natural_v3_generated test has an out-of-range write refused (0x31) and later reads the same DID back
- `dtc_read_reports_masked_status`: no natural_v3_generated test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask
- `s3_timeout_clears_dtc_status`: no natural_v3_generated test stores a DTC status, lets an S3 timeout drop a session, then reads the DTCs
- `suppressed_request_does_not_restart_s3`: no natural_v3_generated test sends a suppressed request in a non-default session and then waits so that S3 is exceeded only when counted from the last answered request

_Reasons come from `uds_assistant/eval/heldout_v3.py`: one predicate per bug, written only from the bug descriptions in `data/bugs/heldout_v3_catalog.yaml` and `docs/behaviour_contract.md` before any v3 result existed. "no X test ..." means no test in that suite applies the stimulus; "N X test(s) ..., but none of their expected responses differs" means the stimulus is present but the oracle-derived expectations do not distinguish the bug. Reporting only — nothing was changed in response._

## Requirement understanding, natural v3 (split test3, FRESH HEADLINE) — mode=mock

Source: `data/requirements_natural_v3.csv` (16 labelled rows). Each requirement was run through the agent pipeline (`mode=mock`, Bm25Retriever). **The test3 split is the main number (fresh, nothing tuned on it).**

| Split | n | Targets exact (parsed) | Parsed P / R / F1 | Targets exact (exercised) | Exercised P / R / F1 | Category recall micro / macro | Precondition recall micro / macro | Fallback / nothing |
|---|---|---|---|---|---|---|---|---|
| **test3** | 16 | 1/16 (6.2%) | 0.857 / 0.267 / 0.407 | 0/16 (0.0%) | 0.278 / 0.444 / 0.342 | 21/50 (42.0%) / 39.6% | 14/29 (48.3%) / 44.9% | 7 (7 excl. empty-label rows) |
| all | 16 | 1/16 (6.2%) | 0.857 / 0.267 / 0.407 | 0/16 (0.0%) | 0.278 / 0.444 / 0.342 | 21/50 (42.0%) / 39.6% | 14/29 (48.3%) / 44.9% | 7 (7 excl. empty-label rows) |

### Per requirement (natural v3, mode=mock)

| Req | Split | Tests | Label targets | Parsed exact | Parsed missed | Parsed extra | Exercised exact | Exercised missed | Exercised extra (n) | Categories missed | Preconditions missed | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NAT3-001 | test3 | 4 | did:0xF187, did:0xF18C, did:0xF190, service:0x22 | no | did:0xF187, service:0x22 | - | no | did:0xF187 | 4 | positive | - | - |
| NAT3-002 | test3 | 0 | service:0x27 | no | service:0x27 | - | no | service:0x27 | 0 | negative, security, timing | extended_session, lockout_active | no parsed services/DIDs/routines; zero tests |
| NAT3-003 | test3 | 0 | did:0x0120, service:0x10, service:0x27, service:0x2E | no | did:0x0120, service:0x10, service:0x27, service:0x2E | - | no | did:0x0120, service:0x10, service:0x27, service:0x2E | 0 | negative, positive, security, session | extended_session, security_level_1 | no parsed services/DIDs/routines; zero tests |
| NAT3-004 | test3 | 14 | did:0x0130, service:0x2E | no | service:0x2E | - | no | - | 8 | - | - | - |
| NAT3-005 | test3 | 15 | routine:0x0201, service:0x31 | no | service:0x31 | - | no | - | 9 | - | - | - |
| NAT3-006 | test3 | 19 | routine:0x0202, service:0x31 | no | service:0x31 | - | no | - | 11 | - | - | - |
| NAT3-007 | test3 | 0 | routine:0x0203, service:0x31 | no | routine:0x0203, service:0x31 | - | no | routine:0x0203, service:0x31 | 0 | negative, positive, security, session, timing | programming_session, security_level_3 | no parsed services/DIDs/routines; zero tests |
| NAT3-008 | test3 | 20 | did:0x0150, service:0x2E | yes | - | - | no | - | 12 | - | - | - |
| NAT3-009 | test3 | 9 | did:0x0160, service:0x10, service:0x11, service:0x22, service:0x27, service:0x2E | no | did:0x0160, service:0x10, service:0x27 | - | no | did:0x0160, service:0x27 | 2 | positive, security | security_level_3 | - |
| NAT3-010 | test3 | 9 | service:0x14, service:0x19 | no | service:0x14, service:0x19 | service:0x22 | no | - | 3 | - | - | - |
| NAT3-011 | test3 | 0 | did:0xF186, service:0x10, service:0x22, service:0x3E | no | did:0xF186, service:0x10, service:0x22, service:0x3E | - | no | did:0xF186, service:0x10, service:0x22, service:0x3E | 0 | positive, session, timing | extended_session, s3_elapsed | no parsed services/DIDs/routines; zero tests |
| NAT3-012 | test3 | 11 | did:0x0100, service:0x10, service:0x27, service:0x2E, service:0x3E | no | did:0x0100, service:0x27, service:0x3E | - | no | service:0x27, service:0x3E | 1 | security, timing | s3_elapsed, security_level_1 | - |
| NAT3-013 | test3 | 0 | service:0x3E | no | service:0x3E | - | no | service:0x3E | 0 | positive, timing | - | no parsed services/DIDs/routines; zero tests |
| NAT3-014 | test3 (ambiguous) | 0 | did:0xF186, service:0x10, service:0x11, service:0x22, service:0x27 | no | did:0xF186, service:0x10, service:0x11, service:0x22, service:0x27 | - | no | did:0xF186, service:0x10, service:0x11, service:0x22, service:0x27 | 0 | positive, security, session | extended_session, security_level_1 | no parsed services/DIDs/routines; zero tests |
| NAT3-015 | test3 (ambiguous) | 0 | did:0x0130, did:0x0131, service:0x2E | no | did:0x0130, did:0x0131, service:0x2E | - | no | did:0x0130, did:0x0131, service:0x2E | 0 | negative, positive, security | extended_session, security_level_1 | no parsed services/DIDs/routines; zero tests |
| NAT3-016 | test3 | 1 | (none) | no | - | service:0x22 | no | - | 2 | positive | - | - |

## Held-out v2 bug detection (15 bugs, SEEN) — mode=mock

Scope: held-out v2, now SEEN: 15 bugs written blind by a subagent after the Part C freeze (fresh in Part C); their Part C results were known before Part D, so they are no longer independent evidence. Catalog: `data/bugs/heldout_v2_catalog.yaml`.

Generated suite = the tests from the 15 seed requirements (the Part C headline definition). The two supplementary columns use all generated tests (seed + natural v1 + natural v2) and the natural-v2 tests alone.

| Bug | Category | Generated (seed reqs) | Generated detecting tests | Gen. tests applying trigger | Gold | Gold tests applying trigger | All generated (suppl.) | trigger | Natural-v2 tests (suppl.) | trigger |
|---|---|---|---|---|---|---|---|---|---|---|
| `session_reentry_keeps_unlock` | session | yes | `req_005__tpl_session_relock_01`, `req_006__tpl_session_relock_01` (+6 more) | 8 | yes | 1 | yes | 22 | yes | 5 |
| `s3_restart_skipped_on_negative_response` | timing | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `s3_timeout_resets_lockout_counters` | session | **no** | - | 12 | **no** | 0 | **no** | 30 | **no** | 6 |
| `ecu_reset_keeps_session` | session | **no** | - | 13 | yes | 1 | **no** | 31 | **no** | 6 |
| `seed_request_keeps_stale_pending_seed` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `key_compare_prefix_only` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `lockout_counter_pooled_across_levels` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `nrc_order_range_before_security` | nrc_order | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `nrc_order_nvm_fault_before_group_check` | nrc_order | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `read_dtc_trailing_bytes_accepted` | format | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `routine_option_record_overlong_accepted` | format | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `write_range_upper_bound_exclusive` | data | yes | `req_006__tpl_write_retained_s3_0101`, `req_006__tpl_write_retained_reset_0101` (+4 more) | 6 | yes | 2 | yes | 10 | yes | 2 |
| `multi_did_read_dedups_repeats` | data | **no** | - | 0 | yes | 1 | **no** | 0 | **no** | 0 |
| `routine_restart_after_stop_blocked` | sequence | **no** | - | 0 | yes | 1 | **no** | 0 | **no** | 0 |
| `suppressed_seed_request_not_stored` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |

Totals: generated 2/15 (13.3%), gold 5/15 (33.3%), union 5/15 (33.3%). Invalid tests (fail on the clean simulator): generated 0, gold 0.
- Supplementary — All generated tests (seed + natural v1 + natural v2): 511 tests, 2/15 (13.3%) detected (0 invalid tests).
- Supplementary — Tests generated from natural v2 alone: 100 tests, 2/15 (13.3%) detected (0 invalid tests).

### Missed held-out v2 bugs — generated suite (mode=mock)

- `s3_restart_skipped_on_negative_response`: no generated test answers a request with an NRC in a non-default session and then wait so that S3 is exceeded only when counted from the last positive request
- `s3_timeout_resets_lockout_counters`: 12 generated test(s) reaches a security lockout, lets S3 expire and then requests a seed, but none of their expected responses differs under the bug
- `ecu_reset_keeps_session`: 13 generated test(s) sends a positive ECUReset from a non-default session and then another request, but none of their expected responses differs under the bug
- `seed_request_keeps_stale_pending_seed`: no generated test requests a seed twice for one level before sending a key for it
- `key_compare_prefix_only`: no generated test sends a key with the right first two bytes and a wrong tail
- `lockout_counter_pooled_across_levels`: no generated test sends wrong keys at two different levels that together reach the attempt limit
- `nrc_order_range_before_security`: no generated test writes an out-of-range value of correct length to a DID in its write session while security is locked
- `nrc_order_nvm_fault_before_group_check`: no generated test clears an unknown DTC group (0x14) while the NVM write fault is set
- `read_dtc_trailing_bytes_accepted`: no generated test sends 19 02 with more than one byte after the sub-function
- `routine_option_record_overlong_accepted`: no generated test starts a routine (in its session) with an over-long option record
- `multi_did_read_dedups_repeats`: no generated test reads one DID several times in a single 0x22 request
- `routine_restart_after_stop_blocked`: no generated test starts a routine again after stopping it
- `suppressed_seed_request_not_stored`: no generated test sends a suppressed seed request (27 81 / 27 83) and then a key for that level

### Missed held-out v2 bugs — gold suite

- `s3_restart_skipped_on_negative_response`: no gold test answers a request with an NRC in a non-default session and then wait so that S3 is exceeded only when counted from the last positive request
- `s3_timeout_resets_lockout_counters`: no gold test reaches a security lockout, lets S3 expire and then requests a seed
- `seed_request_keeps_stale_pending_seed`: no gold test requests a seed twice for one level before sending a key for it
- `key_compare_prefix_only`: no gold test sends a key with the right first two bytes and a wrong tail
- `lockout_counter_pooled_across_levels`: no gold test sends wrong keys at two different levels that together reach the attempt limit
- `nrc_order_range_before_security`: no gold test writes an out-of-range value of correct length to a DID in its write session while security is locked
- `nrc_order_nvm_fault_before_group_check`: no gold test clears an unknown DTC group (0x14) while the NVM write fault is set
- `read_dtc_trailing_bytes_accepted`: no gold test sends 19 02 with more than one byte after the sub-function
- `routine_option_record_overlong_accepted`: no gold test starts a routine (in its session) with an over-long option record
- `suppressed_seed_request_not_stored`: no gold test sends a suppressed seed request (27 81 / 27 83) and then a key for that level

### Missed held-out v2 bugs — all generated tests (supplementary)

- `s3_restart_skipped_on_negative_response`: no all_generated test answers a request with an NRC in a non-default session and then wait so that S3 is exceeded only when counted from the last positive request
- `s3_timeout_resets_lockout_counters`: 30 all_generated test(s) reaches a security lockout, lets S3 expire and then requests a seed, but none of their expected responses differs under the bug
- `ecu_reset_keeps_session`: 31 all_generated test(s) sends a positive ECUReset from a non-default session and then another request, but none of their expected responses differs under the bug
- `seed_request_keeps_stale_pending_seed`: no all_generated test requests a seed twice for one level before sending a key for it
- `key_compare_prefix_only`: no all_generated test sends a key with the right first two bytes and a wrong tail
- `lockout_counter_pooled_across_levels`: no all_generated test sends wrong keys at two different levels that together reach the attempt limit
- `nrc_order_range_before_security`: no all_generated test writes an out-of-range value of correct length to a DID in its write session while security is locked
- `nrc_order_nvm_fault_before_group_check`: no all_generated test clears an unknown DTC group (0x14) while the NVM write fault is set
- `read_dtc_trailing_bytes_accepted`: no all_generated test sends 19 02 with more than one byte after the sub-function
- `routine_option_record_overlong_accepted`: no all_generated test starts a routine (in its session) with an over-long option record
- `multi_did_read_dedups_repeats`: no all_generated test reads one DID several times in a single 0x22 request
- `routine_restart_after_stop_blocked`: no all_generated test starts a routine again after stopping it
- `suppressed_seed_request_not_stored`: no all_generated test sends a suppressed seed request (27 81 / 27 83) and then a key for that level

### Missed held-out v2 bugs — natural-v2 tests alone (supplementary)

- `s3_restart_skipped_on_negative_response`: no natural_v2_generated test answers a request with an NRC in a non-default session and then wait so that S3 is exceeded only when counted from the last positive request
- `s3_timeout_resets_lockout_counters`: 6 natural_v2_generated test(s) reaches a security lockout, lets S3 expire and then requests a seed, but none of their expected responses differs under the bug
- `ecu_reset_keeps_session`: 6 natural_v2_generated test(s) sends a positive ECUReset from a non-default session and then another request, but none of their expected responses differs under the bug
- `seed_request_keeps_stale_pending_seed`: no natural_v2_generated test requests a seed twice for one level before sending a key for it
- `key_compare_prefix_only`: no natural_v2_generated test sends a key with the right first two bytes and a wrong tail
- `lockout_counter_pooled_across_levels`: no natural_v2_generated test sends wrong keys at two different levels that together reach the attempt limit
- `nrc_order_range_before_security`: no natural_v2_generated test writes an out-of-range value of correct length to a DID in its write session while security is locked
- `nrc_order_nvm_fault_before_group_check`: no natural_v2_generated test clears an unknown DTC group (0x14) while the NVM write fault is set
- `read_dtc_trailing_bytes_accepted`: no natural_v2_generated test sends 19 02 with more than one byte after the sub-function
- `routine_option_record_overlong_accepted`: no natural_v2_generated test starts a routine (in its session) with an over-long option record
- `multi_did_read_dedups_repeats`: no natural_v2_generated test reads one DID several times in a single 0x22 request
- `routine_restart_after_stop_blocked`: no natural_v2_generated test starts a routine again after stopping it
- `suppressed_seed_request_not_stored`: no natural_v2_generated test sends a suppressed seed request (27 81 / 27 83) and then a key for that level

_Reasons come from `uds_assistant/eval/heldout_v2.py`: one predicate per bug, written only from the bug descriptions in `data/bugs/heldout_v2_catalog.yaml` and `docs/behaviour_contract.md` before any v2 result existed. "no test X" means no test in that suite applies the stimulus; "N test(s) X, but none of their expected responses differs" means the stimulus is present but the oracle-derived expectations do not distinguish the bug. Reporting only — nothing was changed in response._

## Requirement understanding, natural v2 (split test2, SEEN) — mode=mock

Source: `data/requirements_natural_v2.csv` (16 labelled rows). Each requirement was run through the agent pipeline (`mode=mock`, Bm25Retriever). **The test2 split is SEEN (fresh in Part C).**

| Split | n | Targets exact (parsed) | Parsed P / R / F1 | Targets exact (exercised) | Exercised P / R / F1 | Category recall micro / macro | Precondition recall micro / macro | Fallback / nothing |
|---|---|---|---|---|---|---|---|---|
| **test2** | 16 | 0/16 (0.0%) | 1.000 / 0.225 / 0.367 | 0/16 (0.0%) | 0.380 / 0.551 / 0.450 | 24/50 (48.0%) / 48.9% | 15/27 (55.6%) / 53.8% | 7 (6 excl. empty-label rows) |
| all | 16 | 0/16 (0.0%) | 1.000 / 0.225 / 0.367 | 0/16 (0.0%) | 0.380 / 0.551 / 0.450 | 24/50 (48.0%) / 48.9% | 15/27 (55.6%) / 53.8% | 7 (6 excl. empty-label rows) |

### Per requirement (natural v2, mode=mock)

| Req | Split | Tests | Label targets | Parsed exact | Parsed missed | Parsed extra | Exercised exact | Exercised missed | Exercised extra (n) | Categories missed | Preconditions missed | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NAT2-001 | test2 | 18 | did:0xF187, did:0xF18C, did:0xF190, service:0x22 | no | did:0xF187, did:0xF18C | - | no | - | 7 | - | - | - |
| NAT2-002 | test2 | 14 | did:0x0120, service:0x10, service:0x27, service:0x2E | no | service:0x10, service:0x27, service:0x2E | - | no | - | 6 | - | - | - |
| NAT2-003 | test2 | 16 | did:0x0130, service:0x22, service:0x27, service:0x2E | no | service:0x22, service:0x27 | - | no | - | 6 | - | - | - |
| NAT2-004 | test2 | 8 | routine:0x0201, service:0x31 | no | service:0x31 | - | no | - | 4 | security | - | - |
| NAT2-005 | test2 | 0 | routine:0x0203, service:0x10, service:0x27, service:0x31 | no | routine:0x0203, service:0x10, service:0x27, service:0x31 | - | no | routine:0x0203, service:0x10, service:0x27, service:0x31 | 0 | negative, positive, security, session, timing | programming_session, security_level_3 | no parsed services/DIDs/routines; zero tests |
| NAT2-006 | test2 | 0 | service:0x27 | no | service:0x27 | - | no | service:0x27 | 0 | negative, security, timing | extended_session, lockout_active | no parsed services/DIDs/routines; zero tests |
| NAT2-007 | test2 | 8 | service:0x14, service:0x19 | no | service:0x14, service:0x19 | - | no | - | 1 | negative | - | no parsed services/DIDs/routines |
| NAT2-008 | test2 | 2 | service:0x10, service:0x22, service:0x3E | no | service:0x10, service:0x22, service:0x3E | - | no | service:0x3E | 1 | negative, positive, session | - | no parsed services/DIDs/routines |
| NAT2-009 | test2 | 2 | did:0x0100, service:0x10, service:0x27, service:0x2E | no | did:0x0100, service:0x10, service:0x27 | - | no | service:0x10, service:0x27 | 1 | security, timing | extended_session, s3_elapsed, security_level_1 | - |
| NAT2-010 | test2 | 1 | did:0xF186, service:0x10, service:0x11, service:0x22, service:0x27 | no | did:0xF186, service:0x10, service:0x11, service:0x27 | - | no | did:0xF186, service:0x10, service:0x11, service:0x27 | 1 | positive, security, session | extended_session, security_level_1 | - |
| NAT2-011 | test2 | 2 | service:0x3E | no | service:0x3E | - | no | service:0x3E | 3 | positive | - | no parsed services/DIDs/routines |
| NAT2-012 | test2 | 19 | routine:0x0202, service:0x10, service:0x27, service:0x31 | no | service:0x10, service:0x27, service:0x31 | - | no | - | 9 | - | - | - |
| NAT2-013 | test2 | 1 | did:0x0160, service:0x10, service:0x22, service:0x27, service:0x2E | no | did:0x0160, service:0x10, service:0x27, service:0x2E | - | no | did:0x0160, service:0x10, service:0x27, service:0x2E | 1 | positive, security, session | programming_session, security_level_3 | - |
| NAT2-014 | test2 (ambiguous) | 1 | did:0x0110, did:0x0111, service:0x22, service:0x2E | no | did:0x0110, did:0x0111, service:0x2E | - | no | did:0x0110, did:0x0111, service:0x2E | 1 | positive, security | - | - |
| NAT2-015 | test2 (ambiguous) | 0 | service:0x10, service:0x14 | no | service:0x10, service:0x14 | - | no | service:0x10, service:0x14 | 0 | negative, session | programming_session | no parsed services/DIDs/routines; zero tests |
| NAT2-016 | test2 | 8 | (none) | no | - | - | no | - | 3 | - | - | no parsed services/DIDs/routines |

## Held-out bug detection (12 v1 bugs — SEEN: templates designed against these misses) — mode=mock

Scope: held-out v1, now SEEN: bugs written by an independent subagent that could not see templates, gold tests, eval, LLM or agent code; the template-set-v3 coverage templates were then designed against the misses, so these 12 are no longer independent. Catalog: `data/bugs/heldout_catalog.yaml`.

| Bug | Category | Generated | Generated detecting tests | Gen. tests applying trigger | Gold | Gold detecting tests | Gold tests applying trigger |
|---|---|---|---|---|---|---|---|
| `routine_state_survives_session_change` | session | yes | `req_011__tpl_routine_after_session_0201`, `req_012__tpl_routine_after_session_0202` | 4 | **no** | - | 0 |
| `failed_attempts_reset_by_seed_request` | security | yes | `req_005__tpl_security_lockout_01`, `req_005__tpl_security_lockout_01_reset` (+10 more) | 12 | yes | `gold_security_lockout_after_3` | 1 |
| `seed_returned_while_unlocked` | security | yes | `req_005__tpl_seed_while_unlocked_01`, `req_006__tpl_seed_while_unlocked_01` (+4 more) | 6 | yes | `gold_security_already_unlocked_seed` | 1 |
| `nrc_order_condition_before_security` | nrc_order | yes | `req_012__tpl_condition_not_met_routine_0202_locked` | 1 | **no** | - | 0 |
| `read_did_odd_length_truncated` | format | yes | `req_001__tpl_read_badlen_f190_01`, `req_002__tpl_read_badlen_f187_01` (+1 more) | 3 | **no** | - | 0 |
| `read_did_session_restriction_ignored` | data | yes | `req_009__tpl_read_did_wrong_0150_01`, `req_009__tpl_read_did_wrong_0150_02` | 2 | **no** | - | 0 |
| `uint16_did_stored_byte_swapped` | data | **no** | - | 0 | yes | `gold_write_coding_variant` | 1 |
| `s3_not_refreshed_by_tester_present` | timing | yes | `req_001__tpl_s3_keepalive_02`, `req_001__tpl_s3_keepalive_03` (+11 more) | 13 | **no** | - | 0 |
| `ecu_reset_clears_security_lockout` | security | yes | `req_005__tpl_security_lockout_01_reset`, `req_006__tpl_security_lockout_01_reset` (+4 more) | 6 | **no** | - | 0 |
| `s3_timeout_reverts_written_dids` | timing | yes | `req_005__tpl_write_retained_s3_0100`, `req_006__tpl_write_retained_s3_0101` (+3 more) | 5 | **no** | - | 0 |
| `session_suppress_bit_not_masked` | format | yes | `req_003__tpl_suppress_positive_10_01`, `req_003__tpl_suppress_positive_10_03` (+1 more) | 6 | **no** | - | 0 |
| `suppress_bit_echoed_in_response` | format | **no** | - | 0 | **no** | - | 0 |

Totals: generated 10/12 (83.3%), gold 3/12 (25.0%), union 11/12 (91.7%). Invalid tests (fail on the clean simulator): generated 0, gold 0.

### Missed held-out v1 bugs — generated suite (mode=mock)

- `uint16_did_stored_byte_swapped`: no generated test writes a uint16 DID and reads it back
- `suppress_bit_echoed_in_response`: no generated test sends RoutineControl with the suppress bit where a positive response is still expected (e.g. after 0x78)

### Missed held-out v1 bugs — gold suite

- `routine_state_survives_session_change`: no gold test starts a routine, changes session, then asks for that routine's results
- `nrc_order_condition_before_security`: no gold test starts a vehicle_stationary-gated routine while moving AND still locked
- `read_did_odd_length_truncated`: no gold test sends 0x22 with an odd number (>= 3) of DID bytes
- `read_did_session_restriction_ignored`: no gold test reads a DID outside its read_sessions
- `s3_not_refreshed_by_tester_present`: no gold test keeps a non-default session alive with TesterPresent across idle time
- `ecu_reset_clears_security_lockout`: no gold test resets the ECU after a security lockout and then requests a seed
- `s3_timeout_reverts_written_dids`: no gold test writes a DID, lets S3 expire, then reads the DID back
- `session_suppress_bit_not_masked`: no gold test sends DiagnosticSessionControl with the suppress bit set
- `suppress_bit_echoed_in_response`: no gold test sends RoutineControl with the suppress bit where a positive response is still expected (e.g. after 0x78)

_Reasons come from a static trigger analysis (`uds_assistant/eval/heldout.py`): for each held-out bug, a predicate written from its catalog description checks whether a test applies the stimulus the bug needs. Reporting only — nothing in templates, gold tests, mock LLM or planner was changed in response._

## Requirement understanding (natural requirements) — natural v1: test split SEEN, dev tuned on — mode=mock

Source: `data/requirements_natural.csv` (20 labelled rows). Each requirement was run through the agent pipeline (`mode=mock`, Bm25Retriever). **The test split is the v1 number, but it is SEEN; dev is what the prompts were tuned on.**

| Split | n | Targets exact (parsed) | Parsed P / R / F1 | Targets exact (exercised) | Exercised P / R / F1 | Category recall micro / macro | Precondition recall micro / macro | Fallback / nothing |
|---|---|---|---|---|---|---|---|---|
| **test** | 12 | 5/12 (41.7%) | 0.933 / 0.560 / 0.700 | 2/12 (16.7%) | 0.290 / 0.800 / 0.425 | 19/28 (67.9%) / 69.7% | 12/15 (80.0%) / 75.0% | 3 (2 excl. empty-label rows) |
| dev | 8 | 4/8 (50.0%) | 1.000 / 0.706 / 0.828 | 0/8 (0.0%) | 0.314 / 0.941 / 0.471 | 15/22 (68.2%) / 63.5% | 9/9 (100.0%) / 100.0% | 1 (1 excl. empty-label rows) |
| all | 20 | 9/20 (45.0%) | 0.963 / 0.619 / 0.754 | 2/20 (10.0%) | 0.300 / 0.857 / 0.444 | 34/50 (68.0%) / 67.1% | 21/24 (87.5%) / 83.3% | 4 (3 excl. empty-label rows) |

### Per requirement (natural v1, mode=mock)

| Req | Split | Tests | Label targets | Parsed exact | Parsed missed | Parsed extra | Exercised exact | Exercised missed | Exercised extra (n) | Categories missed | Preconditions missed | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NAT-001 | dev | 18 | did:0xF190, service:0x22 | yes | - | - | no | - | 9 | - | - | - |
| NAT-002 | test | 14 | did:0xF187, did:0xF18C, service:0x22 | no | did:0xF18C | - | no | did:0xF18C | 7 | - | - | - |
| NAT-003 | dev | 0 | service:0x10 | no | service:0x10 | - | no | service:0x10 | 0 | positive, session | - | no parsed services/DIDs/routines; zero tests |
| NAT-004 | test (ambiguous) | 9 | service:0x10 | yes | - | - | yes | - | 0 | session | vehicle_stationary | - |
| NAT-005 | dev | 18 | did:0x0100, service:0x10, service:0x27, service:0x2E | no | service:0x10 | - | no | - | 5 | - | - | - |
| NAT-006 | test (ambiguous) | 14 | did:0x0101, service:0x10, service:0x27, service:0x2E | no | service:0x10, service:0x27, service:0x2E | - | no | - | 6 | - | - | - |
| NAT-007 | dev | 7 | did:0x0130, service:0x2E | no | service:0x2E | - | no | - | 5 | security | - | - |
| NAT-008 | test | 0 | did:0x0131, service:0x2E | no | service:0x2E | - | no | did:0x0131, service:0x2E | 0 | negative, security | extended_session, security_level_1 | zero tests |
| NAT-009 | dev | 20 | did:0x0150, service:0x10, service:0x27, service:0x2E | no | service:0x10, service:0x27 | - | no | - | 10 | - | - | - |
| NAT-010 | test | 3 | service:0x27 | yes | - | - | no | - | 1 | security, timing | - | - |
| NAT-011 | dev | 12 | routine:0x0201, service:0x31 | yes | - | - | no | - | 4 | security | - | - |
| NAT-012 | test | 16 | routine:0x0202, service:0x31 | yes | - | - | no | - | 8 | - | - | - |
| NAT-013 | dev | 6 | service:0x11 | yes | - | - | no | - | 1 | positive | - | - |
| NAT-014 | test | 11 | service:0x19 | no | - | service:0x22 | no | - | 4 | - | - | - |
| NAT-015 | dev | 9 | service:0x3E | yes | - | - | no | - | 1 | session, timing | - | - |
| NAT-016 | test | 13 | did:0x0160, service:0x10, service:0x27, service:0x2E | no | service:0x10, service:0x27, service:0x2E | - | no | - | 6 | - | - | - |
| NAT-017 | test (ambiguous) | 0 | service:0x14, service:0x19 | no | service:0x14, service:0x19 | - | no | service:0x14, service:0x19 | 0 | negative, positive, session | - | no parsed services/DIDs/routines; zero tests |
| NAT-018 | test | 16 | did:0x0120, service:0x27, service:0x2E | no | service:0x27 | - | no | - | 7 | - | - | - |
| NAT-019 | test | 19 | routine:0x0203, service:0x31 | yes | - | - | no | - | 10 | positive | - | - |
| NAT-020 | test | 0 | (none) | yes | - | - | yes | - | 0 | - | - | no parsed services/DIDs/routines; zero tests |

## Secondary: in-sample bug detection (26 bugs — in-sample, templates tuned on these) — mode=mock

Scope: in-sample (templates tuned on these). Generated 25/26 (96.2%), gold 24/26 (92.3%), union 26/26 (100.0%). This is an optimistic, non-independent number: template set v2 was written after seeing which of these bugs v1 missed, by the same author as the catalog.

### Before / after template additions (in-sample, mock)

Baseline read from `eval_report_baseline_v1.json` (run 2026-10-02T21:21:46.279995+00:00).

|  | baseline (v1, 14 templates) | current (v3, 27 templates) |
|---|---|---|
| Generated tests | 101 | 206 |
| Generated-suite bug detection (in-sample) | 17 (65.4%) | 25 (96.2%) |
| Gold bug detection (in-sample) | 92.3% | 92.3% |
| Union bug detection (in-sample) | 96.2% | 100.0% |
| Request validity | 98.9% | 100.0% |
| Citation validity | 100.0% | 100.0% |
| Template reuse | 100.0% | 100.0% |
| Undetected (generated) | nrc_order_did_before_session, security_not_reset_on_session_change, s3_timeout_off_by_one, seed_not_consumed, readonly_did_writable, negative_response_suppressed, dtc_clear_ignores_group, multi_did_read_first_only, missing_response_pending | missing_response_pending |

### Bug detection per injected bug (in-sample) — mode=mock

| Bug | Category | Generated | Generated detecting tests | Gold | Gold detecting tests |
|---|---|---|---|---|---|
| `nrc_order_did_before_session` | nrc_order | yes | 8: `req_001__tpl_nrc_priority_2e_01`, `req_002__tpl_nrc_priority_2e_01`, `req_005__tpl_nrc_priority_2e_01` (+5 more) | yes | 1: `gold_write_unknown_did_default_session` |
| `nrc_order_security_before_length` | nrc_order | yes | 5: `req_005__tpl_write_badlen_0100`, `req_006__tpl_write_badlen_0101`, `req_007__tpl_write_badlen_0130` (+2 more) | yes | 1: `gold_write_wrong_length` |
| `general_reject_instead_of_0x12` | format | yes | 32: `req_003__tpl_unsupported_subfunction_10_01`, `req_003__tpl_unsupported_subfunction_10_03`, `req_003__tpl_negative_suppress_10_01` (+29 more) | yes | 4: `gold_session_unsupported_sub`, `gold_ecu_reset_bad_sub`, `gold_dtc_read_bad_sub` (+1 more) |
| `security_not_reset_on_session_change` | session | yes | 8: `req_005__tpl_session_relock_01`, `req_006__tpl_session_relock_01`, `req_007__tpl_session_relock_01` (+5 more) | yes | 1: `gold_security_relocked_on_session_reentry` |
| `s3_timeout_never_fires` | timing | yes | 13: `req_001__tpl_s3_timeout_02`, `req_001__tpl_s3_timeout_03`, `req_002__tpl_s3_timeout_02` (+10 more) | yes | 1: `gold_s3_timeout_reverts` |
| `s3_timeout_off_by_one` | timing | yes | 13: `req_001__tpl_s3_keepalive_02`, `req_001__tpl_s3_keepalive_03`, `req_002__tpl_s3_keepalive_02` (+10 more) | yes | 1: `gold_s3_no_timeout_at_exactly_s3ms` |
| `lockout_after_extra_attempt` | security | yes | 12: `req_005__tpl_security_lockout_01`, `req_005__tpl_security_lockout_01_reset`, `req_006__tpl_security_lockout_01` (+9 more) | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_ignored` | security | yes | 12: `req_005__tpl_security_lockout_01`, `req_005__tpl_security_lockout_01_reset`, `req_006__tpl_security_lockout_01` (+9 more) | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_never_expires` | timing | yes | 12: `req_005__tpl_security_lockout_01`, `req_005__tpl_security_lockout_01_reset`, `req_006__tpl_security_lockout_01` (+9 more) | **no** | 0: - |
| `accepts_any_key` | security | yes | 12: `req_005__tpl_security_lockout_01`, `req_005__tpl_security_lockout_01_reset`, `req_006__tpl_security_lockout_01` (+9 more) | yes | 3: `gold_security_wrong_key_once`, `gold_security_lockout_after_3`, `gold_security_wrong_level_unlock` |
| `seed_not_consumed` | sequence | yes | 6: `req_005__tpl_seed_replay_01`, `req_006__tpl_seed_replay_01`, `req_007__tpl_seed_replay_01` (+3 more) | **no** | 0: - |
| `static_seed` | security | yes | 22: `req_005__tpl_security_lockout_01`, `req_005__tpl_security_lockout_01_reset`, `req_005__tpl_session_relock_01` (+19 more) | yes | 1: `gold_security_lockout_after_3` |
| `write_ignores_value_range` | data | yes | 5: `req_005__tpl_write_oor_0100`, `req_006__tpl_write_oor_0101`, `req_007__tpl_write_oor_0130` (+2 more) | yes | 2: `gold_write_out_of_range_wiper`, `gold_write_out_of_range_brightness` |
| `readonly_did_writable` | data | yes | 3: `req_001__tpl_write_readonly_f190`, `req_002__tpl_write_readonly_f187`, `req_002__tpl_write_readonly_f18c` | yes | 1: `gold_write_readonly_did` |
| `write_length_off_by_one` | format | yes | 5: `req_005__tpl_write_badlen_0100`, `req_006__tpl_write_badlen_0101`, `req_007__tpl_write_badlen_0130` (+2 more) | yes | 1: `gold_write_wrong_length` |
| `write_positive_sid_wrong` | format | yes | 20: `req_005__tpl_write_secured_0100`, `req_005__tpl_write_retained_s3_0100`, `req_005__tpl_write_retained_reset_0100` (+17 more) | yes | 5: `gold_write_secured_positive_lighting`, `gold_write_secured_positive_ambient_color`, `gold_write_coding_variant` (+2 more) |
| `session_response_missing_timing` | format | yes | 143: `req_001__tpl_read_did_positive_f190_02`, `req_001__tpl_read_did_positive_f190_03`, `req_001__tpl_write_readonly_f190` (+140 more) | yes | 35: `gold_read_vin_extended`, `gold_session_to_extended`, `gold_session_back_default` (+32 more) |
| `suppress_bit_ignored` | format | yes | 8: `req_003__tpl_suppress_positive_10_01`, `req_003__tpl_suppress_positive_10_03`, `req_004__tpl_suppress_positive_10_02` (+5 more) | yes | 2: `gold_tester_present_suppressed`, `gold_ecu_reset_suppressed` |
| `negative_response_suppressed` | format | yes | 13: `req_003__tpl_negative_suppress_10_01`, `req_003__tpl_negative_suppress_10_03`, `req_004__tpl_negative_suppress_10_02` (+10 more) | yes | 1: `gold_tester_present_bad_sub_not_suppressed` |
| `routine_stop_without_start` | sequence | yes | 2: `req_011__tpl_routine_sequence_0201`, `req_012__tpl_routine_sequence_0202` | yes | 1: `gold_routine_stop_before_start` |
| `condition_ignored` | data | yes | 2: `req_009__tpl_condition_not_met_did_0150`, `req_012__tpl_condition_not_met_routine_0202` | yes | 2: `gold_routine_door_cal_condition_fail`, `gold_write_factory_reset_flag_moving` |
| `dtc_clear_ignores_group` | data | yes | 3: `req_014__tpl_dtc_clear_specific_B10101`, `req_014__tpl_dtc_clear_specific_B10205`, `req_014__tpl_dtc_clear_specific_B10310` | yes | 2: `gold_dtc_clear_specific`, `gold_dtc_clear_unknown_group` |
| `dtc_clear_noop` | data | yes | 6: `req_014__tpl_dtc_read_clear_B10101`, `req_014__tpl_dtc_read_clear_B10205`, `req_014__tpl_dtc_read_clear_B10310` (+3 more) | yes | 2: `gold_dtc_clear_all`, `gold_dtc_clear_specific` |
| `multi_did_read_first_only` | data | yes | 9: `req_001__tpl_read_multi_f190_f187_01`, `req_001__tpl_read_multi_f187_f190_01`, `req_001__tpl_read_multi_f18c_f190_01` (+6 more) | yes | 2: `gold_read_partnum_serial_multi`, `gold_duplicate_did_read` |
| `missing_response_pending` | timing | **no** | 0: - | yes | 1: `gold_routine_nvm_restore_long_running` |
| `dtc_read_ignores_mask` | data | yes | 6: `req_014__tpl_dtc_read_clear_B10101`, `req_014__tpl_dtc_read_clear_B10205`, `req_014__tpl_dtc_read_clear_B10310` (+3 more) | yes | 4: `gold_dtc_read_default`, `gold_dtc_set_and_read`, `gold_dtc_clear_all` (+1 more) |

Invalid tests (fail on the clean simulator, excluded from credit): generated 0, gold 0.
Detected only by the generated suite: lockout_delay_never_expires, seed_not_consumed. Only by gold: missing_response_pending. Undetected by both: -.

## Coverage (generated tests per category per seed requirement) — mode=mock

| Requirement | positive | negative | session | security | timing | total |
|---|---|---|---|---|---|---|
| REQ-001 | 9 | 4 | 1 | 0 | 4 | 18 |
| REQ-002 | 9 | 6 | 1 | 0 | 4 | 20 |
| REQ-003 | 2 | 4 | 0 | 0 | 2 | 8 |
| REQ-004 | 1 | 2 | 0 | 0 | 2 | 5 |
| REQ-005 | 2 | 6 | 2 | 5 | 3 | 18 |
| REQ-006 | 2 | 6 | 2 | 5 | 3 | 18 |
| REQ-007 | 2 | 4 | 2 | 5 | 3 | 16 |
| REQ-008 | 2 | 4 | 2 | 5 | 3 | 16 |
| REQ-009 | 1 | 10 | 3 | 5 | 3 | 22 |
| REQ-010 | 0 | 2 | 1 | 5 | 0 | 8 |
| REQ-011 | 2 | 6 | 4 | 0 | 0 | 12 |
| REQ-012 | 2 | 9 | 5 | 0 | 0 | 16 |
| REQ-013 | 0 | 6 | 0 | 0 | 0 | 6 |
| REQ-014 | 6 | 2 | 2 | 0 | 0 | 10 |
| REQ-015 | 3 | 6 | 0 | 0 | 4 | 13 |
| **total** | 43 | 77 | 25 | 30 | 31 | 206 |

Categories present: 100.0%; requirements covered by ≥2 categories: 14/15.

## Request validity — mode=mock

- Send steps: 691; decodable: 691; not rejected with a format NRC (0x11/0x12/0x13): 645 (unadjusted rate 93.3%).
- Intentional format probes (NRC in the template's `intended_nrcs`): 46. Adjusted validity: **691/691 (100.0%)**.

## Template reuse and citations — mode=mock

- Template reuse: 206/206 (100.0%); templates used: 27/27; per template: `condition_not_met` 4, `dtc_clear_specific_keeps_others` 3, `dtc_read_clear` 3, `negative_response_with_suppress_bit` 13, `nrc_priority_session_over_identifier` 11, `read_did_invalid_length` 3, `read_did_positive` 9, `read_did_wrong_session_or_unknown` 4, `read_multiple_dids` 9, `routine_sequence` 2, `routine_start_results` 4, `s3_keepalive_boundary` 13, `s3_timeout_reverts_session` 13, `security_invalid_key_lockout` 12, `seed_replay_rejected` 6, `seed_request_while_unlocked` 6, `service_not_in_session` 21, `session_change_relocks_security` 6, `session_change_resets_routine` 4, `suppress_positive_response` 6, `unsupported_subfunction` 23, `write_did_invalid_length` 5, `write_did_out_of_range` 5, `write_did_secured_positive` 4, `write_did_value_retained` 10, `write_did_without_security` 4, `write_readonly_did` 3
- Citations: 967/967 valid; tests with ≥1 valid citation: 100.0%.

## Pipeline statistics (seed requirements) — mode=mock

| Requirement | tests | dropped | rejected | plan attempts | status | wall s |
|---|---|---|---|---|---|---|
| REQ-001 | 18 | 0 | 0 | 1 | completed | 0.545 |
| REQ-002 | 20 | 0 | 0 | 1 | completed | 0.553 |
| REQ-003 | 8 | 0 | 0 | 1 | completed | 0.271 |
| REQ-004 | 5 | 0 | 0 | 1 | completed | 0.193 |
| REQ-005 | 18 | 0 | 0 | 1 | completed | 0.518 |
| REQ-006 | 18 | 0 | 0 | 1 | completed | 0.524 |
| REQ-007 | 16 | 0 | 0 | 1 | completed | 0.537 |
| REQ-008 | 16 | 0 | 0 | 1 | completed | 0.491 |
| REQ-009 | 22 | 0 | 0 | 1 | completed | 0.684 |
| REQ-010 | 8 | 0 | 0 | 1 | completed | 0.298 |
| REQ-011 | 12 | 0 | 0 | 1 | completed | 0.388 |
| REQ-012 | 16 | 0 | 0 | 1 | completed | 0.496 |
| REQ-013 | 6 | 0 | 0 | 1 | completed | 0.233 |
| REQ-014 | 10 | 0 | 0 | 1 | completed | 0.331 |
| REQ-015 | 13 | 0 | 0 | 1 | completed | 0.352 |

Totals: 206 kept, 0 dropped, 0 rejected, 0 re-plans, 0 failed runs.

## Appendix: Self-consistency check (circular by construction) — mode=mock

Expected bytes in generated tests are produced by the rules-engine oracle, so agreement with a fresh oracle re-run is a consistency check, not an independent accuracy measure. Kept here for completeness; it is not a headline metric.

- Expected-response accuracy vs oracle: 691/691 (100.0%) steps; 206/206 (100.0%) tests.
- Independent simulator (clean): 100.0% of generated tests pass.
- Gold, exact overlap: 25/25 (100.0%) generated/gold pairs with identical step sequences agree.
- Gold, shared prefix: 21/21 (100.0%) distinct send steps reached by an identical prefix in both suites agree.

# Details — mode=ollama

Generated tests (seed requirements): **73** (64 unique template instantiations); 73/73 (100.0%) pass on the clean simulator; P2/P2* wall-clock warnings: 0.

## Held-out v3 bug detection (15 FRESH bugs) — FRESH HEADLINE — mode=ollama

Scope: held-out v3 (FRESH): 15 bugs written blind by a subagent after the Part D freeze, which could not see templates, the conformance sweep, prompts, eval code or any report; nothing was changed after seeing these results. Catalog: `data/bugs/heldout_v3_catalog.yaml`.

15 bugs written blind after the Part D freeze by a subagent that could not see templates, the conformance sweep, prompts, eval code or any report; nothing was changed after seeing these results.

| Bug | Category | (a) req-driven | tests | (b) sweep | tests | (c) full output | gold | all generated (suppl.) | natural v3 (suppl.) | tests applying the trigger, per suite | reason if missed by the headline suite |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `session_switch_keeps_pending_seed` | session | **no** | 0 | **no** | 0 | **no** | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=0, full_output=0, all_generated=0, natural_v3_generated=0 | no full_output test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24) |
| `session_response_p2_star_in_ms` | timing | yes | 50 | yes | 1037 | yes | yes | yes | yes | requirement_driven=50, gold=35, conformance=1037, full_output=1087, all_generated=256, natural_v3_generated=75 | - |
| `failed_key_keeps_pending_seed` | security | **no** | 0 | yes | 6 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=6, full_output=6, all_generated=0, natural_v3_generated=0 | - |
| `lockout_expiry_resets_attempt_count` | security | **no** | 0 | **no** | 0 | **no** | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=0, full_output=0, all_generated=0, natural_v3_generated=0 | no full_output test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36) |
| `nrc_order_subfunction_before_length` | nrc_order | **no** | 0 | **no** | 0 | **no** | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=0, full_output=0, all_generated=0, natural_v3_generated=0 | no full_output test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13) |
| `nrc_order_write_range_before_condition` | nrc_order | **no** | 0 | yes | 1 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=1, full_output=1, all_generated=0, natural_v3_generated=0 | - |
| `routine_results_trailing_bytes_accepted` | format | **no** | 0 | yes | 3 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=3, full_output=3, all_generated=0, natural_v3_generated=0 | - |
| `read_did_speed_not_clamped` | data | **no** | 0 | **no** | 0 | **no** | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=0, full_output=0, all_generated=0, natural_v3_generated=0 | no full_output test reads DID 0x0140 while the vehicle speed is above 255 kph |
| `write_stores_value_before_range_rejection` | data | **no** | 0 | yes | 1 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=1, full_output=1, all_generated=0, natural_v3_generated=0 | - |
| `routine_stop_reports_completed_status` | data | yes | 1 | yes | 20 | yes | yes | yes | **no** | requirement_driven=1, gold=1, conformance=20, full_output=21, all_generated=2, natural_v3_generated=0 | - |
| `dtc_clear_single_clears_neighbour` | data | **no** | 0 | **no** | 0 | **no** | yes | yes | **no** | requirement_driven=0, gold=1, conformance=0, full_output=0, all_generated=4, natural_v3_generated=0 | no full_output test clears one DTC while the next DTC in spec order is stored, then reads the DTCs back with a mask that shows it |
| `dtc_read_reports_masked_status` | data | **no** | 0 | **no** | 0 | **no** | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=0, full_output=0, all_generated=0, natural_v3_generated=0 | no full_output test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask |
| `ecu_reset_resets_seed_counter` | security | **no** | 0 | yes | 15 | yes | **no** | yes | yes | requirement_driven=0, gold=0, conformance=15, full_output=15, all_generated=6, natural_v3_generated=1 | - |
| `s3_timeout_clears_dtc_status` | timing | **no** | 0 | yes | 6 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=6, full_output=6, all_generated=0, natural_v3_generated=0 | - |
| `suppressed_request_does_not_restart_s3` | timing | **no** | 0 | yes | 33 | yes | **no** | **no** | **no** | requirement_driven=0, gold=0, conformance=37, full_output=37, all_generated=0, natural_v3_generated=0 | - |

Totals: (a) requirement-driven 2/15 (13.3%), (b) sweep alone 9/15 (60.0%), (c) full output 9/15 (60.0%), gold 3/15 (20.0%). Invalid tests (fail on the clean simulator): requirement-driven 0, gold 0.

### Trigger coverage: how many bugs' stimuli each suite applies (coverage report only)

| Suite | bugs whose stimulus is applied | total stimulus applications |
|---|---|---|
| requirement_driven | 2/15 | 51 |
| gold | 3/15 | 37 |
| conformance | 9/15 | 1126 |
| full_output | 9/15 | 1177 |
| all_generated | 4/15 | 268 |
| natural_v3_generated | 2/15 | 76 |

### Missed v3 bugs — full_output (the headline suite, mode=ollama)

- `session_switch_keeps_pending_seed`: no full_output test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no full_output test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no full_output test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `read_did_speed_not_clamped`: no full_output test reads DID 0x0140 while the vehicle speed is above 255 kph
- `dtc_clear_single_clears_neighbour`: no full_output test clears one DTC while the next DTC in spec order is stored, then reads the DTCs back with a mask that shows it
- `dtc_read_reports_masked_status`: no full_output test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask

### Missed v3 bugs — requirement-driven suite

- `session_switch_keeps_pending_seed`: no requirement_driven test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `failed_key_keeps_pending_seed`: no requirement_driven test sends a wrong key and then a second key for the same seed (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no requirement_driven test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no requirement_driven test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `nrc_order_write_range_before_condition`: no requirement_driven test writes an out-of-range value to a conditioned DID while the condition fails (expected 0x22)
- `routine_results_trailing_bytes_accepted`: no requirement_driven test sends a requestResults (31 03 RID) with trailing bytes (expected 0x13)
- `read_did_speed_not_clamped`: no requirement_driven test reads DID 0x0140 while the vehicle speed is above 255 kph
- `write_stores_value_before_range_rejection`: no requirement_driven test has an out-of-range write refused (0x31) and later reads the same DID back
- `dtc_clear_single_clears_neighbour`: no requirement_driven test clears one DTC while the next DTC in spec order is stored, then reads the DTCs back with a mask that shows it
- `dtc_read_reports_masked_status`: no requirement_driven test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask
- `ecu_reset_resets_seed_counter`: no requirement_driven test issues a seed, resets the ECU, and then observes a newly issued seed
- `s3_timeout_clears_dtc_status`: no requirement_driven test stores a DTC status, lets an S3 timeout drop a session, then reads the DTCs
- `suppressed_request_does_not_restart_s3`: no requirement_driven test sends a suppressed request in a non-default session and then waits so that S3 is exceeded only when counted from the last answered request

### Missed v3 bugs — conformance suite

- `session_switch_keeps_pending_seed`: no conformance test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no conformance test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no conformance test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `read_did_speed_not_clamped`: no conformance test reads DID 0x0140 while the vehicle speed is above 255 kph
- `dtc_clear_single_clears_neighbour`: no conformance test clears one DTC while the next DTC in spec order is stored, then reads the DTCs back with a mask that shows it
- `dtc_read_reports_masked_status`: no conformance test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask

### Missed v3 bugs — gold suite

- `session_switch_keeps_pending_seed`: no gold test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `failed_key_keeps_pending_seed`: no gold test sends a wrong key and then a second key for the same seed (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no gold test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no gold test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `nrc_order_write_range_before_condition`: no gold test writes an out-of-range value to a conditioned DID while the condition fails (expected 0x22)
- `routine_results_trailing_bytes_accepted`: no gold test sends a requestResults (31 03 RID) with trailing bytes (expected 0x13)
- `read_did_speed_not_clamped`: no gold test reads DID 0x0140 while the vehicle speed is above 255 kph
- `write_stores_value_before_range_rejection`: no gold test has an out-of-range write refused (0x31) and later reads the same DID back
- `dtc_read_reports_masked_status`: no gold test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask
- `ecu_reset_resets_seed_counter`: no gold test issues a seed, resets the ECU, and then observes a newly issued seed
- `s3_timeout_clears_dtc_status`: no gold test stores a DTC status, lets an S3 timeout drop a session, then reads the DTCs
- `suppressed_request_does_not_restart_s3`: no gold test sends a suppressed request in a non-default session and then waits so that S3 is exceeded only when counted from the last answered request

### Missed v3 bugs — all generated tests (supplementary)

- `session_switch_keeps_pending_seed`: no all_generated test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `failed_key_keeps_pending_seed`: no all_generated test sends a wrong key and then a second key for the same seed (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no all_generated test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no all_generated test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `nrc_order_write_range_before_condition`: no all_generated test writes an out-of-range value to a conditioned DID while the condition fails (expected 0x22)
- `routine_results_trailing_bytes_accepted`: no all_generated test sends a requestResults (31 03 RID) with trailing bytes (expected 0x13)
- `read_did_speed_not_clamped`: no all_generated test reads DID 0x0140 while the vehicle speed is above 255 kph
- `write_stores_value_before_range_rejection`: no all_generated test has an out-of-range write refused (0x31) and later reads the same DID back
- `dtc_read_reports_masked_status`: no all_generated test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask
- `s3_timeout_clears_dtc_status`: no all_generated test stores a DTC status, lets an S3 timeout drop a session, then reads the DTCs
- `suppressed_request_does_not_restart_s3`: no all_generated test sends a suppressed request in a non-default session and then waits so that S3 is exceeded only when counted from the last answered request

### Missed v3 bugs — natural-v3 tests alone (supplementary)

- `session_switch_keeps_pending_seed`: no natural_v3_generated test requests a seed, switches session with a positive 10 xx, then sends a key for that level (expected 0x24)
- `failed_key_keeps_pending_seed`: no natural_v3_generated test sends a wrong key and then a second key for the same seed (expected 0x24)
- `lockout_expiry_resets_attempt_count`: no natural_v3_generated test reaches a lockout, waits for the delay to run out, requests a seed and sends another wrong key (expected 0x36)
- `nrc_order_subfunction_before_length`: no natural_v3_generated test sends 10 / 11 / 3E with an unsupported subfunction and a wrong total length (expected 0x13)
- `nrc_order_write_range_before_condition`: no natural_v3_generated test writes an out-of-range value to a conditioned DID while the condition fails (expected 0x22)
- `routine_results_trailing_bytes_accepted`: no natural_v3_generated test sends a requestResults (31 03 RID) with trailing bytes (expected 0x13)
- `read_did_speed_not_clamped`: no natural_v3_generated test reads DID 0x0140 while the vehicle speed is above 255 kph
- `write_stores_value_before_range_rejection`: no natural_v3_generated test has an out-of-range write refused (0x31) and later reads the same DID back
- `routine_stop_reports_completed_status`: no natural_v3_generated test checks the response of a positive stopRoutine (31 02 RID)
- `dtc_clear_single_clears_neighbour`: no natural_v3_generated test clears one DTC while the next DTC in spec order is stored, then reads the DTCs back with a mask that shows it
- `dtc_read_reports_masked_status`: no natural_v3_generated test reads DTCs (19 02 mm) where a listed DTC has status bits outside the request mask
- `s3_timeout_clears_dtc_status`: no natural_v3_generated test stores a DTC status, lets an S3 timeout drop a session, then reads the DTCs
- `suppressed_request_does_not_restart_s3`: no natural_v3_generated test sends a suppressed request in a non-default session and then waits so that S3 is exceeded only when counted from the last answered request

_Reasons come from `uds_assistant/eval/heldout_v3.py`: one predicate per bug, written only from the bug descriptions in `data/bugs/heldout_v3_catalog.yaml` and `docs/behaviour_contract.md` before any v3 result existed. "no X test ..." means no test in that suite applies the stimulus; "N X test(s) ..., but none of their expected responses differs" means the stimulus is present but the oracle-derived expectations do not distinguish the bug. Reporting only — nothing was changed in response._

## Requirement understanding, natural v3 (split test3, FRESH HEADLINE) — mode=ollama

Source: `data/requirements_natural_v3.csv` (16 labelled rows). Each requirement was run through the agent pipeline (`mode=ollama`, Bm25Retriever). **The test3 split is the main number (fresh, nothing tuned on it).**

| Split | n | Targets exact (parsed) | Parsed P / R / F1 | Targets exact (exercised) | Exercised P / R / F1 | Category recall micro / macro | Precondition recall micro / macro | Fallback / nothing |
|---|---|---|---|---|---|---|---|---|
| **test3** | 16 | 2/16 (12.5%) | 0.596 / 0.622 / 0.609 | 0/16 (0.0%) | 0.343 / 0.756 / 0.472 | 35/50 (70.0%) / 72.2% | 26/29 (89.7%) / 91.0% | 0 (0 excl. empty-label rows) |
| all | 16 | 2/16 (12.5%) | 0.596 / 0.622 / 0.609 | 0/16 (0.0%) | 0.343 / 0.756 / 0.472 | 35/50 (70.0%) / 72.2% | 26/29 (89.7%) / 91.0% | 0 (0 excl. empty-label rows) |

### Per requirement (natural v3, mode=ollama)

| Req | Split | Tests | Label targets | Parsed exact | Parsed missed | Parsed extra | Exercised exact | Exercised missed | Exercised extra (n) | Categories missed | Preconditions missed | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NAT3-001 | test3 | 4 | did:0xF187, did:0xF18C, did:0xF190, service:0x22 | no | did:0xF187, did:0xF190 | - | no | did:0xF187 | 1 | session | - | - |
| NAT3-002 | test3 | 4 | service:0x27 | no | - | service:0x10, service:0x2E | no | - | 5 | - | - | - |
| NAT3-003 | test3 | 5 | did:0x0120, service:0x10, service:0x27, service:0x2E | no | - | did:0x0110, did:0x0111, did:0x0131 | no | - | 3 | session | - | - |
| NAT3-004 | test3 | 8 | did:0x0130, service:0x2E | no | - | service:0x10, service:0x27 | no | - | 5 | - | - | - |
| NAT3-005 | test3 | 7 | routine:0x0201, service:0x31 | no | routine:0x0201 | service:0x10, service:0x27 | no | - | 6 | positive | - | - |
| NAT3-006 | test3 | 4 | routine:0x0202, service:0x31 | no | routine:0x0202, service:0x31 | service:0x10, service:0x27 | no | routine:0x0202, service:0x31 | 6 | positive, session | security_level_1, vehicle_stationary | - |
| NAT3-007 | test3 | 8 | routine:0x0203, service:0x31 | no | routine:0x0203 | did:0x0150, service:0x10, service:0x27 | no | routine:0x0203 | 9 | session | - | - |
| NAT3-008 | test3 | 8 | did:0x0150, service:0x2E | no | - | service:0x11, service:0x27 | no | - | 5 | session | - | - |
| NAT3-009 | test3 | 8 | did:0x0160, service:0x10, service:0x11, service:0x22, service:0x27, service:0x2E | yes | - | - | no | service:0x11 | 2 | session | - | - |
| NAT3-010 | test3 | 8 | service:0x14, service:0x19 | no | service:0x14 | service:0x2E | no | - | 7 | - | - | - |
| NAT3-011 | test3 | 4 | did:0xF186, service:0x10, service:0x22, service:0x3E | no | did:0xF186, service:0x22, service:0x3E | - | no | service:0x3E | 0 | session | - | - |
| NAT3-012 | test3 | 4 | did:0x0100, service:0x10, service:0x27, service:0x2E, service:0x3E | no | service:0x3E | - | no | service:0x3E | 2 | security, session | - | - |
| NAT3-013 | test3 | 4 | service:0x3E | yes | - | - | no | - | 3 | - | - | - |
| NAT3-014 | test3 (ambiguous) | 4 | did:0xF186, service:0x10, service:0x11, service:0x22, service:0x27 | no | did:0xF186, service:0x10, service:0x22, service:0x27 | - | no | did:0xF186, service:0x22, service:0x27 | 0 | positive, security, session | security_level_1 | - |
| NAT3-015 | test3 (ambiguous) | 6 | did:0x0130, did:0x0131, service:0x2E | no | did:0x0131, service:0x2E | service:0x22 | no | did:0x0131 | 5 | security | - | - |
| NAT3-016 | test3 | 8 | (none) | no | - | service:0x22 | no | - | 6 | - | - | - |

## Held-out v2 bug detection (15 bugs, SEEN) — mode=ollama

Scope: held-out v2, now SEEN: 15 bugs written blind by a subagent after the Part C freeze (fresh in Part C); their Part C results were known before Part D, so they are no longer independent evidence. Catalog: `data/bugs/heldout_v2_catalog.yaml`.

Generated suite = the tests from the 15 seed requirements (the Part C headline definition). The two supplementary columns use all generated tests (seed + natural v1 + natural v2) and the natural-v2 tests alone.

| Bug | Category | Generated (seed reqs) | Generated detecting tests | Gen. tests applying trigger | Gold | Gold tests applying trigger | All generated (suppl.) | trigger | Natural-v2 tests (suppl.) | trigger |
|---|---|---|---|---|---|---|---|---|---|---|
| `session_reentry_keeps_unlock` | session | yes | `req_006__tpl_session_relock_01`, `req_010__tpl_session_relock_03` (+1 more) | 3 | yes | 1 | yes | 16 | yes | 4 |
| `s3_restart_skipped_on_negative_response` | timing | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `s3_timeout_resets_lockout_counters` | session | **no** | - | 4 | **no** | 0 | **no** | 14 | **no** | 6 |
| `ecu_reset_keeps_session` | session | **no** | - | 1 | yes | 1 | **no** | 7 | **no** | 5 |
| `seed_request_keeps_stale_pending_seed` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `key_compare_prefix_only` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `lockout_counter_pooled_across_levels` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `nrc_order_range_before_security` | nrc_order | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `nrc_order_nvm_fault_before_group_check` | nrc_order | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `read_dtc_trailing_bytes_accepted` | format | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `routine_option_record_overlong_accepted` | format | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `write_range_upper_bound_exclusive` | data | yes | `req_007__tpl_write_retained_s3_0130`, `req_009__tpl_write_retained_s3_0150` | 2 | yes | 2 | yes | 5 | yes | 1 |
| `multi_did_read_dedups_repeats` | data | **no** | - | 0 | yes | 1 | **no** | 0 | **no** | 0 |
| `routine_restart_after_stop_blocked` | sequence | **no** | - | 0 | yes | 1 | **no** | 0 | **no** | 0 |
| `suppressed_seed_request_not_stored` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |

Totals: generated 2/15 (13.3%), gold 5/15 (33.3%), union 5/15 (33.3%). Invalid tests (fail on the clean simulator): generated 0, gold 0.
- Supplementary — All generated tests (seed + natural v1 + natural v2): 274 tests, 2/15 (13.3%) detected (0 invalid tests).
- Supplementary — Tests generated from natural v2 alone: 87 tests, 2/15 (13.3%) detected (0 invalid tests).

### Missed held-out v2 bugs — generated suite (mode=ollama)

- `s3_restart_skipped_on_negative_response`: no generated test answers a request with an NRC in a non-default session and then wait so that S3 is exceeded only when counted from the last positive request
- `s3_timeout_resets_lockout_counters`: 4 generated test(s) reaches a security lockout, lets S3 expire and then requests a seed, but none of their expected responses differs under the bug
- `ecu_reset_keeps_session`: 1 generated test(s) sends a positive ECUReset from a non-default session and then another request, but none of their expected responses differs under the bug
- `seed_request_keeps_stale_pending_seed`: no generated test requests a seed twice for one level before sending a key for it
- `key_compare_prefix_only`: no generated test sends a key with the right first two bytes and a wrong tail
- `lockout_counter_pooled_across_levels`: no generated test sends wrong keys at two different levels that together reach the attempt limit
- `nrc_order_range_before_security`: no generated test writes an out-of-range value of correct length to a DID in its write session while security is locked
- `nrc_order_nvm_fault_before_group_check`: no generated test clears an unknown DTC group (0x14) while the NVM write fault is set
- `read_dtc_trailing_bytes_accepted`: no generated test sends 19 02 with more than one byte after the sub-function
- `routine_option_record_overlong_accepted`: no generated test starts a routine (in its session) with an over-long option record
- `multi_did_read_dedups_repeats`: no generated test reads one DID several times in a single 0x22 request
- `routine_restart_after_stop_blocked`: no generated test starts a routine again after stopping it
- `suppressed_seed_request_not_stored`: no generated test sends a suppressed seed request (27 81 / 27 83) and then a key for that level

### Missed held-out v2 bugs — gold suite

- `s3_restart_skipped_on_negative_response`: no gold test answers a request with an NRC in a non-default session and then wait so that S3 is exceeded only when counted from the last positive request
- `s3_timeout_resets_lockout_counters`: no gold test reaches a security lockout, lets S3 expire and then requests a seed
- `seed_request_keeps_stale_pending_seed`: no gold test requests a seed twice for one level before sending a key for it
- `key_compare_prefix_only`: no gold test sends a key with the right first two bytes and a wrong tail
- `lockout_counter_pooled_across_levels`: no gold test sends wrong keys at two different levels that together reach the attempt limit
- `nrc_order_range_before_security`: no gold test writes an out-of-range value of correct length to a DID in its write session while security is locked
- `nrc_order_nvm_fault_before_group_check`: no gold test clears an unknown DTC group (0x14) while the NVM write fault is set
- `read_dtc_trailing_bytes_accepted`: no gold test sends 19 02 with more than one byte after the sub-function
- `routine_option_record_overlong_accepted`: no gold test starts a routine (in its session) with an over-long option record
- `suppressed_seed_request_not_stored`: no gold test sends a suppressed seed request (27 81 / 27 83) and then a key for that level

### Missed held-out v2 bugs — all generated tests (supplementary)

- `s3_restart_skipped_on_negative_response`: no all_generated test answers a request with an NRC in a non-default session and then wait so that S3 is exceeded only when counted from the last positive request
- `s3_timeout_resets_lockout_counters`: 14 all_generated test(s) reaches a security lockout, lets S3 expire and then requests a seed, but none of their expected responses differs under the bug
- `ecu_reset_keeps_session`: 7 all_generated test(s) sends a positive ECUReset from a non-default session and then another request, but none of their expected responses differs under the bug
- `seed_request_keeps_stale_pending_seed`: no all_generated test requests a seed twice for one level before sending a key for it
- `key_compare_prefix_only`: no all_generated test sends a key with the right first two bytes and a wrong tail
- `lockout_counter_pooled_across_levels`: no all_generated test sends wrong keys at two different levels that together reach the attempt limit
- `nrc_order_range_before_security`: no all_generated test writes an out-of-range value of correct length to a DID in its write session while security is locked
- `nrc_order_nvm_fault_before_group_check`: no all_generated test clears an unknown DTC group (0x14) while the NVM write fault is set
- `read_dtc_trailing_bytes_accepted`: no all_generated test sends 19 02 with more than one byte after the sub-function
- `routine_option_record_overlong_accepted`: no all_generated test starts a routine (in its session) with an over-long option record
- `multi_did_read_dedups_repeats`: no all_generated test reads one DID several times in a single 0x22 request
- `routine_restart_after_stop_blocked`: no all_generated test starts a routine again after stopping it
- `suppressed_seed_request_not_stored`: no all_generated test sends a suppressed seed request (27 81 / 27 83) and then a key for that level

### Missed held-out v2 bugs — natural-v2 tests alone (supplementary)

- `s3_restart_skipped_on_negative_response`: no natural_v2_generated test answers a request with an NRC in a non-default session and then wait so that S3 is exceeded only when counted from the last positive request
- `s3_timeout_resets_lockout_counters`: 6 natural_v2_generated test(s) reaches a security lockout, lets S3 expire and then requests a seed, but none of their expected responses differs under the bug
- `ecu_reset_keeps_session`: 5 natural_v2_generated test(s) sends a positive ECUReset from a non-default session and then another request, but none of their expected responses differs under the bug
- `seed_request_keeps_stale_pending_seed`: no natural_v2_generated test requests a seed twice for one level before sending a key for it
- `key_compare_prefix_only`: no natural_v2_generated test sends a key with the right first two bytes and a wrong tail
- `lockout_counter_pooled_across_levels`: no natural_v2_generated test sends wrong keys at two different levels that together reach the attempt limit
- `nrc_order_range_before_security`: no natural_v2_generated test writes an out-of-range value of correct length to a DID in its write session while security is locked
- `nrc_order_nvm_fault_before_group_check`: no natural_v2_generated test clears an unknown DTC group (0x14) while the NVM write fault is set
- `read_dtc_trailing_bytes_accepted`: no natural_v2_generated test sends 19 02 with more than one byte after the sub-function
- `routine_option_record_overlong_accepted`: no natural_v2_generated test starts a routine (in its session) with an over-long option record
- `multi_did_read_dedups_repeats`: no natural_v2_generated test reads one DID several times in a single 0x22 request
- `routine_restart_after_stop_blocked`: no natural_v2_generated test starts a routine again after stopping it
- `suppressed_seed_request_not_stored`: no natural_v2_generated test sends a suppressed seed request (27 81 / 27 83) and then a key for that level

_Reasons come from `uds_assistant/eval/heldout_v2.py`: one predicate per bug, written only from the bug descriptions in `data/bugs/heldout_v2_catalog.yaml` and `docs/behaviour_contract.md` before any v2 result existed. "no test X" means no test in that suite applies the stimulus; "N test(s) X, but none of their expected responses differs" means the stimulus is present but the oracle-derived expectations do not distinguish the bug. Reporting only — nothing was changed in response._

## Requirement understanding, natural v2 (split test2, SEEN) — mode=ollama

Source: `data/requirements_natural_v2.csv` (16 labelled rows). Each requirement was run through the agent pipeline (`mode=ollama`, Bm25Retriever). **The test2 split is SEEN (fresh in Part C).**

| Split | n | Targets exact (parsed) | Parsed P / R / F1 | Targets exact (exercised) | Exercised P / R / F1 | Category recall micro / macro | Precondition recall micro / macro | Fallback / nothing |
|---|---|---|---|---|---|---|---|---|
| **test2** | 16 | 4/16 (25.0%) | 0.808 / 0.775 / 0.792 | 0/16 (0.0%) | 0.484 / 0.939 / 0.639 | 36/50 (72.0%) / 72.0% | 25/27 (92.6%) / 95.5% | 0 (0 excl. empty-label rows) |
| all | 16 | 4/16 (25.0%) | 0.808 / 0.775 / 0.792 | 0/16 (0.0%) | 0.484 / 0.939 / 0.639 | 36/50 (72.0%) / 72.0% | 25/27 (92.6%) / 95.5% | 0 (0 excl. empty-label rows) |

### Per requirement (natural v2, mode=ollama)

| Req | Split | Tests | Label targets | Parsed exact | Parsed missed | Parsed extra | Exercised exact | Exercised missed | Exercised extra (n) | Categories missed | Preconditions missed | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NAT2-001 | test2 | 7 | did:0xF187, did:0xF18C, did:0xF190, service:0x22 | no | did:0xF190 | - | no | - | 2 | session | - | - |
| NAT2-002 | test2 | 4 | did:0x0120, service:0x10, service:0x27, service:0x2E | no | did:0x0120 | - | no | - | 3 | session | - | - |
| NAT2-003 | test2 | 8 | did:0x0130, service:0x22, service:0x27, service:0x2E | no | service:0x22 | service:0x10 | no | - | 3 | - | - | - |
| NAT2-004 | test2 | 4 | routine:0x0201, service:0x31 | no | routine:0x0201 | - | no | - | 2 | security | - | - |
| NAT2-005 | test2 | 5 | routine:0x0203, service:0x10, service:0x27, service:0x31 | no | routine:0x0203, service:0x31 | did:0x0150, service:0x22 | no | routine:0x0203, service:0x31 | 6 | session | - | - |
| NAT2-006 | test2 | 6 | service:0x27 | yes | - | - | no | - | 4 | negative, timing | - | - |
| NAT2-007 | test2 | 6 | service:0x14, service:0x19 | no | service:0x14 | service:0x22 | no | - | 4 | - | - | - |
| NAT2-008 | test2 | 6 | service:0x10, service:0x22, service:0x3E | no | service:0x22 | - | no | - | 1 | session | - | - |
| NAT2-009 | test2 | 4 | did:0x0100, service:0x10, service:0x27, service:0x2E | yes | - | - | no | - | 1 | session, timing | s3_elapsed | - |
| NAT2-010 | test2 | 8 | did:0xF186, service:0x10, service:0x11, service:0x22, service:0x27 | no | - | service:0x2E | no | service:0x11 | 4 | session | - | - |
| NAT2-011 | test2 | 3 | service:0x3E | yes | - | - | no | - | 3 | - | - | - |
| NAT2-012 | test2 | 4 | routine:0x0202, service:0x10, service:0x27, service:0x31 | no | service:0x31 | did:0x0110, did:0x0111 | no | - | 3 | negative | vehicle_moving | - |
| NAT2-013 | test2 | 4 | did:0x0160, service:0x10, service:0x22, service:0x27, service:0x2E | yes | - | - | no | - | 2 | session | - | - |
| NAT2-014 | test2 (ambiguous) | 6 | did:0x0110, did:0x0111, service:0x22, service:0x2E | no | service:0x2E | - | no | - | 2 | security | - | - |
| NAT2-015 | test2 (ambiguous) | 4 | service:0x10, service:0x14 | no | service:0x10 | - | no | - | 1 | negative | - | - |
| NAT2-016 | test2 | 8 | (none) | no | - | service:0x22, service:0x2E | no | - | 8 | - | - | - |

## Held-out bug detection (12 v1 bugs — SEEN: templates designed against these misses) — mode=ollama

Scope: held-out v1, now SEEN: bugs written by an independent subagent that could not see templates, gold tests, eval, LLM or agent code; the template-set-v3 coverage templates were then designed against the misses, so these 12 are no longer independent. Catalog: `data/bugs/heldout_catalog.yaml`.

| Bug | Category | Generated | Generated detecting tests | Gen. tests applying trigger | Gold | Gold detecting tests | Gold tests applying trigger |
|---|---|---|---|---|---|---|---|
| `routine_state_survives_session_change` | session | yes | `req_012__tpl_routine_after_session_0202` | 1 | **no** | - | 0 |
| `failed_attempts_reset_by_seed_request` | security | yes | `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01` (+2 more) | 4 | yes | `gold_security_lockout_after_3` | 1 |
| `seed_returned_while_unlocked` | security | yes | `req_006__tpl_seed_while_unlocked_01` | 1 | yes | `gold_security_already_unlocked_seed` | 1 |
| `nrc_order_condition_before_security` | nrc_order | **no** | - | 0 | **no** | - | 0 |
| `read_did_odd_length_truncated` | format | yes | `req_001__tpl_read_badlen_f190_01`, `req_002__tpl_read_badlen_f187_01` | 2 | **no** | - | 0 |
| `read_did_session_restriction_ignored` | data | yes | `req_009__tpl_read_did_wrong_0150_02`, `req_009__tpl_read_did_wrong_0150_01` | 2 | **no** | - | 0 |
| `uint16_did_stored_byte_swapped` | data | **no** | - | 0 | yes | `gold_write_coding_variant` | 1 |
| `s3_not_refreshed_by_tester_present` | timing | yes | `req_015__tpl_s3_keepalive_03` | 1 | **no** | - | 0 |
| `ecu_reset_clears_security_lockout` | security | **no** | - | 0 | **no** | - | 0 |
| `s3_timeout_reverts_written_dids` | timing | yes | `req_007__tpl_write_retained_s3_0130`, `req_008__tpl_write_retained_s3_0100` (+1 more) | 3 | **no** | - | 0 |
| `session_suppress_bit_not_masked` | format | yes | `req_003__tpl_suppress_positive_10_02`, `req_004__tpl_suppress_positive_10_03` | 5 | **no** | - | 0 |
| `suppress_bit_echoed_in_response` | format | **no** | - | 0 | **no** | - | 0 |

Totals: generated 8/12 (66.7%), gold 3/12 (25.0%), union 9/12 (75.0%). Invalid tests (fail on the clean simulator): generated 0, gold 0.

### Missed held-out v1 bugs — generated suite (mode=ollama)

- `nrc_order_condition_before_security`: no generated test starts a vehicle_stationary-gated routine while moving AND still locked
- `uint16_did_stored_byte_swapped`: no generated test writes a uint16 DID and reads it back
- `ecu_reset_clears_security_lockout`: no generated test resets the ECU after a security lockout and then requests a seed
- `suppress_bit_echoed_in_response`: no generated test sends RoutineControl with the suppress bit where a positive response is still expected (e.g. after 0x78)

### Missed held-out v1 bugs — gold suite

- `routine_state_survives_session_change`: no gold test starts a routine, changes session, then asks for that routine's results
- `nrc_order_condition_before_security`: no gold test starts a vehicle_stationary-gated routine while moving AND still locked
- `read_did_odd_length_truncated`: no gold test sends 0x22 with an odd number (>= 3) of DID bytes
- `read_did_session_restriction_ignored`: no gold test reads a DID outside its read_sessions
- `s3_not_refreshed_by_tester_present`: no gold test keeps a non-default session alive with TesterPresent across idle time
- `ecu_reset_clears_security_lockout`: no gold test resets the ECU after a security lockout and then requests a seed
- `s3_timeout_reverts_written_dids`: no gold test writes a DID, lets S3 expire, then reads the DID back
- `session_suppress_bit_not_masked`: no gold test sends DiagnosticSessionControl with the suppress bit set
- `suppress_bit_echoed_in_response`: no gold test sends RoutineControl with the suppress bit where a positive response is still expected (e.g. after 0x78)

_Reasons come from a static trigger analysis (`uds_assistant/eval/heldout.py`): for each held-out bug, a predicate written from its catalog description checks whether a test applies the stimulus the bug needs. Reporting only — nothing in templates, gold tests, mock LLM or planner was changed in response._

## Requirement understanding (natural requirements) — natural v1: test split SEEN, dev tuned on — mode=ollama

Source: `data/requirements_natural.csv` (20 labelled rows). Each requirement was run through the agent pipeline (`mode=ollama`, Bm25Retriever). **The test split is the v1 number, but it is SEEN; dev is what the prompts were tuned on.**

| Split | n | Targets exact (parsed) | Parsed P / R / F1 | Targets exact (exercised) | Exercised P / R / F1 | Category recall micro / macro | Precondition recall micro / macro | Fallback / nothing |
|---|---|---|---|---|---|---|---|---|
| **test** | 12 | 5/12 (41.7%) | 0.690 / 0.800 / 0.741 | 1/12 (8.3%) | 0.339 / 0.880 / 0.489 | 21/28 (75.0%) / 78.0% | 14/15 (93.3%) / 87.5% | 1 (0 excl. empty-label rows) |
| dev | 8 | 5/8 (62.5%) | 0.929 / 0.765 / 0.839 | 0/8 (0.0%) | 0.405 / 1.000 / 0.576 | 15/22 (68.2%) / 67.7% | 9/9 (100.0%) / 100.0% | 0 (0 excl. empty-label rows) |
| all | 20 | 10/20 (50.0%) | 0.767 / 0.786 / 0.776 | 1/20 (5.0%) | 0.364 / 0.929 / 0.523 | 36/50 (72.0%) / 73.7% | 23/24 (95.8%) / 91.7% | 1 (0 excl. empty-label rows) |

### Per requirement (natural v1, mode=ollama)

| Req | Split | Tests | Label targets | Parsed exact | Parsed missed | Parsed extra | Exercised exact | Exercised missed | Exercised extra (n) | Categories missed | Preconditions missed | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NAT-001 | dev | 7 | did:0xF190, service:0x22 | no | did:0xF190 | service:0x10 | no | - | 3 | - | - | - |
| NAT-002 | test | 7 | did:0xF187, did:0xF18C, service:0x22 | yes | - | - | no | - | 3 | - | - | - |
| NAT-003 | dev | 4 | service:0x10 | yes | - | - | no | - | 2 | session | - | - |
| NAT-004 | test (ambiguous) | 4 | service:0x10 | yes | - | - | no | - | 2 | session | vehicle_stationary | - |
| NAT-005 | dev | 7 | did:0x0100, service:0x10, service:0x27, service:0x2E | no | service:0x10, service:0x27 | - | no | - | 3 | security | - | - |
| NAT-006 | test (ambiguous) | 8 | did:0x0101, service:0x10, service:0x27, service:0x2E | no | service:0x10 | - | no | - | 2 | - | - | - |
| NAT-007 | dev | 4 | did:0x0130, service:0x2E | yes | - | - | no | - | 4 | security | - | - |
| NAT-008 | test | 4 | did:0x0131, service:0x2E | no | - | service:0x22 | no | - | 4 | security | - | - |
| NAT-009 | dev | 7 | did:0x0150, service:0x10, service:0x27, service:0x2E | yes | - | - | no | - | 4 | session | - | - |
| NAT-010 | test | 4 | service:0x27 | yes | - | - | no | - | 4 | negative, timing | - | - |
| NAT-011 | dev | 8 | routine:0x0201, service:0x31 | no | routine:0x0201 | - | no | - | 5 | security | - | - |
| NAT-012 | test | 8 | routine:0x0202, service:0x31 | no | service:0x31 | did:0x0110, did:0x0111, did:0x0140 | no | - | 7 | - | - | - |
| NAT-013 | dev | 6 | service:0x11 | yes | - | - | no | - | 1 | positive | - | - |
| NAT-014 | test | 8 | service:0x19 | no | - | service:0x22 | no | - | 7 | - | - | - |
| NAT-015 | dev | 4 | service:0x3E | yes | - | - | no | - | 3 | session | - | - |
| NAT-016 | test | 8 | did:0x0160, service:0x10, service:0x27, service:0x2E | yes | - | - | no | - | 4 | session | - | - |
| NAT-017 | test (ambiguous) | 4 | service:0x14, service:0x19 | no | service:0x19 | - | no | - | 1 | negative | - | - |
| NAT-018 | test | 8 | did:0x0120, service:0x27, service:0x2E | no | did:0x0120 | service:0x10 | no | did:0x0120 | 3 | - | - | - |
| NAT-019 | test | 4 | routine:0x0203, service:0x31 | no | routine:0x0203 | did:0x0150, service:0x10, service:0x27 | no | routine:0x0203, service:0x31 | 6 | security | - | - |
| NAT-020 | test | 0 | (none) | yes | - | - | yes | - | 0 | - | - | no parsed services/DIDs/routines; zero tests |

## Secondary: in-sample bug detection (26 bugs — in-sample, templates tuned on these) — mode=ollama

Scope: in-sample (templates tuned on these). Generated 21/26 (80.8%), gold 24/26 (92.3%), union 25/26 (96.2%). This is an optimistic, non-independent number: template set v2 was written after seeing which of these bugs v1 missed, by the same author as the catalog.

### Bug detection per injected bug (in-sample) — mode=ollama

| Bug | Category | Generated | Generated detecting tests | Gold | Gold detecting tests |
|---|---|---|---|---|---|
| `nrc_order_did_before_session` | nrc_order | yes | 1: `req_009__tpl_nrc_priority_2e_01` | yes | 1: `gold_write_unknown_did_default_session` |
| `nrc_order_security_before_length` | nrc_order | **no** | 0: - | yes | 1: `gold_write_wrong_length` |
| `general_reject_instead_of_0x12` | format | yes | 14: `req_003__tpl_unsupported_subfunction_10_01`, `req_003__tpl_negative_suppress_10_02`, `req_004__tpl_negative_suppress_10_02` (+11 more) | yes | 4: `gold_session_unsupported_sub`, `gold_ecu_reset_bad_sub`, `gold_dtc_read_bad_sub` (+1 more) |
| `security_not_reset_on_session_change` | session | yes | 3: `req_006__tpl_session_relock_01`, `req_010__tpl_session_relock_03`, `req_012__tpl_routine_after_session_0202` | yes | 1: `gold_security_relocked_on_session_reentry` |
| `s3_timeout_never_fires` | timing | yes | 5: `req_003__tpl_s3_timeout_03`, `req_004__tpl_s3_timeout_02`, `req_004__tpl_s3_timeout_03` (+2 more) | yes | 1: `gold_s3_timeout_reverts` |
| `s3_timeout_off_by_one` | timing | yes | 1: `req_015__tpl_s3_keepalive_03` | yes | 1: `gold_s3_no_timeout_at_exactly_s3ms` |
| `lockout_after_extra_attempt` | security | yes | 4: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_010__tpl_security_lockout_01` (+1 more) | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_ignored` | security | yes | 4: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_010__tpl_security_lockout_01` (+1 more) | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_never_expires` | timing | yes | 4: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_010__tpl_security_lockout_01` (+1 more) | **no** | 0: - |
| `accepts_any_key` | security | yes | 4: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_010__tpl_security_lockout_01` (+1 more) | yes | 3: `gold_security_wrong_key_once`, `gold_security_lockout_after_3`, `gold_security_wrong_level_unlock` |
| `seed_not_consumed` | sequence | **no** | 0: - | **no** | 0: - |
| `static_seed` | security | yes | 7: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_006__tpl_session_relock_01` (+4 more) | yes | 1: `gold_security_lockout_after_3` |
| `write_ignores_value_range` | data | yes | 2: `req_007__tpl_write_oor_0130`, `req_008__tpl_write_oor_0100` | yes | 2: `gold_write_out_of_range_wiper`, `gold_write_out_of_range_brightness` |
| `readonly_did_writable` | data | yes | 1: `req_001__tpl_write_readonly_f190` | yes | 1: `gold_write_readonly_did` |
| `write_length_off_by_one` | format | **no** | 0: - | yes | 1: `gold_write_wrong_length` |
| `write_positive_sid_wrong` | format | yes | 9: `req_005__tpl_write_secured_0100`, `req_006__tpl_write_secured_0101`, `req_006__tpl_seed_while_unlocked_01` (+6 more) | yes | 5: `gold_write_secured_positive_lighting`, `gold_write_secured_positive_ambient_color`, `gold_write_coding_variant` (+2 more) |
| `session_response_missing_timing` | format | yes | 50: `req_001__tpl_read_did_positive_f190_02`, `req_001__tpl_read_did_positive_f190_03`, `req_001__tpl_write_readonly_f190` (+47 more) | yes | 35: `gold_read_vin_extended`, `gold_session_to_extended`, `gold_session_back_default` (+32 more) |
| `suppress_bit_ignored` | format | yes | 3: `req_003__tpl_suppress_positive_10_02`, `req_004__tpl_suppress_positive_10_03`, `req_015__tpl_suppress_positive_3e_02` | yes | 2: `gold_tester_present_suppressed`, `gold_ecu_reset_suppressed` |
| `negative_response_suppressed` | format | yes | 11: `req_003__tpl_negative_suppress_10_02`, `req_004__tpl_negative_suppress_10_02`, `req_006__tpl_negative_suppress_10_03` (+8 more) | yes | 1: `gold_tester_present_bad_sub_not_suppressed` |
| `routine_stop_without_start` | sequence | yes | 1: `req_012__tpl_routine_sequence_0202` | yes | 1: `gold_routine_stop_before_start` |
| `condition_ignored` | data | yes | 1: `req_009__tpl_condition_not_met_did_0150` | yes | 2: `gold_routine_door_cal_condition_fail`, `gold_write_factory_reset_flag_moving` |
| `dtc_clear_ignores_group` | data | **no** | 0: - | yes | 2: `gold_dtc_clear_specific`, `gold_dtc_clear_unknown_group` |
| `dtc_clear_noop` | data | yes | 1: `req_014__tpl_dtc_read_clear_B10101` | yes | 2: `gold_dtc_clear_all`, `gold_dtc_clear_specific` |
| `multi_did_read_first_only` | data | yes | 5: `req_002__tpl_read_multi_f190_f187_01`, `req_002__tpl_read_multi_f187_f190_01`, `req_002__tpl_read_multi_f18c_f190_01` (+2 more) | yes | 2: `gold_read_partnum_serial_multi`, `gold_duplicate_did_read` |
| `missing_response_pending` | timing | **no** | 0: - | yes | 1: `gold_routine_nvm_restore_long_running` |
| `dtc_read_ignores_mask` | data | yes | 1: `req_014__tpl_dtc_read_clear_B10101` | yes | 4: `gold_dtc_read_default`, `gold_dtc_set_and_read`, `gold_dtc_clear_all` (+1 more) |

Invalid tests (fail on the clean simulator, excluded from credit): generated 0, gold 0.
Detected only by the generated suite: lockout_delay_never_expires. Only by gold: nrc_order_security_before_length, write_length_off_by_one, dtc_clear_ignores_group, missing_response_pending. Undetected by both: seed_not_consumed.

## Coverage (generated tests per category per seed requirement) — mode=ollama

| Requirement | positive | negative | session | security | timing | total |
|---|---|---|---|---|---|---|
| REQ-001 | 3 | 2 | 0 | 0 | 0 | 5 |
| REQ-002 | 7 | 1 | 0 | 0 | 0 | 8 |
| REQ-003 | 1 | 2 | 0 | 0 | 1 | 4 |
| REQ-004 | 1 | 1 | 0 | 0 | 2 | 4 |
| REQ-005 | 2 | 0 | 0 | 1 | 1 | 4 |
| REQ-006 | 3 | 1 | 0 | 3 | 1 | 8 |
| REQ-007 | 2 | 1 | 0 | 0 | 1 | 4 |
| REQ-008 | 4 | 1 | 0 | 0 | 1 | 6 |
| REQ-009 | 1 | 5 | 1 | 0 | 1 | 8 |
| REQ-010 | 0 | 0 | 0 | 3 | 0 | 3 |
| REQ-011 | 0 | 2 | 0 | 0 | 0 | 2 |
| REQ-012 | 0 | 2 | 2 | 0 | 0 | 4 |
| REQ-013 | 0 | 5 | 0 | 0 | 0 | 5 |
| REQ-014 | 1 | 2 | 1 | 0 | 0 | 4 |
| REQ-015 | 1 | 2 | 0 | 0 | 1 | 4 |
| **total** | 26 | 27 | 4 | 7 | 9 | 73 |

Categories present: 100.0%; requirements covered by ≥2 categories: 12/15.

## Request validity — mode=ollama

- Send steps: 226; decodable: 226; not rejected with a format NRC (0x11/0x12/0x13): 206 (unadjusted rate 91.1%).
- Intentional format probes (NRC in the template's `intended_nrcs`): 20. Adjusted validity: **226/226 (100.0%)**.

## Template reuse and citations — mode=ollama

- Template reuse: 73/73 (100.0%); templates used: 22/27; per template: `condition_not_met` 2, `dtc_read_clear` 1, `negative_response_with_suppress_bit` 11, `nrc_priority_session_over_identifier` 1, `read_did_invalid_length` 2, `read_did_positive` 12, `read_did_wrong_session_or_unknown` 2, `read_multiple_dids` 5, `routine_sequence` 1, `s3_keepalive_boundary` 1, `s3_timeout_reverts_session` 5, `security_invalid_key_lockout` 4, `seed_request_while_unlocked` 1, `service_not_in_session` 3, `session_change_relocks_security` 2, `session_change_resets_routine` 1, `suppress_positive_response` 3, `unsupported_subfunction` 5, `write_did_out_of_range` 2, `write_did_secured_positive` 4, `write_did_value_retained` 4, `write_readonly_did` 1
- Citations: 353/353 valid; tests with ≥1 valid citation: 100.0%.

## Pipeline statistics (seed requirements) — mode=ollama

| Requirement | tests | dropped | rejected | plan attempts | status | wall s |
|---|---|---|---|---|---|---|
| REQ-001 | 5 | 0 | 0 | 1 | completed | 25.727 |
| REQ-002 | 8 | 0 | 0 | 1 | completed | 30.491 |
| REQ-003 | 4 | 0 | 0 | 1 | completed | 18.636 |
| REQ-004 | 4 | 0 | 0 | 1 | completed | 18.698 |
| REQ-005 | 4 | 0 | 0 | 1 | completed | 20.623 |
| REQ-006 | 8 | 0 | 0 | 1 | completed | 30.411 |
| REQ-007 | 4 | 0 | 0 | 1 | completed | 17.351 |
| REQ-008 | 6 | 0 | 0 | 1 | completed | 21.448 |
| REQ-009 | 8 | 0 | 0 | 1 | completed | 25.875 |
| REQ-010 | 3 | 0 | 0 | 1 | completed | 19.13 |
| REQ-011 | 2 | 0 | 0 | 1 | completed | 22.725 |
| REQ-012 | 4 | 0 | 0 | 1 | completed | 20.69 |
| REQ-013 | 5 | 0 | 0 | 1 | completed | 22.737 |
| REQ-014 | 4 | 0 | 0 | 1 | completed | 21.853 |
| REQ-015 | 4 | 0 | 0 | 1 | completed | 21.43 |

Totals: 73 kept, 0 dropped, 0 rejected, 0 re-plans, 0 failed runs.

## Appendix: Self-consistency check (circular by construction) — mode=ollama

Expected bytes in generated tests are produced by the rules-engine oracle, so agreement with a fresh oracle re-run is a consistency check, not an independent accuracy measure. Kept here for completeness; it is not a headline metric.

- Expected-response accuracy vs oracle: 226/226 (100.0%) steps; 73/73 (100.0%) tests.
- Independent simulator (clean): 100.0% of generated tests pass.
- Gold, exact overlap: 11/11 (100.0%) generated/gold pairs with identical step sequences agree.
- Gold, shared prefix: 15/15 (100.0%) distinct send steps reached by an identical prefix in both suites agree.

# Shared

### Precondition mapping (how 'established' is derived from test steps)

- `default_session`: a request other than 0x10 is sent while the tracked session is the default session (no session change before it, or after a reset / S3 timeout), or a positive 10 01
- `extended_session`: a 0x10 request with sub-function 0x03 (suppress bit masked) whose expected outcome is positive
- `programming_session`: a 0x10 request with sub-function 0x02 whose expected outcome is positive
- `security_level_N`: a sendKey (0x27, the level's key sub-function from the spec) whose expected outcome is positive; level 0x01 -> security_level_1, 0x03 -> security_level_3
- `vehicle_moving`: a set_environment step with vehicle_speed_kph > 0
- `vehicle_stationary`: a set_environment step with vehicle_speed_kph == 0, or a positive 0x2E write / 0x31 start of a DID / routine whose spec conditions require vehicle_stationary
- `nvm_fault`: a set_environment step with nvm_write_fault = true
- `dtc_status_set`: a set_dtc_status step
- `routine_started`: a positive 0x31 startRoutine (sub-function 0x01) followed by at least one later send step
- `s3_elapsed`: clock advanced by more than the active session's S3 time between two send steps
- `lockout_active`: an expected 7F 27 36 (exceededNumberOfAttempts) or 7F 27 37 (requiredTimeDelayNotExpired) response

## Exports

- `exports/generated_tests_test.py` (mode=mock)
- `exports/gold_tests_test.py` (mode=mock)
- `exports/generated_tests.can` (mode=mock)
- `exports/gold_tests.can` (mode=mock)
- `generated_tests.yaml` (mode=mock)
- Ran `generated_tests_test.py` for mode=mock (transport `inprocess`) with pytest in a subprocess: **PASSED** — `206 passed in 1.96s` (6.41 s).
- `exports/ollama/generated_tests_test.py` (mode=ollama)
- `exports/ollama/gold_tests_test.py` (mode=ollama)
- `exports/ollama/generated_tests.can` (mode=ollama)
- `exports/ollama/gold_tests.can` (mode=ollama)
- `generated_tests_ollama.yaml` (mode=ollama)
- Ran `generated_tests_test.py` for mode=ollama (transport `inprocess`) with pytest in a subprocess: **PASSED** — `73 passed in 1.20s` (4.51 s).
- CAPL files (`*.can`) are **UNVERIFIED TEMPLATES — not compiled or run in CANoe**.

## Runtime

| Phase | seconds |
|---|---|
| setup | 7.24 |
| gold_suites | 0.959 |
| conformance_sweep | 100.949 |
| mock.generation | 6.415 |
| mock.requirement_understanding | 6.896 |
| mock.requirement_understanding_v2 | 3.935 |
| mock.requirement_understanding_v3 | 4.258 |
| mock.execution_and_bug_matrices | 46.593 |
| mock.part_d_detection | 0.0 |
| mock.noise_check | 4.045 |
| mock.provenance | 0.41 |
| mock.metrics | 0.432 |
| mock.total | 72.993 |
| ollama.generation | 337.826 |
| ollama.requirement_understanding | 426.786 |
| ollama.requirement_understanding_v2 | 348.434 |
| ollama.requirement_understanding_v3 | 332.486 |
| ollama.execution_and_bug_matrices | 18.271 |
| ollama.part_d_detection | 0.0 |
| ollama.noise_run_2 | 335.555 |
| ollama.noise_run_3 | 325.699 |
| ollama.noise_check | 661.475 |
| ollama.provenance | 0.306 |
| ollama.metrics | 0.152 |
| ollama.total | 2125.751 |
| simulator_rules_agreement | 0.665 |
| udsoncan_virtual_can | 0.553 |
| exports | 12.881 |
| retrieval_compare | 5.636 |
| total | 2327.64 |

## Metric definitions

- **request_validity**: Over every send step of every generated test: the request is replayed through the rules-engine oracle in sequence (same set-up and time steps). A request counts as well-formed if (a) protocol.codec.decode_request decodes it and (b) the oracle does not reject it with a format NRC (0x11 serviceNotSupported, 0x12 subFunctionNotSupported, 0x13 incorrectMessageLengthOrInvalidFormat), unless that NRC is listed in the template's declared intended_nrcs (a deliberate malformed-request probe such as write_did_invalid_length -> 0x13). rate = well-formed / send steps. The unadjusted rate (no intent exemption) is reported alongside.
- **expected_response_accuracy**: SELF-CONSISTENCY CHECK, circular by construction (expected bytes are produced by the same oracle; reported in an appendix, not a headline). oracle: share of generated send steps whose expected response frames equal a fresh rules-engine re-run of the test (and share of whole tests with zero mismatches). simulator: share of generated tests passing on the bug-free independent simulator. gold: (1) exact overlap = generated tests whose full step sequence (requests and set-up/time steps, ignoring expected responses) is identical to a gold test; agreement = identical expected responses on every step. (2) shared-prefix overlap = every distinct send step reached by an identical step prefix from power-on in both a generated and a gold test (deduplicated by prefix); agreement = identical expected frames for that step.
- **coverage**: Number of generated tests per category (positive/negative/session/security/timing) per requirement. rate = requirements with >= 1 generated test / requirements; category_presence = categories with >= 1 test across the suite / 5.
- **template_reuse_rate**: Share of generated tests whose template_id is a registered template AND whose steps are byte-identical to a fresh instantiation of that template with the test's stored parameters (independent re-check of byte provenance).
- **citation_validity**: Share of all citations attached to generated tests for which rag.citations.citation_is_valid is true against the evaluation corpus (source+ref exists; a quote must appear verbatim and its hex identifiers must belong to the chunk).
- **bug_detection_rate**: Each catalog bug is enabled alone in a fresh simulator per test. A bug is detected if >= 1 test that passes on the clean simulator fails with the bug enabled. Tests failing on the clean simulator are reported as invalid and get no credit. rate = detected bugs / catalog bugs. Reported for the generated suite, the hand-written gold suite (baseline) and their union. The 26-bug catalog (data/bugs/bug_catalog.yaml) is IN-SAMPLE: templates v2 were added after inspecting which of these bugs v1 missed.
- **heldout_bug_detection_rate**: Same procedure as bug_detection_rate on the 12 held-out bugs in data/bugs/heldout_catalog.yaml, written by a subagent that could not see templates, gold tests, eval, LLM or agent code. HEADLINE = held-out generated-suite detection. Missed-bug reasons come from a static trigger analysis (eval/heldout.py): whether any test applies the stimulus the bug description needs; reporting only.
- **simulator_rules_agreement**: A deterministic seeded random sample (eval/agreement.py; >= 5000 requests over 60-step walks with clock advances, environment/DTC changes and computed seed/key handshakes) is sent to a bug-free SimulatedEcu and a RulesSession in lockstep. agreed = requests with byte-identical response frames; a walk stops at its first disagreement.
- **udsoncan_virtual_can**: udsoncan.Client over ISO-TP on a python-can virtual bus against the simulator: 10 03 -> 27 01 seed -> 27 02 key -> 22 0100 -> 2E 0100 50 -> 22 0100 read-back == 0x50. pass/fail (fail includes any exception, with its text); 'skipped' with --skip-can.
- **gold_clean_pass**: Gold tests passing on the bug-free simulator / gold tests.
- **pipeline_stats**: Per requirement: kept tests, dropped tests (failed validation), rejected planner choices, plan attempts (retries = attempts - 1), run status.
- **runtime**: Wall-clock seconds per evaluation phase and in total (machine dependent).
- **target_identification**: Label set = target_services U target_dids U target_routines (typed, so service 0x22 and DID 0x0022 differ). Two predicted sets: (a) 'parsed' = services U dids U routines of the ParsedRequirement returned by the pipeline; (b) 'exercised' = every SID of every send step in the requirement's generated tests, every DID named by a 0x22 (all complete pairs) or 0x2E (first pair) request, and every routine id of a 0x31 request. Exact match = predicted set equals label set; for a requirement with an empty label set (NAT-020, unsupported) exact match additionally requires zero generated tests. Micro precision / recall / F1 sum TP / FP / FN over requirements.
- **category_recall**: |required_categories n categories of the requirement's generated tests| / |required_categories|. Micro = summed numerators / summed denominators; macro = mean over requirements with >= 1 required category (NAT-020 has none and is excluded).
- **precondition_recall**: |required_preconditions n preconditions established by >= 1 generated test| / |required_preconditions|, `none` skipped (requirements whose label is `none` are excluded). 'Established' is derived statically from each test's concrete steps and oracle-expected responses (mapping below). Micro and macro as for categories.
- **fallback**: A requirement counts as fallback / produced-nothing if the pipeline status is not 'completed', or the parsed requirement has no services, DIDs or routines, or it kept zero tests. Reported with the list of ids (for NAT-020 producing nothing is the correct outcome).
- **heldout_v2_bug_detection_rate**: Same procedure as bug_detection_rate on the 15 held-out v2 bugs in data/bugs/heldout_v2_catalog.yaml (heldout_v2: true), written blind after the Part C freeze and SEEN since Part D. Generated-suite detection, where the generated suite is the tests generated from the 15 seed requirements (the same definition as the held-out v1 headline). Supplementary: detection by the union of all generated tests (seed + natural v1 + natural v2) and by the natural-v2 tests alone. Missed-bug reasons come from eval/heldout_v2.py (static trigger predicates written before any v2 result).
- **natural_v2_understanding**: Requirement understanding on data/requirements_natural_v2.csv (16 rows, split test2, written blind after the freeze) with the same label schema and scoring as the v1 natural set; test2 is the headline split.
- **part_d_detection**: Per bug catalog and LLM mode: (a) requirement_driven = the tests generated from the 15 seed requirements (exactly the Part C 'generated' suite, comparable with Part C); (b) conformance = the requirement-independent conformance sweep alone (uds_assistant/testgen/conformance.py, generated deterministically from the spec; it uses no LLM and is the same in every mode); (c) full_output = (a) union (b), the system's full output. A bug counts as detected by a suite when a test that passes on the clean simulator fails with the bug enabled; (c) is computed per bug from (a) and (b) because every test runs on a fresh simulator.
- **conformance_sweep**: Setups (spec-derived states) x stimuli (spec-derived requests and mutations), each followed by a fixed probe set; every expected byte from the rules engine; reduced by deterministic greedy covering. Deterministic lazy-greedy set cover over oracle-observable items, in priority phases; each phase adds tests until its items are covered or the cap is reached, ties broken by catalog order (setup, then stimulus). Phase 1: every (stimulus, response class) the oracle can produce for it over all setups, and every (setup, service family) pair for the spec's services. Phase 2: transition tuples (session, unlocked level, active lockouts, time since last request vs S3, stimulus class, response class) and state effects (stimulus class, response class, which abstract state components changed and how). Phase 3: (stimulus, active session, response class). Phase 4: fine transitions (full abstract pre-state, stimulus class, response class, full abstract post-state).
- **heldout_v3_bug_detection**: FRESH headline for bugs: the 15 held-out v3 bugs in data/bugs/heldout_v3_catalog.yaml (heldout_v3: true), written blind after the Part D freeze. HEADLINE = detection by the system's FULL OUTPUT = (c) the requirement-driven tests from the 15 seed requirements UNION (per bug) the conformance sweep. Reported next to it and clearly labelled: (a) requirement-driven only (comparable with Part C), (b) the sweep alone, (d) gold. Supplementary: all generated tests (seed + natural v1 + v2 + v3) and the natural-v3 tests alone. Missed-bug reasons come from eval/heldout_v3.py (static trigger predicates written from the bug descriptions before any v3 result existed).
- **natural_v3_understanding**: Requirement understanding on data/requirements_natural_v3.csv (16 rows, split test3, written blind after the Part D freeze) with the same label schema and scoring as v1 / v2. test3 is the requirement headline. Nothing was tuned on it.
- **noise_check**: ollama runs the pipeline over natural v3 --noise-runs times in total; run 1 feeds the tables, every run is listed, and the summary is the mean and min-max range over ALL runs (never only the best). mock is deterministic: one run, plus an equality re-run as a check. natural v2 (SEEN) keeps its single run.
- **by_kind**: Parsed (and exercised) false positives and false negatives by identifier kind (service / did / routine / dtc), per requirement set, from each requirement's missed and extra identifiers. tp = label items of that kind minus the missed ones.
- **rejected_by_reason**: Rejected planner choices by reason: unknown template id; option index out of range; option not in the offered shortlist; duplicate / other (a choice that previously failed, or an instantiate / validate failure). Counted per requirement set.
- **seen_sets**: SEEN = their results were known when Part D was designed or tuned: held-out v1 and v2 bugs, natural v1 (test and dev) and v2 requirements. The 26 in-sample bugs were tuned on. Only the v3 rows are independent evidence.
