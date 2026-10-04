# Results (honest one-page summary, after Part D)

Source of every number: [outputs/eval_report.md](../outputs/eval_report.md) and `outputs/eval_report.json` (report version 5, generated 2026-10-04T08:15:23Z, git `1f0c293`, template set `v3` with 27 templates plus the conformance sweep, Bm25Retriever, LangGraph engine). One invocation (`python -m uds_assistant.eval.run_eval --mode ollama --noise-runs 3 --before-after`) ran **both** `mock` and `ollama` on the same inputs, templates, sweep and retriever. The before/after table is [outputs/partD/before_after.md](../outputs/partD/before_after.md); the written interpretation is [outputs/partD/interpretation.md](../outputs/partD/interpretation.md). Numbers were copied, not rounded up. Part C's results are in [outputs/partC/](../outputs/partC/).

> The ECU spec is **synthetic** (a fictional Body Control Module written for this project). Every number below is measured against the project's own simulator, not a real ECU.

**Headline (fresh v3 data, written blind after the Part D freeze, nothing tuned on it).**

1. **Bug detection on fresh bugs: 10/15 (66.7%) with mock and 9/15 (60.0%) with ollama** for the system's full output (requirement-driven tests plus the conformance sweep). Almost all of that comes from the sweep: the requirement-driven tests alone catch 4/15 (mock) and 2/15 (ollama), the sweep alone 9/15 in both modes, gold 3/15. The Part C headline (2/15) was on a different bug set.
2. **Requirement understanding on natural v3 is better with the model than with the mock**: parsed F1 0.609 vs 0.407, category recall 70.0% vs 42.0%, precondition recall 89.7% vs 48.3% (ollama; identical in all three runs). Ollama's precision is only 0.596 (19 false positives: 15 services, 4 DIDs); the mock's precision is 0.857 but its recall is 0.267.
3. **Rejected planner choices fell to 0** on every set (15 and 12 in Part C), and ollama had 0 truncation events.
4. **The service-precision problem is reduced on seen sets, not solved on fresh data**: v2 false positives went from 30 to 9 and the v1 test split from 21 to 9, but those sets were read when the fix was designed. On fresh v3 precision is 0.596 (0.565 on v2 in Part C, a different set).

Everything marked **SEEN** or **in-sample** below is not independent evidence.

## Headline table

| Metric | mock | ollama |
|---|---|---|
| **1. Held-out v3 bugs, FRESH (15): FULL OUTPUT = requirement-driven + sweep** | **10/15 (66.7%)** | **9/15 (60.0%)** |
| 1a. requirement-driven only (the Part C "generated" suite) | 4/15 (26.7%) | 2/15 (13.3%) |
| 1b. conformance sweep alone (LLM-independent) | 9/15 (60.0%) | 9/15 (60.0%) |
| 1c. gold (LLM-independent) | 3/15 (20.0%) | 3/15 (20.0%) |
| Suite sizes (requirement-driven / sweep / full output) | 206 / 1200 / 1406 | 73 / 1200 / 1273 |
| **2a. Natural v3, FRESH (test3, n=16): parsed exact** | 1/16 | 2/16 |
| **2b. Natural v3, FRESH: parsed P / R / F1** | 0.857 / 0.267 / 0.407 | 0.596 / 0.622 / 0.609 (3-run mean identical) |
| **2c. Natural v3, FRESH: exercised F1** | 0.342 | 0.472 (3-run mean 0.465, range 0.462-0.472) |
| **2d. Natural v3, FRESH: category recall (micro)** | 42.0% | 70.0% (3 runs identical) |
| **2e. Natural v3, FRESH: precondition recall (micro)** | 48.3% | 89.7% (3 runs identical) |
| 2f. Natural v3: false positives / false negatives by kind | FP service 2; FN service 24, did 8, routine 1 | FP service 15, did 4; FN service 9, did 5, routine 3 |
| 2g. Natural v3: rejected planner choices | 0 | 0 |
| 3. Simulator <-> rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 4. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 5. udsoncan virtual-CAN sequence | PASS | same (LLM-independent) |
| 6. Conformance sweep: tests passing on the clean simulator; byte provenance | 1200/1200; 1200/1200 | same (LLM-independent) |
| 7. Coverage (seed requirements; tests per category) | positive 43, negative 77, session 25, security 30, timing 31; 15/15 requirements with >=1 test | positive 26, negative 27, session 4, security 7, timing 9; 15/15 |
| 8. Citation validity | 967/967 (100.0%) | 353/353 (100.0%) |
| Byte provenance, all generated tests, all runs | 613/613 | 552/552 |
| **SEEN** Held-out v2 bugs (15): requirement-driven / sweep / full / gold | 2 / 9 / 9 / 5 of 15 | 2 / 9 / 9 / 5 of 15 |
| **SEEN** Natural v2 (n=16): parsed exact; P / R / F1 | 0/16; 1.000 / 0.225 / 0.367 | 4/16; 0.808 / 0.775 / 0.792 |
| **SEEN** Held-out v1 bugs (12): requirement-driven / sweep / full / gold | 10 / 10 / 12 / 3 of 12 | 8 / 10 / 11 / 3 of 12 |
| **SEEN** Natural v1 test split (n=12): parsed exact; P / R / F1 | 5/12; 0.933 / 0.560 / 0.700 | 5/12; 0.690 / 0.800 / 0.741 |
| **In-sample (tuned on)** 26 bugs: requirement-driven / sweep / full / gold | 25 / 26 / 26 / 24 of 26 | 21 / 26 / 26 / 24 of 26 |

