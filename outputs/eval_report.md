# Evaluation report — UDS test generation assistant

- **Generated:** 2026-10-03T20:49:18.726723+00:00 (git `c669e1e1080b873361f0211b01e85f4d14f2cfd5`, uncommitted changes present)
- **LLM mode used:** `ollama` (requested `ollama`)
- **Modes evaluated in this invocation:** `mock`, `ollama`
- **Agent engine:** `langgraph` · **Retriever:** `Bm25Retriever`
- **Template set:** `v3` (27 templates)
- **Inputs:** 15 seed requirements, 20 labelled natural v1 + 16 natural v2 requirements, 60 gold tests, 15 held-out v2 (fresh) + 12 held-out v1 (seen) + 26 in-sample injectable simulator bugs
- **Ollama settings:** model `qwen2.5:3b-instruct-q4_K_M`, num_ctx 4096, temperature 0, keep_alive `10m`
- **Byte provenance:** all generated tests re-instantiate byte-identically from their templates

> **The ECU spec is synthetic.** `data/bcm_spec.yaml` describes a fictional Body Control Module written for this project in an OEM-like style; no real OEM document or ISO 14229 text is used. All numbers below are measured against the project's own simulator.
>
> **Modes:** `mock` is a deterministic keyword/rule stand-in; `ollama` is the local Qwen2.5-3B model. Both columns come from this single invocation, on the same inputs, templates and retriever. LLM-independent rows are identical for both.

> **Template set v3:** v2 + 4 generic templates (malformed 0x22 lengths, seed request while unlocked, routine status across session change / ECU reset, written DID value byte order + retention across S3 timeout / ECU reset) and new parameter variants of 3 templates (lockout + ECU reset, precondition failing while locked, routine start with the suppress bit). Added in Part C3 from the static stimulus analysis of the held-out v1 misses, so v1 held-out numbers after v3 are 'seen'; only fresh held-out sets measure v3 fairly.

## Headline metrics

| Metric | mock | ollama |
|---|---|---|
| **1. NEW HEADLINE — Held-out v2 bug detection (15 fresh bugs; generated suite = tests from the 15 seed requirements)** | **generated 2/15 (13.3%)** · gold 5/15 (33.3%) · union 5/15 (33.3%) | **generated 2/15 (13.3%)** · gold 5/15 (33.3%) · union 5/15 (33.3%) |
| 1b. supplementary (not comparable to the headline): v2 bugs detected by other suites | all generated tests (seed + natural v1 + natural v2) 2/15 (13.3%), 511 tests; natural-v2 tests alone 2/15 (13.3%), 100 tests | all generated tests (seed + natural v1 + natural v2) 2/15 (13.3%), 258 tests; natural-v2 tests alone 1/15 (6.7%), 81 tests |
| **2. NEW HEADLINE — Requirement understanding, natural v2 (split test2, fresh)** | test2 (n=16): parsed exact 0/16, P/R/F1 1.000/0.225/0.367; exercised exact 0/16, F1 0.450; category recall 48.0% micro / 48.9% macro; precondition recall 55.6% micro / 53.8% macro; fallback/nothing 7/16 (6 excl. empty-label rows) | test2 (n=16): parsed exact 4/16, P/R/F1 0.565/0.796/0.661; exercised exact 1/16, F1 0.583; category recall 74.0% micro / 74.6% macro; precondition recall 77.8% micro / 80.8% macro; fallback/nothing 0/16 (0 excl. empty-label rows) |
| 3. Simulator ↔ rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 4. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 5. udsoncan virtual-CAN sequence (session → seed/key → read → write → read-back) | PASS | same (LLM-independent) |
| 6. Coverage (seed requirements; tests per category) | positive 43, negative 77, session 25, security 30, timing 31; requirements with ≥1 test 15/15 (100.0%) | positive 26, negative 18, session 9, security 9, timing 4; requirements with ≥1 test 15/15 (100.0%) |
| 7. Citation validity | 967/967 (100.0%) | 315/315 (100.0%) |
| 8. Held-out v1 bug detection (12 bugs) — **seen (templates designed against these misses)** | generated 10/12 (83.3%) · gold 3/12 (25.0%) · union 11/12 (91.7%) | generated 5/12 (41.7%) · gold 3/12 (25.0%) · union 6/12 (50.0%) |
| 9. Requirement understanding, natural v1 test split — **seen** | test split (n=12): parsed exact 5/12, P/R/F1 0.933/0.560/0.700; exercised exact 2/12, F1 0.425; category recall 67.9% micro / 69.7% macro; precondition recall 80.0% micro / 75.0% macro; fallback/nothing 3/12 (2 excl. empty-label rows) | test split (n=12): parsed exact 3/12, P/R/F1 0.500/0.840/0.627; exercised exact 0/12, F1 0.416; category recall 82.1% micro / 84.1% macro; precondition recall 73.3% micro / 75.0% macro; fallback/nothing 0/12 (0 excl. empty-label rows) |
| 10. Requirement understanding, natural v1 dev split — **dev (tuned on)** | dev split (n=8): parsed exact 4/8, P/R/F1 1.000/0.706/0.828; exercised exact 0/8, F1 0.471; category recall 68.2% micro / 63.5% macro; precondition recall 100.0% micro / 100.0% macro; fallback/nothing 1/8 (1 excl. empty-label rows) | dev split (n=8): parsed exact 2/8, P/R/F1 0.619/0.765/0.684; exercised exact 0/8, F1 0.500; category recall 72.7% micro / 74.0% macro; precondition recall 100.0% micro / 100.0% macro; fallback/nothing 0/8 (0 excl. empty-label rows) |
| 11. In-sample bug detection (26 bugs) — **in-sample (templates tuned on these)** | generated 25/26 (96.2%) · gold 24/26 (92.3%) · union 26/26 (100.0%) | generated 19/26 (73.1%) · gold 24/26 (92.3%) · union 26/26 (100.0%) |

Rows 1-2 are the NEW HEADLINE: both data sets were written blind, after the Part C freeze, and nothing was tuned on them. Rows 3-5 and the gold figures in rows 1, 8 and 11 do not depend on the LLM; everything else is measured per mode. Rows 8-11 are labelled because their data was seen or tuned on: held-out v1 results shaped the template set, the natural v1 dev split shaped the prompts, and the 26 in-sample bugs shaped templates v2. The self-consistency check (expected responses vs the oracle that produced them) is in the appendix.

## Interpretation: where the LLM helped and where it didn't

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

_Written after reading the measured numbers in this report (source `outputs/partC/interpretation.md`); no number was edited by hand._

## Noise check — natural v2 (fresh), run-to-run variation

### mode=mock: 1 run(s) over the 16 natural-v2 requirements (requested 3)

| Run | Parsed P | Parsed R | Parsed F1 | Exercised F1 | Category recall (micro) | Precondition recall (micro) | Tests kept | Rejected choices | Fallback events | Byte provenance |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 (used for the main tables) | 1.000 | 0.225 | 0.367 | 0.450 | 48.0% | 55.6% | 100 | 0 | 0 | 100/100 |
| **mean (min–max) over all runs** | 1.000 (1.000–1.000) | 0.225 (0.225–0.225) | 0.367 (0.367–0.367) | 0.450 (0.450–0.450) | 48.0% (48.0%–48.0%) | 55.6% (55.6%–55.6%) | 100 (100–100) | 0 (0–0) | 0 (0–0) | - |

_mock is deterministic (keyword rules, no sampling), so it was run once for the tables; a second run was compared for equality as a check._

