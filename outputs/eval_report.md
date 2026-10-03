# Evaluation report — UDS test generation assistant

- **Generated:** 2026-10-03T09:37:51.233888+00:00 (git `a6a311f1d8a0eee76f97517f4846efbbb4bbcdb8`, uncommitted changes present)
- **LLM mode used:** `ollama` (requested `ollama`)
- **Modes evaluated in this invocation:** `mock`, `ollama`
- **Agent engine:** `langgraph` · **Retriever:** `Bm25Retriever`
- **Template set:** `v2` (23 templates)
- **Inputs:** 15 seed requirements, 20 labelled natural requirements, 60 gold tests, 12 held-out + 26 in-sample injectable simulator bugs
- **Ollama settings:** model `qwen2.5:3b-instruct-q4_K_M`, num_ctx 4096, temperature 0, keep_alive `10m`
- **Byte provenance:** all generated tests re-instantiate byte-identically from their templates

> **The ECU spec is synthetic.** `data/bcm_spec.yaml` describes a fictional Body Control Module written for this project in an OEM-like style; no real OEM document or ISO 14229 text is used. All numbers below are measured against the project's own simulator.
>
> **Modes:** `mock` is a deterministic keyword/rule stand-in; `ollama` is the local Qwen2.5-3B model. Both columns come from this single invocation, on the same inputs, templates and retriever. LLM-independent rows are identical for both.

> **Template set v2:** v1 + 9 generic templates (multi-DID read, write to read-only DID, session change re-locks security, key replay, DTC clear specific/unknown group, negative response with suppress bit, S3 keep-alive boundary, NRC priority session-before-identifier, routine start+results incl. 0x78) and a fix so routine starts carry the spec'd option record. Added in Phase 7 AFTER inspecting which catalog bugs v1 missed; the same author wrote the bug catalog, so v2 detection is an optimistic, non-independent number.

## Headline metrics

| Metric | mock | ollama |
|---|---|---|
| 1. Simulator ↔ rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 2. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 3. udsoncan virtual-CAN sequence (session → seed/key → read → write → read-back) | PASS | same (LLM-independent) |
| **4. Held-out bug detection (12 bugs; HEADLINE = generated)** | **generated 3/12 (25.0%)** · gold 3/12 (25.0%) · union 5/12 (41.7%) | **generated 3/12 (25.0%)** · gold 3/12 (25.0%) · union 5/12 (41.7%) |
| 5. Requirement understanding (natural requirements) | test split (n=12): target exact match parsed 5/12 (F1 0.700), exercised 2/12 (F1 0.449); category recall 67.9% micro / 69.7% macro; precondition recall 80.0% micro / 75.0% macro; fallback/nothing 3/12 (2 excl. NAT-020-style empty-label rows) | test split (n=12): target exact match parsed 4/12 (F1 0.647), exercised 0/12 (F1 0.435); category recall 64.3% micro / 64.4% macro; precondition recall 73.3% micro / 75.0% macro; fallback/nothing 1/12 (1 excl. NAT-020-style empty-label rows) |
| 6. Coverage (seed requirements; tests per category) | positive 36, negative 70, session 21, security 18, timing 26; requirements with ≥1 test 15/15 (100.0%) | positive 29, negative 19, session 7, security 8, timing 5; requirements with ≥1 test 15/15 (100.0%) |
| 7. Citation validity | 774/774 (100.0%) | 335/335 (100.0%) |

Rows 1-3 and the gold number in row 4 do not depend on the LLM; row 4 generated/union and rows 5-7 do. The self-consistency check (expected responses vs the oracle that produced them) is in the appendix, and the in-sample 26-bug detection is a secondary section, because the templates were tuned on those bugs.

## Interpretation: where the LLM helped and where it didn't

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

_Written after reading the measured numbers in this report (source `outputs/eval_interpretation.md`); no number was edited by hand._

## Mock vs Ollama — side by side

### Requirement understanding — TEST split (headline)

Natural requirements from `data/requirements_natural.csv`. The prompts were tuned on the 8 dev rows only and frozen before the test split was run in Ollama mode.

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 12 | 12 |
| Target exact match — parsed | 5/12 (41.7%) | 4/12 (33.3%) |
| Target exact match — exercised by kept tests | 2/12 (16.7%) | 0/12 (0.0%) |
| Parsed targets P / R / F1 (micro) | 0.933 / 0.560 / 0.700 | 0.512 / 0.880 / 0.647 |
| Parsed targets tp / fp / fn | 14 / 1 / 11 | 22 / 21 / 3 |
| Exercised targets P / R / F1 (micro) | 0.312 / 0.800 / 0.449 | 0.298 / 0.800 / 0.435 |
| Category recall micro (hit/required) / macro | 19/28 (67.9%) / 69.7% | 18/28 (64.3%) / 64.4% |
| Precondition recall micro (hit/required) / macro | 12/15 (80.0%) / 75.0% | 11/15 (73.3%) / 75.0% |
| Fallback / nothing generated | 3 (2 excl. empty-label rows) | 1 (1 excl. empty-label rows) |

Per requirement, test split:

| Req | Label targets | mock parsed exact | mock parsed miss/extra | mock tests (categories missed) | mock preconds missed | ollama parsed exact | ollama parsed miss/extra | ollama tests (categories missed) | ollama preconds missed |
|---|---|---|---|---|---|---|---|---|---|
| NAT-002 | did:0xF187, did:0xF18C, service:0x22 | no | miss did:0xF18C; extra - | 13 (none missed) | - | yes | miss -; extra - | 6 (none missed) | - |
| NAT-004 | service:0x10 | yes | miss -; extra - | 9 (session missed) | vehicle_stationary | no | miss -; extra did:0xF186, service:0x27, service:0x2E | 4 (session missed) | vehicle_stationary |
| NAT-006 | did:0x0101, service:0x10, service:0x27, service:0x2E | no | miss service:0x10, service:0x27, service:0x2E; extra - | 12 (none missed) | - | yes | miss -; extra - | 4 (session missed) | - |
| NAT-008 | did:0x0131, service:0x2E | no | miss service:0x2E; extra - | 0 (negative, security missed) | extended_session, security_level_1 | yes | miss -; extra - | 4 (security missed) | - |
| NAT-010 | service:0x27 | yes | miss -; extra - | 3 (security, timing missed) | - | no | miss -; extra did:0x0101 | 4 (negative, timing missed) | - |
| NAT-012 | routine:0x0202, service:0x31 | yes | miss -; extra - | 12 (none missed) | - | no | miss routine:0x0202; extra did:0x0140, service:0x10, service:0x2E, service:0x3E | 0 (negative, positive missed) | extended_session, security_level_1, vehicle_stationary |
| NAT-014 | service:0x19 | no | miss -; extra service:0x22 | 11 (none missed) | - | no | miss -; extra did:0x0140 | 4 (none missed) | - |
| NAT-016 | did:0x0160, service:0x10, service:0x27, service:0x2E | no | miss service:0x10, service:0x27, service:0x2E; extra - | 11 (none missed) | - | yes | miss -; extra - | 4 (session missed) | - |
| NAT-017 | service:0x14, service:0x19 | no | miss service:0x14, service:0x19; extra - | 0 (negative, positive, session missed) | - | no | miss service:0x19; extra did:0x0140 | 4 (none missed) | - |
| NAT-018 | did:0x0120, service:0x27, service:0x2E | no | miss service:0x27; extra - | 12 (none missed) | - | no | miss -; extra did:0x0110, did:0x0111, service:0x10 | 4 (security missed) | - |
| NAT-019 | routine:0x0203, service:0x31 | yes | miss -; extra - | 14 (positive missed) | - | no | miss routine:0x0203; extra did:0x0150, service:0x10, service:0x27, service:0x2E | 4 (timing missed) | - |
| NAT-020 | (none) | yes | miss -; extra - | 0 (none missed) | - | no | miss -; extra did:0x0150, service:0x10, service:0x11, service:0x2E | 5 (none missed) | - |