Rows 1 and 2 are the headline. The natural v1 dev split (n=8) is what the prompts were tuned on: mock parsed exact 4/8 (F1 0.828), ollama 5/8 (F1 0.839).

## Before / after Part D

From `outputs/partD/before_after.md`. Before = the frozen Part C final report (commit `942f438`); after = this report. The v3 rows have no "before" because the data did not exist; v2 is seen, so its rows are context.

| Metric | mock before | mock after | ollama before | ollama after |
|---|---|---|---|---|
| **Held-out v3, FRESH (15): full output** | n/a | 10/15 | n/a | 9/15 |
| Held-out v3, FRESH: requirement-driven / sweep / gold | n/a | 4 / 9 / 3 | n/a | 2 / 9 / 3 |
| **Natural v3, FRESH (n=16): parsed P / R / F1** | n/a | 0.857 / 0.267 / 0.407 | n/a | 0.596 / 0.622 / 0.609 |
| Natural v3, FRESH: exercised F1; category; precondition | n/a | 0.342; 42.0%; 48.3% | n/a | 0.472; 70.0%; 89.7% |
| Held-out v2, SEEN (15): requirement-driven | 2/15 | 2/15 | 2/15 | 2/15 |
| Held-out v2, SEEN: full output (Part C had no sweep) | 2/15 | 9/15 | 2/15 | 9/15 |
| Natural v2, SEEN (n=16): parsed P / R / F1 | 1.000 / 0.225 / 0.367 | 1.000 / 0.225 / 0.367 | 0.565 / 0.796 / 0.661 | 0.808 / 0.775 / 0.792 |
| Natural v2, SEEN: category; precondition recall | 48.0%; 55.6% | 48.0%; 55.6% | 74.0%; 77.8% | 72.0%; 92.6% |
| Parsed false positives, natural v2 (SEEN) | none | none | service 25, did 5 | service 6, did 3 |
| Parsed false positives, natural v1 test split (SEEN) | service 1 | service 1 | service 17, did 4 | service 5, did 4 |
| Parsed false positives, natural v3 (FRESH) | n/a | service 2 | n/a | service 15, did 4 |
| Rejected planner choices, 35 old requirements (SEEN) | 0 | 0 | 15 | 0 |
| Rejected planner choices, natural v2 (SEEN) | 0 | 0 | 12 | 0 |
| Rejected planner choices, natural v3 (FRESH) | n/a | 0 | n/a | 0 |
| Latency per requirement, mean / p95 (35 requirements) | 0.27 s / 0.46 s | 0.38 s / 0.63 s | 21.37 s / 28.52 s | 21.85 s / 30.41 s |
| Explain LLM calls per requirement, mean | 0.89 | 0.89 | 1.00 | 0.97 |
| Tests: requirement-driven / full output | 206 / 206 | 206 / 1406 | 66 / 66 | 73 / 1273 |
| SWS disagreements open | 5 | 5 | 5 | 5 |

**Comparability.** (1) v3 sets differ from v1 and v2, so v3 rows are not "after" values of v2 rows. (2) v1 and v2 are seen: Part D was designed after their results were known, so their improvements (for example v2 full output 2/15 to 9/15, or ollama v2 precision 0.565 to 0.808) are not evidence of general improvement. Only v3 rows are. (3) Mock is deterministic. (4) Ollama output varies from run to run; see the noise check. (5) The sweep is the same in every mode.

## Noise check: natural v3 (fresh), ollama, 3 runs

Run 1 feeds every table above. Every run is listed; the summary is the mean and min-max range, never the best run.