Determinism check: a second `mock` run over natural v2 was identical = **True** (compared: parsed requirement, status and every kept test's template, parameters and steps, over all natural-v2 requirements).

### mode=ollama: 3 run(s) over the 16 natural-v2 requirements (requested 3)

| Run | Parsed P | Parsed R | Parsed F1 | Exercised F1 | Category recall (micro) | Precondition recall (micro) | Tests kept | Rejected choices | Fallback events | Byte provenance |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 (used for the main tables) | 0.565 | 0.796 | 0.661 | 0.583 | 74.0% | 77.8% | 81 | 12 | 18 | 81/81 |
| 2 (extra) | 0.565 | 0.796 | 0.661 | 0.611 | 76.0% | 85.2% | 80 | 8 | 11 | 80/80 |
| 3 (extra) | 0.565 | 0.796 | 0.661 | 0.611 | 76.0% | 85.2% | 80 | 8 | 11 | 80/80 |
| **mean (min–max) over all runs** | 0.565 (0.565–0.565) | 0.796 (0.796–0.796) | 0.661 (0.661–0.661) | 0.602 (0.583–0.611) | 75.3% (74.0%–76.0%) | 82.7% (77.8%–85.2%) | 80.33 (80–81) | 9.33 (8–12) | 13.33 (11–18) | - |

_Run 1 is the run used for every main table. Every run is listed; the summary is the mean and the min-max range over all runs, never the best run._

## Mock vs Ollama — side by side

### Requirement understanding — natural v2 (split test2): NEW HEADLINE, fresh

Natural requirements from `data/requirements_natural_v2.csv`: 16 rows written blind after the Part C freeze, by a subagent that could not see the v1 set. Nothing was tuned on them. Same label schema and scoring as v1.

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 16 | 16 |
| Target exact match — parsed | 0/16 (0.0%) | 4/16 (25.0%) |
| Target exact match — exercised by kept tests | 0/16 (0.0%) | 1/16 (6.2%) |
| Parsed targets P / R / F1 (micro) | 1.000 / 0.225 / 0.367 | 0.565 / 0.796 / 0.661 |
| Parsed targets tp / fp / fn | 11 / 0 / 38 | 39 / 30 / 10 |
| Exercised targets P / R / F1 (micro) | 0.380 / 0.551 / 0.450 | 0.442 / 0.857 / 0.583 |
| Category recall micro (hit/required) / macro | 24/50 (48.0%) / 48.9% | 37/50 (74.0%) / 74.6% |
| Precondition recall micro (hit/required) / macro | 15/27 (55.6%) / 53.8% | 21/27 (77.8%) / 80.8% |
| Fallback / nothing generated | 7 (6 excl. empty-label rows) | 0 (0 excl. empty-label rows) |

Per requirement, natural v2 (misses shown):

| Req | Label targets | mock parsed exact | mock parsed miss/extra | mock tests (categories missed) | mock preconds missed | ollama parsed exact | ollama parsed miss/extra | ollama tests (categories missed) | ollama preconds missed |
|---|---|---|---|---|---|---|---|---|---|
| NAT2-001 | did:0xF187, did:0xF18C, did:0xF190, service:0x22 | no | miss did:0xF187, did:0xF18C; extra - | 18 (none missed) | - | no | miss did:0xF190; extra did:0xF186 | 8 (session missed) | - |
| NAT2-002 | did:0x0120, service:0x10, service:0x27, service:0x2E | no | miss service:0x10, service:0x27, service:0x2E; extra - | 14 (none missed) | - | no | miss did:0x0120; extra - | 4 (security missed) | - |
| NAT2-003 | did:0x0130, service:0x22, service:0x27, service:0x2E | no | miss service:0x22, service:0x27; extra - | 16 (none missed) | - | no | miss service:0x22; extra service:0x10 | 8 (none missed) | - |
| NAT2-004 | routine:0x0201, service:0x31 | no | miss service:0x31; extra - | 8 (security missed) | - | no | miss routine:0x0201; extra - | 4 (security missed) | - |
| NAT2-005 | routine:0x0203, service:0x10, service:0x27, service:0x31 | no | miss routine:0x0203, service:0x10, service:0x27, service:0x31; extra - | 0 (negative, positive, security, session, timing missed) | programming_session, security_level_3 | no | miss routine:0x0203; extra did:0x0150, service:0x11, service:0x14, service:0x22, service:0x2E, service:0x3E | 4 (negative, session missed) | programming_session, security_level_3 |
| NAT2-006 | service:0x27 | no | miss service:0x27; extra - | 0 (negative, security, timing missed) | extended_session, lockout_active | yes | miss -; extra - | 3 (negative, timing missed) | lockout_active |
| NAT2-007 | service:0x14, service:0x19 | no | miss service:0x14, service:0x19; extra - | 8 (negative missed) | - | no | miss service:0x14; extra service:0x22 | 8 (none missed) | - |
| NAT2-008 | service:0x10, service:0x22, service:0x3E | no | miss service:0x10, service:0x22, service:0x3E; extra - | 2 (negative, positive, session missed) | - | no | miss service:0x22; extra did:0xF186, service:0x27, service:0x2E, service:0x31 | 4 (session missed) | - |
| NAT2-009 | did:0x0100, service:0x10, service:0x27, service:0x2E | no | miss did:0x0100, service:0x10, service:0x27; extra - | 2 (security, timing missed) | extended_session, s3_elapsed, security_level_1 | yes | miss -; extra - | 2 (negative, security, timing missed) | extended_session, s3_elapsed, security_level_1 |
| NAT2-010 | did:0xF186, service:0x10, service:0x11, service:0x22, service:0x27 | no | miss did:0xF186, service:0x10, service:0x11, service:0x27; extra - | 1 (positive, security, session missed) | extended_session, security_level_1 | no | miss -; extra service:0x14, service:0x2E, service:0x31, service:0x3E | 8 (none missed) | - |
| NAT2-011 | service:0x3E | no | miss service:0x3E; extra - | 2 (positive missed) | - | yes | miss -; extra - | 3 (none missed) | - |
| NAT2-012 | routine:0x0202, service:0x10, service:0x27, service:0x31 | no | miss service:0x10, service:0x27, service:0x31; extra - | 19 (none missed) | - | no | miss service:0x31; extra did:0x0110, did:0x0111, service:0x22, service:0x2E | 7 (none missed) | - |
| NAT2-013 | did:0x0160, service:0x10, service:0x22, service:0x27, service:0x2E | no | miss did:0x0160, service:0x10, service:0x27, service:0x2E; extra - | 1 (positive, security, session missed) | programming_session, security_level_3 | yes | miss -; extra - | 4 (session missed) | - |
| NAT2-014 | did:0x0110, did:0x0111, service:0x22, service:0x2E | no | miss did:0x0110, did:0x0111, service:0x2E; extra - | 1 (positive, security missed) | - | no | miss service:0x2E; extra service:0x10, service:0x27 | 5 (none missed) | - |
| NAT2-015 | service:0x10, service:0x14 | no | miss service:0x10, service:0x14; extra - | 0 (negative, session missed) | programming_session | no | miss service:0x10; extra - | 4 (negative missed) | - |
| NAT2-016 | (none) | no | miss -; extra - | 8 (none missed) | - | no | miss -; extra service:0x10, service:0x11, service:0x14, service:0x22, service:0x2E, service:0x31, service:0x3E | 5 (none missed) | - |

### Requirement understanding — natural v1 TEST split: SEEN

Natural requirements from `data/requirements_natural.csv`. The template set was designed after these results, so they are no longer independent. The prompts were tuned on the 8 dev rows only.

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 12 | 12 |
| Target exact match — parsed | 5/12 (41.7%) | 3/12 (25.0%) |
| Target exact match — exercised by kept tests | 2/12 (16.7%) | 0/12 (0.0%) |
| Parsed targets P / R / F1 (micro) | 0.933 / 0.560 / 0.700 | 0.500 / 0.840 / 0.627 |
| Parsed targets tp / fp / fn | 14 / 1 / 11 | 21 / 21 / 4 |
| Exercised targets P / R / F1 (micro) | 0.290 / 0.800 / 0.425 | 0.276 / 0.840 / 0.416 |
| Category recall micro (hit/required) / macro | 19/28 (67.9%) / 69.7% | 23/28 (82.1%) / 84.1% |
| Precondition recall micro (hit/required) / macro | 12/15 (80.0%) / 75.0% | 11/15 (73.3%) / 75.0% |
| Fallback / nothing generated | 3 (2 excl. empty-label rows) | 0 (0 excl. empty-label rows) |

Per requirement, v1 test split:

| Req | Label targets | mock parsed exact | mock parsed miss/extra | mock tests (categories missed) | mock preconds missed | ollama parsed exact | ollama parsed miss/extra | ollama tests (categories missed) | ollama preconds missed |
|---|---|---|---|---|---|---|---|---|---|
| NAT-002 | did:0xF187, did:0xF18C, service:0x22 | no | miss did:0xF18C; extra - | 14 (none missed) | - | yes | miss -; extra - | 7 (none missed) | - |
| NAT-004 | service:0x10 | yes | miss -; extra - | 9 (session missed) | vehicle_stationary | no | miss -; extra service:0x27, service:0x2E | 4 (session missed) | vehicle_stationary |
| NAT-006 | did:0x0101, service:0x10, service:0x27, service:0x2E | no | miss service:0x10, service:0x27, service:0x2E; extra - | 14 (none missed) | - | yes | miss -; extra - | 7 (session missed) | - |
| NAT-008 | did:0x0131, service:0x2E | no | miss service:0x2E; extra - | 0 (negative, security missed) | extended_session, security_level_1 | no | miss -; extra service:0x22, service:0x27 | 8 (none missed) | - |
| NAT-010 | service:0x27 | yes | miss -; extra - | 3 (security, timing missed) | - | no | miss -; extra service:0x2E | 5 (none missed) | - |
| NAT-012 | routine:0x0202, service:0x31 | yes | miss -; extra - | 16 (none missed) | - | no | miss service:0x31; extra did:0x0110, did:0x0111, did:0x0140, service:0x10, service:0x27, service:0x2E | 6 (positive missed) | extended_session, security_level_1, vehicle_stationary |
| NAT-014 | service:0x19 | no | miss -; extra service:0x22 | 11 (none missed) | - | no | miss -; extra service:0x22 | 4 (none missed) | - |
| NAT-016 | did:0x0160, service:0x10, service:0x27, service:0x2E | no | miss service:0x10, service:0x27, service:0x2E; extra - | 13 (none missed) | - | yes | miss -; extra - | 8 (session missed) | - |
| NAT-017 | service:0x14, service:0x19 | no | miss service:0x14, service:0x19; extra - | 0 (negative, positive, session missed) | - | no | miss service:0x19; extra - | 4 (negative missed) | - |
| NAT-018 | did:0x0120, service:0x27, service:0x2E | no | miss service:0x27; extra - | 16 (none missed) | - | no | miss did:0x0120; extra service:0x10 | 4 (none missed) | - |
| NAT-019 | routine:0x0203, service:0x31 | yes | miss -; extra - | 19 (positive missed) | - | no | miss routine:0x0203; extra did:0x0150, service:0x10, service:0x27, service:0x2E | 4 (none missed) | - |
| NAT-020 | (none) | yes | miss -; extra - | 0 (none missed) | - | no | miss -; extra service:0x10, service:0x22, service:0x27, service:0x2E | 8 (none missed) | - |

### Requirement understanding — natural v1 dev split (dev: the rows the prompts were tuned on)

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 8 | 8 |
| Target exact match — parsed | 4/8 (50.0%) | 2/8 (25.0%) |
| Target exact match — exercised by kept tests | 0/8 (0.0%) | 0/8 (0.0%) |
| Parsed targets P / R / F1 (micro) | 1.000 / 0.706 / 0.828 | 0.619 / 0.765 / 0.684 |
| Parsed targets tp / fp / fn | 12 / 0 / 5 | 13 / 8 / 4 |
| Exercised targets P / R / F1 (micro) | 0.314 / 0.941 / 0.471 | 0.333 / 1.000 / 0.500 |
| Category recall micro (hit/required) / macro | 15/22 (68.2%) / 63.5% | 16/22 (72.7%) / 74.0% |
| Precondition recall micro (hit/required) / macro | 9/9 (100.0%) / 100.0% | 9/9 (100.0%) / 100.0% |
| Fallback / nothing generated | 1 (1 excl. empty-label rows) | 0 (0 excl. empty-label rows) |

### Requirement understanding — natural v1 all split

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 20 | 20 |
| Target exact match — parsed | 9/20 (45.0%) | 5/20 (25.0%) |
| Target exact match — exercised by kept tests | 2/20 (10.0%) | 0/20 (0.0%) |
| Parsed targets P / R / F1 (micro) | 0.963 / 0.619 / 0.754 | 0.540 / 0.809 / 0.648 |
| Parsed targets tp / fp / fn | 26 / 1 / 16 | 34 / 29 / 8 |
| Exercised targets P / R / F1 (micro) | 0.300 / 0.857 / 0.444 | 0.299 / 0.905 / 0.450 |
| Category recall micro (hit/required) / macro | 34/50 (68.0%) / 67.1% | 39/50 (78.0%) / 79.8% |
| Precondition recall micro (hit/required) / macro | 21/24 (87.5%) / 83.3% | 20/24 (83.3%) / 83.3% |
| Fallback / nothing generated | 4 (3 excl. empty-label rows) | 0 (0 excl. empty-label rows) |

Per requirement, v1 dev split:

| Req | Label targets | mock parsed exact | mock parsed miss/extra | mock tests (categories missed) | mock preconds missed | ollama parsed exact | ollama parsed miss/extra | ollama tests (categories missed) | ollama preconds missed |
|---|---|---|---|---|---|---|---|---|---|
| NAT-001 | did:0xF190, service:0x22 | yes | miss -; extra - | 18 (none missed) | - | no | miss did:0xF190; extra service:0x10 | 5 (none missed) | - |
| NAT-003 | service:0x10 | no | miss service:0x10; extra - | 0 (positive, session missed) | - | no | miss -; extra did:0xF186, service:0x27, service:0x2E, service:0x31, service:0x3E | 8 (session missed) | - |
| NAT-005 | did:0x0100, service:0x10, service:0x27, service:0x2E | no | miss service:0x10; extra - | 18 (none missed) | - | no | miss service:0x10, service:0x27; extra - | 7 (security missed) | - |
| NAT-007 | did:0x0130, service:0x2E | no | miss service:0x2E; extra - | 7 (security missed) | - | yes | miss -; extra - | 4 (security missed) | - |
| NAT-009 | did:0x0150, service:0x10, service:0x27, service:0x2E | no | miss service:0x10, service:0x27; extra - | 20 (none missed) | - | yes | miss -; extra - | 5 (negative missed) | - |
| NAT-011 | routine:0x0201, service:0x31 | yes | miss -; extra - | 12 (security missed) | - | no | miss routine:0x0201; extra - | 4 (security missed) | - |
| NAT-013 | service:0x11 | yes | miss -; extra - | 6 (positive missed) | - | no | miss -; extra did:0x0150 | 5 (none missed) | - |
| NAT-015 | service:0x3E | yes | miss -; extra - | 9 (session, timing missed) | - | no | miss -; extra did:0xF186 | 4 (session missed) | - |

### Held-out v2 bug detection (15 FRESH bugs) — NEW HEADLINE: generated suite, gold, union

"Generated suite" = tests generated from the 15 seed requirements, exactly as for the v1 headline, so numbers are comparable. The last three rows are supplementary and use other test sets.

| Suite | mock | ollama |
|---|---|---|
| **Generated (headline)** | 2/15 (13.3%) | 2/15 (13.3%) |
| Gold (LLM-independent) | 5/15 (33.3%) | 5/15 (33.3%) |
| Union generated ∪ gold | 5/15 (33.3%) | 5/15 (33.3%) |
| Generated tests (seed requirements) | 206 | 66 |
| Invalid generated tests (fail on clean simulator) | 0 | 0 |
| Supplementary: union of ALL generated tests (seed + natural v1 + natural v2) | 2/15 (13.3%) (511 tests) | 2/15 (13.3%) (258 tests) |
| Supplementary: tests generated from natural v2 alone | 2/15 (13.3%) (100 tests) | 1/15 (6.7%) (81 tests) |

Per held-out v2 bug (generated suite):

| Bug | Category | mock generated | ollama generated | gold |
|---|---|---|---|---|
| `session_reentry_keeps_unlock` | session | yes (8 tests) | yes (6 tests) | yes |
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
| `write_range_upper_bound_exclusive` | data | yes (6 tests) | yes (1 tests) | yes |
| `multi_did_read_dedups_repeats` | data | **no** (0 tests) | **no** (0 tests) | yes |
| `routine_restart_after_stop_blocked` | sequence | **no** (0 tests) | **no** (0 tests) | yes |
| `suppressed_seed_request_not_stored` | security | **no** (0 tests) | **no** (0 tests) | **no** |

### Held-out v1 bug detection (12 bugs) — SEEN (templates designed against these misses)

| Suite | mock | ollama |
|---|---|---|
| **Generated** | 10/12 (83.3%) | 5/12 (41.7%) |
| Gold (LLM-independent) | 3/12 (25.0%) | 3/12 (25.0%) |
| Union generated ∪ gold | 11/12 (91.7%) | 6/12 (50.0%) |
| Generated tests (seed requirements) | 206 | 66 |
| Invalid generated tests (fail on clean simulator) | 0 | 0 |

Per held-out v1 bug (generated suite):

| Bug | Category | mock generated | ollama generated | gold |
|---|---|---|---|---|
| `routine_state_survives_session_change` | session | yes (2 tests) | yes (2 tests) | **no** |
| `failed_attempts_reset_by_seed_request` | security | yes (12 tests) | yes (1 tests) | yes |
| `seed_returned_while_unlocked` | security | yes (6 tests) | yes (3 tests) | yes |
| `nrc_order_condition_before_security` | nrc_order | yes (1 tests) | **no** (0 tests) | **no** |
| `read_did_odd_length_truncated` | format | yes (3 tests) | yes (6 tests) | **no** |
| `read_did_session_restriction_ignored` | data | yes (2 tests) | **no** (0 tests) | **no** |
| `uint16_did_stored_byte_swapped` | data | **no** (0 tests) | **no** (0 tests) | yes |
| `s3_not_refreshed_by_tester_present` | timing | yes (13 tests) | yes (1 tests) | **no** |
| `ecu_reset_clears_security_lockout` | security | yes (6 tests) | **no** (0 tests) | **no** |
| `s3_timeout_reverts_written_dids` | timing | yes (5 tests) | **no** (0 tests) | **no** |
| `session_suppress_bit_not_masked` | format | yes (3 tests) | **no** (0 tests) | **no** |
| `suppress_bit_echoed_in_response` | format | **no** (0 tests) | **no** (0 tests) | **no** |

### In-sample bug detection (26 bugs — in-sample, templates tuned on these)

| Suite | mock | ollama |
|---|---|---|
| Generated | 25/26 (96.2%) | 19/26 (73.1%) |
| Gold | 24/26 (92.3%) | 24/26 (92.3%) |
| Union | 26/26 (100.0%) | 26/26 (100.0%) |
| Undetected by the generated suite | missing_response_pending | nrc_order_security_before_length, write_ignores_value_range, write_length_off_by_one, routine_stop_without_start, condition_ignored, dtc_clear_ignores_group, missing_response_pending |

### Validation: rejections, re-plans (retries), plan attempts, dropped tests

Per requirement (15 seed + 20 natural v1 + 16 natural v2). *rejected* = planner choices refused (unknown template/option, outside the shortlist, or failed validation); *retries* = re-plan rounds (plan attempts − 1); *dropped* = instantiated tests that failed validation.

| Req | Split | mock tests | mock rejected | mock retries | mock plan attempts | mock dropped | ollama tests | ollama rejected | ollama retries | ollama plan attempts | ollama dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| REQ-001 | seed | 18 | 0 | 0 | 1 | 0 | 3 | 0 | 0 | 1 | 0 |
| REQ-002 | seed | 20 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| REQ-003 | seed | 8 | 0 | 0 | 1 | 0 | 2 | 2 | 0 | 1 | 0 |
| REQ-004 | seed | 5 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| REQ-005 | seed | 18 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| REQ-006 | seed | 18 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| REQ-007 | seed | 16 | 0 | 0 | 1 | 0 | 3 | 1 | 0 | 1 | 0 |
| REQ-008 | seed | 16 | 0 | 0 | 1 | 0 | 2 | 2 | 0 | 1 | 0 |
| REQ-009 | seed | 22 | 0 | 0 | 1 | 0 | 3 | 1 | 0 | 1 | 0 |
| REQ-010 | seed | 8 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| REQ-011 | seed | 12 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-012 | seed | 16 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-013 | seed | 6 | 0 | 0 | 1 | 0 | 3 | 2 | 0 | 1 | 0 |
| REQ-014 | seed | 10 | 0 | 0 | 1 | 0 | 4 | 2 | 0 | 1 | 0 |
| REQ-015 | seed | 13 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-001 | dev | 18 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| NAT-002 | test | 14 | 0 | 0 | 1 | 0 | 7 | 0 | 0 | 1 | 0 |
| NAT-003 | dev | 0 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT-004 | test | 9 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-005 | dev | 18 | 0 | 0 | 1 | 0 | 7 | 0 | 0 | 1 | 0 |
| NAT-006 | test | 14 | 0 | 0 | 1 | 0 | 7 | 0 | 0 | 1 | 0 |
| NAT-007 | dev | 7 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-008 | test | 0 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT-009 | dev | 20 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| NAT-010 | test | 3 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| NAT-011 | dev | 12 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-012 | test | 16 | 0 | 0 | 1 | 0 | 6 | 2 | 0 | 1 | 0 |
| NAT-013 | dev | 6 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| NAT-014 | test | 11 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-015 | dev | 9 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-016 | test | 13 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT-017 | test | 0 | 0 | 0 | 1 | 0 | 4 | 3 | 0 | 1 | 0 |
| NAT-018 | test | 16 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-019 | test | 19 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-020 | test | 0 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT2-001 | test2 | 18 | 0 | 0 | 1 | 0 | 8 | 1 | 0 | 1 | 0 |
| NAT2-002 | test2 | 14 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT2-003 | test2 | 16 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT2-004 | test2 | 8 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT2-005 | test2 | 0 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT2-006 | test2 | 0 | 0 | 0 | 1 | 0 | 3 | 4 | 0 | 1 | 0 |
| NAT2-007 | test2 | 8 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT2-008 | test2 | 2 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT2-009 | test2 | 2 | 0 | 0 | 1 | 0 | 2 | 2 | 0 | 1 | 0 |
| NAT2-010 | test2 | 1 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT2-011 | test2 | 2 | 0 | 0 | 1 | 0 | 3 | 2 | 0 | 1 | 0 |
| NAT2-012 | test2 | 19 | 0 | 0 | 1 | 0 | 7 | 1 | 0 | 1 | 0 |
| NAT2-013 | test2 | 1 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT2-014 | test2 | 1 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| NAT2-015 | test2 | 0 | 0 | 0 | 1 | 0 | 4 | 2 | 0 | 1 | 0 |
| NAT2-016 | test2 | 8 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| **total** |  | 511 | 0 | 0 | 51 | 0 | 258 | 27 | 0 | 51 | 0 |

LLM call counters (all 51 requirements):

| Counter | mock | ollama |
|---|---|---|
| LLM calls | 146 | 153 |
| Explain LLM calls | 44 | 51 |
| JSON/schema failures | 0 | 0 |
| LLM re-prompts/retries | 0 | 0 |
| LLM errors | 0 | 0 |
| Failed pipeline runs | 0 | 0 |

Rejection reasons — `mock` (0):

- none

Rejection reasons — `ollama` (27):

- REQ-003: plan: session_change_relocks_security[1]: option was not in the offered shortlist
- REQ-003: plan: read_readonly_did_positive[10]: unknown template id 'read_readonly_did_positive'
- REQ-007: plan: write_did_out_of_range[28]: option_index 28 out of range for write_did_out_of_range (6 options)
- REQ-008: plan: write_did_out_of_range[10]: option_index 10 out of range for write_did_out_of_range (6 options)
- REQ-008: plan: write_did_without_security[1]: option was not in the offered shortlist
- REQ-009: plan: write_did_invalid_length[12]: option_index 12 out of range for write_did_invalid_length (7 options)
- REQ-013: plan: negative_response_with_suppress_bit[10]: option was not in the offered shortlist
- REQ-013: plan: negative_response_with_suppress_bit[5]: option was not in the offered shortlist
- REQ-014: plan: service_not_in_session[2]: option was not in the offered shortlist
- REQ-014: plan: service_not_in_session[1]: option was not in the offered shortlist
- NAT-012: plan: read_did_positive[11]: option was not in the offered shortlist
- NAT-012: plan: read_readonly_did[4]: unknown template id 'read_readonly_did'
- NAT-017: plan: service_not_in_session[1]: option was not in the offered shortlist
- NAT-017: plan: service_not_in_session[2]: option was not in the offered shortlist
- NAT-017: plan: service_not_in_session[0]: option was not in the offered shortlist
- NAT2-001: plan: read_did_positive[1]: option was not in the offered shortlist
- NAT2-006: plan: seed_key_handshake_failure[0]: unknown template id 'seed_key_handshake_failure'
- NAT2-006: plan: seed_key_handshake_failure[1]: unknown template id 'seed_key_handshake_failure'
- NAT2-006: plan: seed_key_handshake_failure[2]: unknown template id 'seed_key_handshake_failure'
- NAT2-006: plan: seed_key_handshake_failure[3]: unknown template id 'seed_key_handshake_failure'
- NAT2-009: plan: write_did_value_retained[1]: option was not in the offered shortlist
- NAT2-009: plan: negative_response_with_suppress_bit[1]: option was not in the offered shortlist
- NAT2-011: plan: negative_subfunction_in_session_02 (negative)[3]: unknown template id 'negative_subfunction_in_session_02 (negative)'
- NAT2-011: plan: negative_subfunction_in_session_03 (negative)[3]: unknown template id 'negative_subfunction_in_session_03 (negative)'
- NAT2-012: plan: read_multiple_dids[20]: option_index 20 out of range for read_multiple_dids (14 options)
- NAT2-015: plan: dtc_clear_specific_keeps_others[3]: option_index 3 out of range for dtc_clear_specific_keeps_others (3 options)
- NAT2-015: plan: service_not_in_session[1]: option was not in the offered shortlist

### Fallback-to-mock and truncation events (verbatim)

**`mock` — fallback events (0):**

- none

**`mock` — truncation events (0):**

- none

**`ollama` — fallback events (62):**

- REQ-002: `explain: req_002__tpl_read_did_positive_f18c_01: missing in LLM reply; used fallback text`
- REQ-002: `explain: req_002__tpl_read_did_positive_f18c_03: missing in LLM reply; used fallback text`
- REQ-005: `explain: req_005__tpl_negative_suppress_10_03: missing in LLM reply; used fallback text`
- REQ-005: `explain: req_005__tpl_read_multi_0100_f190_01: missing in LLM reply; used fallback text`
- REQ-005: `explain: req_005__tpl_service_not_in_session_27_01: missing in LLM reply; used fallback text`
- REQ-005: `explain: req_005__tpl_s3_timeout_03: missing in LLM reply; used fallback text`
- REQ-005: `explain: req_005__tpl_seed_while_unlocked_01: missing in LLM reply; used fallback text`
- REQ-008: `explain: req_008__tpl_write_retained_reset_0100: missing in LLM reply; used fallback text`
- REQ-011: `explain: req_011__tpl_routine_after_session_0201: missing in LLM reply; used fallback text`
- REQ-013: `explain: req_013__tpl_negative_suppress_11_02: missing in LLM reply; used fallback text`
- REQ-013: `explain: req_013__tpl_negative_suppress_11_01: missing in LLM reply; used fallback text`
- NAT-001: `explain: nat_001__tpl_s3_timeout_02: missing in LLM reply; used fallback text`
- NAT-001: `explain: nat_001__tpl_suppress_positive_10_01: missing in LLM reply; used fallback text`
- NAT-003: `explain: nat_003__tpl_read_did_positive_f186_03: missing in LLM reply; used fallback text`
- NAT-003: `explain: nat_003__tpl_negative_suppress_31_03: missing in LLM reply; used fallback text`
- NAT-003: `explain: nat_003__tpl_session_relock_01: missing in LLM reply; used fallback text`
- NAT-003: `explain: nat_003__tpl_seed_while_unlocked_01: missing in LLM reply; used fallback text`
- NAT-003: `explain: nat_003__tpl_read_multi_f186_f190_01: missing in LLM reply; used fallback text`
- NAT-003: `explain: nat_003__tpl_s3_keepalive_03: missing in LLM reply; used fallback text`
- NAT-003: `explain: nat_003__tpl_nrc_priority_2e_01: missing in LLM reply; used fallback text`
- NAT-005: `explain: nat_005__tpl_read_did_positive_0100_01: missing in LLM reply; used fallback text`
- NAT-005: `explain: nat_005__tpl_service_not_in_session_2e_01: missing in LLM reply; used fallback text`
- NAT-005: `explain: nat_005__tpl_read_multi_0100_f190_01: missing in LLM reply; used fallback text`
- NAT-005: `explain: nat_005__tpl_nrc_priority_2e_01: missing in LLM reply; used fallback text`
- NAT-006: `explain: nat_006__tpl_s3_timeout_03: missing in LLM reply; used fallback text`
- NAT-006: `explain: nat_006__tpl_security_lockout_03: missing in LLM reply; used fallback text`
- NAT-006: `explain: nat_006__tpl_seed_while_unlocked_03: missing in LLM reply; used fallback text`
- NAT-006: `explain: nat_006__tpl_read_badlen_0101_01: missing in LLM reply; used fallback text`
- NAT-010: `explain: nat_010__tpl_unsupported_subfunction_27_03: missing in LLM reply; used fallback text`
- NAT-010: `explain: nat_010__tpl_condition_not_met_did_0150: missing in LLM reply; used fallback text`
- NAT-012: `explain: nat_012__tpl_security_lockout_03: missing in LLM reply; used fallback text`
- NAT-012: `explain: nat_012__tpl_session_relock_03: missing in LLM reply; used fallback text`
- NAT-012: `explain: nat_012__tpl_seed_while_unlocked_03: missing in LLM reply; used fallback text`
- NAT-016: `explain: nat_016__tpl_write_badlen_0160: missing in LLM reply; used fallback text`
- NAT-016: `explain: nat_016__tpl_s3_timeout_02: missing in LLM reply; used fallback text`
- NAT-016: `explain: nat_016__tpl_negative_suppress_10_02: missing in LLM reply; used fallback text`
- NAT-016: `explain: nat_016__tpl_read_multi_0160_f190_01: missing in LLM reply; used fallback text`
- NAT-016: `explain: nat_016__tpl_security_lockout_01: missing in LLM reply; used fallback text`
- NAT-016: `explain: nat_016__tpl_seed_while_unlocked_01: missing in LLM reply; used fallback text`
- NAT-020: `explain: nat_020__tpl_read_did_positive_f190_01: missing in LLM reply; used fallback text`
- NAT-020: `explain: nat_020__tpl_security_lockout_01: missing in LLM reply; used fallback text`
- NAT-020: `explain: nat_020__tpl_session_relock_01: missing in LLM reply; used fallback text`
- NAT-020: `explain: nat_020__tpl_seed_replay_01: missing in LLM reply; used fallback text`
- NAT-020: `explain: nat_020__tpl_seed_while_unlocked_01: missing in LLM reply; used fallback text`
- NAT2-001: `explain: nat2_001__tpl_read_badlen_f187_01: missing in LLM reply; used fallback text`
- NAT2-001: `explain: nat2_001__tpl_read_badlen_f18c_01: missing in LLM reply; used fallback text`
- NAT2-001: `explain: nat2_001__tpl_read_badlen_f186_01: missing in LLM reply; used fallback text`
- NAT2-001: `explain: nat2_001__tpl_write_readonly_f187: missing in LLM reply; used fallback text`
- NAT2-001: `explain: nat2_001__tpl_write_readonly_f18c: missing in LLM reply; used fallback text`
- NAT2-001: `explain: nat2_001__tpl_write_readonly_f186: missing in LLM reply; used fallback text`
- NAT2-003: `explain: nat2_003__tpl_session_relock_03: missing in LLM reply; used fallback text`
- NAT2-003: `explain: nat2_003__tpl_s3_timeout_03: missing in LLM reply; used fallback text`
- NAT2-003: `explain: nat2_003__tpl_read_multi_0130_f190_01: missing in LLM reply; used fallback text`
- NAT2-003: `explain: nat2_003__tpl_negative_suppress_10_03: missing in LLM reply; used fallback text`
- NAT2-003: `explain: nat2_003__tpl_seed_while_unlocked_01: missing in LLM reply; used fallback text`
- NAT2-008: `explain: nat2_008__tpl_read_did_positive_f186_02: missing in LLM reply; used fallback text`
- NAT2-008: `explain: nat2_008__tpl_session_relock_01: missing in LLM reply; used fallback text`
- NAT2-008: `explain: nat2_008__tpl_negative_suppress_10_01: missing in LLM reply; used fallback text`
- NAT2-009: `explain: nat2_009__tpl_read_multi_0100_f190_01: missing in LLM reply; used fallback text`
- NAT2-013: `explain: nat2_013__tpl_negative_suppress_10_03: missing in LLM reply; used fallback text`
- NAT2-016: `explain: nat2_016__tpl_write_nosec_0100: missing in LLM reply; used fallback text`
- NAT2-016: `explain: nat2_016__tpl_routine_sequence_0201: missing in LLM reply; used fallback text`

**`ollama` — truncation events (0):**

- none

### Latency per requirement (wall clock)

| Scope | mock mean | ollama mean | mock p95 | ollama p95 | mock max | ollama max |
|---|---|---|---|---|---|---|
| seed (n=15) | 0.3 s | 21.3 s | 0.5 s | 30.1 s | 0.5 s | 30.1 s |
| natural (n=20) | 0.2 s | 21.5 s | 0.4 s | 27.9 s | 0.4 s | 28.5 s |
| all (n=35) | 0.3 s | 21.4 s | 0.5 s | 28.5 s | 0.5 s | 30.1 s |
| natural v2 (n=16) | 0.2 s | 21.7 s | 0.4 s | 29.8 s | 0.4 s | 29.8 s |
| all with v2 (n=51) | 0.2 s | 21.5 s | 0.4 s | 28.5 s | 0.5 s | 30.1 s |

Per-node mean latency per requirement (ms; p95 in brackets):

| Node | mock | ollama |
|---|---|---|
| parse | 1.3 [1.5] | 4601.3 [6095.5] |
| retrieve | 4.2 [6.0] | 5.3 [8.6] |
| plan | 12.2 [11.4] | 7653.7 [9633.2] |
| instantiate | 10.7 [19.1] | 6.1 [11.2] |
| validate | 13.3 [26.3] | 9.0 [13.8] |
| explain | 2.8 [4.6] | 8941.9 [14820.2] |
| time inside LLM calls | 0.0 [0.0] | 21172.6 [28301.9] |

_wall clock seconds of one run_pipeline call per requirement (parse through explain, including all LLM calls and re-plans); p95 is nearest-rank; per-node values are per requirement in milliseconds._

### Coverage, citations, request validity, byte provenance

| Metric | mock | ollama |
|---|---|---|
| Coverage: tests per category (positive, negative, session, security, timing) | 43 / 77 / 25 / 30 / 31 | 26 / 18 / 9 / 9 / 4 |
| Coverage: seed requirements with ≥1 test | 15/15 (100.0%) | 15/15 (100.0%) |
| Citation validity | 967/967 (100.0%) | 315/315 (100.0%) |
| Request validity (adjusted) | 691/691 (100.0%) | 207/207 (100.0%) |
| Generated tests passing on the clean simulator | 206/206 (100.0%) | 66/66 (100.0%) |
| Byte provenance — seed-requirement tests | 206/206 passed | 66/66 passed |
| Byte provenance — natural v1 requirement tests | 205/205 passed | 111/111 passed |
| Byte provenance — natural v2 requirement tests | 100/100 passed | 81/81 passed |
| Byte provenance — extra noise-check runs (natural v2) | none (no extra runs) | 160/160 passed over 2 run(s) |
| **Byte provenance — all generated tests, all runs** | 511/511 passed | 418/418 passed |

_Byte provenance: each generated test re-instantiated from TEMPLATES[template_id].instantiate(spec, params_model.model_validate(test.parameters)); template_id must be registered, parameters must round-trip, and every step must be identical (request and expected-response bytes, time/environment/DTC steps, descriptions, timing limits)._

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

## Freeze verification (Part C: templates / prompts / agent / gold)

Recorded hashes are parsed from PROGRESS.md 'Part C freeze' table; current = `git rev-parse HEAD:<path>` when this report ran.

| Path | recorded (Part C freeze) | current | result | worktree clean |
|---|---|---|---|---|
| freeze commit | `5a36eb432ed5aa05fb4a8ccb6776e8232a43d309` | `c669e1e1080b873361f0211b01e85f4d14f2cfd5` (HEAD) | ancestor of HEAD | - |
| `uds_assistant/testgen` | `a4b6491fc2d01421c4cff10143aabd3c75017df1` | `a4b6491fc2d01421c4cff10143aabd3c75017df1` | match | True |
| `uds_assistant/llm` | `95ebf497e3e31a4d6d1377ca960b15e94e5cad66` | `95ebf497e3e31a4d6d1377ca960b15e94e5cad66` | match | True |
| `uds_assistant/agent` | `9696c352234501d72ac54c18af5189317482321d` | `9696c352234501d72ac54c18af5189317482321d` | match | True |
| `uds_assistant/llm/prompts.py` | `c0c6d5a6f0b64790beb13bf0179a6ef7877f31f7` | `c0c6d5a6f0b64790beb13bf0179a6ef7877f31f7` | match | True |
| `data/gold` | `778740195a3dc923ae2f6a34fd4b78e11d87b024` | `778740195a3dc923ae2f6a34fd4b78e11d87b024` | match | True |

All recorded freeze hashes match and are clean: **True**.

# Details — mode=mock

Generated tests (seed requirements): **206** (119 unique template instantiations); 206/206 (100.0%) pass on the clean simulator; P2/P2* wall-clock warnings: 0.

## Held-out v2 bug detection (15 FRESH bugs) — NEW HEADLINE — mode=mock

Scope: held-out v2 (FRESH): 15 bugs written blind by a subagent after the Part C freeze, which could not see templates, gold tests, eval, LLM or agent code; nothing was changed after seeing these results. Catalog: `data/bugs/heldout_v2_catalog.yaml`.

Headline = the generated suite from the 15 seed requirements (same definition as the v1 headline). The two supplementary columns use all generated tests (seed + natural v1 + natural v2) and the natural-v2 tests alone.

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

## Requirement understanding, natural v2 (split test2, FRESH — NEW HEADLINE) — mode=mock

Source: `data/requirements_natural_v2.csv` (16 labelled rows). Each requirement was run through the agent pipeline (`mode=mock`, Bm25Retriever). **The test2 split is the main number.**

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
| REQ-001 | 18 | 0 | 0 | 1 | completed | 0.383 |
| REQ-002 | 20 | 0 | 0 | 1 | completed | 0.412 |
| REQ-003 | 8 | 0 | 0 | 1 | completed | 0.191 |
| REQ-004 | 5 | 0 | 0 | 1 | completed | 0.141 |
| REQ-005 | 18 | 0 | 0 | 1 | completed | 0.461 |
| REQ-006 | 18 | 0 | 0 | 1 | completed | 0.381 |
| REQ-007 | 16 | 0 | 0 | 1 | completed | 0.356 |
| REQ-008 | 16 | 0 | 0 | 1 | completed | 0.363 |
| REQ-009 | 22 | 0 | 0 | 1 | completed | 0.48 |
| REQ-010 | 8 | 0 | 0 | 1 | completed | 0.203 |
| REQ-011 | 12 | 0 | 0 | 1 | completed | 0.266 |
| REQ-012 | 16 | 0 | 0 | 1 | completed | 0.332 |
| REQ-013 | 6 | 0 | 0 | 1 | completed | 0.166 |
| REQ-014 | 10 | 0 | 0 | 1 | completed | 0.227 |
| REQ-015 | 13 | 0 | 0 | 1 | completed | 0.265 |

Totals: 206 kept, 0 dropped, 0 rejected, 0 re-plans, 0 failed runs.

## Appendix: Self-consistency check (circular by construction) — mode=mock

Expected bytes in generated tests are produced by the rules-engine oracle, so agreement with a fresh oracle re-run is a consistency check, not an independent accuracy measure. Kept here for completeness; it is not a headline metric.

- Expected-response accuracy vs oracle: 691/691 (100.0%) steps; 206/206 (100.0%) tests.
- Independent simulator (clean): 100.0% of generated tests pass.
- Gold, exact overlap: 25/25 (100.0%) generated/gold pairs with identical step sequences agree.
- Gold, shared prefix: 21/21 (100.0%) distinct send steps reached by an identical prefix in both suites agree.

# Details — mode=ollama

Generated tests (seed requirements): **66** (54 unique template instantiations); 66/66 (100.0%) pass on the clean simulator; P2/P2* wall-clock warnings: 0.

## Held-out v2 bug detection (15 FRESH bugs) — NEW HEADLINE — mode=ollama

Scope: held-out v2 (FRESH): 15 bugs written blind by a subagent after the Part C freeze, which could not see templates, gold tests, eval, LLM or agent code; nothing was changed after seeing these results. Catalog: `data/bugs/heldout_v2_catalog.yaml`.

Headline = the generated suite from the 15 seed requirements (same definition as the v1 headline). The two supplementary columns use all generated tests (seed + natural v1 + natural v2) and the natural-v2 tests alone.

| Bug | Category | Generated (seed reqs) | Generated detecting tests | Gen. tests applying trigger | Gold | Gold tests applying trigger | All generated (suppl.) | trigger | Natural-v2 tests (suppl.) | trigger |
|---|---|---|---|---|---|---|---|---|---|---|
| `session_reentry_keeps_unlock` | session | yes | `req_004__tpl_session_relock_03`, `req_005__tpl_session_relock_01` (+4 more) | 6 | yes | 1 | yes | 18 | yes | 6 |
| `s3_restart_skipped_on_negative_response` | timing | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `s3_timeout_resets_lockout_counters` | session | **no** | - | 1 | **no** | 0 | **no** | 10 | **no** | 3 |
| `ecu_reset_keeps_session` | session | **no** | - | 2 | yes | 1 | **no** | 5 | **no** | 1 |
| `seed_request_keeps_stale_pending_seed` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `key_compare_prefix_only` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `lockout_counter_pooled_across_levels` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `nrc_order_range_before_security` | nrc_order | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `nrc_order_nvm_fault_before_group_check` | nrc_order | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `read_dtc_trailing_bytes_accepted` | format | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `routine_option_record_overlong_accepted` | format | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |
| `write_range_upper_bound_exclusive` | data | yes | `req_007__tpl_write_retained_reset_0130` | 1 | yes | 2 | yes | 4 | **no** | 0 |
| `multi_did_read_dedups_repeats` | data | **no** | - | 0 | yes | 1 | **no** | 0 | **no** | 0 |
| `routine_restart_after_stop_blocked` | sequence | **no** | - | 0 | yes | 1 | **no** | 0 | **no** | 0 |
| `suppressed_seed_request_not_stored` | security | **no** | - | 0 | **no** | 0 | **no** | 0 | **no** | 0 |

Totals: generated 2/15 (13.3%), gold 5/15 (33.3%), union 5/15 (33.3%). Invalid tests (fail on the clean simulator): generated 0, gold 0.
- Supplementary — All generated tests (seed + natural v1 + natural v2): 258 tests, 2/15 (13.3%) detected (0 invalid tests).
- Supplementary — Tests generated from natural v2 alone: 81 tests, 1/15 (6.7%) detected (0 invalid tests).

### Missed held-out v2 bugs — generated suite (mode=ollama)

- `s3_restart_skipped_on_negative_response`: no generated test answers a request with an NRC in a non-default session and then wait so that S3 is exceeded only when counted from the last positive request
- `s3_timeout_resets_lockout_counters`: 1 generated test(s) reaches a security lockout, lets S3 expire and then requests a seed, but none of their expected responses differs under the bug
- `ecu_reset_keeps_session`: 2 generated test(s) sends a positive ECUReset from a non-default session and then another request, but none of their expected responses differs under the bug
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
- `s3_timeout_resets_lockout_counters`: 10 all_generated test(s) reaches a security lockout, lets S3 expire and then requests a seed, but none of their expected responses differs under the bug
- `ecu_reset_keeps_session`: 5 all_generated test(s) sends a positive ECUReset from a non-default session and then another request, but none of their expected responses differs under the bug
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
- `s3_timeout_resets_lockout_counters`: 3 natural_v2_generated test(s) reaches a security lockout, lets S3 expire and then requests a seed, but none of their expected responses differs under the bug
- `ecu_reset_keeps_session`: 1 natural_v2_generated test(s) sends a positive ECUReset from a non-default session and then another request, but none of their expected responses differs under the bug
- `seed_request_keeps_stale_pending_seed`: no natural_v2_generated test requests a seed twice for one level before sending a key for it
- `key_compare_prefix_only`: no natural_v2_generated test sends a key with the right first two bytes and a wrong tail
- `lockout_counter_pooled_across_levels`: no natural_v2_generated test sends wrong keys at two different levels that together reach the attempt limit
- `nrc_order_range_before_security`: no natural_v2_generated test writes an out-of-range value of correct length to a DID in its write session while security is locked
- `nrc_order_nvm_fault_before_group_check`: no natural_v2_generated test clears an unknown DTC group (0x14) while the NVM write fault is set
- `read_dtc_trailing_bytes_accepted`: no natural_v2_generated test sends 19 02 with more than one byte after the sub-function
- `routine_option_record_overlong_accepted`: no natural_v2_generated test starts a routine (in its session) with an over-long option record
- `write_range_upper_bound_exclusive`: no natural_v2_generated test writes the DID's maximum in-range value and has it accepted
- `multi_did_read_dedups_repeats`: no natural_v2_generated test reads one DID several times in a single 0x22 request
- `routine_restart_after_stop_blocked`: no natural_v2_generated test starts a routine again after stopping it
- `suppressed_seed_request_not_stored`: no natural_v2_generated test sends a suppressed seed request (27 81 / 27 83) and then a key for that level

_Reasons come from `uds_assistant/eval/heldout_v2.py`: one predicate per bug, written only from the bug descriptions in `data/bugs/heldout_v2_catalog.yaml` and `docs/behaviour_contract.md` before any v2 result existed. "no test X" means no test in that suite applies the stimulus; "N test(s) X, but none of their expected responses differs" means the stimulus is present but the oracle-derived expectations do not distinguish the bug. Reporting only — nothing was changed in response._

## Requirement understanding, natural v2 (split test2, FRESH — NEW HEADLINE) — mode=ollama

Source: `data/requirements_natural_v2.csv` (16 labelled rows). Each requirement was run through the agent pipeline (`mode=ollama`, Bm25Retriever). **The test2 split is the main number.**

| Split | n | Targets exact (parsed) | Parsed P / R / F1 | Targets exact (exercised) | Exercised P / R / F1 | Category recall micro / macro | Precondition recall micro / macro | Fallback / nothing |
|---|---|---|---|---|---|---|---|---|
| **test2** | 16 | 4/16 (25.0%) | 0.565 / 0.796 / 0.661 | 1/16 (6.2%) | 0.442 / 0.857 / 0.583 | 37/50 (74.0%) / 74.6% | 21/27 (77.8%) / 80.8% | 0 (0 excl. empty-label rows) |
| all | 16 | 4/16 (25.0%) | 0.565 / 0.796 / 0.661 | 1/16 (6.2%) | 0.442 / 0.857 / 0.583 | 37/50 (74.0%) / 74.6% | 21/27 (77.8%) / 80.8% | 0 (0 excl. empty-label rows) |

### Per requirement (natural v2, mode=ollama)

| Req | Split | Tests | Label targets | Parsed exact | Parsed missed | Parsed extra | Exercised exact | Exercised missed | Exercised extra (n) | Categories missed | Preconditions missed | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NAT2-001 | test2 | 8 | did:0xF187, did:0xF18C, did:0xF190, service:0x22 | no | did:0xF190 | did:0xF186 | no | - | 3 | session | - | - |
| NAT2-002 | test2 | 4 | did:0x0120, service:0x10, service:0x27, service:0x2E | no | did:0x0120 | - | no | - | 2 | security | - | - |
| NAT2-003 | test2 | 8 | did:0x0130, service:0x22, service:0x27, service:0x2E | no | service:0x22 | service:0x10 | no | - | 5 | - | - | - |
| NAT2-004 | test2 | 4 | routine:0x0201, service:0x31 | no | routine:0x0201 | - | no | - | 2 | security | - | - |
| NAT2-005 | test2 | 4 | routine:0x0203, service:0x10, service:0x27, service:0x31 | no | routine:0x0203 | did:0x0150, service:0x11, service:0x14, service:0x22, service:0x2E, service:0x3E | no | routine:0x0203, service:0x31 | 5 | negative, session | programming_session, security_level_3 | - |
| NAT2-006 | test2 | 3 | service:0x27 | yes | - | - | no | - | 4 | negative, timing | lockout_active | - |
| NAT2-007 | test2 | 8 | service:0x14, service:0x19 | no | service:0x14 | service:0x22 | no | - | 5 | - | - | - |
| NAT2-008 | test2 | 4 | service:0x10, service:0x22, service:0x3E | no | service:0x22 | did:0xF186, service:0x27, service:0x2E, service:0x31 | no | service:0x3E | 4 | session | - | - |
| NAT2-009 | test2 | 2 | did:0x0100, service:0x10, service:0x27, service:0x2E | yes | - | - | no | service:0x10, service:0x27 | 2 | negative, security, timing | extended_session, s3_elapsed, security_level_1 | - |
| NAT2-010 | test2 | 8 | did:0xF186, service:0x10, service:0x11, service:0x22, service:0x27 | no | - | service:0x14, service:0x2E, service:0x31, service:0x3E | no | service:0x11 | 2 | - | - | - |
| NAT2-011 | test2 | 3 | service:0x3E | yes | - | - | no | - | 3 | - | - | - |
| NAT2-012 | test2 | 7 | routine:0x0202, service:0x10, service:0x27, service:0x31 | no | service:0x31 | did:0x0110, did:0x0111, service:0x22, service:0x2E | no | - | 4 | - | - | - |
| NAT2-013 | test2 | 4 | did:0x0160, service:0x10, service:0x22, service:0x27, service:0x2E | yes | - | - | yes | - | 0 | session | - | - |
| NAT2-014 | test2 (ambiguous) | 5 | did:0x0110, did:0x0111, service:0x22, service:0x2E | no | service:0x2E | service:0x10, service:0x27 | no | did:0x0111 | 3 | - | - | - |
| NAT2-015 | test2 (ambiguous) | 4 | service:0x10, service:0x14 | no | service:0x10 | - | no | - | 1 | negative | - | - |
| NAT2-016 | test2 | 5 | (none) | no | - | service:0x10, service:0x11, service:0x14, service:0x22, service:0x2E, service:0x31, service:0x3E | no | - | 8 | - | - | - |

## Held-out bug detection (12 v1 bugs — SEEN: templates designed against these misses) — mode=ollama

Scope: held-out v1, now SEEN: bugs written by an independent subagent that could not see templates, gold tests, eval, LLM or agent code; the template-set-v3 coverage templates were then designed against the misses, so these 12 are no longer independent. Catalog: `data/bugs/heldout_catalog.yaml`.

| Bug | Category | Generated | Generated detecting tests | Gen. tests applying trigger | Gold | Gold detecting tests | Gold tests applying trigger |
|---|---|---|---|---|---|---|---|
| `routine_state_survives_session_change` | session | yes | `req_011__tpl_routine_after_session_0201`, `req_012__tpl_routine_after_session_0202` | 2 | **no** | - | 0 |
| `failed_attempts_reset_by_seed_request` | security | yes | `req_006__tpl_security_lockout_01` | 1 | yes | `gold_security_lockout_after_3` | 1 |
| `seed_returned_while_unlocked` | security | yes | `req_005__tpl_seed_while_unlocked_01`, `req_006__tpl_seed_while_unlocked_01` (+1 more) | 3 | yes | `gold_security_already_unlocked_seed` | 1 |
| `nrc_order_condition_before_security` | nrc_order | **no** | - | 0 | **no** | - | 0 |
| `read_did_odd_length_truncated` | format | yes | `req_001__tpl_read_badlen_f190_01`, `req_002__tpl_read_badlen_f187_01` (+4 more) | 6 | **no** | - | 0 |
| `read_did_session_restriction_ignored` | data | **no** | - | 0 | **no** | - | 0 |
| `uint16_did_stored_byte_swapped` | data | **no** | - | 0 | yes | `gold_write_coding_variant` | 1 |
| `s3_not_refreshed_by_tester_present` | timing | yes | `req_015__tpl_s3_keepalive_03` | 1 | **no** | - | 0 |
| `ecu_reset_clears_security_lockout` | security | **no** | - | 0 | **no** | - | 0 |
| `s3_timeout_reverts_written_dids` | timing | **no** | - | 0 | **no** | - | 0 |
| `session_suppress_bit_not_masked` | format | **no** | - | 3 | **no** | - | 0 |
| `suppress_bit_echoed_in_response` | format | **no** | - | 0 | **no** | - | 0 |

Totals: generated 5/12 (41.7%), gold 3/12 (25.0%), union 6/12 (50.0%). Invalid tests (fail on the clean simulator): generated 0, gold 0.

### Missed held-out v1 bugs — generated suite (mode=ollama)

- `nrc_order_condition_before_security`: no generated test starts a vehicle_stationary-gated routine while moving AND still locked
- `read_did_session_restriction_ignored`: no generated test reads a DID outside its read_sessions
- `uint16_did_stored_byte_swapped`: no generated test writes a uint16 DID and reads it back
- `ecu_reset_clears_security_lockout`: no generated test resets the ECU after a security lockout and then requests a seed
- `s3_timeout_reverts_written_dids`: no generated test writes a DID, lets S3 expire, then reads the DID back
- `session_suppress_bit_not_masked`: 3 generated test(s) sends DiagnosticSessionControl with the suppress bit set, but none of their expected responses differs under the bug
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
| **test** | 12 | 3/12 (25.0%) | 0.500 / 0.840 / 0.627 | 0/12 (0.0%) | 0.276 / 0.840 / 0.416 | 23/28 (82.1%) / 84.1% | 11/15 (73.3%) / 75.0% | 0 (0 excl. empty-label rows) |
| dev | 8 | 2/8 (25.0%) | 0.619 / 0.765 / 0.684 | 0/8 (0.0%) | 0.333 / 1.000 / 0.500 | 16/22 (72.7%) / 74.0% | 9/9 (100.0%) / 100.0% | 0 (0 excl. empty-label rows) |
| all | 20 | 5/20 (25.0%) | 0.540 / 0.809 / 0.648 | 0/20 (0.0%) | 0.299 / 0.905 / 0.450 | 39/50 (78.0%) / 79.8% | 20/24 (83.3%) / 83.3% | 0 (0 excl. empty-label rows) |

### Per requirement (natural v1, mode=ollama)

| Req | Split | Tests | Label targets | Parsed exact | Parsed missed | Parsed extra | Exercised exact | Exercised missed | Exercised extra (n) | Categories missed | Preconditions missed | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NAT-001 | dev | 5 | did:0xF190, service:0x22 | no | did:0xF190 | service:0x10 | no | - | 2 | - | - | - |
| NAT-002 | test | 7 | did:0xF187, did:0xF18C, service:0x22 | yes | - | - | no | - | 3 | - | - | - |
| NAT-003 | dev | 8 | service:0x10 | no | - | did:0xF186, service:0x27, service:0x2E, service:0x31, service:0x3E | no | - | 10 | session | - | - |
| NAT-004 | test (ambiguous) | 4 | service:0x10 | no | - | service:0x27, service:0x2E | no | - | 4 | session | vehicle_stationary | - |
| NAT-005 | dev | 7 | did:0x0100, service:0x10, service:0x27, service:0x2E | no | service:0x10, service:0x27 | - | no | - | 3 | security | - | - |
| NAT-006 | test (ambiguous) | 7 | did:0x0101, service:0x10, service:0x27, service:0x2E | yes | - | - | no | - | 3 | session | - | - |
| NAT-007 | dev | 4 | did:0x0130, service:0x2E | yes | - | - | no | - | 5 | security | - | - |
| NAT-008 | test | 8 | did:0x0131, service:0x2E | no | - | service:0x22, service:0x27 | no | - | 5 | - | - | - |
| NAT-009 | dev | 5 | did:0x0150, service:0x10, service:0x27, service:0x2E | yes | - | - | no | - | 3 | negative | - | - |
| NAT-010 | test | 5 | service:0x27 | no | - | service:0x2E | no | - | 5 | - | - | - |
| NAT-011 | dev | 4 | routine:0x0201, service:0x31 | no | routine:0x0201 | - | no | - | 2 | security | - | - |
| NAT-012 | test | 6 | routine:0x0202, service:0x31 | no | service:0x31 | did:0x0110, did:0x0111, did:0x0140, service:0x10, service:0x27, service:0x2E | no | routine:0x0202, service:0x31 | 8 | positive | extended_session, security_level_1, vehicle_stationary | - |
| NAT-013 | dev | 5 | service:0x11 | no | - | did:0x0150 | no | - | 6 | - | - | - |
| NAT-014 | test | 4 | service:0x19 | no | - | service:0x22 | no | - | 5 | - | - | - |
| NAT-015 | dev | 4 | service:0x3E | no | - | did:0xF186 | no | - | 3 | session | - | - |
| NAT-016 | test | 8 | did:0x0160, service:0x10, service:0x27, service:0x2E | yes | - | - | no | - | 4 | session | - | - |
| NAT-017 | test (ambiguous) | 4 | service:0x14, service:0x19 | no | service:0x19 | - | no | - | 1 | negative | - | - |
| NAT-018 | test | 4 | did:0x0120, service:0x27, service:0x2E | no | did:0x0120 | service:0x10 | no | - | 4 | - | - | - |
| NAT-019 | test | 4 | routine:0x0203, service:0x31 | no | routine:0x0203 | did:0x0150, service:0x10, service:0x27, service:0x2E | no | routine:0x0203, service:0x31 | 7 | - | - | - |
| NAT-020 | test | 8 | (none) | no | - | service:0x10, service:0x22, service:0x27, service:0x2E | no | - | 6 | - | - | - |

## Secondary: in-sample bug detection (26 bugs — in-sample, templates tuned on these) — mode=ollama

Scope: in-sample (templates tuned on these). Generated 19/26 (73.1%), gold 24/26 (92.3%), union 26/26 (100.0%). This is an optimistic, non-independent number: template set v2 was written after seeing which of these bugs v1 missed, by the same author as the catalog.

### Bug detection per injected bug (in-sample) — mode=ollama

| Bug | Category | Generated | Generated detecting tests | Gold | Gold detecting tests |
|---|---|---|---|---|---|
| `nrc_order_did_before_session` | nrc_order | yes | 1: `req_009__tpl_nrc_priority_2e_01` | yes | 1: `gold_write_unknown_did_default_session` |
| `nrc_order_security_before_length` | nrc_order | **no** | 0: - | yes | 1: `gold_write_wrong_length` |
| `general_reject_instead_of_0x12` | format | yes | 8: `req_004__tpl_negative_suppress_10_03`, `req_005__tpl_negative_suppress_10_03`, `req_006__tpl_negative_suppress_10_03` (+5 more) | yes | 4: `gold_session_unsupported_sub`, `gold_ecu_reset_bad_sub`, `gold_dtc_read_bad_sub` (+1 more) |
| `security_not_reset_on_session_change` | session | yes | 6: `req_004__tpl_session_relock_03`, `req_005__tpl_session_relock_01`, `req_006__tpl_session_relock_01` (+3 more) | yes | 1: `gold_security_relocked_on_session_reentry` |
| `s3_timeout_never_fires` | timing | yes | 3: `req_003__tpl_s3_timeout_03`, `req_005__tpl_s3_timeout_03`, `req_006__tpl_s3_timeout_03` | yes | 1: `gold_s3_timeout_reverts` |
| `s3_timeout_off_by_one` | timing | yes | 1: `req_015__tpl_s3_keepalive_03` | yes | 1: `gold_s3_no_timeout_at_exactly_s3ms` |
| `lockout_after_extra_attempt` | security | yes | 1: `req_006__tpl_security_lockout_01` | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_ignored` | security | yes | 1: `req_006__tpl_security_lockout_01` | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_never_expires` | timing | yes | 1: `req_006__tpl_security_lockout_01` | **no** | 0: - |
| `accepts_any_key` | security | yes | 1: `req_006__tpl_security_lockout_01` | yes | 3: `gold_security_wrong_key_once`, `gold_security_lockout_after_3`, `gold_security_wrong_level_unlock` |
| `seed_not_consumed` | sequence | yes | 1: `req_010__tpl_seed_replay_01` | **no** | 0: - |
| `static_seed` | security | yes | 7: `req_004__tpl_session_relock_03`, `req_005__tpl_session_relock_01`, `req_006__tpl_security_lockout_01` (+4 more) | yes | 1: `gold_security_lockout_after_3` |
| `write_ignores_value_range` | data | **no** | 0: - | yes | 2: `gold_write_out_of_range_wiper`, `gold_write_out_of_range_brightness` |
| `readonly_did_writable` | data | yes | 1: `req_001__tpl_write_readonly_f190` | yes | 1: `gold_write_readonly_did` |
| `write_length_off_by_one` | format | **no** | 0: - | yes | 1: `gold_write_wrong_length` |
| `write_positive_sid_wrong` | format | yes | 7: `req_005__tpl_write_secured_0100`, `req_005__tpl_seed_while_unlocked_01`, `req_006__tpl_write_secured_0101` (+4 more) | yes | 5: `gold_write_secured_positive_lighting`, `gold_write_secured_positive_ambient_color`, `gold_write_coding_variant` (+2 more) |
| `session_response_missing_timing` | format | yes | 38: `req_001__tpl_write_readonly_f190`, `req_002__tpl_read_did_positive_f18c_03`, `req_003__tpl_read_did_positive_f186_03` (+35 more) | yes | 35: `gold_read_vin_extended`, `gold_session_to_extended`, `gold_session_back_default` (+32 more) |
| `suppress_bit_ignored` | format | yes | 1: `req_015__tpl_suppress_positive_3e_02` | yes | 2: `gold_tester_present_suppressed`, `gold_ecu_reset_suppressed` |
| `negative_response_suppressed` | format | yes | 9: `req_004__tpl_negative_suppress_10_03`, `req_005__tpl_negative_suppress_10_03`, `req_006__tpl_negative_suppress_10_03` (+6 more) | yes | 1: `gold_tester_present_bad_sub_not_suppressed` |
| `routine_stop_without_start` | sequence | **no** | 0: - | yes | 1: `gold_routine_stop_before_start` |
| `condition_ignored` | data | **no** | 0: - | yes | 2: `gold_routine_door_cal_condition_fail`, `gold_write_factory_reset_flag_moving` |
| `dtc_clear_ignores_group` | data | **no** | 0: - | yes | 2: `gold_dtc_clear_specific`, `gold_dtc_clear_unknown_group` |
| `dtc_clear_noop` | data | yes | 3: `req_014__tpl_dtc_read_clear_B10101`, `req_014__tpl_dtc_read_clear_B10205`, `req_014__tpl_dtc_read_clear_B10310` | yes | 2: `gold_dtc_clear_all`, `gold_dtc_clear_specific` |
| `multi_did_read_first_only` | data | yes | 4: `req_002__tpl_read_multi_f190_f187_01`, `req_005__tpl_read_multi_0100_f190_01`, `req_006__tpl_read_multi_0101_f190_01` (+1 more) | yes | 2: `gold_read_partnum_serial_multi`, `gold_duplicate_did_read` |
| `missing_response_pending` | timing | **no** | 0: - | yes | 1: `gold_routine_nvm_restore_long_running` |
| `dtc_read_ignores_mask` | data | yes | 3: `req_014__tpl_dtc_read_clear_B10101`, `req_014__tpl_dtc_read_clear_B10205`, `req_014__tpl_dtc_read_clear_B10310` | yes | 4: `gold_dtc_read_default`, `gold_dtc_set_and_read`, `gold_dtc_clear_all` (+1 more) |

Invalid tests (fail on the clean simulator, excluded from credit): generated 0, gold 0.
Detected only by the generated suite: lockout_delay_never_expires, seed_not_consumed. Only by gold: nrc_order_security_before_length, write_ignores_value_range, write_length_off_by_one, routine_stop_without_start, condition_ignored, dtc_clear_ignores_group, missing_response_pending. Undetected by both: -.

## Coverage (generated tests per category per seed requirement) — mode=ollama

| Requirement | positive | negative | session | security | timing | total |
|---|---|---|---|---|---|---|
| REQ-001 | 1 | 2 | 0 | 0 | 0 | 3 |
| REQ-002 | 3 | 2 | 0 | 0 | 0 | 5 |
| REQ-003 | 1 | 0 | 0 | 0 | 1 | 2 |
| REQ-004 | 1 | 2 | 1 | 1 | 0 | 5 |
| REQ-005 | 3 | 1 | 1 | 2 | 1 | 8 |
| REQ-006 | 3 | 1 | 0 | 3 | 1 | 8 |
| REQ-007 | 2 | 1 | 0 | 0 | 0 | 3 |
| REQ-008 | 2 | 0 | 0 | 0 | 0 | 2 |
| REQ-009 | 1 | 1 | 1 | 0 | 0 | 3 |
| REQ-010 | 2 | 2 | 1 | 3 | 0 | 8 |
| REQ-011 | 1 | 1 | 2 | 0 | 0 | 4 |
| REQ-012 | 1 | 1 | 2 | 0 | 0 | 4 |
| REQ-013 | 0 | 3 | 0 | 0 | 0 | 3 |
| REQ-014 | 3 | 0 | 1 | 0 | 0 | 4 |
| REQ-015 | 2 | 1 | 0 | 0 | 1 | 4 |
| **total** | 26 | 18 | 9 | 9 | 4 | 66 |

Categories present: 100.0%; requirements covered by ≥2 categories: 13/15.

## Request validity — mode=ollama

- Send steps: 207; decodable: 207; not rejected with a format NRC (0x11/0x12/0x13): 181 (unadjusted rate 87.4%).
- Intentional format probes (NRC in the template's `intended_nrcs`): 26. Adjusted validity: **207/207 (100.0%)**.

## Template reuse and citations — mode=ollama

- Template reuse: 66/66 (100.0%); templates used: 20/27; per template: `dtc_read_clear` 3, `negative_response_with_suppress_bit` 9, `nrc_priority_session_over_identifier` 1, `read_did_invalid_length` 6, `read_did_positive` 12, `read_multiple_dids` 4, `routine_start_results` 2, `s3_keepalive_boundary` 1, `s3_timeout_reverts_session` 3, `security_invalid_key_lockout` 1, `seed_replay_rejected` 1, `seed_request_while_unlocked` 3, `service_not_in_session` 7, `session_change_relocks_security` 4, `session_change_resets_routine` 2, `suppress_positive_response` 1, `write_did_secured_positive` 2, `write_did_value_retained` 2, `write_did_without_security` 1, `write_readonly_did` 1
- Citations: 315/315 valid; tests with ≥1 valid citation: 100.0%.

## Pipeline statistics (seed requirements) — mode=ollama

| Requirement | tests | dropped | rejected | plan attempts | status | wall s |
|---|---|---|---|---|---|---|
| REQ-001 | 3 | 0 | 0 | 1 | completed | 27.872 |
| REQ-002 | 5 | 0 | 0 | 1 | completed | 19.856 |
| REQ-003 | 2 | 0 | 2 | 1 | completed | 18.266 |
| REQ-004 | 5 | 0 | 0 | 1 | completed | 21.657 |
| REQ-005 | 8 | 0 | 0 | 1 | completed | 22.388 |
| REQ-006 | 8 | 0 | 0 | 1 | completed | 27.634 |
| REQ-007 | 3 | 0 | 1 | 1 | completed | 17.915 |
| REQ-008 | 2 | 0 | 2 | 1 | completed | 14.454 |
| REQ-009 | 3 | 0 | 1 | 1 | completed | 18.686 |
| REQ-010 | 8 | 0 | 0 | 1 | completed | 30.079 |
| REQ-011 | 4 | 0 | 0 | 1 | completed | 17.919 |
| REQ-012 | 4 | 0 | 0 | 1 | completed | 19.924 |
| REQ-013 | 3 | 0 | 2 | 1 | completed | 18.889 |
| REQ-014 | 4 | 0 | 2 | 1 | completed | 23.696 |
| REQ-015 | 4 | 0 | 0 | 1 | completed | 19.667 |

Totals: 66 kept, 0 dropped, 10 rejected, 0 re-plans, 0 failed runs.

## Appendix: Self-consistency check (circular by construction) — mode=ollama

Expected bytes in generated tests are produced by the rules-engine oracle, so agreement with a fresh oracle re-run is a consistency check, not an independent accuracy measure. Kept here for completeness; it is not a headline metric.

- Expected-response accuracy vs oracle: 207/207 (100.0%) steps; 66/66 (100.0%) tests.
- Independent simulator (clean): 100.0% of generated tests pass.
- Gold, exact overlap: 6/6 (100.0%) generated/gold pairs with identical step sequences agree.
- Gold, shared prefix: 11/11 (100.0%) distinct send steps reached by an identical prefix in both suites agree.

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
- Ran `generated_tests_test.py` for mode=mock (transport `inprocess`) with pytest in a subprocess: **PASSED** — `206 passed in 1.68s` (8.81 s).
- `exports/ollama/generated_tests_test.py` (mode=ollama)
- `exports/ollama/gold_tests_test.py` (mode=ollama)
- `exports/ollama/generated_tests.can` (mode=ollama)
- `exports/ollama/gold_tests.can` (mode=ollama)
- `generated_tests_ollama.yaml` (mode=ollama)
- Ran `generated_tests_test.py` for mode=ollama (transport `inprocess`) with pytest in a subprocess: **PASSED** — `66 passed in 0.99s` (4.32 s).
- CAPL files (`*.can`) are **UNVERIFIED TEMPLATES — not compiled or run in CANoe**.

## Runtime

| Phase | seconds |
|---|---|
| setup | 5.348 |
| gold_suites | 0.542 |
| mock.generation | 4.63 |
| mock.requirement_understanding | 4.806 |
| mock.requirement_understanding_v2 | 2.776 |
| mock.execution_and_bug_matrices | 30.116 |
| mock.noise_check | 2.811 |
| mock.provenance | 0.269 |
| mock.metrics | 0.324 |
| mock.total | 45.735 |
| ollama.generation | 318.901 |
| ollama.requirement_understanding | 429.04 |
| ollama.requirement_understanding_v2 | 347.644 |
| ollama.execution_and_bug_matrices | 10.581 |
| ollama.noise_run_2 | 340.606 |
| ollama.noise_run_3 | 335.033 |
| ollama.noise_check | 675.795 |
| ollama.provenance | 0.148 |
| ollama.metrics | 0.103 |
| ollama.total | 1782.214 |
| simulator_rules_agreement | 0.531 |
| udsoncan_virtual_can | 0.42 |
| exports | 14.609 |
| retrieval_compare | 4.965 |
| total | 1854.37 |

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
- **heldout_v2_bug_detection_rate**: Same procedure as bug_detection_rate on the 15 held-out v2 bugs in data/bugs/heldout_v2_catalog.yaml (heldout_v2: true), written blind after the Part C freeze. HEADLINE = generated-suite detection, where the generated suite is the tests generated from the 15 seed requirements (the same definition as the held-out v1 headline). Supplementary: detection by the union of all generated tests (seed + natural v1 + natural v2) and by the natural-v2 tests alone. Missed-bug reasons come from eval/heldout_v2.py (static trigger predicates written before any v2 result).
- **natural_v2_understanding**: Requirement understanding on data/requirements_natural_v2.csv (16 rows, split test2, written blind after the freeze) with the same label schema and scoring as the v1 natural set; test2 is the headline split.
- **noise_check**: ollama runs the pipeline over natural v2 --noise-runs times in total; run 1 feeds the tables, every run is listed, and the summary is the mean and min-max range over all runs. mock is deterministic: one run, plus an equality re-run as a check.
