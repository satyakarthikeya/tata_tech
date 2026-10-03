# Part C: before / after

Before = frozen baseline `outputs/partC/baseline_before_partC.json` (commit `38aa7197d0a330f6f2f8f550fb3796ea5ae9db20`, report 2026-10-03T09:37:51.233888+00:00). After = `eval_report.json` generated 2026-10-03T20:49:18.726723+00:00 (git `c669e1e1080b873361f0211b01e85f4d14f2cfd5`, template set `v3`).

| Metric | mock before | mock after | ollama before | ollama after |
|---|---|---|---|---|
| **Held-out v2, FRESH (15 bugs): generated / gold / union** | n/a (no v2 before) | 2/15 / 5/15 / 5/15 | n/a (no v2 before) | 2/15 / 5/15 / 5/15 |
| Held-out v1, SEEN (12 bugs): generated / gold / union | 3/12 / 3/12 / 5/12 | 10/12 / 3/12 / 11/12 | 3/12 / 3/12 / 5/12 | 5/12 / 3/12 / 6/12 |
| In-sample (26 bugs): generated / gold / union | 25/26 / 24/26 / 26/26 | 25/26 / 24/26 / 26/26 | 21/26 / 24/26 / 26/26 | 19/26 / 24/26 / 26/26 |
| **Natural v2, FRESH (test2, n=16): parsed exact** | n/a (no v2 before) | 0/16 | n/a (no v2 before) | 4/16 |
| Natural v2, FRESH: parsed P / R / F1 | n/a (no v2 before) | 1.000 / 0.225 / 0.367 | n/a (no v2 before) | 0.565 / 0.796 / 0.661 |
| Natural v2, FRESH: exercised F1 | n/a (no v2 before) | 0.450 | n/a (no v2 before) | 0.583 |
| Natural v2, FRESH: category recall (micro) | n/a (no v2 before) | 48.0% | n/a (no v2 before) | 74.0% |
| Natural v2, FRESH: precondition recall (micro) | n/a (no v2 before) | 55.6% | n/a (no v2 before) | 77.8% |
| Natural v1 test split, SEEN (n=12): parsed exact | 5/12 | 5/12 | 4/12 | 3/12 |
| Natural v1 test split, SEEN: parsed P / R / F1 | 0.933 / 0.560 / 0.700 | 0.933 / 0.560 / 0.700 | 0.512 / 0.880 / 0.647 | 0.500 / 0.840 / 0.627 |
| Natural v1 test split, SEEN: exercised F1 | 0.449 | 0.425 | 0.435 | 0.416 |
| Natural v1 test split, SEEN: category recall (micro) | 67.9% | 67.9% | 64.3% | 82.1% |
| Natural v1 test split, SEEN: precondition recall (micro) | 80.0% | 80.0% | 73.3% | 73.3% |
| Parsed precision / false positives, v1 test split (SEEN) | 0.933 / 1 FP | 0.933 / 1 FP | 0.512 / 21 FP | 0.500 / 21 FP |
| **Parsed precision / false positives, v2 (FRESH)** | n/a (no v2 before) | 1.000 / 0 FP | n/a (no v2 before) | 0.565 / 30 FP |
| Rejected planner choices (15 seed + 20 natural v1) | 0 | 0 | 10 | 15 |
| Rejected planner choices, natural v2 (16, FRESH) | n/a (no v2 before) | 0 | n/a (no v2 before) | 12 |
| Latency per requirement, mean / p95 (35 requirements) | 0.25 s / 0.45 s | 0.27 s / 0.46 s | 30.79 s / 43.41 s | 21.37 s / 28.52 s |
| Explain LLM calls per requirement, mean (min-max) | 9.80 (0-18) (derived from tests kept) | 0.89 (0-1) | 4.51 (0-8) (derived from tests kept) | 1.00 (1-1) |
| SWS disagreements open | 9 | 5 | 9 | 5 |

SWS disagreements: counted from `docs/SWS_DISAGREEMENTS.md`: open D1, D3, D4, D8, D9 (5), FIXED D2, D5, D6, D7 (4); baseline open D1, D2, D3, D4, D5, D6, D7, D8, D9 (9).

**Comparability.** (1) The v2 bug set (15) and the natural-v2 set (16) are different from the v1 sets, so v2 rows are not 'after' values of the v1 rows; there was no v2 'before'. (2) The v1 numbers are SEEN: the Part C templates were designed against the v1 held-out misses, so v1 'after' is not independent evidence; only the v2 rows are fresh. (3) mock is deterministic: its numbers repeat exactly. (4) ollama output varies from run to run (about +-0.05 F1 on parsed targets), so small ollama differences are noise; see the noise-check section of the report. (5) Latency and explain calls are wall-clock / call counts over the 35 seed + natural-v1 requirements in both reports, so they are comparable; the baseline's explain calls are derived from tests kept (explain was one call per kept test).
