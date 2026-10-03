# Results (honest one-page summary, after Part C)

Source of every number: [outputs/eval_report.md](../outputs/eval_report.md) and `outputs/eval_report.json` (report version 3, generated 2026-10-03T20:49:18Z, git `c669e1e`, template set `v3` with 27 templates, Bm25Retriever, LangGraph engine). One invocation (`python -m uds_assistant.eval.run_eval --mode ollama --noise-runs 3 --before-after`) ran **both** `mock` and `ollama` on the same inputs, templates and retriever. The before/after table is [outputs/partC/before_after.md](../outputs/partC/before_after.md); the written interpretation is [outputs/partC/interpretation.md](../outputs/partC/interpretation.md). Numbers were copied, not rounded up.

> The ECU spec is **synthetic** (a fictional Body Control Module written for this project). Every number below is measured against the project's own simulator, not a real ECU.

**Headline (fresh v2 data, written blind after the Part C freeze, nothing tuned on it).**

1. **Held-out v2 bug detection is low: 2/15 (13.3%) for the generated suite, in both modes.** The gold suite catches 5/15 and the union is 5/15. The coverage templates added in Part C did not transfer from the seen v1 bugs to the fresh ones.
2. **Requirement understanding on natural v2 is better with the model than with the mock**: parsed F1 0.661 vs 0.367, category recall 74.0% vs 48.0%, precondition recall 77.8% vs 55.6% (ollama run 1). The model's precision is only 0.565, with 30 false positives (25 services, 5 DIDs); the mock's precision is 1.000 but its recall is 0.225.
3. **The precision fix did not work.** The grounding check does not cover services, and most false positives are services. The template-id normalisation fired 0 times, and rejected planner choices went up, not down.
4. **Explain batching worked**: 1.00 LLM call per requirement (4.51 before) and mean latency 21.37 s (30.79 s before).

Everything marked **SEEN** or **in-sample** below is not independent evidence: the Part C templates were designed against the v1 held-out misses, and the in-sample bugs shaped templates v2.

## Headline table

| Metric | mock | ollama |
|---|---|---|
| **1. Held-out v2 bug detection, FRESH (15 bugs): generated / gold / union** | **generated 2/15 (13.3%)** · gold 5/15 (33.3%) · union 5/15 (33.3%) | **generated 2/15 (13.3%)** · gold 5/15 (33.3%) · union 5/15 (33.3%) |
| **2a. Natural v2, FRESH (test2, n=16): parsed exact** | 0/16 | 4/16 |
| **2b. Natural v2, FRESH: parsed P / R / F1** | 1.000 / 0.225 / 0.367 | 0.565 / 0.796 / 0.661 (3-run mean 0.565 / 0.796 / 0.661, range 0.661-0.661) |
| **2c. Natural v2, FRESH: exercised F1** | 0.450 | 0.583 (3-run mean 0.602, range 0.583-0.611) |
| **2d. Natural v2, FRESH: category recall (micro)** | 48.0% | 74.0% (3-run mean 75.3%, range 74.0%-76.0%) |
| **2e. Natural v2, FRESH: precondition recall (micro)** | 55.6% | 77.8% (3-run mean 82.7%, range 77.8%-85.2%) |
| 3. Simulator <-> rules-engine agreement (seeded random sample, live; seed 20261003, 89 walks) | 5000/5000 (100.0%) | same (LLM-independent) |
| 4. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 5. udsoncan virtual-CAN sequence (session -> seed/key -> read -> write -> read-back) | PASS | same (LLM-independent) |
| 6. Coverage (seed requirements; tests per category) | positive 43, negative 77, session 25, security 30, timing 31; requirements with >=1 test 15/15 (100.0%) | positive 26, negative 18, session 9, security 9, timing 4; requirements with >=1 test 15/15 (100.0%) |
| 7. Citation validity | 967/967 (100.0%) | 315/315 (100.0%) |
| Generated tests for the 15 seed requirements | 206 | 66 |
| Byte provenance, all generated tests, all runs | 511/511 | 418/418 |
| **SEEN** 8. Held-out v1 bug detection (12 bugs; templates were designed against these misses): generated / gold / union | generated 10/12 (83.3%) · gold 3/12 (25.0%) · union 11/12 (91.7%) | generated 5/12 (41.7%) · gold 3/12 (25.0%) · union 6/12 (50.0%) |
| **SEEN** 9. Natural v1 test split (n=12): parsed exact; parsed P / R / F1 | 5/12; 0.933 / 0.560 / 0.700 | 3/12; 0.500 / 0.840 / 0.627 |
| **SEEN** 9b. Natural v1 test split: exercised F1; category recall; precondition recall | 0.425; 67.9%; 80.0% | 0.416; 82.1%; 73.3% |
| **In-sample (templates tuned on these)** 10. In-sample bug detection (26 bugs): generated / gold / union | generated 25/26 (96.2%) · gold 24/26 (92.3%) · union 26/26 (100.0%) | generated 19/26 (73.1%) · gold 24/26 (92.3%) · union 26/26 (100.0%) |