### Requirement understanding — dev split (the rows the prompts were tuned on)

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 8 | 8 |
| Target exact match — parsed | 4/8 (50.0%) | 1/8 (12.5%) |
| Target exact match — exercised by kept tests | 0/8 (0.0%) | 0/8 (0.0%) |
| Parsed targets P / R / F1 (micro) | 1.000 / 0.706 / 0.828 | 0.583 / 0.824 / 0.683 |
| Parsed targets tp / fp / fn | 12 / 0 / 5 | 14 / 10 / 3 |
| Exercised targets P / R / F1 (micro) | 0.333 / 0.941 / 0.492 | 0.347 / 1.000 / 0.515 |
| Category recall micro (hit/required) / macro | 14/22 (63.6%) / 60.4% | 16/22 (72.7%) / 77.1% |
| Precondition recall micro (hit/required) / macro | 9/9 (100.0%) / 100.0% | 9/9 (100.0%) / 100.0% |
| Fallback / nothing generated | 1 (1 excl. empty-label rows) | 0 (0 excl. empty-label rows) |

### Requirement understanding — all split

| Metric | mock | ollama |
|---|---|---|
| Requirements (n) | 20 | 20 |
| Target exact match — parsed | 9/20 (45.0%) | 5/20 (25.0%) |
| Target exact match — exercised by kept tests | 2/20 (10.0%) | 0/20 (0.0%) |
| Parsed targets P / R / F1 (micro) | 0.963 / 0.619 / 0.754 | 0.537 / 0.857 / 0.661 |
| Parsed targets tp / fp / fn | 26 / 1 / 16 | 36 / 31 / 6 |
| Exercised targets P / R / F1 (micro) | 0.321 / 0.857 / 0.468 | 0.319 / 0.881 / 0.468 |
| Category recall micro (hit/required) / macro | 33/50 (66.0%) / 65.8% | 34/50 (68.0%) / 69.7% |
| Precondition recall micro (hit/required) / macro | 21/24 (87.5%) / 83.3% | 20/24 (83.3%) / 83.3% |
| Fallback / nothing generated | 4 (3 excl. empty-label rows) | 1 (1 excl. empty-label rows) |

Per requirement, dev split:

| Req | Label targets | mock parsed exact | mock parsed miss/extra | mock tests (categories missed) | mock preconds missed | ollama parsed exact | ollama parsed miss/extra | ollama tests (categories missed) | ollama preconds missed |
|---|---|---|---|---|---|---|---|---|---|
| NAT-001 | did:0xF190, service:0x22 | yes | miss -; extra - | 17 (none missed) | - | no | miss did:0xF190; extra did:0xF18C, service:0x10 | 6 (none missed) | - |
| NAT-003 | service:0x10 | no | miss service:0x10; extra - | 0 (positive, session missed) | - | no | miss -; extra did:0xF186, service:0x27, service:0x2E, service:0x3E | 7 (none missed) | - |
| NAT-005 | did:0x0100, service:0x10, service:0x27, service:0x2E | no | miss service:0x10; extra - | 14 (none missed) | - | no | miss service:0x27; extra - | 7 (security missed) | - |
| NAT-007 | did:0x0130, service:0x2E | no | miss service:0x2E; extra - | 7 (security missed) | - | no | miss -; extra service:0x10, service:0x27 | 3 (security missed) | - |
| NAT-009 | did:0x0150, service:0x10, service:0x27, service:0x2E | no | miss service:0x10, service:0x27; extra - | 13 (positive missed) | - | yes | miss -; extra - | 4 (session missed) | - |
| NAT-011 | routine:0x0201, service:0x31 | yes | miss -; extra - | 9 (security missed) | - | no | miss routine:0x0201; extra - | 4 (security, session missed) | - |
| NAT-013 | service:0x11 | yes | miss -; extra - | 6 (positive missed) | - | no | miss -; extra did:0x0140 | 8 (none missed) | - |
| NAT-015 | service:0x3E | yes | miss -; extra - | 9 (session, timing missed) | - | no | miss -; extra did:0x0140 | 4 (session missed) | - |

### Held-out bug detection (12 bugs) — generated suite, gold, union

| Suite | mock | ollama |
|---|---|---|
| **Generated (headline)** | 3/12 (25.0%) | 3/12 (25.0%) |
| Gold (LLM-independent) | 3/12 (25.0%) | 3/12 (25.0%) |
| Union generated ∪ gold | 5/12 (41.7%) | 5/12 (41.7%) |
| Generated tests (seed requirements) | 171 | 68 |
| Invalid generated tests (fail on clean simulator) | 0 | 0 |

Per held-out bug (generated suite):

| Bug | Category | mock generated | ollama generated | gold |
|---|---|---|---|---|
| `routine_state_survives_session_change` | session | **no** (0 tests) | **no** (0 tests) | **no** |
| `failed_attempts_reset_by_seed_request` | security | yes (6 tests) | yes (3 tests) | yes |
| `seed_returned_while_unlocked` | security | **no** (0 tests) | **no** (0 tests) | yes |
| `nrc_order_condition_before_security` | nrc_order | **no** (0 tests) | **no** (0 tests) | **no** |
| `read_did_odd_length_truncated` | format | **no** (0 tests) | **no** (0 tests) | **no** |
| `read_did_session_restriction_ignored` | data | **no** (0 tests) | **no** (0 tests) | **no** |
| `uint16_did_stored_byte_swapped` | data | **no** (0 tests) | **no** (0 tests) | yes |
| `s3_not_refreshed_by_tester_present` | timing | yes (13 tests) | yes (1 tests) | **no** |
| `ecu_reset_clears_security_lockout` | security | **no** (0 tests) | **no** (0 tests) | **no** |
| `s3_timeout_reverts_written_dids` | timing | **no** (0 tests) | **no** (0 tests) | **no** |
| `session_suppress_bit_not_masked` | format | yes (3 tests) | yes (1 tests) | **no** |
| `suppress_bit_echoed_in_response` | format | **no** (0 tests) | **no** (0 tests) | **no** |

### In-sample bug detection (26 bugs — templates tuned on these)

| Suite | mock | ollama |
|---|---|---|
| Generated | 25/26 (96.2%) | 21/26 (80.8%) |
| Gold | 24/26 (92.3%) | 24/26 (92.3%) |
| Union | 26/26 (100.0%) | 26/26 (100.0%) |
| Undetected by the generated suite | missing_response_pending | routine_stop_without_start, dtc_clear_ignores_group, dtc_clear_noop, missing_response_pending, dtc_read_ignores_mask |

### Validation: rejections, re-plans (retries), plan attempts, dropped tests

Per requirement (15 seed + 20 natural). *rejected* = planner choices refused (unknown template/option, outside the shortlist, or failed validation); *retries* = re-plan rounds (plan attempts − 1); *dropped* = instantiated tests that failed validation.

