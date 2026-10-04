# Results (one page)

Every section states its run. Numbers are copied from `outputs/eval_report.json` (rendered at [outputs/eval_report.md](../outputs/eval_report.md)), not rounded up. Nothing here mixes runs inside a section.

| Run label | What | Date (UTC) | Git |
|---|---|---|---|
| **Main eval** | `run_eval --mode ollama --noise-runs 3` (mock and ollama on the same inputs), report version 5 | 2026-10-04 08:15 | `1f0c293` (recorded with uncommitted phase files; generator bytes verified unchanged since, DECISIONS E32/E33, so the numbers stand) |
| **Q&A run** | `qa_eval --modes mock,ollama` (clean tree) | 2026-10-04 13:02 | `9e66f7a` |
| **Timing run** | `scripts/time_generation.py`, 5 requirements x 3 repeats | 2026-10-04 11:51 | `8357ec0` |

> The ECU spec is synthetic (section 6). Everything is measured against the project's own simulator, not a real ECU.

## 1. Correctness, independent of the LLM (Main eval, 2026-10-04, `1f0c293`)

| Check | Result |
|---|---|
| Simulator vs rules engine, seeded random sample (seed 20261003, 89 walks) | 5000/5000 (100.0%) |
| Gold tests passing on the bug-free simulator | 60/60 (100.0%) |
| udsoncan client over ISO-TP on a python-can virtual bus (session, seed/key, read, write, read-back) | PASS (one happy path) |
| Conformance sweep tests passing on the clean simulator; byte provenance | 1200/1200; 1200/1200 |

The simulator is a separate implementation from the rules engine; agreement is the key test. The udsoncan sequence is the only third-party check.

## 2. Bug detection on the freshest blind set (Main eval, 2026-10-04, `1f0c293`)

Held-out v3: 15 bugs written blind after the Part D freeze by a subagent that could not see templates, sweep, gold, eval or LLM code; nothing was tuned on them.

Terms: **generated** = tests generated from the 15 seed requirements (requirement-driven). **gold** = 60 hand-written tests. **sweep** = the conformance sweep, 1200 tests built from the spec alone (no LLM, same in both modes). **full output** = generated plus sweep, per bug (the headline). A bug counts as found if any test fails with it injected. The generated-union-gold figure is not reported for v3.

| Suite | mock | ollama |
|---|---|---|
| **Full output (headline)** | **10/15 (66.7%)** | **9/15 (60.0%)** |
| generated (requirement-driven) | 4/15 (26.7%), 206 tests | 2/15 (13.3%), 73 tests |
| sweep alone | 9/15 (60.0%) | 9/15 (60.0%) |
| gold | 3/15 (20.0%) | 3/15 (20.0%) |

Most of the detection comes from the sweep, not the model. Five bugs are missed in both modes (ollama also misses `dtc_clear_single_clears_neighbour`). One bug is 6.7 points, so a one-bug difference between modes is not evidence.

## 3. Requirement understanding, natural v3 (Main eval, 2026-10-04, `1f0c293`)

16 blind requirements. Mock is deterministic (a second run was identical: range 0). Ollama was run 3 times; values are mean (min-max) over all runs.

| Metric | mock | ollama |
|---|---|---|
| Parsed F1 | 0.407 (range 0) | 0.609 (0.609-0.609) |
| Parsed precision / recall | 0.857 / 0.267 | 0.596 / 0.622 |
| Category recall (micro) | 42.0% (range 0) | 70.0% (70.0%-70.0%) |
| Precondition recall (micro) | 48.3% (range 0) | 89.7% (89.7%-89.7%) |
| Exercised F1 | 0.342 (range 0) | 0.465 (0.462-0.472) |

The model understands more than the mock but over-predicts services (19 false positives on v3). Three runs is a small sample.

## 4. Diagnostic Q&A, blind 25 questions (Q&A run, 2026-10-04, `9e66f7a`)

`data/qa_eval.csv`: 21 answerable, 4 unanswerable; answers must cite retrieved chunks or spec lookups.