Rows 1 and 2 are the headline. The natural v1 dev split (n=8) is what the Part B prompts were tuned on, so it is not evidence: mock parsed exact 4/8 (F1 0.828), ollama 2/8 (F1 0.684).

## Before / after Part C

From `outputs/partC/before_after.md`. Before = the frozen pre-Part C report (commit `38aa719`); after = this report. Rows labelled FRESH have no "before" because the data did not exist.

| Metric | mock before | mock after | ollama before | ollama after |
|---|---|---|---|---|
| **Held-out v2, FRESH (15 bugs): generated / gold / union** | n/a | 2/15 / 5/15 / 5/15 | n/a | 2/15 / 5/15 / 5/15 |
| Held-out v1, SEEN (12 bugs): generated / gold / union | 3/12 / 3/12 / 5/12 | 10/12 / 3/12 / 11/12 | 3/12 / 3/12 / 5/12 | 5/12 / 3/12 / 6/12 |
| In-sample (26 bugs), tuned on: generated / gold / union | 25/26 / 24/26 / 26/26 | 25/26 / 24/26 / 26/26 | 21/26 / 24/26 / 26/26 | 19/26 / 24/26 / 26/26 |
| **Natural v2, FRESH (n=16): parsed exact** | n/a | 0/16 | n/a | 4/16 |
| **Natural v2, FRESH: parsed P / R / F1** | n/a | 1.000 / 0.225 / 0.367 | n/a | 0.565 / 0.796 / 0.661 |
| Natural v2, FRESH: exercised F1 | n/a | 0.450 | n/a | 0.583 |
| Natural v2, FRESH: category recall (micro) | n/a | 48.0% | n/a | 74.0% |
| Natural v2, FRESH: precondition recall (micro) | n/a | 55.6% | n/a | 77.8% |
| Natural v1 test split, SEEN (n=12): parsed exact | 5/12 | 5/12 | 4/12 | 3/12 |
| Natural v1 test split, SEEN: parsed P / R / F1 | 0.933 / 0.560 / 0.700 | 0.933 / 0.560 / 0.700 | 0.512 / 0.880 / 0.647 | 0.500 / 0.840 / 0.627 |
| Natural v1 test split, SEEN: exercised F1 | 0.449 | 0.425 | 0.435 | 0.416 |
| Natural v1 test split, SEEN: category recall (micro) | 67.9% | 67.9% | 64.3% | 82.1% |
| Natural v1 test split, SEEN: precondition recall (micro) | 80.0% | 80.0% | 73.3% | 73.3% |
| Parsed precision / false positives, v1 test split (SEEN) | 0.933 / 1 FP | 0.933 / 1 FP | 0.512 / 21 FP | 0.500 / 21 FP |
| **Parsed precision / false positives, v2 (FRESH)** | n/a | 1.000 / 0 FP | n/a | 0.565 / 30 FP |
| Rejected planner choices (15 seed + 20 natural v1) | 0 | 0 | 10 | 15 |
| Rejected planner choices, natural v2 (16, FRESH) | n/a | 0 | n/a | 12 |
| Latency per requirement, mean / p95 (35 requirements) | 0.25 s / 0.45 s | 0.27 s / 0.46 s | 30.79 s / 43.41 s | 21.37 s / 28.52 s |
| Explain LLM calls per requirement, mean (min-max) | 9.80 (0-18), derived from tests kept | 0.89 (0-1) | 4.51 (0-8), derived from tests kept | 1.00 (1-1) |
| SWS disagreements open | 9 | 5 | 9 | 5 |