| Req | Split | mock tests | mock rejected | mock retries | mock plan attempts | mock dropped | ollama tests | ollama rejected | ollama retries | ollama plan attempts | ollama dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| REQ-001 | seed | 17 | 0 | 0 | 1 | 0 | 3 | 1 | 0 | 1 | 0 |
| REQ-002 | seed | 18 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| REQ-003 | seed | 8 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-004 | seed | 5 | 0 | 0 | 1 | 0 | 4 | 4 | 0 | 1 | 0 |
| REQ-005 | seed | 14 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| REQ-006 | seed | 14 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| REQ-007 | seed | 12 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| REQ-008 | seed | 12 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-009 | seed | 15 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| REQ-010 | seed | 6 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| REQ-011 | seed | 9 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| REQ-012 | seed | 12 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-013 | seed | 6 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| REQ-014 | seed | 10 | 0 | 0 | 1 | 0 | 3 | 0 | 0 | 1 | 0 |
| REQ-015 | seed | 13 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-001 | dev | 17 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| NAT-002 | test | 13 | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 1 | 0 |
| NAT-003 | dev | 0 | 0 | 0 | 1 | 0 | 7 | 0 | 0 | 1 | 0 |
| NAT-004 | test | 9 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-005 | dev | 14 | 0 | 0 | 1 | 0 | 7 | 0 | 0 | 1 | 0 |
| NAT-006 | test | 12 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-007 | dev | 7 | 0 | 0 | 1 | 0 | 3 | 1 | 0 | 1 | 0 |
| NAT-008 | test | 0 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-009 | dev | 13 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-010 | test | 3 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-011 | dev | 9 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-012 | test | 12 | 0 | 0 | 1 | 0 | 0 | 4 | 0 | 1 | 0 |
| NAT-013 | dev | 6 | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 1 | 0 |
| NAT-014 | test | 11 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-015 | dev | 9 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-016 | test | 11 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-017 | test | 0 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-018 | test | 12 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-019 | test | 14 | 0 | 0 | 1 | 0 | 4 | 0 | 0 | 1 | 0 |
| NAT-020 | test | 0 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 1 | 0 |
| **total** |  | 343 | 0 | 0 | 35 | 0 | 158 | 10 | 0 | 35 | 0 |

LLM call counters (all 35 requirements):

| Counter | mock | ollama |
|---|---|---|
| LLM calls | 413 | 228 |
| JSON/schema failures | 0 | 0 |
| LLM re-prompts/retries | 0 | 0 |
| LLM errors | 0 | 0 |
| Failed pipeline runs | 0 | 0 |

Rejection reasons — `mock` (0):

- none

Rejection reasons — `ollama` (10):

- REQ-001: plan: write_readonly_did_negative[0]: unknown template id 'write_readonly_did_negative'
- REQ-004: plan: write_did_positive[0]: unknown template id 'write_did_positive'
- REQ-004: plan: write_did_positive[1]: unknown template id 'write_did_positive'
- REQ-004: plan: write_did_positive[2]: unknown template id 'write_did_positive'
- REQ-004: plan: write_did_positive[3]: unknown template id 'write_did_positive'
- NAT-007: plan: write_did_positive[27]: unknown template id 'write_did_positive'
- NAT-012: plan: read_did_positive (positive)[34]: unknown template id 'read_did_positive (positive)'
- NAT-012: plan: negative_response_with_suppress_bit (negative)[5]: unknown template id 'negative_response_with_suppress_bit (negative)'
- NAT-012: plan: s3_timeout_reverts_session (timing)[0]: unknown template id 's3_timeout_reverts_session (timing)'
- NAT-012: plan: s3_keepalive_boundary (timing)[1]: unknown template id 's3_keepalive_boundary (timing)'

### Fallback-to-mock and truncation events (verbatim)

**`mock` — fallback events (0):**

- none

**`mock` — truncation events (0):**

- none

**`ollama` — fallback events (0):**

- none

**`ollama` — truncation events (0):**

- none

### Latency per requirement (wall clock)

| Scope | mock mean | ollama mean | mock p95 | ollama p95 | mock max | ollama max |
|---|---|---|---|---|---|---|
| seed (n=15) | 0.3 s | 30.9 s | 0.5 s | 39.6 s | 0.5 s | 39.6 s |
| natural (n=20) | 0.2 s | 30.7 s | 0.4 s | 43.4 s | 0.4 s | 49.4 s |
| all (n=35) | 0.3 s | 30.8 s | 0.4 s | 43.4 s | 0.5 s | 49.4 s |

Per-node mean latency per requirement (ms; p95 in brackets):

| Node | mock | ollama |
|---|---|---|
| parse | 1.5 [2.6] | 4222.1 [5235.4] |
| retrieve | 4.5 [8.3] | 6.2 [11.9] |
| plan | 10.2 [16.7] | 7019.9 [8899.4] |
| instantiate | 8.9 [19.1] | 6.4 [13.0] |
| validate | 10.8 [26.1] | 7.3 [13.0] |
| explain | 2.7 [6.0] | 19365.1 [30377.8] |
| time inside LLM calls | 0.0 [0.0] | 30578.7 [43174.9] |

_wall clock seconds of one run_pipeline call per requirement (parse through explain, including all LLM calls and re-plans); p95 is nearest-rank; per-node values are per requirement in milliseconds._

### Coverage, citations, request validity, byte provenance

| Metric | mock | ollama |
|---|---|---|
| Coverage: tests per category (positive, negative, session, security, timing) | 36 / 70 / 21 / 18 / 26 | 29 / 19 / 7 / 8 / 5 |
| Coverage: seed requirements with ≥1 test | 15/15 (100.0%) | 15/15 (100.0%) |
| Citation validity | 774/774 (100.0%) | 335/335 (100.0%) |
| Request validity (adjusted) | 445/445 (100.0%) | 192/192 (100.0%) |
| Generated tests passing on the clean simulator | 171/171 (100.0%) | 68/68 (100.0%) |
| Byte provenance — seed-requirement tests | 171/171 passed | 68/68 passed |
| Byte provenance — natural-requirement tests | 172/172 passed | 90/90 passed |
| **Byte provenance — all generated tests** | 343/343 passed | 158/158 passed |

_Byte provenance: each generated test re-instantiated from TEMPLATES[template_id].instantiate(spec, params_model.model_validate(test.parameters)); template_id must be registered, parameters must round-trip, and every step must be identical (request and expected-response bytes, time/environment/DTC steps, descriptions, timing limits)._

## Retrieval comparison (BM25 vs Chroma)

Queries are the `text` of each row of `data/requirements_natural.csv`; 19 of 20 scored (NAT-020 excluded: no target service/DID/routine). Relevant chunks: ecu_spec chunks carrying a target DID/routine identifier; for rows with no DID/routine, the standard-collection `svc-<sid>` chunk of each target service. Search spans all collections; MRR uses the first relevant rank in the top 10 (0 if none); citation validity is over the top 3 hits.

| split | backend | queries | hit@1 | hit@3 | MRR | citation validity (top 3) |
|---|---|---|---|---|---|---|
| dev | bm25 | 8 | 0.0% | 37.5% | 0.271 | 100.0% |
| dev | chroma | 8 | 0.0% | 75.0% | 0.374 | 100.0% |
| **test** | **bm25** | 11 | 36.4% | 63.6% | 0.552 | 100.0% |
| **test** | **chroma** | 11 | 18.2% | 63.6% | 0.462 | 100.0% |
| all | bm25 | 19 | 21.1% | 52.6% | 0.434 | 100.0% |
| all | chroma | 19 | 10.5% | 68.4% | 0.425 | 100.0% |

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
| NAT-009 | dev | 1 | 6 | 3 |
| NAT-010 | test | 1 | 5 | 2 |
| NAT-011 | dev | 1 | 4 | 2 |
| NAT-012 | test | 1 | 4 | 2 |
| NAT-013 | dev | 1 | 2 | 2 |
| NAT-014 | test | 1 | 1 | 1 |
| NAT-015 | dev | 1 | 3 | 2 |
| NAT-016 | test | 1 | 1 | 1 |
| NAT-017 | test | 2 | 2 | 3 |
| NAT-018 | test | 1 | 8 | 4 |
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

## Freeze verification (prompts / agent / templates)

| Path | expected object id | HEAD object id | matches | worktree clean |
|---|---|---|---|---|
| `uds_assistant/llm/prompts.py` | `98a4741604338c3a0ffc2b17dc433e9c90d47620` | `98a4741604338c3a0ffc2b17dc433e9c90d47620` | True | True |
| `uds_assistant/llm` | `3559f7e7e0e53b5d08212b5cbccd5aa06e6bba71` | `3559f7e7e0e53b5d08212b5cbccd5aa06e6bba71` | True | True |
| `uds_assistant/agent` | `1d678f0f41eb23962defd6c8ea387bea4fcffb59` | `1d678f0f41eb23962defd6c8ea387bea4fcffb59` | True | True |
| `uds_assistant/testgen` | `9a121b2742c5f85fa48fd4f5340caf3b85979c67` | `9a121b2742c5f85fa48fd4f5340caf3b85979c67` | True | True |