| Run | Parsed P | Parsed R | Parsed F1 | Exercised F1 | Category recall | Precondition recall | Tests kept | Rejected | Fallback events | Byte provenance |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 (main tables) | 0.596 | 0.622 | 0.609 | 0.472 | 70.0% | 89.7% | 94 | 0 | 44 | 94/94 |
| 2 | 0.596 | 0.622 | 0.609 | 0.462 | 70.0% | 89.7% | 92 | 0 | 33 | 92/92 |
| 3 | 0.596 | 0.622 | 0.609 | 0.462 | 70.0% | 89.7% | 92 | 0 | 36 | 92/92 |

The mock is deterministic: a second mock run over natural v3 was identical. Parsing is identical in all three runs; the only variation is in planning and explaining (exercised F1, tests kept). Three runs is a small sample.

## Held-out v3 bug detection (15 fresh bugs)

| Suite | mock | ollama |
|---|---|---|
| **Full output (headline)** | 10/15 (66.7%) | 9/15 (60.0%) |
| (a) requirement-driven only | 4/15 | 2/15 |
| (b) conformance sweep alone | 9/15 | 9/15 |
| Gold | 3/15 | 3/15 |
| Supplementary: all generated tests (seed + natural v1, v2, v3), no sweep | 4/15 (613 tests) | 4/15 (368 tests) |
| Supplementary: natural-v3 tests alone | 4/15 (102 tests) | 2/15 (94 tests) |
| Invalid tests (fail on the clean simulator) | 0 | 0 |

**Missed by the full output.** In each case no test applies the stimulus:

