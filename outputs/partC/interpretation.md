## Interpretation (Part C, fresh v2 data): what improved, what didn't, and why

All numbers are from this run of `python -m uds_assistant.eval.run_eval --mode ollama --noise-runs 3 --before-after`, with mock and the local Qwen2.5-3B model on the same data. The v2 sets are fresh: 15 bugs and 16 requirements, each written blind by a subagent after the Part C freeze, and nothing was changed after their results were seen. The v1 sets were seen and are shown only for context.

### Summary

1. **Bug detection on fresh bugs is low and did not improve with the model: 2/15 (13.3%) for the generated suite in both modes.** The gold suite catches 5/15, and the union is 5/15. Both modes catch the same two bugs, `session_reentry_keeps_unlock` and `write_range_upper_bound_exclusive`.
2. **Requirement understanding on fresh requirements is clearly better with the model than with the mock.** This reverses the Part B result on the seen v1 test split, where the mock was at least as good.
3. **The precision fix did not work.** Ollama's parsed precision is 0.565 on v2 and 0.500 on the seen v1 test split, against 0.512 before Part C. Most false positives are services, which the new identifier check deliberately does not cover.
4. **The explain batching worked.** It uses 1.00 LLM call per requirement instead of 4.51, and mean latency fell from 30.8 s to 21.4 s.

### Held-out v2 bug detection (15 bugs, fresh): the headline

| Suite | mock | ollama |
|---|---|---|
| Generated (tests from the 15 seed requirements) | 2/15 (13.3%) | 2/15 (13.3%) |
| Gold | 5/15 (33.3%) | 5/15 (33.3%) |
| Union | 5/15 (33.3%) | 5/15 (33.3%) |
| Generated tests in the suite | 206 | 66 |

- **The coverage templates written in C3 did not transfer.** On the seen v1 bugs, the mock's generated suite went from 3/12 to 10/12 after those templates were added, but they were designed against exactly those misses. On 15 bugs it had never seen, the same suite catches 2. The v1 jump measured how well the templates fit known misses. It was not evidence of general coverage, which is why v2 was written.
- **Why the 13 missed bugs were missed.** The report's trigger analysis gives one reason for each, and the pattern is one of two causes:
  - **No generated test applies the stimulus (11 bugs).** For example: requesting a seed twice for one level before sending a key; sending a key whose first two bytes are right and tail is wrong; sending wrong keys at two levels that together reach the limit; an out-of-range write with security still locked; clearing an unknown DTC group while the NVM fault is set; `19 02` with extra bytes; a routine start with an over-long option record; reading one DID several times in one request; restarting a routine after stopping it; a suppressed seed request followed by a key; and an NRC-only exchange followed by an S3 wait.
  - **Tests apply the stimulus but cannot see the bug (2 bugs).** For `s3_timeout_resets_lockout_counters`, 12 generated tests reach a lockout, let S3 expire and request a seed, but none of their expected responses differs when the bug is on. For `ecu_reset_keeps_session`, 13 tests send a reset from a non-default session and then another request, with the same result. The gold suite does catch `ecu_reset_keeps_session`. The trigger analysis is necessary, not sufficient: applying a stimulus does not mean checking the one response that exposes the defect.
- **Gold beats generated here (5 against 2).** The three extra bugs it catches are `multi_did_read_dedups_repeats`, `routine_restart_after_stop_blocked` and `ecu_reset_keeps_session`. A short hand-written set that checks different things found more than a much larger generated one.
- **The model did not change this number.** The model-driven suite is smaller (66 tests against 206) and still catches the same two bugs. The limit is which stimuli the templates can produce, not which templates get selected.
- **On seen bugs the model's smaller suite is worse.** On held-out v1, generated detection is 5/12 for ollama and 10/12 for mock. In-sample, it is 19/26 against 25/26. Smaller, more selective plans skip checks that a catalog of known bugs happens to need. These sets are seen, so this is context and not a headline.

### Requirement understanding on natural v2 (16 requirements, fresh): the headline

| Metric | mock | ollama (run 1) | ollama mean over 3 runs (min–max) |
|---|---|---|---|
| Parsed targets, exact match | 0/16 | 4/16 | – |
| Parsed precision / recall / F1 | 1.000 / 0.225 / 0.367 | 0.565 / 0.796 / 0.661 | 0.565 / 0.796 / 0.661 (0.661–0.661) |
| Exercised F1 | 0.450 | 0.583 | 0.602 (0.583–0.611) |
| Category recall (micro) | 48.0% | 74.0% | 75.3% (74.0%–76.0%) |
| Precondition recall (micro) | 55.6% | 77.8% | 82.7% (77.8%–85.2%) |
| Produced nothing or fell back | 7 (6 without the empty-label row) | – | – |

