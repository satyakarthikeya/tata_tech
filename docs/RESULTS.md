# Results (honest one-page summary)

Source of every number: [outputs/eval_report.md](../outputs/eval_report.md) and `outputs/eval_report.json` (report version 2; generated 2026-10-03, template set v2, 23 templates, Bm25Retriever, LangGraph engine). One invocation (`python -m uds_assistant.eval.run_eval --mode ollama`) ran **both** `mock` and `ollama` on the same inputs, templates and retriever. Numbers were copied, not rounded up. The written interpretation is `outputs/eval_interpretation.md`.

> The ECU spec is **synthetic** (a fictional Body Control Module written for this project). Every number below is measured against the project's own simulator, not a real ECU.

**Headline.** On the held-out TEST split (n=12) the local Qwen2.5-3B model (`ollama`) did **not** beat the deterministic mock on any headline metric. It has higher parsed-target recall (0.880 vs 0.560) but much lower precision (0.512 vs 0.933); held-out bug detection is 3/12 for both; and it is about 120x slower (30.8 s vs 0.25 s mean per requirement, 30.785 s vs 0.254 s unrounded). The mock stays the default.

## Headline table

| Metric | mock | ollama |
|---|---|---|
| 1. Simulator <-> rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 2. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 3. udsoncan virtual-CAN sequence (session -> seed/key -> read -> write -> read-back) | PASS | same (LLM-independent) |
| **4. Held-out bug detection (12 bugs; HEADLINE = generated)** | **generated 3/12 (25.0%)** · gold 3/12 (25.0%) · union 5/12 (41.7%) | **generated 3/12 (25.0%)** · gold 3/12 (25.0%) · union 5/12 (41.7%) |
| 5. Requirement understanding (natural requirements) | test split (n=12): target exact match parsed 5/12 (F1 0.700), exercised 2/12 (F1 0.449); category recall 67.9% micro / 69.7% macro; precondition recall 80.0% micro / 75.0% macro; fallback/nothing 3/12 (2 excl. NAT-020-style empty-label rows) | test split (n=12): target exact match parsed 4/12 (F1 0.647), exercised 0/12 (F1 0.435); category recall 64.3% micro / 64.4% macro; precondition recall 73.3% micro / 75.0% macro; fallback/nothing 1/12 (1 excl. NAT-020-style empty-label rows) |
| 6. Coverage (seed requirements; tests per category) | positive 36, negative 70, session 21, security 18, timing 26; requirements with >=1 test 15/15 (100.0%) | positive 29, negative 19, session 7, security 8, timing 5; requirements with >=1 test 15/15 (100.0%) |
| 7. Citation validity | 774/774 (100.0%) | 335/335 (100.0%) |

Also in the report: for the 15 seed requirements the mock generated 171 tests (94 unique template instantiations) and ollama generated 68; all pass on the clean simulator (171/171 and 68/68).

## Mock vs ollama, side by side

### Requirement understanding, TEST split (n=12, the main number)

| Metric | mock | ollama |
|---|---|---|
| Target exact match, parsed | 5/12 (41.7%) | 4/12 (33.3%) |
| Target exact match, exercised by kept tests | 2/12 (16.7%) | 0/12 (0.0%) |
| Parsed targets P / R / F1 (micro) | 0.933 / 0.560 / 0.700 | 0.512 / 0.880 / 0.647 |
| Parsed targets tp / fp / fn | 14 / 1 / 11 | 22 / 21 / 3 |
| Exercised targets P / R / F1 (micro) | 0.312 / 0.800 / 0.449 | 0.298 / 0.800 / 0.435 |
| Category recall micro (hit/required) / macro | 19/28 (67.9%) / 69.7% | 18/28 (64.3%) / 64.4% |
| Precondition recall micro (hit/required) / macro | 12/15 (80.0%) / 75.0% | 11/15 (73.3%) / 75.0% |
| Fallback / nothing generated | 3 (2 excl. empty-label rows) | 1 (1 excl. empty-label rows) |

The dev split (n=8) is what the prompts were tuned on, so it is not evidence: parsed exact 4/8 (F1 0.828) for mock, 1/8 (F1 0.683) for ollama. All 20 rows: parsed exact 9/20 (F1 0.754) mock, 5/20 (F1 0.661) ollama.

### Held-out bug detection (12 bugs)