| Metric | mock | ollama |
|---|---|---|
| Answer accuracy (answerable) | 90.5% (19/21) | 90.5% (19/21) |
| Citation correctness | 95.2% (20/21) | 90.5% (19/21) |
| Citation precision | 80.6% (25/31) | 79.3% (23/29) |
| Correct not-found (unanswerable) | 75.0% (3/4) | 75.0% (3/4) |
| False not-found / LLM fallback events | 0 / 0 | 0 / 13 |

This clean-tree run reproduced the headline numbers of the earlier run (`3a8c4e3+dirty`, 12:30); only ollama fallback events (12 to 13) and some answer wording differed. Known misses: QA-018 answered instead of refused; QA-022 and QA-023 are retrieval misses.

## 5. Case-study success metrics

| Metric | Value | How measured | Run |
|---|---|---|---|
| Test design time | Tool side, per requirement (mean of 5 requirement means): mock 0.217 s, ollama 19.36 s (ollama range of means 16.25-28.75 s; mock 0.046-0.776 s, the high value includes warm-up). Manual comparison: **pending owner measurement** | wall clock of generation only, in-process; no human review time ([TEST_DESIGN_TIME.md](TEST_DESIGN_TIME.md)) | Timing run, `8357ec0` |
| Generation accuracy (proxy) | Generated send-steps whose expected bytes equal the rules-engine oracle: mock 691/691, ollama 226/226; tests passing on the bug-free simulator: 206/206 and 73/73 | `expected_response_accuracy`. Circular by construction (bytes come from the oracle, never the LLM); the independent evidence is section 1 | Main eval, `1f0c293` |
| Coverage | Seed requirements with at least one generated test: 15/15 (both modes). Sweep: 1034/1034 stimulus-response-class and setup-service items (phase 1); 1336/2038 transition and effect items (phase 2, capped at 1200 tests) | oracle-observable items, not code coverage | Main eval, `1f0c293` |
| Reuse rate (proxy) | Generated tests instantiated from the reusable template catalog: 206/206 mock, 73/73 ollama; catalog templates used: 27/27 and 22/27 | `template_reuse`. 100% by construction, so it shows catalog breadth, not saved effort; exported pytest files also ran green (206 and 73 passed) | Main eval, `1f0c293` |
| Defect detection | v3 full output 10/15 (mock), 9/15 (ollama); see section 2 | held-out v3 bug matrix | Main eval, `1f0c293` |

Manual-vs-tool time, real-engineer reuse and effort saved are **not measured**.

## 6. Spec provenance

The ECU spec (`data/bcm_spec.yaml`) is hand-authored structured data, synthetic and OEM-style, **not** extracted from a PDF. Real OEM diagnostic specifications are confidential and none are public, so none could be used (see [PROJECT.md](../PROJECT.md)). The OEM guideline in the Q&A layer is synthetic too.

## 7. Limitations

- Small samples: 15 bugs, 16 requirements, 25 questions; one item moves a score by 4 to 7 points. One 3B model, prompts tuned on 8 dev rows.
- Synthetic spec and a simulator written by the same team; the sweep and generated tests share the rules-engine oracle, so a misreading shared by engine and simulator is invisible. v3 bugs were written by a language model.
- Seen sets (v1, v2) and in-sample bugs are context only; the sweep misses 5 of 15 fresh bugs, and service precision on fresh phrasing is weak (0.596).
- Test design time and reuse have only tool-side or proxy measures; CAPL exports never ran in CANoe; UI never clicked through in a real browser.
- Open AUTOSAR SWS disagreements D1, D3, D4, D8, D9 ([SWS_DISAGREEMENTS.md](SWS_DISAGREEMENTS.md)).

## 8. History

Earlier runs, kept for the record and not current results:
[eval_report.md#history](../outputs/eval_report.md#history) · [Part D before/after](../outputs/partD/before_after.md) · [Part C results](../outputs/partC/) · [Part D interpretation](../outputs/partD/interpretation.md) · [Q&A per-question table](../outputs/qa/qa_eval.md)
