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
