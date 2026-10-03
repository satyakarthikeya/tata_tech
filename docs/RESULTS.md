# Results (honest one-page summary)

Source of every number: [outputs/eval_report.md](../outputs/eval_report.md) (generated 2026-10-03, template set v2, 23 templates, LLM mode `mock`, Bm25Retriever, LangGraph engine). Numbers were copied, not rounded up. Regenerate with `python -m uds_assistant.eval.run_eval --mode mock`.

> The ECU spec is **synthetic** (a fictional Body Control Module written for this project). Every number below is measured against the project's own simulator, not a real ECU.

## Headline table

| Metric | mock | ollama |
|---|---|---|
| 1. Simulator <-> rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 2. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 3. udsoncan virtual-CAN sequence (session -> seed/key -> read -> write -> read-back) | PASS | same (LLM-independent) |
| **4. Held-out bug detection (12 bugs; HEADLINE = generated)** | **generated 3/12 (25.0%)** · gold 3/12 (25.0%) · union 5/12 (41.7%) | pending Part B |
| 5. Requirement understanding (natural requirements) | test split (n=12): target exact match parsed 5/12 (F1 0.700), exercised 2/12 (F1 0.449); category recall 67.9% micro / 69.7% macro; precondition recall 80.0% micro / 75.0% macro; fallback/nothing 3/12 (2 excl. NAT-020-style empty-label rows) | pending Part B |
| 6. Coverage (seed requirements; tests per category) | positive 36, negative 70, session 21, security 18, timing 26; requirements with >=1 test 15/15 (100.0%) | pending Part B |
| 7. Citation validity | 774/774 (100.0%) | pending Part B |

Also in the report: 171 generated tests (94 unique template instantiations) for the 15 seed requirements, 171/171 pass on the clean simulator; the exported pytest file ran in-process with `171 passed`.

## What the numbers mean

- **Held-out 3/12 is the real detection number.** Those 12 bugs were written by an independent subagent that could not see the templates, gold tests, eval, LLM or agent code, and nothing was changed after seeing the results. The generated suite catches 3 of them (25.0%). The 9 misses each have a stated reason, for example no generated test writes a uint16 DID and reads it back, or reads a DID outside its allowed sessions.
- **In-sample 25/26 (96.2%) was optimistic.** Template set v2 was written after seeing which of the 26 catalog bugs v1 missed, by the same author as the catalog (v1 caught 17/26, 65.4%). Treat it as "the templates cover what their author thought of", not as a general detection rate.
- **Self-consistency is circular.** Generated tests pass 171/171 on the clean simulator, but their expected bytes come from the rules engine, which the simulator was checked against. That shows the pieces agree, not that either is right. Rows 1 to 3 are the independent-ish evidence, and even they share an author (row 3, udsoncan, is the only third-party check, and it covers one happy path).
- **Gold and generated suites miss different bugs.** Union is 5/12, so each suite catches something the other does not (for example only gold catches `seed_returned_while_unlocked`; only generated catches `s3_not_refreshed_by_tester_present`).

## Requirement understanding (mock LLM; test split is the main number)

Source: the "Requirement understanding" table in the eval report, 20 labelled natural-language requirements (12 test, 8 dev). Ollama is **pending Part B**.

| Split | n | Targets exact (parsed) | Parsed F1 | Targets exact (exercised) | Exercised F1 |
|---|---|---|---|---|---|
| **test** | 12 | 5/12 (41.7%) | 0.700 | 2/12 (16.7%) | 0.449 |
| dev | 8 | 4/8 (50.0%) | 0.828 | 0/8 (0.0%) | 0.492 |
| all | 20 | 9/20 (45.0%) | 0.754 | 2/20 (10.0%) | 0.468 |

"Parsed" = which services/DIDs/routines the LLM said the requirement is about. "Exercised" = which ones the generated tests actually touch. Parsed precision is high (0.933) but recall is low (0.560): the mock LLM is a keyword stand-in and misses requirements phrased without the expected words. 3 of 12 test-split requirements fell back to nothing or produced zero tests. Exercised precision is low (0.312) because templates add extra generic tests around the target.

## Limitations

- **Synthetic spec.** A fictional BCM, not a real OEM document; no ISO 14229 text is used.
- **Mock LLM only.** All LLM-dependent numbers are from a deterministic keyword stand-in. The local-model run (Ollama, Qwen2.5-3B) has not been run; those cells say "pending Part B". Real-model quality is unknown.
- **Held-out set is small** (12 bugs): one bug is 8.3 percentage points. Treat 25.0% as indicative, not precise.
- **Oracle vs AUTOSAR.** Nine documented disagreements (D1 to D9) with the AUTOSAR Dcm specification are **not fixed** ([SWS_DISAGREEMENTS.md](SWS_DISAGREEMENTS.md)); fixing them means coordinated changes to the oracle, simulator, contract and frozen test data.
- **Same author on both sides.** The simulator, rules engine, gold tests and v2 templates share an author and one prose contract, so shared misreadings are possible.
- **CAPL is unverified.** The `.can` exports were never compiled or run in CANoe.
- **Citation validity** means each citation points at a retrieved chunk; it does not prove the chunk justifies the test.
- **Timing** is in-process wall-clock; P2/P2* overruns are only warnings (0 in the seed run).
- **UI not click-tested** by a human; only a headless smoke run exists. The API and UI are extras to the measured pipeline.