**Comparability.** (1) The v2 sets are different from the v1 sets, so v2 rows are not "after" values of v1 rows; there was no v2 "before". (2) v1 numbers are SEEN: the Part C templates were designed against the v1 held-out misses, so the v1 jump (mock 3/12 to 10/12) measures how well the templates fit known misses, not general coverage. (3) mock is deterministic. (4) ollama output varies from run to run, so small ollama differences are noise (see the noise check). (5) Latency and explain calls are over the 35 seed + natural-v1 requirements in both reports; the baseline's explain calls are derived from tests kept. For ollama, in-sample detection fell (21/26 to 19/26) and held-out v1 rose only from 3/12 to 5/12 (mock: 3/12 to 10/12); the interpretation attributes this to smaller, more selective plans that skip checks a catalog of known bugs happens to need.

## Noise check: natural v2 (fresh), ollama, 3 runs

Run 1 feeds every table above. Every run is listed; the summary is the mean and min-max range, never the best run.

| Run | Parsed P | Parsed R | Parsed F1 | Exercised F1 | Category recall | Precondition recall | Tests kept | Rejected choices | Fallback events | Byte provenance |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 (used for the main tables) | 0.565 | 0.796 | 0.661 | 0.583 | 74.0% | 77.8% | 81 | 12 | 18 | 81/81 |
| 2 | 0.565 | 0.796 | 0.661 | 0.611 | 76.0% | 85.2% | 80 | 8 | 11 | 80/80 |
| 3 | 0.565 | 0.796 | 0.661 | 0.611 | 76.0% | 85.2% | 80 | 8 | 11 | 80/80 |
| **mean (min-max)** | 0.565 (0.565-0.565) | 0.796 (0.796-0.796) | 0.661 (0.661-0.661) | 0.602 (0.583-0.611) | 75.3% (74.0%-76.0%) | 82.7% (77.8%-85.2%) | 80.33 (80-81) | 9.33 (8-12) | 13.33 (11-18) | |

The mock is deterministic: a second mock run over natural v2 was identical (True). Parse runs at temperature 0 with a fixed seed and gave identical parsed numbers in all three runs; the variation is in planning and explaining. The roughly +-0.05 F1 seen on the dev split in Part B did not show up here, but three runs is a small sample.

## Held-out v2 bug detection (15 fresh bugs)

| Suite | mock | ollama |
|---|---|---|
| **Generated (headline)** | 2/15 (13.3%) | 2/15 (13.3%) |
| Gold (LLM-independent) | 5/15 (33.3%) | 5/15 (33.3%) |
| Union generated + gold | 5/15 (33.3%) | 5/15 (33.3%) |
| Generated tests (seed requirements) | 206 | 66 |
| Invalid generated tests (fail on clean simulator) | 0 | 0 |
| Supplementary: all generated tests (seed + natural v1 + natural v2) | 2/15 (511 tests) | 2/15 (258 tests) |
| Supplementary: natural-v2 tests alone | 2/15 (100 tests) | 1/15 (81 tests) |

Both generated suites catch the same two bugs: `session_reentry_keeps_unlock` and `write_range_upper_bound_exclusive`. The gold suite catches those two plus `ecu_reset_keeps_session`, `multi_did_read_dedups_repeats` and `routine_restart_after_stop_blocked`.

### The 13 missed v2 bugs and why (generated suite; the report's static trigger analysis)

**11 bugs: no generated test applies the stimulus.**

- `s3_restart_skipped_on_negative_response`: no test answers an NRC in a non-default session and then waits so that S3 is exceeded only when counted from the last positive request.
- `seed_request_keeps_stale_pending_seed`: no test requests a seed twice for one level before sending a key.
- `key_compare_prefix_only`: no test sends a key with the right first two bytes and a wrong tail.
- `lockout_counter_pooled_across_levels`: no test sends wrong keys at two levels that together reach the attempt limit.
- `nrc_order_range_before_security`: no test writes an out-of-range value of correct length while security is locked.
- `nrc_order_nvm_fault_before_group_check`: no test clears an unknown DTC group (0x14) while the NVM write fault is set.
- `read_dtc_trailing_bytes_accepted`: no test sends `19 02` with more than one byte after the sub-function.
- `routine_option_record_overlong_accepted`: no test starts a routine with an over-long option record.
- `multi_did_read_dedups_repeats`: no test reads one DID several times in one `0x22` request (gold catches it).
- `routine_restart_after_stop_blocked`: no test starts a routine again after stopping it (gold catches it).
- `suppressed_seed_request_not_stored`: no test sends a suppressed seed request (`27 81` / `27 83`) and then a key for that level.