| Suite | mock | ollama |
|---|---|---|
| **Generated (headline)** | 3/12 (25.0%) | 3/12 (25.0%) |
| Gold (LLM-independent) | 3/12 (25.0%) | 3/12 (25.0%) |
| Union generated + gold | 5/12 (41.7%) | 5/12 (41.7%) |
| Generated tests (seed requirements) | 171 | 68 |
| Invalid generated tests (fail on clean simulator) | 0 | 0 |

Both generated suites catch the same three bugs: `failed_attempts_reset_by_seed_request`, `s3_not_refreshed_by_tester_present`, `session_suppress_bit_not_masked`. The 2.5x smaller ollama suite lost no held-out detection, but it also gained none.

In-sample (26 bugs; the templates were tuned on these, so secondary): generated 25/26 (96.2%) mock vs 21/26 (80.8%) ollama; gold 24/26 for both; union 26/26 for both. Ollama additionally missed `routine_stop_without_start`, `dtc_clear_ignores_group`, `dtc_clear_noop` and `dtc_read_ignores_mask`.

### Rejections, retries, fallback and truncation events

| | mock | ollama |
|---|---|---|
| Planner choices rejected (35 requirements) | 0 | 10 |
| Re-plans / retries | 0 | 0 |
| Plan attempts | 35 | 35 |
| LLM calls | 413 | 228 |
| JSON/schema failures, LLM errors, failed runs | 0 | 0 |
| Fallback-to-mock events | 0 | 0 |
| Prompt truncation events | 0 | 0 |