All frozen paths unchanged: **True**.

# Details — mode=mock

Generated tests (seed requirements): **171** (94 unique template instantiations); 171/171 (100.0%) pass on the clean simulator; P2/P2* wall-clock warnings: 0.

## Held-out bug detection (12 bugs, not seen when templates/gold were written) — mode=mock

Scope: held-out (bugs written by an independent subagent that could not see templates, gold tests, eval, LLM or agent code; nothing was changed after seeing these results). Catalog: `data/bugs/heldout_catalog.yaml`.

| Bug | Category | Generated | Generated detecting tests | Gen. tests applying trigger | Gold | Gold detecting tests | Gold tests applying trigger |
|---|---|---|---|---|---|---|---|
| `routine_state_survives_session_change` | session | **no** | - | 0 | **no** | - | 0 |
| `failed_attempts_reset_by_seed_request` | security | yes | `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01` (+4 more) | 6 | yes | `gold_security_lockout_after_3` | 1 |
| `seed_returned_while_unlocked` | security | **no** | - | 0 | yes | `gold_security_already_unlocked_seed` | 1 |
| `nrc_order_condition_before_security` | nrc_order | **no** | - | 0 | **no** | - | 0 |
| `read_did_odd_length_truncated` | format | **no** | - | 0 | **no** | - | 0 |
| `read_did_session_restriction_ignored` | data | **no** | - | 0 | **no** | - | 0 |
| `uint16_did_stored_byte_swapped` | data | **no** | - | 0 | yes | `gold_write_coding_variant` | 1 |
| `s3_not_refreshed_by_tester_present` | timing | yes | `req_001__tpl_s3_keepalive_02`, `req_001__tpl_s3_keepalive_03` (+11 more) | 13 | **no** | - | 0 |
| `ecu_reset_clears_security_lockout` | security | **no** | - | 0 | **no** | - | 0 |
| `s3_timeout_reverts_written_dids` | timing | **no** | - | 0 | **no** | - | 0 |
| `session_suppress_bit_not_masked` | format | yes | `req_003__tpl_suppress_positive_10_01`, `req_003__tpl_suppress_positive_10_03` (+1 more) | 6 | **no** | - | 0 |
| `suppress_bit_echoed_in_response` | format | **no** | - | 0 | **no** | - | 0 |

Totals: generated 3/12 (25.0%), gold 3/12 (25.0%), union 5/12 (41.7%). Invalid tests (fail on the clean simulator): generated 0, gold 0.

### Missed held-out bugs — generated suite (mode=mock)

- `routine_state_survives_session_change`: no generated test starts a routine, changes session, then asks for that routine's results
- `seed_returned_while_unlocked`: no generated test requests a seed for a level that is already unlocked
- `nrc_order_condition_before_security`: no generated test starts a vehicle_stationary-gated routine while moving AND still locked
- `read_did_odd_length_truncated`: no generated test sends 0x22 with an odd number (>= 3) of DID bytes
- `read_did_session_restriction_ignored`: no generated test reads a DID outside its read_sessions
- `uint16_did_stored_byte_swapped`: no generated test writes a uint16 DID and reads it back
- `ecu_reset_clears_security_lockout`: no generated test resets the ECU after a security lockout and then requests a seed
- `s3_timeout_reverts_written_dids`: no generated test writes a DID, lets S3 expire, then reads the DID back
- `suppress_bit_echoed_in_response`: no generated test sends RoutineControl with the suppress bit where a positive response is still expected (e.g. after 0x78)

### Missed held-out bugs — gold suite

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

## Requirement understanding (natural requirements) — mode=mock

Source: `data/requirements_natural.csv` (20 labelled rows). Each requirement was run through the agent pipeline (`mode=mock`, Bm25Retriever). **The TEST split is the main number.**

| Split | n | Targets exact (parsed) | Parsed P / R / F1 | Targets exact (exercised) | Exercised P / R / F1 | Category recall micro / macro | Precondition recall micro / macro | Fallback / nothing |
|---|---|---|---|---|---|---|---|---|
| **test** | 12 | 5/12 (41.7%) | 0.933 / 0.560 / 0.700 | 2/12 (16.7%) | 0.312 / 0.800 / 0.449 | 19/28 (67.9%) / 69.7% | 12/15 (80.0%) / 75.0% | 3 (2 excl. empty-label rows) |
| dev | 8 | 4/8 (50.0%) | 1.000 / 0.706 / 0.828 | 0/8 (0.0%) | 0.333 / 0.941 / 0.492 | 14/22 (63.6%) / 60.4% | 9/9 (100.0%) / 100.0% | 1 (1 excl. empty-label rows) |
| all | 20 | 9/20 (45.0%) | 0.963 / 0.619 / 0.754 | 2/20 (10.0%) | 0.321 / 0.857 / 0.468 | 33/50 (66.0%) / 65.8% | 21/24 (87.5%) / 83.3% | 4 (3 excl. empty-label rows) |

### Per requirement (mode=mock)

| Req | Split | Tests | Label targets | Parsed exact | Parsed missed | Parsed extra | Exercised exact | Exercised missed | Exercised extra (n) | Categories missed | Preconditions missed | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NAT-001 | dev | 17 | did:0xF190, service:0x22 | yes | - | - | no | - | 9 | - | - | - |
| NAT-002 | test | 13 | did:0xF187, did:0xF18C, service:0x22 | no | did:0xF18C | - | no | did:0xF18C | 7 | - | - | - |
| NAT-003 | dev | 0 | service:0x10 | no | service:0x10 | - | no | service:0x10 | 0 | positive, session | - | no parsed services/DIDs/routines; zero tests |
| NAT-004 | test (ambiguous) | 9 | service:0x10 | yes | - | - | yes | - | 0 | session | vehicle_stationary | - |
| NAT-005 | dev | 14 | did:0x0100, service:0x10, service:0x27, service:0x2E | no | service:0x10 | - | no | - | 4 | - | - | - |
| NAT-006 | test (ambiguous) | 12 | did:0x0101, service:0x10, service:0x27, service:0x2E | no | service:0x10, service:0x27, service:0x2E | - | no | - | 5 | - | - | - |
| NAT-007 | dev | 7 | did:0x0130, service:0x2E | no | service:0x2E | - | no | - | 5 | security | - | - |
| NAT-008 | test | 0 | did:0x0131, service:0x2E | no | service:0x2E | - | no | did:0x0131, service:0x2E | 0 | negative, security | extended_session, security_level_1 | zero tests |
| NAT-009 | dev | 13 | did:0x0150, service:0x10, service:0x27, service:0x2E | no | service:0x10, service:0x27 | - | no | - | 9 | positive | - | - |
| NAT-010 | test | 3 | service:0x27 | yes | - | - | no | - | 1 | security, timing | - | - |
| NAT-011 | dev | 9 | routine:0x0201, service:0x31 | yes | - | - | no | - | 3 | security | - | - |
| NAT-012 | test | 12 | routine:0x0202, service:0x31 | yes | - | - | no | - | 7 | - | - | - |
| NAT-013 | dev | 6 | service:0x11 | yes | - | - | no | - | 1 | positive | - | - |
| NAT-014 | test | 11 | service:0x19 | no | - | service:0x22 | no | - | 4 | - | - | - |
| NAT-015 | dev | 9 | service:0x3E | yes | - | - | no | - | 1 | session, timing | - | - |
| NAT-016 | test | 11 | did:0x0160, service:0x10, service:0x27, service:0x2E | no | service:0x10, service:0x27, service:0x2E | - | no | - | 5 | - | - | - |
| NAT-017 | test (ambiguous) | 0 | service:0x14, service:0x19 | no | service:0x14, service:0x19 | - | no | service:0x14, service:0x19 | 0 | negative, positive, session | - | no parsed services/DIDs/routines; zero tests |
| NAT-018 | test | 12 | did:0x0120, service:0x27, service:0x2E | no | service:0x27 | - | no | - | 6 | - | - | - |
| NAT-019 | test | 14 | routine:0x0203, service:0x31 | yes | - | - | no | - | 9 | positive | - | - |
| NAT-020 | test | 0 | (none) | yes | - | - | yes | - | 0 | - | - | no parsed services/DIDs/routines; zero tests |

