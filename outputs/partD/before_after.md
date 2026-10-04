# Part D: before / after

Before = frozen baseline `outputs/partD/baseline_before_partD.json` (the Part C final report, commit `942f43898de38361f0797c5009e3cfcfd6f042c0`, report 2026-10-03T20:49:18.726723+00:00). After = `eval_report.json` generated 2026-10-04T08:15:23.200078+00:00 (git `1f0c293a2033da0e4316197341c814d10aa16b1f`, report version 5, template set `v3`).

## (i) FRESH v3 rows (written blind after the Part D freeze; after only)

| Metric | mock after | ollama after |
|---|---|---|
| **Held-out v3 bugs (15): FULL OUTPUT = requirement-driven + sweep (headline)** | **10/15** | **9/15** |
| (a) requirement-driven only (comparable with Part C) | 4/15 | 2/15 |
| (b) conformance sweep alone (LLM-independent) | 9/15 | 9/15 |
| (d) gold (LLM-independent) | 3/15 | 3/15 |
| Suite sizes (tests) | 206 requirement-driven, 1200 sweep, 1406 full output | 73 requirement-driven, 1200 sweep, 1273 full output |
| **Natural v3 (test3, n=16): parsed exact** | 1/16 | 2/16 |
| Natural v3: parsed P / R / F1 | 0.857 / 0.267 / 0.407 | 0.596 / 0.622 / 0.609 |
| Natural v3: exercised F1 | 0.342 | 0.472 |
| Natural v3: category recall (micro) | 42.0% | 70.0% |
| Natural v3: precondition recall (micro) | 48.3% | 89.7% |
| Natural v3: fallback / nothing generated | 7 | 0 |
| Natural v3: parsed false positives by kind | service 2 | service 15, did 4 |
| Natural v3: parsed false negatives by kind | service 24, did 8, routine 1 | service 9, did 5, routine 3 |
| Natural v3: rejected planner choices by reason | 0 (none) | 0 (none) |
| Natural v3: noise check | 1 run(s), parsed F1 mean 0.407 (min-max 0.407-0.407) | 3 run(s), parsed F1 mean 0.609 (min-max 0.609-0.609) |

## (ii) SEEN v2 rows, before / after (context only: v2 is seen)

| Metric | mock before | mock after | ollama before | ollama after |
|---|---|---|---|---|
| Held-out v2 bugs (15, SEEN): requirement-driven (generated) | 2/15 | 2/15 | 2/15 | 2/15 |
| Held-out v2 bugs (SEEN): FULL OUTPUT (Part C had no sweep: = requirement-driven) | 2/15 | 9/15 | 2/15 | 9/15 |
| Held-out v2 bugs (SEEN): gold | 5/15 | 5/15 | 5/15 | 5/15 |
| Natural v2 (test2, n=16, SEEN): parsed exact | 0/16 | 0/16 | 4/16 | 4/16 |
| Natural v2 (test2, n=16, SEEN): parsed P / R / F1 | 1.000 / 0.225 / 0.367 | 1.000 / 0.225 / 0.367 | 0.565 / 0.796 / 0.661 | 0.808 / 0.775 / 0.792 |
| Natural v2 (test2, n=16, SEEN): exercised F1 | 0.450 | 0.450 | 0.583 | 0.639 |
| Natural v2 (test2, n=16, SEEN): category recall (micro) | 48.0% | 48.0% | 74.0% | 72.0% |
| Natural v2 (test2, n=16, SEEN): precondition recall (micro) | 55.6% | 55.6% | 77.8% | 92.6% |
| Natural v2 (SEEN): parsed false positives by kind | none | none | service 25, did 5 | service 6, did 3 |
| Natural v2 (SEEN): parsed false negatives by kind | service 30, did 7, routine 1 | service 30, did 7, routine 1 | service 6, did 2, routine 2 | service 7, did 2, routine 2 |

## (iii) Rejected planner choices by reason

| Set | mock before | mock after | ollama before | ollama after |
|---|---|---|---|---|
| 15 seed + 20 natural v1 requirements (SEEN) | 0 (none) | 0 (none) | 15 (unknown template id 2, option index out of range 3, option not in the offered shortlist 10) | 0 (none) |
| Natural v2 (16, SEEN) | 0 (none) | 0 (none) | 12 (unknown template id 6, option index out of range 2, option not in the offered shortlist 4) | 0 (none) |

Natural v3 (FRESH, after only): mock: 0 (none); ollama: 0 (none)

## (iv) Parsed false positives by kind

| Set | mock before | mock after | ollama before | ollama after |
|---|---|---|---|---|
| Natural v1 test split (n=12, SEEN) | service 1 | service 1 | service 17, did 4 | service 5, did 4 |
| Natural v2 (n=16, SEEN) | none | none | service 25, did 5 | service 6, did 3 |

Natural v3 (FRESH, after only): mock: service 2; ollama: service 15, did 4


## (v) Latency and explain calls (35 seed + natural-v1 requirements)

| Metric | mock before | mock after | ollama before | ollama after |
|---|---|---|---|---|
| Latency per requirement, mean / p95 | 0.27 s / 0.46 s | 0.38 s / 0.63 s | 21.37 s / 28.52 s | 21.85 s / 30.41 s |
| Explain LLM calls per requirement, mean (min-max) | 0.89 (0-1) | 0.89 (0-1) | 1.00 (1-1) | 0.97 (0-1) |

## (vi) SWS disagreements

| Metric | before | after |
|---|---|---|
| SWS disagreements open | 5 | 5 |

Counted from `docs/SWS_DISAGREEMENTS.md`: open D1, D3, D4, D8, D9 (5), FIXED D2, D5, D6, D7 (4); baseline open D1, D3, D4, D8, D9 (5).

## (vii) Test counts: requirement-driven suite vs full output

| Suite (tests) | mock before | mock after | ollama before | ollama after |
|---|---|---|---|---|
| requirement-driven / full output (Part C: no sweep) | 206 requirement-driven / 206 full output | 206 requirement-driven / 1406 full output | 66 requirement-driven / 66 full output | 73 requirement-driven / 1273 full output |

**Comparability.** (1) The v3 bug set (15) and the natural-v3 set (16) are fresh and different from the v1 and v2 sets, so the v3 rows have only an 'after' value; they are not 'after' values of the v2 rows. (2) v1 and v2 (bugs and natural requirements) are SEEN: their Part C results were known when Part D was designed, so the v2 before/after rows are context, not independent evidence; only the v3 rows are. (3) mock is deterministic: its numbers repeat exactly. (4) ollama output varies from run to run, so small ollama differences are noise; the v3 noise check (mean and min-max over all runs) is in the report. (5) The conformance sweep is LLM-independent: it is identical in every mode, so 'full output' differs between modes only through the requirement-driven part. (6) Part C had no sweep, so its 'full output' equals its requirement-driven suite. (7) Latency, explain calls and the rejected-choice rows over the 35 seed + natural-v1 requirements use the same requirements in both reports; the baseline's explain calls are derived from tests kept only if the report lacks per-node LLM call counts.