All 10 ollama rejections were template ids that are not in the catalog: invented names (`write_did_positive`, `write_readonly_did_negative`) and the known failure of copying the "(category)" suffix into `template_id` (for example `read_did_positive (positive)`; all 4 choices on NAT-012 were rejected this way, which produced the run's only zero-test requirement). The validator caught every one, so no invalid test was kept.

### Latency (wall clock per requirement, 35 requirements)

| | mock | ollama |
|---|---|---|
| mean | 0.254 s | 30.785 s |
| p95 | 0.445 s | 43.405 s |
| max | 0.510 s | 49.394 s |

Ollama's explain node dominates (19.4 s mean per requirement, one LLM call per kept test), then plan (7.0 s) and parse (4.2 s). The whole ollama run took about 18 minutes for 35 requirements on an RTX 3050 Laptop GPU (4 GB).

### Byte provenance

Every generated test re-instantiates byte-for-byte from `TEMPLATES[template_id]` with its stored parameters: **343/343** (mock) and **158/158** (ollama). This is what "the LLM never emits bytes" means in practice: even when the 3B model picks bad templates, no model-written byte reaches a test.

### Retrieval: BM25 vs Chroma (bge-small-en-v1.5 via fastembed)

19 of 20 natural requirements scored (NAT-020 has no target). Relevant chunk = the spec chunk carrying the target DID/routine, or the standard `svc-<sid>` chunk for service-only targets.

| split | backend | queries | hit@1 | hit@3 | MRR | citation validity (top 3) |
|---|---|---|---|---|---|---|
| dev | bm25 | 8 | 0.0% | 37.5% | 0.271 | 100.0% |
| dev | chroma | 8 | 0.0% | 75.0% | 0.374 | 100.0% |
| **test** | **bm25** | 11 | 36.4% | 63.6% | 0.552 | 100.0% |
| **test** | **chroma** | 11 | 18.2% | 63.6% | 0.462 | 100.0% |
| all | bm25 | 19 | 21.1% | 52.6% | 0.434 | 100.0% |
| all | chroma | 19 | 10.5% | 68.4% | 0.425 | 100.0% |

On the test split BM25 is ahead on hit@1 and MRR and the two tie on hit@3; Chroma is ahead on dev and on hit@3 over all rows. Neither backend is clearly better on 19 queries, so the default stays BM25.

## Interpretation

Condensed from `outputs/eval_interpretation.md`, written after the numbers existed; no number was edited by hand.

- **Where ollama was better.** Parsed-target recall on the test split (0.880 vs 0.560; 3 vs 11 missed targets). It parsed NAT-002, NAT-006, NAT-008 and NAT-016 exactly where the keyword-based mock missed session and security services that are only implied. It had 1 empty run on the test split against 3 for the mock.
- **Where ollama was worse.** Parsed precision collapsed (0.512 vs 0.933; 21 false positives vs 1) because the 3B model invents identifiers: the prompt's example DID 0x0140 appears on NAT-012, NAT-014 and NAT-017, and 0x10/0x27/0x2E appear on rows that never name them. On NAT-020, which has an empty label set, ollama made 5 tests where the mock correctly made none. Parsed exact match, F1, category recall, precondition recall and exercised exact match are all lower. Its suite on the seed requirements was much smaller (68 vs 171 tests).
- **Where they were equal.** Held-out detection (3/12, the same three bugs), request validity, clean-simulator pass rate, citation validity and byte provenance (all 100%).
- **Effect of the 4096-token context.** No prompt was truncated in either mode. The cost is the shortlist: at most 24 options and at most 4 per template, against the full 154-option catalog the mock plans from, plus a rev-8 instruction asking for selective plans (3 to 6 tests per seed requirement against 5 to 18). That explains the lower negative, timing and in-sample coverage; it did not cost held-out detection on this 12-bug catalog.
- **Conclusion.** The LLM path is viable and safe (every byte comes from templates, the validator caught every bad choice), but with a 3B model at 4096 tokens it is not better than the rule-based mock. Next steps that target observed failures: strip the "(category)" suffix before validation and suppress the copied example DID.

## What the numbers mean

- **Held-out 3/12 is the real detection number.** Those 12 bugs were written by an independent subagent that could not see the templates, gold tests, eval, LLM or agent code, and nothing was changed after seeing the results. The 9 misses each have a stated reason, for example no generated test writes a uint16 DID and reads it back, or reads a DID outside its allowed sessions. Both modes share these gaps because they share the templates.
- **The LLM does not change what the templates can do.** The same templates sit behind both modes, which is why detection is equal. A better planner can only choose better among the same 154 options.
- **In-sample 25/26 was optimistic.** Template set v2 was written after seeing which of the 26 catalog bugs v1 missed, by the same author as the catalog (v1 caught 17/26, 65.4%). Treat it as "the templates cover what their author thought of".
- **Self-consistency is circular.** Generated tests pass on the clean simulator, but their expected bytes come from the rules engine, which the simulator was checked against. Rows 1 to 3 are the independent-ish evidence, and even they share an author (row 3, udsoncan, is the only third-party check, and it covers one happy path).
- **Gold and generated suites miss different bugs.** Union is 5/12 in both modes.

## Limitations

- **Small samples.** The held-out set has 12 bugs and the test split 12 requirements: one item is 8.3 percentage points. Treat every difference as indicative, not precise.
- **GPU nondeterminism.** Greedy decoding on the GPU is not bit-reproducible: identical runs differ by about +-0.05 F1. The test-split parsed-F1 gap (0.647 vs 0.700, delta 0.053) is at the edge of noise. The precision gap (0.512 vs 0.933) is far outside it.
- **Prompts tuned on 8 dev rows only.** Revision 8 was selected on the dev split (parsed F1 0.683 reproduced exactly in the final run, but dev exact match was only 1/8). Overfitting to those rows is plausible. The test split was run in ollama mode once, after the freeze.
- **Plan-context shortlist.** To fit 4096 tokens the planner sees at most 24 options (4 per template) instead of all 154. The ollama column therefore measures "3B model with a shortlist", not "3B model with the full catalog". A larger context or model was not tested.
- **One model, one prompt revision.** Only `qwen2.5:3b-instruct-q4_K_M` was evaluated; no larger model, no other prompt set, no fine-tuning.
- **Mock favoured on precision.** The mock's keyword rules and the requirement labels share an author.
- **Synthetic spec.** A fictional BCM, not a real OEM document; no ISO 14229 text is used.
- **Oracle vs AUTOSAR.** Nine documented disagreements (D1 to D9) with the AUTOSAR Dcm specification are **not fixed** ([SWS_DISAGREEMENTS.md](SWS_DISAGREEMENTS.md)); D2, D5, D6 and D7 are the ones to fix first, with a new held-out bug set.
- **Same author on both sides.** The simulator, rules engine, gold tests and v2 templates share an author and one prose contract, so shared misreadings are possible.
- **CAPL is unverified.** The `.can` exports were never compiled or run in CANoe.
- **Citation validity** means each citation points at a retrieved chunk; it does not prove the chunk justifies the test.
- **Timing** is in-process wall-clock; P2/P2* overruns are only warnings.
- **UI not click-tested by a human**; only headless AppTest runs exist. The API and UI are extras to the measured pipeline.