## Secondary: in-sample bug detection (26 bugs — templates tuned on these) — mode=mock

Scope: in-sample (templates tuned on these). Generated 25/26 (96.2%), gold 24/26 (92.3%), union 26/26 (100.0%). This is an optimistic, non-independent number: template set v2 was written after seeing which of these bugs v1 missed, by the same author as the catalog.

### Before / after template additions (in-sample, mock)

Baseline read from `eval_report_baseline_v1.json` (run 2026-10-02T21:21:46.279995+00:00).

|  | baseline (v1, 14 templates) | current (v2, 23 templates) |
|---|---|---|
| Generated tests | 101 | 171 |
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
| `general_reject_instead_of_0x12` | format | yes | 36: `req_003__tpl_unsupported_subfunction_10_01`, `req_003__tpl_unsupported_subfunction_10_03`, `req_003__tpl_negative_suppress_10_01` (+33 more) | yes | 4: `gold_session_unsupported_sub`, `gold_ecu_reset_bad_sub`, `gold_dtc_read_bad_sub` (+1 more) |
| `security_not_reset_on_session_change` | session | yes | 6: `req_005__tpl_session_relock_01`, `req_006__tpl_session_relock_01`, `req_007__tpl_session_relock_01` (+3 more) | yes | 1: `gold_security_relocked_on_session_reentry` |
| `s3_timeout_never_fires` | timing | yes | 13: `req_001__tpl_s3_timeout_02`, `req_001__tpl_s3_timeout_03`, `req_002__tpl_s3_timeout_02` (+10 more) | yes | 1: `gold_s3_timeout_reverts` |
| `s3_timeout_off_by_one` | timing | yes | 13: `req_001__tpl_s3_keepalive_02`, `req_001__tpl_s3_keepalive_03`, `req_002__tpl_s3_keepalive_02` (+10 more) | yes | 1: `gold_s3_no_timeout_at_exactly_s3ms` |
| `lockout_after_extra_attempt` | security | yes | 6: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_007__tpl_security_lockout_01` (+3 more) | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_ignored` | security | yes | 6: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_007__tpl_security_lockout_01` (+3 more) | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_never_expires` | timing | yes | 6: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_007__tpl_security_lockout_01` (+3 more) | **no** | 0: - |
| `accepts_any_key` | security | yes | 6: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_007__tpl_security_lockout_01` (+3 more) | yes | 3: `gold_security_wrong_key_once`, `gold_security_lockout_after_3`, `gold_security_wrong_level_unlock` |
| `seed_not_consumed` | sequence | yes | 6: `req_005__tpl_seed_replay_01`, `req_006__tpl_seed_replay_01`, `req_007__tpl_seed_replay_01` (+3 more) | **no** | 0: - |
| `static_seed` | security | yes | 12: `req_005__tpl_security_lockout_01`, `req_005__tpl_session_relock_01`, `req_006__tpl_security_lockout_01` (+9 more) | yes | 1: `gold_security_lockout_after_3` |
| `write_ignores_value_range` | data | yes | 5: `req_005__tpl_write_oor_0100`, `req_006__tpl_write_oor_0101`, `req_007__tpl_write_oor_0130` (+2 more) | yes | 2: `gold_write_out_of_range_wiper`, `gold_write_out_of_range_brightness` |
| `readonly_did_writable` | data | yes | 3: `req_001__tpl_write_readonly_f190`, `req_002__tpl_write_readonly_f187`, `req_002__tpl_write_readonly_f18c` | yes | 1: `gold_write_readonly_did` |
| `write_length_off_by_one` | format | yes | 5: `req_005__tpl_write_badlen_0100`, `req_006__tpl_write_badlen_0101`, `req_007__tpl_write_badlen_0130` (+2 more) | yes | 1: `gold_write_wrong_length` |
| `write_positive_sid_wrong` | format | yes | 4: `req_005__tpl_write_secured_0100`, `req_006__tpl_write_secured_0101`, `req_007__tpl_write_secured_0130` (+1 more) | yes | 5: `gold_write_secured_positive_lighting`, `gold_write_secured_positive_ambient_color`, `gold_write_coding_variant` (+2 more) |
| `session_response_missing_timing` | format | yes | 112: `req_001__tpl_read_did_positive_f190_02`, `req_001__tpl_read_did_positive_f190_03`, `req_001__tpl_write_readonly_f190` (+109 more) | yes | 35: `gold_read_vin_extended`, `gold_session_to_extended`, `gold_session_back_default` (+32 more) |
| `suppress_bit_ignored` | format | yes | 6: `req_003__tpl_suppress_positive_10_01`, `req_003__tpl_suppress_positive_10_03`, `req_004__tpl_suppress_positive_10_02` (+3 more) | yes | 2: `gold_tester_present_suppressed`, `gold_ecu_reset_suppressed` |
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
| REQ-001 | 9 | 3 | 1 | 0 | 4 | 17 |
| REQ-002 | 9 | 4 | 1 | 0 | 4 | 18 |
| REQ-003 | 2 | 4 | 0 | 0 | 2 | 8 |
| REQ-004 | 1 | 2 | 0 | 0 | 2 | 5 |
| REQ-005 | 1 | 6 | 2 | 3 | 2 | 14 |
| REQ-006 | 1 | 6 | 2 | 3 | 2 | 14 |
| REQ-007 | 1 | 4 | 2 | 3 | 2 | 12 |
| REQ-008 | 1 | 4 | 2 | 3 | 2 | 12 |
| REQ-009 | 0 | 7 | 3 | 3 | 2 | 15 |
| REQ-010 | 0 | 2 | 1 | 3 | 0 | 6 |
| REQ-011 | 1 | 6 | 2 | 0 | 0 | 9 |
| REQ-012 | 1 | 8 | 3 | 0 | 0 | 12 |
| REQ-013 | 0 | 6 | 0 | 0 | 0 | 6 |
| REQ-014 | 6 | 2 | 2 | 0 | 0 | 10 |
| REQ-015 | 3 | 6 | 0 | 0 | 4 | 13 |
| **total** | 36 | 70 | 21 | 18 | 26 | 171 |

Categories present: 100.0%; requirements covered by ≥2 categories: 14/15.

## Request validity — mode=mock