**2 bugs: tests apply the stimulus but cannot see the bug.**

- `s3_timeout_resets_lockout_counters`: 12 mock tests (1 ollama test) reach a lockout, let S3 expire and request a seed, but no expected response differs when the bug is on.
- `ecu_reset_keeps_session`: 13 mock tests (2 ollama tests) send a reset from a non-default session and then another request, with the same result. Gold catches this bug.

Applying a stimulus does not mean checking the one response that exposes the defect.

## Honest interpretation (condensed from outputs/partC/interpretation.md)

Written after the numbers existed; no number was edited by hand.

- **Bug detection on fresh bugs is low and the model did not change it.** 2/15 in both modes. The model-driven suite is smaller (66 vs 206 tests) and catches the same two bugs. The limit is which stimuli the templates can produce, not which templates get selected.
- **The v1 jump was not evidence.** On the seen v1 bugs the mock's generated suite went from 3/12 to 10/12 after the new templates, but they were designed against exactly those misses. On 15 bugs it had never seen, the same suite catches 2.
- **Gold beats generated here (5 vs 2).** A short hand-written set that checks different things found more than a much larger generated one.
- **On seen bugs the model's smaller suite is worse** (held-out v1 5/12 vs 10/12 for mock; in-sample 19/26 vs 25/26). This is context only, since those sets are seen.
- **Requirement understanding: the model is clearly better than the mock on fresh data.** This reverses the Part B result on the seen v1 test split, where the mock was at least as good. The model finds many more targets (recall 0.796 vs 0.225); the mock's keyword rules produced nothing for 7 of 16 requirements (6 without the empty-label row), because they were written by the people who wrote the v1 requirements and do well only on that phrasing.
- **But the model invents targets**: 30 false positives on v2 (25 services, 5 DIDs) against none for the mock. The mock never invents a target, but finds under a quarter of them.
- **The precision fix did not work.** Ollama's parsed precision is 0.565 on v2 and 0.500 on the seen v1 test split, against 0.512 before Part C. 25 of the 30 v2 false positives are services (for example 0x2E 5 times, 0x22 4 times; 0x10, 0x14, 0x3E and 0x31 3 times each); 17 of 21 on the v1 test split. The grounding check covers DIDs, routines and DTCs only, deliberately, so it could not touch most of the problem. The one attributable gain is that the copied example DID (0x0140) appears once among the v1 test-split extras, against three requirements in Part B.
- **Rejected planner choices rose and normalisation never fired.** 15 rejections across the 35 old requirements (10 before) and 12 on v2. The validator rejected every one, so no invalid test was kept. Normalisation fired 0 times in any run: the model no longer produced the `(category)` suffix it handles. The remaining rejections are invented template names, option numbers out of range, and options not in the shortlist. It is a harmless safeguard with no measurable effect here.
- **Explain batching worked.** 1.00 LLM call per requirement and mean latency 21.37 s (p95 28.52 s) against 30.79 s (43.41 s). There were 62 fallback events in the ollama report (18, 11 and 11 on the three v2 runs); none were fallbacks to the mock model. The ones inspected were the batched explain noticing that the reply left out some tests and using a short deterministic explanation for them. No truncation events and no JSON failures.
- **Provenance and freeze.** Byte provenance passed on every generated test in both modes and all three noise runs (511/511 mock, 418/418 ollama), so no model-written byte reached any test. Every recorded Part C freeze hash matches and is clean.

### What would help next

1. Generate the stimuli behind the 11 unapplied v2 bugs. Any template built from this list makes v2 seen, so a v3 bug set and v3 requirement set must be written blind to measure it.
2. Make generated tests check the response that exposes a defect after the stimulus (the two applied-but-undetected bugs).
3. Add a service-level check to parsing (each parsed service justified by a keyword or retrieved evidence) for the false positives. Not built or measured.
4. Repeat the model run on a larger fresh requirement set, and with a larger model.

## Rejections, fallback and latency

