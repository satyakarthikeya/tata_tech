**Summary.** On the held-out TEST split (n=12), the local Qwen2.5-3B model (`ollama`, prompts frozen at B3 revision 8) does **not** beat the deterministic mock on any headline metric. It is better on parsed-target *recall*. It is worse on parsed precision, F1, exact match, category recall and precondition recall. It is equal on held-out bug detection. It is about 120× slower.

**Where ollama was better**
- **Parsed-target recall on the test split:** 0.880 against 0.560 for mock (fn 3 vs 11).
- **More exact parses on hard rows.** Ollama parsed NAT-002, NAT-006, NAT-008 and NAT-016 exactly. Mock missed DIDs or services on all four; for example, on NAT-006 and NAT-016 mock missed 0x10, 0x27 and 0x2E, because its keyword rules miss session and security services that are only implied.
- **Fewer empty runs.** Ollama had 1 fallback or empty run on the test split (NAT-012). Mock had 3 (NAT-008, NAT-017, NAT-020). Across all 20 natural rows it was 1 against 4.
- **Dev split:** ollama category recall was 72.7% against 63.6%. This split was used for tuning, so it is not evidence.

**Where ollama was worse**
- **Parsed precision collapsed:** 0.512 against 0.933 (fp 21 vs 1). So test-split parsed F1 is 0.647 against 0.700, and parsed exact match is 4/12 against 5/12.
- **Invented identifiers.** The per-requirement table shows the 3B model adding identifiers the requirement never names:
  - DID 0x0140, the example DID in the parse prompt, appears on NAT-012, NAT-014 and NAT-017;
  - 0x10, 0x27 and 0x2E appear on NAT-004, NAT-019 and NAT-020;
  - on NAT-020, which has an empty label set, ollama made 5 tests where mock correctly made none.
- **Exercised exact match:** 0/12 against 2/12; exercised F1 0.435 against 0.449.
- **Category recall:** 18/28 (64.3%) against 19/28 (67.9%).
- **Precondition recall:** 11/15 (73.3%) against 12/15 (80.0%).
- **Generated suite on the seed requirements was much smaller:** 68 tests against 171. Negative tests fell from 70 to 19, session from 21 to 7, timing from 26 to 5.
- **In-sample detection:** 21/26 against 25/26. Ollama additionally missed `routine_stop_without_start`, `dtc_clear_ignores_group`, `dtc_clear_noop` and `dtc_read_ignores_mask`.

**Where they were equal**
- **Held-out bug detection (the headline):** 3/12 for both, the same three bugs: `failed_attempts_reset_by_seed_request`, `s3_not_refreshed_by_tester_present` and `session_suppress_bit_not_masked`. Union with gold was 5/12 for both, so the 2.5× smaller ollama suite lost no held-out detection.
- **Quality checks:** request validity, clean-simulator pass rate and citation validity were 100% in both modes (ollama 335/335 citations, mock 774/774).
- **Byte provenance** passed for every generated test: 158/158 ollama, 343/343 mock.
- **Retries:** no JSON or schema failures, no LLM retries and no re-plans in either mode.

**Validation evidence**
- Ollama had 10 planner choices rejected; mock had 0.
- All 10 were template ids not in the catalog:
  - invented names: `write_did_positive` (REQ-004, NAT-007) and `write_readonly_did_negative` (REQ-001);
  - the known B3 failure of copying the "(category)" suffix into `template_id`, such as `read_did_positive (positive)`. On NAT-012 all four choices were rejected this way, which produced the run's only zero-test requirement.
- The validator caught every one of these, so no invalid test was kept.

**Effect of the 4096-token context budget**
- No prompt was truncated in either mode (0 truncation events, 0 fallback-to-mock events).
- The cost is the shortlist: at most 24 options and at most 4 per template, against the full 154-option catalog the mock plans from.
- The rev-8 instruction asks for selective plans, so ollama kept 3–6 tests per seed requirement against mock's 5–18.
- This explains the lower negative, timing and in-sample coverage. For example, the DTC-clear and routine-stop bugs need template options that a short, selective plan did not choose.
- The same selectivity did not cost held-out detection on this 12-bug catalog.

**Latency**
- Wall-clock time per requirement was 30.8 s mean and 43.4 s p95 for ollama, against 0.25 s mean and 0.45 s p95 for mock. The maximum was 49.4 s.
- The ollama total was about 18 minutes for 35 requirements.
- Explain dominates, at 19.4 s mean per requirement (one LLM call per kept test). Plan takes 7.0 s and parse 4.2 s. Retrieval, instantiation and validation stay under 10 ms.

**Caveats**
- **Small sample.** The test split has n=12, and one requirement moves exact match by 8.3 points and recall noticeably.
- **GPU nondeterminism.** B3 measured about ±0.05 F1 between identical runs. The test-split F1 gap (0.647 vs 0.700, Δ = 0.053) is therefore at the edge of noise. Dev parsed F1 reproduced B3's 0.683 exactly in this run.
- **Little tuning data.** The prompts were tuned on only 8 dev rows, so overfitting to them is plausible; dev exact match was 1/8, the same as in B3.
- **Not compared against the gold tests or a larger model.** The mock's keyword rules were also written by the same author who labelled the requirements, which favours mock on precision.

**Conclusion.** With a 3B model at a 4096-token context, the LLM path is viable and safe: every byte comes from templates, and the validator caught every bad choice. It is not yet better than the rule-based mock. The clearest next steps are stripping the "(category)" suffix before validation (deferred in [PB-B3-RISK]) and suppressing the copied example DID 0x0140.