- Send steps: 445; decodable: 445; not rejected with a format NRC (0x11/0x12/0x13): 404 (unadjusted rate 90.8%).
- Intentional format probes (NRC in the template's `intended_nrcs`): 41. Adjusted validity: **445/445 (100.0%)**.

## Template reuse and citations — mode=mock

- Template reuse: 171/171 (100.0%); templates used: 23/23; per template: `condition_not_met` 2, `dtc_clear_specific_keeps_others` 3, `dtc_read_clear` 3, `negative_response_with_suppress_bit` 13, `nrc_priority_session_over_identifier` 11, `read_did_positive` 9, `read_did_wrong_session_or_unknown` 2, `read_multiple_dids` 9, `routine_sequence` 2, `routine_start_results` 2, `s3_keepalive_boundary` 13, `s3_timeout_reverts_session` 13, `security_invalid_key_lockout` 6, `seed_replay_rejected` 6, `service_not_in_session` 21, `session_change_relocks_security` 6, `suppress_positive_response` 6, `unsupported_subfunction` 23, `write_did_invalid_length` 5, `write_did_out_of_range` 5, `write_did_secured_positive` 4, `write_did_without_security` 4, `write_readonly_did` 3
- Citations: 774/774 valid; tests with ≥1 valid citation: 100.0%.

## Pipeline statistics (seed requirements) — mode=mock

| Requirement | tests | dropped | rejected | plan attempts | status | wall s |
|---|---|---|---|---|---|---|
| REQ-001 | 17 | 0 | 0 | 1 | completed | 0.51 |
| REQ-002 | 18 | 0 | 0 | 1 | completed | 0.29 |
| REQ-003 | 8 | 0 | 0 | 1 | completed | 0.135 |
| REQ-004 | 5 | 0 | 0 | 1 | completed | 0.101 |
| REQ-005 | 14 | 0 | 0 | 1 | completed | 0.215 |
| REQ-006 | 14 | 0 | 0 | 1 | completed | 0.209 |
| REQ-007 | 12 | 0 | 0 | 1 | completed | 0.208 |
| REQ-008 | 12 | 0 | 0 | 1 | completed | 0.398 |
| REQ-009 | 15 | 0 | 0 | 1 | completed | 0.445 |
| REQ-010 | 6 | 0 | 0 | 1 | completed | 0.221 |
| REQ-011 | 9 | 0 | 0 | 1 | completed | 0.331 |
| REQ-012 | 12 | 0 | 0 | 1 | completed | 0.351 |
| REQ-013 | 6 | 0 | 0 | 1 | completed | 0.187 |
| REQ-014 | 10 | 0 | 0 | 1 | completed | 0.252 |
| REQ-015 | 13 | 0 | 0 | 1 | completed | 0.285 |

Totals: 171 kept, 0 dropped, 0 rejected, 0 re-plans, 0 failed runs.

## Appendix: Self-consistency check (circular by construction) — mode=mock

Expected bytes in generated tests are produced by the rules-engine oracle, so agreement with a fresh oracle re-run is a consistency check, not an independent accuracy measure. Kept here for completeness; it is not a headline metric.

- Expected-response accuracy vs oracle: 445/445 (100.0%) steps; 171/171 (100.0%) tests.
- Independent simulator (clean): 100.0% of generated tests pass.
- Gold, exact overlap: 25/25 (100.0%) generated/gold pairs with identical step sequences agree.
- Gold, shared prefix: 18/18 (100.0%) distinct send steps reached by an identical prefix in both suites agree.

# Details — mode=ollama

Generated tests (seed requirements): **68** (50 unique template instantiations); 68/68 (100.0%) pass on the clean simulator; P2/P2* wall-clock warnings: 0.

## Held-out bug detection (12 bugs, not seen when templates/gold were written) — mode=ollama

Scope: held-out (bugs written by an independent subagent that could not see templates, gold tests, eval, LLM or agent code; nothing was changed after seeing these results). Catalog: `data/bugs/heldout_catalog.yaml`.

| Bug | Category | Generated | Generated detecting tests | Gen. tests applying trigger | Gold | Gold detecting tests | Gold tests applying trigger |
|---|---|---|---|---|---|---|---|
| `routine_state_survives_session_change` | session | **no** | - | 0 | **no** | - | 0 |
| `failed_attempts_reset_by_seed_request` | security | yes | `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01` (+1 more) | 3 | yes | `gold_security_lockout_after_3` | 1 |
| `seed_returned_while_unlocked` | security | **no** | - | 0 | yes | `gold_security_already_unlocked_seed` | 1 |
| `nrc_order_condition_before_security` | nrc_order | **no** | - | 0 | **no** | - | 0 |
| `read_did_odd_length_truncated` | format | **no** | - | 0 | **no** | - | 0 |
| `read_did_session_restriction_ignored` | data | **no** | - | 0 | **no** | - | 0 |
| `uint16_did_stored_byte_swapped` | data | **no** | - | 0 | yes | `gold_write_coding_variant` | 1 |
| `s3_not_refreshed_by_tester_present` | timing | yes | `req_015__tpl_s3_keepalive_03` | 1 | **no** | - | 0 |
| `ecu_reset_clears_security_lockout` | security | **no** | - | 0 | **no** | - | 0 |
| `s3_timeout_reverts_written_dids` | timing | **no** | - | 0 | **no** | - | 0 |
| `session_suppress_bit_not_masked` | format | yes | `req_003__tpl_suppress_positive_10_01` | 2 | **no** | - | 0 |
| `suppress_bit_echoed_in_response` | format | **no** | - | 0 | **no** | - | 0 |

Totals: generated 3/12 (25.0%), gold 3/12 (25.0%), union 5/12 (41.7%). Invalid tests (fail on the clean simulator): generated 0, gold 0.

### Missed held-out bugs — generated suite (mode=ollama)

- `routine_state_survives_session_change`: no generated test starts a routine, changes session, then asks for that routine's results
- `seed_returned_while_unlocked`: no generated test requests a seed for a level that is already unlocked
- `nrc_order_condition_before_security`: no generated test starts a vehicle_stationary-gated routine while moving AND still locked
- `read_did_odd_length_truncated`: no generated test sends 0x22 with an odd number (>= 3) of DID bytes
- `read_did_session_restriction_ignored`: no generated test reads a DID outside its read_sessions
- `uint16_did_stored_byte_swapped`: no generated test writes a uint16 DID and reads it back
- `ecu_reset_clears_security_lockout`: no generated test resets the ECU after a security lockout and then requests a seed
- `s3_timeout_reverts_written_dids`: no generated test writes a DID, lets S3 expire, then reads the DID back
- `suppress_bit_echoed_in_response`: no generated test sends RoutineControl with the suppress bit where a positive response is still expected (e.g. after 0x78)

### Missed held-out bugs — gold suite

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

## Requirement understanding (natural requirements) — mode=ollama

Source: `data/requirements_natural.csv` (20 labelled rows). Each requirement was run through the agent pipeline (`mode=ollama`, Bm25Retriever). **The TEST split is the main number.**

| Split | n | Targets exact (parsed) | Parsed P / R / F1 | Targets exact (exercised) | Exercised P / R / F1 | Category recall micro / macro | Precondition recall micro / macro | Fallback / nothing |
|---|---|---|---|---|---|---|---|---|
| **test** | 12 | 4/12 (33.3%) | 0.512 / 0.880 / 0.647 | 0/12 (0.0%) | 0.298 / 0.800 / 0.435 | 18/28 (64.3%) / 64.4% | 11/15 (73.3%) / 75.0% | 1 (1 excl. empty-label rows) |
| dev | 8 | 1/8 (12.5%) | 0.583 / 0.824 / 0.683 | 0/8 (0.0%) | 0.347 / 1.000 / 0.515 | 16/22 (72.7%) / 77.1% | 9/9 (100.0%) / 100.0% | 0 (0 excl. empty-label rows) |
| all | 20 | 5/20 (25.0%) | 0.537 / 0.857 / 0.661 | 0/20 (0.0%) | 0.319 / 0.881 / 0.468 | 34/50 (68.0%) / 69.7% | 20/24 (83.3%) / 83.3% | 1 (1 excl. empty-label rows) |

### Per requirement (mode=ollama)

| Req | Split | Tests | Label targets | Parsed exact | Parsed missed | Parsed extra | Exercised exact | Exercised missed | Exercised extra (n) | Categories missed | Preconditions missed | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NAT-001 | dev | 6 | did:0xF190, service:0x22 | no | did:0xF190 | did:0xF18C, service:0x10 | no | - | 3 | - | - | - |
| NAT-002 | test | 6 | did:0xF187, did:0xF18C, service:0x22 | yes | - | - | no | - | 2 | - | - | - |
| NAT-003 | dev | 7 | service:0x10 | no | - | did:0xF186, service:0x27, service:0x2E, service:0x3E | no | - | 6 | - | - | - |
| NAT-004 | test (ambiguous) | 4 | service:0x10 | no | - | did:0xF186, service:0x27, service:0x2E | no | - | 5 | session | vehicle_stationary | - |
| NAT-005 | dev | 7 | did:0x0100, service:0x10, service:0x27, service:0x2E | no | service:0x27 | - | no | - | 4 | security | - | - |
| NAT-006 | test (ambiguous) | 4 | did:0x0101, service:0x10, service:0x27, service:0x2E | yes | - | - | no | - | 3 | session | - | - |
| NAT-007 | dev | 3 | did:0x0130, service:0x2E | no | - | service:0x10, service:0x27 | no | - | 4 | security | - | - |
| NAT-008 | test | 4 | did:0x0131, service:0x2E | yes | - | - | no | - | 4 | security | - | - |
| NAT-009 | dev | 4 | did:0x0150, service:0x10, service:0x27, service:0x2E | yes | - | - | no | - | 3 | session | - | - |
| NAT-010 | test | 4 | service:0x27 | no | - | did:0x0101 | no | - | 5 | negative, timing | - | - |
| NAT-011 | dev | 4 | routine:0x0201, service:0x31 | no | routine:0x0201 | - | no | - | 4 | security, session | - | - |
| NAT-012 | test | 0 | routine:0x0202, service:0x31 | no | routine:0x0202 | did:0x0140, service:0x10, service:0x2E, service:0x3E | no | routine:0x0202, service:0x31 | 0 | negative, positive | extended_session, security_level_1, vehicle_stationary | zero tests |
| NAT-013 | dev | 8 | service:0x11 | no | - | did:0x0140 | no | - | 4 | - | - | - |
| NAT-014 | test | 4 | service:0x19 | no | - | did:0x0140 | no | - | 4 | - | - | - |
| NAT-015 | dev | 4 | service:0x3E | no | - | did:0x0140 | no | - | 4 | session | - | - |
| NAT-016 | test | 4 | did:0x0160, service:0x10, service:0x27, service:0x2E | yes | - | - | no | - | 1 | session | - | - |
| NAT-017 | test (ambiguous) | 4 | service:0x14, service:0x19 | no | service:0x19 | did:0x0140 | no | service:0x19 | 5 | - | - | - |
| NAT-018 | test | 4 | did:0x0120, service:0x27, service:0x2E | no | - | did:0x0110, did:0x0111, service:0x10 | no | - | 3 | security | - | - |
| NAT-019 | test | 4 | routine:0x0203, service:0x31 | no | routine:0x0203 | did:0x0150, service:0x10, service:0x27, service:0x2E | no | routine:0x0203, service:0x31 | 7 | timing | - | - |
| NAT-020 | test | 5 | (none) | no | - | did:0x0150, service:0x10, service:0x11, service:0x2E | no | - | 8 | - | - | - |

## Secondary: in-sample bug detection (26 bugs — templates tuned on these) — mode=ollama

Scope: in-sample (templates tuned on these). Generated 21/26 (80.8%), gold 24/26 (92.3%), union 26/26 (100.0%). This is an optimistic, non-independent number: template set v2 was written after seeing which of these bugs v1 missed, by the same author as the catalog.

### Bug detection per injected bug (in-sample) — mode=ollama

| Bug | Category | Generated | Generated detecting tests | Gold | Gold detecting tests |
|---|---|---|---|---|---|
| `nrc_order_did_before_session` | nrc_order | yes | 1: `req_007__tpl_nrc_priority_2e_01` | yes | 1: `gold_write_unknown_did_default_session` |
| `nrc_order_security_before_length` | nrc_order | yes | 2: `req_007__tpl_write_badlen_0130`, `req_008__tpl_write_badlen_0100` | yes | 1: `gold_write_wrong_length` |
| `general_reject_instead_of_0x12` | format | yes | 8: `req_009__tpl_negative_suppress_10_03`, `req_011__tpl_negative_suppress_31_02`, `req_011__tpl_negative_suppress_31_03` (+5 more) | yes | 4: `gold_session_unsupported_sub`, `gold_ecu_reset_bad_sub`, `gold_dtc_read_bad_sub` (+1 more) |
| `security_not_reset_on_session_change` | session | yes | 4: `req_003__tpl_session_relock_01`, `req_005__tpl_session_relock_01`, `req_006__tpl_session_relock_01` (+1 more) | yes | 1: `gold_security_relocked_on_session_reentry` |
| `s3_timeout_never_fires` | timing | yes | 4: `req_003__tpl_s3_timeout_03`, `req_005__tpl_s3_timeout_03`, `req_006__tpl_s3_timeout_03` (+1 more) | yes | 1: `gold_s3_timeout_reverts` |
| `s3_timeout_off_by_one` | timing | yes | 1: `req_015__tpl_s3_keepalive_03` | yes | 1: `gold_s3_no_timeout_at_exactly_s3ms` |
| `lockout_after_extra_attempt` | security | yes | 3: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_010__tpl_security_lockout_01` | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_ignored` | security | yes | 3: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_010__tpl_security_lockout_01` | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_never_expires` | timing | yes | 3: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_010__tpl_security_lockout_01` | **no** | 0: - |
| `accepts_any_key` | security | yes | 3: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_010__tpl_security_lockout_01` | yes | 3: `gold_security_wrong_key_once`, `gold_security_lockout_after_3`, `gold_security_wrong_level_unlock` |
| `seed_not_consumed` | sequence | yes | 1: `req_010__tpl_seed_replay_01` | **no** | 0: - |
| `static_seed` | security | yes | 7: `req_003__tpl_session_relock_01`, `req_005__tpl_security_lockout_01`, `req_005__tpl_session_relock_01` (+4 more) | yes | 1: `gold_security_lockout_after_3` |
| `write_ignores_value_range` | data | yes | 3: `req_004__tpl_write_oor_0100`, `req_007__tpl_write_oor_0130`, `req_008__tpl_write_oor_0100` | yes | 2: `gold_write_out_of_range_wiper`, `gold_write_out_of_range_brightness` |
| `readonly_did_writable` | data | yes | 1: `req_013__tpl_write_readonly_0140` | yes | 1: `gold_write_readonly_did` |
| `write_length_off_by_one` | format | yes | 2: `req_007__tpl_write_badlen_0130`, `req_008__tpl_write_badlen_0100` | yes | 1: `gold_write_wrong_length` |
| `write_positive_sid_wrong` | format | yes | 7: `req_005__tpl_write_secured_0100`, `req_006__tpl_write_secured_0101`, `req_007__tpl_write_secured_0130` (+4 more) | yes | 5: `gold_write_secured_positive_lighting`, `gold_write_secured_positive_ambient_color`, `gold_write_coding_variant` (+2 more) |
| `session_response_missing_timing` | format | yes | 46: `req_001__tpl_read_did_positive_f190_02`, `req_001__tpl_read_did_positive_f190_03`, `req_002__tpl_read_did_positive_f187_02` (+43 more) | yes | 35: `gold_read_vin_extended`, `gold_session_to_extended`, `gold_session_back_default` (+32 more) |
| `suppress_bit_ignored` | format | yes | 1: `req_003__tpl_suppress_positive_10_01` | yes | 2: `gold_tester_present_suppressed`, `gold_ecu_reset_suppressed` |
| `negative_response_suppressed` | format | yes | 6: `req_009__tpl_negative_suppress_10_03`, `req_011__tpl_negative_suppress_31_02`, `req_011__tpl_negative_suppress_31_03` (+3 more) | yes | 1: `gold_tester_present_bad_sub_not_suppressed` |
| `routine_stop_without_start` | sequence | **no** | 0: - | yes | 1: `gold_routine_stop_before_start` |
| `condition_ignored` | data | yes | 2: `req_004__tpl_condition_not_met_did_0150`, `req_011__tpl_condition_not_met_routine_0202` | yes | 2: `gold_routine_door_cal_condition_fail`, `gold_write_factory_reset_flag_moving` |
| `dtc_clear_ignores_group` | data | **no** | 0: - | yes | 2: `gold_dtc_clear_specific`, `gold_dtc_clear_unknown_group` |
| `dtc_clear_noop` | data | **no** | 0: - | yes | 2: `gold_dtc_clear_all`, `gold_dtc_clear_specific` |
| `multi_did_read_first_only` | data | yes | 2: `req_002__tpl_read_multi_f187_f190_01`, `req_014__tpl_read_multi_0140_f190_01` | yes | 2: `gold_read_partnum_serial_multi`, `gold_duplicate_did_read` |
| `missing_response_pending` | timing | **no** | 0: - | yes | 1: `gold_routine_nvm_restore_long_running` |
| `dtc_read_ignores_mask` | data | **no** | 0: - | yes | 4: `gold_dtc_read_default`, `gold_dtc_set_and_read`, `gold_dtc_clear_all` (+1 more) |

Invalid tests (fail on the clean simulator, excluded from credit): generated 0, gold 0.
Detected only by the generated suite: lockout_delay_never_expires, seed_not_consumed. Only by gold: routine_stop_without_start, dtc_clear_ignores_group, dtc_clear_noop, missing_response_pending, dtc_read_ignores_mask. Undetected by both: -.

## Coverage (generated tests per category per seed requirement) — mode=ollama

| Requirement | positive | negative | session | security | timing | total |
|---|---|---|---|---|---|---|
| REQ-001 | 3 | 0 | 0 | 0 | 0 | 3 |
| REQ-002 | 5 | 0 | 0 | 0 | 0 | 5 |
| REQ-003 | 2 | 0 | 0 | 1 | 1 | 4 |
| REQ-004 | 1 | 3 | 0 | 0 | 0 | 4 |
| REQ-005 | 2 | 0 | 1 | 2 | 1 | 6 |
| REQ-006 | 2 | 0 | 1 | 2 | 1 | 6 |
| REQ-007 | 2 | 3 | 1 | 0 | 0 | 6 |
| REQ-008 | 2 | 2 | 0 | 0 | 0 | 4 |
| REQ-009 | 1 | 1 | 1 | 1 | 1 | 5 |
| REQ-010 | 2 | 0 | 1 | 2 | 0 | 5 |
| REQ-011 | 1 | 4 | 0 | 0 | 0 | 5 |
| REQ-012 | 2 | 1 | 1 | 0 | 0 | 4 |
| REQ-013 | 1 | 3 | 0 | 0 | 0 | 4 |
| REQ-014 | 1 | 1 | 1 | 0 | 0 | 3 |
| REQ-015 | 2 | 1 | 0 | 0 | 1 | 4 |
| **total** | 29 | 19 | 7 | 8 | 5 | 68 |

Categories present: 100.0%; requirements covered by ≥2 categories: 13/15.

## Request validity — mode=ollama

- Send steps: 192; decodable: 192; not rejected with a format NRC (0x11/0x12/0x13): 182 (unadjusted rate 94.8%).
- Intentional format probes (NRC in the template's `intended_nrcs`): 10. Adjusted validity: **192/192 (100.0%)**.

## Template reuse and citations — mode=ollama

- Template reuse: 68/68 (100.0%); templates used: 19/23; per template: `condition_not_met` 2, `negative_response_with_suppress_bit` 6, `nrc_priority_session_over_identifier` 2, `read_did_positive` 18, `read_multiple_dids` 2, `routine_start_results` 1, `s3_keepalive_boundary` 1, `s3_timeout_reverts_session` 4, `security_invalid_key_lockout` 3, `seed_replay_rejected` 1, `service_not_in_session` 7, `session_change_relocks_security` 4, `suppress_positive_response` 1, `unsupported_subfunction` 2, `write_did_invalid_length` 2, `write_did_out_of_range` 3, `write_did_secured_positive` 7, `write_did_without_security` 1, `write_readonly_did` 1
- Citations: 335/335 valid; tests with ≥1 valid citation: 100.0%.

## Pipeline statistics (seed requirements) — mode=ollama

| Requirement | tests | dropped | rejected | plan attempts | status | wall s |
|---|---|---|---|---|---|---|
| REQ-001 | 3 | 0 | 1 | 1 | completed | 23.247 |
| REQ-002 | 5 | 0 | 0 | 1 | completed | 33.669 |
| REQ-003 | 4 | 0 | 0 | 1 | completed | 29.142 |
| REQ-004 | 4 | 0 | 4 | 1 | completed | 32.846 |
| REQ-005 | 6 | 0 | 0 | 1 | completed | 38.021 |
| REQ-006 | 6 | 0 | 0 | 1 | completed | 39.554 |
| REQ-007 | 6 | 0 | 0 | 1 | completed | 36.475 |
| REQ-008 | 4 | 0 | 0 | 1 | completed | 26.058 |
| REQ-009 | 5 | 0 | 0 | 1 | completed | 34.733 |
| REQ-010 | 5 | 0 | 0 | 1 | completed | 33.624 |
| REQ-011 | 5 | 0 | 0 | 1 | completed | 32.737 |
| REQ-012 | 4 | 0 | 0 | 1 | completed | 26.969 |
| REQ-013 | 4 | 0 | 0 | 1 | completed | 27.61 |
| REQ-014 | 3 | 0 | 0 | 1 | completed | 22.428 |
| REQ-015 | 4 | 0 | 0 | 1 | completed | 26.895 |

Totals: 68 kept, 0 dropped, 5 rejected, 0 re-plans, 0 failed runs.

## Appendix: Self-consistency check (circular by construction) — mode=ollama

Expected bytes in generated tests are produced by the rules-engine oracle, so agreement with a fresh oracle re-run is a consistency check, not an independent accuracy measure. Kept here for completeness; it is not a headline metric.

- Expected-response accuracy vs oracle: 192/192 (100.0%) steps; 68/68 (100.0%) tests.
- Independent simulator (clean): 100.0% of generated tests pass.
- Gold, exact overlap: 14/14 (100.0%) generated/gold pairs with identical step sequences agree.
- Gold, shared prefix: 14/14 (100.0%) distinct send steps reached by an identical prefix in both suites agree.

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
- Ran `generated_tests_test.py` for mode=mock (transport `inprocess`) with pytest in a subprocess: **PASSED** — `171 passed in 1.75s` (8.95 s).
- `exports/ollama/generated_tests_test.py` (mode=ollama)
- `exports/ollama/gold_tests_test.py` (mode=ollama)
- `exports/ollama/generated_tests.can` (mode=ollama)
- `exports/ollama/gold_tests.can` (mode=ollama)
- `generated_tests_ollama.yaml` (mode=ollama)
- Ran `generated_tests_test.py` for mode=ollama (transport `inprocess`) with pytest in a subprocess: **PASSED** — `68 passed in 1.25s` (4.66 s).
- CAPL files (`*.can`) are **UNVERIFIED TEMPLATES — not compiled or run in CANoe**.

## Runtime

| Phase | seconds |
|---|---|
| setup | 5.45 |
| gold_suites | 0.484 |
| mock.generation | 4.141 |
| mock.requirement_understanding | 4.758 |
| mock.execution_and_bug_matrices | 26.325 |
| mock.provenance | 0.235 |
| mock.metrics | 0.365 |
| mock.total | 35.827 |
| ollama.generation | 464.01 |
| ollama.requirement_understanding | 613.492 |
| ollama.execution_and_bug_matrices | 12.058 |
| ollama.provenance | 0.08 |
| ollama.metrics | 0.151 |
| ollama.total | 1089.793 |
| simulator_rules_agreement | 0.613 |
| udsoncan_virtual_can | 0.487 |
| exports | 15.0 |
| retrieval_compare | 5.501 |
| total | 1153.166 |

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