| | mock | ollama |
|---|---|---|
| Planner choices rejected (15 seed + 20 natural v1) | 0 | 15 |
| Planner choices rejected, natural v2 (16, FRESH) | 0 | 12 |
| Explain LLM calls per requirement, mean (min-max) | 0.89 (0-1) | 1.00 (1-1) |
| Latency per requirement, mean / p95 (35 requirements) | 0.27 s / 0.46 s | 21.37 s / 28.52 s |
| Fallback events (all runs) | - | 62 (none to the mock model) |

Runtime of the whole evaluation: 1854.37 s (about 31 minutes): ollama 1782.2 s (generation 318.9 s, requirement understanding 429.0 s, natural v2 347.6 s, two extra noise runs 340.6 s and 335.0 s), mock 45.7 s. The GPU was an RTX 3050 Laptop (4 GB).

## Retrieval: BM25 vs Chroma (bge-small-en-v1.5 via fastembed)

19 of 20 natural v1 requirements scored (NAT-020 has no target). Relevant chunk = the spec chunk carrying the target DID/routine, or the standard `svc-<sid>` chunk for service-only targets. This table is from the current report; it differs from the Part B report for BM25 (test split hit@1 27.3% here, 36.4% there). A likely cause, not confirmed by an ablation: the behaviour contract (part of the `project` search collection) grew from about 10,000 to 17,500 characters in Part C, with the same 24 sections, so each chunk is longer and BM25 rankings shift.

| split | backend | queries | hit@1 | hit@3 | MRR | citation validity (top 3) |
|---|---|---|---|---|---|---|
| dev | bm25 | 8 | 0.0% | 37.5% | 0.275 | 100.0% |
| dev | chroma | 8 | 0.0% | 75.0% | 0.374 | 100.0% |
| **test** | **bm25** | 11 | 27.3% | 63.6% | 0.506 | 100.0% |
| **test** | **chroma** | 11 | 18.2% | 63.6% | 0.458 | 100.0% |
| all | bm25 | 19 | 15.8% | 52.6% | 0.408 | 100.0% |
| all | chroma | 19 | 10.5% | 68.4% | 0.422 | 100.0% |

Neither backend is clearly better on 19 queries, so the default stays BM25. End-to-end test generation with `RETRIEVER=chroma` was never measured.

## What the numbers mean

- **Held-out v2 2/15 is the real detection number.** Those 15 bugs were written by a subagent that could not see the templates, gold tests, eval, LLM or agent code, after the Part C freeze, and nothing was changed after seeing the results.
- **The LLM does not change what the templates can do.** The same templates sit behind both modes, which is why detection is equal on v2.
- **The v1 and in-sample numbers are not evidence of general coverage.** v1 is SEEN and in-sample is tuned-on.
- **Self-consistency is circular.** Generated tests pass on the clean simulator, but their expected bytes come from the rules engine. Rows 3 to 5 (agreement 5000/5000, gold 60/60, udsoncan PASS) are the independent-ish evidence, and even they share an author; the udsoncan sequence is the only third-party check and it covers one happy path.
- **Gold and generated suites miss different bugs.**

## Limitations

- **Small samples.** 15 bugs and 16 requirements: one bug is 6.7 points, one requirement 6.25 points on exact match. Differences of one or two items are within what chance can produce.
- **One model, one prompt set.** Only `qwen2.5:3b-instruct-q4_K_M` was tested, with prompts tuned on 8 dev rows in Part B. A larger model or context was not tested. Ollama noise was measured over three runs only.
- **Synthetic spec.** A fictional BCM, not a real OEM document. The v2 bugs are realistic but written by a language model, so they are not real ECU defects.
- **The v1 sets are seen.** Their results are context, not evidence of improvement.
- **Oracle vs AUTOSAR.** SWS disagreements D1, D3, D4, D8 and D9 are still open ([SWS_DISAGREEMENTS.md](SWS_DISAGREEMENTS.md)); D2, D5, D6 and D7 were fixed in Part C (rules engine, contract, independent simulator, one hand-updated gold test, agreement 100% on two seeds).
- **Same author on both sides.** The simulator, rules engine and gold tests share one prose contract, so shared misreadings are possible.
- **CAPL is unverified.** The `.can` exports were never compiled or run in CANoe.
- **UI not clicked through in a real browser.** Only headless AppTest runs exist; the manual checklist is [UI_CHECKLIST.md](UI_CHECKLIST.md).
- **Citation validity** means each citation points at a retrieved chunk; it does not prove the chunk justifies the test.
- **Timing** is in-process wall-clock; P2/P2* overruns are only warnings.