- `session_switch_keeps_pending_seed`: no test requests a seed, switches session with a positive `10 xx`, then sends a key for that level.
- `lockout_expiry_resets_attempt_count`: no test reaches a lockout, waits for the delay to expire, requests a seed and sends another wrong key.
- `nrc_order_subfunction_before_length`: no test sends `10`, `11` or `3E` with an unsupported sub-function and a wrong total length.
- `read_did_speed_not_clamped`: no test reads DID 0x0140 while the vehicle speed is above 255 kph.
- `dtc_read_reports_masked_status`: no test reads DTCs where a listed DTC has status bits outside the request mask.
- ollama only: `dtc_clear_single_clears_neighbour` (the mock's larger requirement-driven suite catches it; the sweep does not).

**Found only by the sweep** (not by the requirement-driven tests): 6 bugs with mock, 7 with ollama, for example `failed_key_keeps_pending_seed`, `nrc_order_write_range_before_condition`, `routine_results_trailing_bytes_accepted`, `write_stores_value_before_range_rejection`, `s3_timeout_clears_dtc_status`, `suppressed_request_does_not_restart_s3`. The seed requirements never ask for those stimuli.

## What the conformance sweep is

A requirement-independent suite of 1200 tests built from the spec alone (no LLM, same in every mode): 54 state setups x 215 stimuli, chosen by greedy covering from 11,610 candidates. Every expected byte comes from the rules engine. Generation takes about 7 s, the clean run about 1 s, and the bug matrix over all four catalogs 85 s. All 1200 pass on the clean simulator and re-instantiate byte-identically. It is not offered to the planner. Its limit: it can only apply stimuli its setups and mutations include, which is why 5 fresh bugs were still missed.

## Honest interpretation (condensed from outputs/partD/interpretation.md)

Written after the numbers existed; no number was edited by hand.

- **Bug detection on fresh bugs is clearly better than Part C's 2/15, but the gain is the sweep, not the model.** Both modes reach 9/15 with the sweep alone; mock is one bug ahead of ollama (10 against 9) because its larger requirement-driven suite catches one more. The sweep also caught 9/15 on the seen v2 bugs, so its rate did not drop on bugs written after the freeze. Different bug sets, so this is a consistency check and not a before/after pair.
- **The model still adds little to detection.** The requirement-driven suite is smaller with ollama (73 tests, 2/15) than with mock (206 tests, 4/15).
- **Requirement understanding: the model is better than the mock on fresh data, as in Part C.** Recall 0.622 against 0.267, category recall 70.0% against 42.0%, precondition recall 89.7% against 48.3%. The mock's keyword rules produced nothing for 7 of 16 requirements.
- **Precision is still the weak point on fresh data.** 0.596, 19 false positives (15 services: `0x10` x5, `0x27` x5, `0x2E` x2, `0x22` x2, `0x11` x1; and 4 DIDs). On seen sets the false positives fell a lot (v2 30 to 9, v1 test split 21 to 9), but the changes were designed after reading those errors.
- **Recall is lower than in Part C's v2 run** (0.622 against 0.796). The sets differ, so this may be set difficulty. `0x3E` is missed in 2 requirements.
- **Rejected planner choices fell to 0** (15 and 12 in Part C), on every set including fresh v3. The likely cause is constrained decoding (only offered options can be emitted); no ablation was run.
- **Explain fallbacks.** 123 fallback events in the ollama report, all the batched explain step leaving out some test ids and a short deterministic explanation being used; none were fallbacks to the mock model; 0 truncation events.
- **Provenance and freeze.** Byte provenance passed on every generated test in all runs (613/613 mock, 552/552 ollama, 1200/1200 sweep), so no model-written byte reached any test. Every recorded Part D freeze hash matches and is clean.

### What would help next

1. Close the five stimuli still missed. They are known now, so any template built from them makes v3 seen; a v4 blind set is needed to measure it.
2. Improve service precision on fresh phrasing (extra `0x10`/`0x27`, missed `0x3E`).
3. Try a larger model or context; only one 3B model was tried.

## Rejections, fallback and latency

| | mock | ollama |
|---|---|---|
| Planner choices rejected (15 seed + 20 natural v1) | 0 | 0 |
| Planner choices rejected, natural v2 (SEEN) / v3 (FRESH) | 0 / 0 | 0 / 0 |
| Explain LLM calls per requirement, mean (min-max) | 0.89 (0-1) | 0.97 (0-1) |
| Latency per requirement, mean / p95 (35 requirements) | 0.38 s / 0.63 s | 21.85 s / 30.41 s |
| Latency per requirement, natural v3, mean / p95 | 0.3 s / 0.6 s | 20.8 s / 26.3 s |
| Fallback events (all runs) | 0 | 123 (all batched-explain omissions; none to the mock) |
| Truncation events | 0 | 0 |

Runtime of the whole evaluation: 2327.6 s (about 39 minutes): ollama 2125.8 s (generation 337.8 s, requirement understanding 426.8 s, natural v2 348.4 s, natural v3 332.5 s, two extra noise runs 335.6 s and 325.7 s), conformance sweep 100.9 s, mock 73.0 s. The GPU was an RTX 3050 Laptop (4 GB).

## Retrieval: BM25 vs Chroma

Re-run in this evaluation; the numbers are identical to Part C's (19 natural v1 queries scored).

| split | backend | queries | hit@1 | hit@3 | MRR |
|---|---|---|---|---|---|
| dev | bm25 | 8 | 0.0% | 37.5% | 0.275 |
| dev | chroma | 8 | 0.0% | 75.0% | 0.374 |
| **test** | **bm25** | 11 | 27.3% | 63.6% | 0.506 |
| **test** | **chroma** | 11 | 18.2% | 63.6% | 0.458 |
| all | bm25 | 19 | 15.8% | 52.6% | 0.408 |
| all | chroma | 19 | 10.5% | 68.4% | 0.422 |

Citation validity is 100.0% for both. Neither backend is clearly better, so the default stays BM25. End-to-end test generation with `RETRIEVER=chroma` was never measured.

## What the numbers mean

- **Held-out v3 9/15 to 10/15 is the real detection number.** Those 15 bugs were written by a subagent that could not see the templates, sweep, gold tests, eval, LLM or agent code, after the Part D freeze, and nothing was changed after seeing the results.
- **The sweep does most of the work and the LLM does not change what it can find.** It is identical in both modes.
- **The v1, v2 and in-sample numbers are not evidence of general coverage.** They are seen or tuned on.
- **Self-consistency is circular.** Generated and sweep tests pass on the clean simulator, but their expected bytes come from the rules engine. Rows 3 to 5 (agreement 5000/5000, gold 60/60, udsoncan PASS) are the independent-ish evidence, and even they share an author; the udsoncan sequence is the only third-party check and covers one happy path.

## Limitations

- **Small samples.** 15 bugs and 16 requirements: one bug is 6.7 points, one requirement 6.25 points on exact match. A one-bug difference between modes is not evidence of a difference.
- **One model, one prompt set.** Only `qwen2.5:3b-instruct-q4_K_M`, prompts tuned on 8 dev rows. Ollama noise was measured over three runs only.
- **Synthetic spec.** A fictional BCM, not a real OEM document. The v3 bugs are realistic but were written by a language model, not real ECU defects.
- **The sweep shares the oracle.** Its expected bytes come from the rules engine; a misreading shared by the engine and the simulator is invisible to it.
- **The v1 and v2 sets are seen.** Their results are context, not evidence of improvement.
- **Oracle vs AUTOSAR.** SWS disagreements D1, D3, D4, D8 and D9 are still open ([SWS_DISAGREEMENTS.md](SWS_DISAGREEMENTS.md)).
- **CAPL is unverified.** The `.can` exports were never compiled or run in CANoe.
- **UI not clicked through in a real browser.** Only headless AppTest runs exist; the manual checklist is [UI_CHECKLIST.md](UI_CHECKLIST.md).
- **Citation validity** means each citation points at a retrieved chunk; it does not prove the chunk justifies the test.
- **Timing** is in-process wall-clock; P2/P2* overruns are only warnings.