- **Where the model helps.** It finds many more of the targets (recall 0.796 against 0.225) and its generated tests cover more of the required categories and preconditions. The mock's keyword rules produced nothing for 7 of 16 requirements. They were written by the same people who wrote and labelled the v1 requirements, so they do well on that phrasing and poorly on unfamiliar phrasing.
- **Where it hurts.** The model adds targets that are not in the labels: 30 false positives on v2, against none for the mock. The mock never invents a target, but it finds under a quarter of them.
- **Noise.** All three runs gave identical parsed numbers (0.565 / 0.796 / 0.661). Parse runs at temperature 0 with a fixed seed, and this time showed no variation. The variation is in planning and explaining: exercised F1 from 0.583 to 0.611, category recall from 74.0% to 76.0%, and precondition recall from 77.8% to 85.2%. The ±0.05 F1 seen on dev during Part B tuning did not show up here, but three runs is a small sample, and the GPU is not guaranteed to repeat exactly. Quote the means and ranges, not the best run.
- **Small sample.** With 16 requirements, one requirement moves the exact-match rate by 6.25 points. Ambiguous and unsupported rows are included.

### Precision: why the fix did not work

- **Services dominate the false positives.** On v2, 25 of the 30 false positives are services (such as 0x2E 5 times, 0x22 4 times, and 0x10, 0x14, 0x3E and 0x31 3 times each), and only 5 are DIDs. On the seen v1 test split, 17 of 21 are services and 4 are DIDs.
- **The grounding check covers DIDs, routines and DTCs only.** That was deliberate in C1, because services and sessions are implied by wording and cannot be checked against the text the same way. It therefore could not touch most of the problem.
- **What did change.** The example DID that used to be copied now appears once among the v1 test-split extras (DID 0x0140), against three requirements in Part B. That is the only improvement I can attribute to the prompt and grounding changes, and it is small.
- **Next fix.** A service-level check, for example requiring each parsed service to be justified by a keyword or by the retrieved evidence, is the obvious next step. It has not been built or measured.

### Planner choices and the normalisation fix

- **Rejected planner choices went up, not down.** Ollama had 15 rejections across the 15 seed and 20 natural v1 requirements (10 before), and 12 on the 16 v2 requirements. The validator rejected every one, so no invalid test was kept.
- **The new normalisation never fired.** There were 0 normalisations in any run. The model no longer produced the `(category)` suffix that the fix handles. The remaining rejections are invented template names, option numbers outside a template's range, and options that were not in the offered shortlist. The normalisation is a harmless safeguard here and has no measurable effect on this data.

### Explain batching and the fallback events

- **Latency.** Mean per requirement fell from 30.79 s to 21.37 s, and p95 from 43.41 s to 28.52 s, on the same 35 requirements as the baseline.
- **Calls.** Explain makes exactly 1 LLM call per requirement (0 to 8 before, derived from tests kept). Mock is unchanged.
- **Fallback events.** There were 62 in the ollama report (18, 11 and 11 on the three v2 runs). None were fallbacks to the mock model. All of the ones I inspected were the batched explain step noticing that the model's reply left out some tests, and using a short deterministic explanation for them. The full text is quoted in the report. There were no truncation events and no JSON failures.

### Freeze and provenance

- Every recorded Part C freeze hash matches and is clean.
- Byte provenance passed on every generated test, in both modes and in all three noise runs: 418/418 for ollama and 511/511 for mock. No model-written bytes reached any final test.

### Caveats

- **Sample sizes.** 15 bugs and 16 requirements. Differences of one or two items are within what chance can produce.
- **One model, one prompt set.** Only Qwen2.5-3B was tested, with prompts tuned on 8 dev rows in Part B.
- **Synthetic setting.** The ECU spec is synthetic, and the v2 bugs are realistic but invented by a language model, so they are not real ECU defects.
- **The v1 sets are seen.** Their results appear in the report but are not evidence of improvement.
- **Five SWS disagreements remain open** (D1, D3, D4, D8, D9).

### What would help next

1. Generate the stimuli behind the 11 unapplied v2 bugs. Any templates built from this list make v2 seen, so a v3 bug set and a v3 requirement set must be written blind to measure them.
2. Make generated tests check the response that exposes a defect after the stimulus, as in the two bugs that were applied but not detected.
3. Add a service-level check to parsing to deal with the false positives.
4. Repeat the model run on a larger fresh requirement set.
