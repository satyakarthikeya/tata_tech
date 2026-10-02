# Evaluation report — UDS test generation assistant

- **Generated:** 2026-10-02T21:50:46.917317+00:00 (git `f3c643c40c15ee4ecbc7e7de2c440904b6a07e57`)
- **LLM mode used:** `mock` (requested `mock`)
- **Agent engine:** `langgraph` · **Retriever:** `Bm25Retriever`
- **Template set:** `v2` (23 templates)
- **Inputs:** 15 seed requirements, 60 gold tests, 26 injectable simulator bugs

> **The ECU spec is synthetic.** `data/bcm_spec.yaml` describes a fictional Body Control Module written for this project in an OEM-like style; no real OEM document or ISO 14229 text is used. All numbers below are measured against the project's own simulator.
>
> **Mode:** these numbers are for `mode=mock`. In mock mode the LLM is a deterministic keyword/rule stand-in; numbers for `mode=ollama` (local Qwen2.5-3B) are **deferred / not run** (no model download in the offline build).

> **Template set v2:** v1 + 9 generic templates (multi-DID read, write to read-only DID, session change re-locks security, key replay, DTC clear specific/unknown group, negative response with suppress bit, S3 keep-alive boundary, NRC priority session-before-identifier, routine start+results incl. 0x78) and a fix so routine starts carry the spec'd option record. Added in Phase 7 AFTER inspecting which catalog bugs v1 missed; the same author wrote the bug catalog, so v2 detection is an optimistic, non-independent number.

## Headline metrics

| Metric | mock | ollama |
|---|---|---|
| **Bug detection rate — generated suite** | **25/26 (96.2%)** | not run |
| Bug detection rate — gold baseline | 24/26 (92.3%) | not run |
| Bug detection rate — union | 26/26 (100.0%) | not run |
| Request validity | 445/445 (100.0%) | not run |
| Expected-response accuracy vs oracle (steps) | 445/445 (100.0%) | not run |
| Expected-response accuracy vs gold (exact overlap) | 25/25 (100.0%) | not run |
| Expected-response accuracy vs gold (shared-prefix steps) | 18/18 (100.0%) | not run |
| Generated tests passing on clean simulator | 171/171 (100.0%) | not run |
| Coverage (requirements with ≥1 test) | 15/15 (100.0%) | not run |
| Template reuse rate | 171/171 (100.0%) | not run |
| Citation validity | 774/774 (100.0%) | not run |

Generated tests: **171** (94 unique template instantiations; the same check can be generated for several requirements). P2/P2* wall-clock warnings on the clean run: 0.

## Before / after template additions

Baseline read from `eval_report_baseline_v1.json` (run 2026-10-02T21:21:46.279995+00:00).

|  | baseline (v1, 14 templates) | current (v2, 23 templates) |
|---|---|---|
| Generated tests | 101 | 171 |
| Generated-suite bug detection | 17 (65.4%) | 25 (96.2%) |
| Gold bug detection | 92.3% | 92.3% |
| Union bug detection | 96.2% | 100.0% |
| Request validity | 98.9% | 100.0% |
| Citation validity | 100.0% | 100.0% |
| Template reuse | 100.0% | 100.0% |
| Undetected (generated) | nrc_order_did_before_session, security_not_reset_on_session_change, s3_timeout_off_by_one, seed_not_consumed, readonly_did_writable, negative_response_suppressed, dtc_clear_ignores_group, multi_did_read_first_only, missing_response_pending | missing_response_pending |

## Bug detection per injected bug

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

## Coverage (generated tests per category per requirement)

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

## Request validity

- Send steps: 445; decodable: 445; not rejected with a format NRC (0x11/0x12/0x13): 404 (unadjusted rate 90.8%).
- Intentional format probes (NRC in the template's `intended_nrcs`): 41. Adjusted validity: **100.0%**.

## Expected-response accuracy

- Oracle re-run: 445/445 (100.0%) steps; 171/171 (100.0%) tests. (Expected bytes are produced by the oracle, so this is a consistency check, not an independent accuracy measure.)
- Independent simulator (clean): 100.0% of generated tests pass.
- Gold, exact overlap: 25 generated/gold pairs with identical step sequences; agreement 100.0%.
- Gold, shared prefix: 18 distinct send steps reached by an identical prefix in both suites; agreement 100.0%.

## Template reuse and citations

- Templates used: 23/23; per template: `condition_not_met` 2, `dtc_clear_specific_keeps_others` 3, `dtc_read_clear` 3, `negative_response_with_suppress_bit` 13, `nrc_priority_session_over_identifier` 11, `read_did_positive` 9, `read_did_wrong_session_or_unknown` 2, `read_multiple_dids` 9, `routine_sequence` 2, `routine_start_results` 2, `s3_keepalive_boundary` 13, `s3_timeout_reverts_session` 13, `security_invalid_key_lockout` 6, `seed_replay_rejected` 6, `service_not_in_session` 21, `session_change_relocks_security` 6, `suppress_positive_response` 6, `unsupported_subfunction` 23, `write_did_invalid_length` 5, `write_did_out_of_range` 5, `write_did_secured_positive` 4, `write_did_without_security` 4, `write_readonly_did` 3
- Citations: 774/774 valid; tests with ≥1 valid citation: 100.0%.

## Pipeline statistics

| Requirement | tests | dropped | rejected | plan attempts | status |
|---|---|---|---|---|---|
| REQ-001 | 17 | 0 | 0 | 1 | completed |
| REQ-002 | 18 | 0 | 0 | 1 | completed |
| REQ-003 | 8 | 0 | 0 | 1 | completed |
| REQ-004 | 5 | 0 | 0 | 1 | completed |
| REQ-005 | 14 | 0 | 0 | 1 | completed |
| REQ-006 | 14 | 0 | 0 | 1 | completed |
| REQ-007 | 12 | 0 | 0 | 1 | completed |
| REQ-008 | 12 | 0 | 0 | 1 | completed |
| REQ-009 | 15 | 0 | 0 | 1 | completed |
| REQ-010 | 6 | 0 | 0 | 1 | completed |
| REQ-011 | 9 | 0 | 0 | 1 | completed |
| REQ-012 | 12 | 0 | 0 | 1 | completed |
| REQ-013 | 6 | 0 | 0 | 1 | completed |
| REQ-014 | 10 | 0 | 0 | 1 | completed |
| REQ-015 | 13 | 0 | 0 | 1 | completed |

Totals: 171 kept, 0 dropped, 0 rejected, 0 re-plans, 0 failed runs.

## Exports

- `exports/generated_tests_test.py`
- `exports/gold_tests_test.py`
- `exports/generated_tests.can`
- `exports/gold_tests.can`
- Ran `generated_tests_test.py` (transport `inprocess`) with pytest in a subprocess: **PASSED** — `171 passed in 0.97s` (3.51 s).
- CAPL files (`*.can`) are **UNVERIFIED TEMPLATES — not compiled or run in CANoe**.

## Runtime

| Phase | seconds |
|---|---|
| setup | 1.658 |
| generation | 3.55 |
| execution_and_bug_matrix | 19.263 |
| metrics | 0.215 |
| exports | 4.314 |
| total | 29.001 |

## Metric definitions

- **request_validity**: Over every send step of every generated test: the request is replayed through the rules-engine oracle in sequence (same set-up and time steps). A request counts as well-formed if (a) protocol.codec.decode_request decodes it and (b) the oracle does not reject it with a format NRC (0x11 serviceNotSupported, 0x12 subFunctionNotSupported, 0x13 incorrectMessageLengthOrInvalidFormat), unless that NRC is listed in the template's declared intended_nrcs (a deliberate malformed-request probe such as write_did_invalid_length -> 0x13). rate = well-formed / send steps. The unadjusted rate (no intent exemption) is reported alongside.
- **expected_response_accuracy**: oracle: share of generated send steps whose expected response frames equal a fresh rules-engine re-run of the test (and share of whole tests with zero mismatches). simulator: share of generated tests passing on the bug-free independent simulator. gold: (1) exact overlap = generated tests whose full step sequence (requests and set-up/time steps, ignoring expected responses) is identical to a gold test; agreement = identical expected responses on every step. (2) shared-prefix overlap = every distinct send step reached by an identical step prefix from power-on in both a generated and a gold test (deduplicated by prefix); agreement = identical expected frames for that step.
- **coverage**: Number of generated tests per category (positive/negative/session/security/timing) per requirement. rate = requirements with >= 1 generated test / requirements; category_presence = categories with >= 1 test across the suite / 5.
- **template_reuse_rate**: Share of generated tests whose template_id is a registered template AND whose steps are byte-identical to a fresh instantiation of that template with the test's stored parameters (independent re-check of byte provenance).
- **citation_validity**: Share of all citations attached to generated tests for which rag.citations.citation_is_valid is true against the evaluation corpus (source+ref exists; a quote must appear verbatim and its hex identifiers must belong to the chunk).
- **bug_detection_rate**: Each catalog bug is enabled alone in a fresh simulator per test. A bug is detected if >= 1 test that passes on the clean simulator fails with the bug enabled. Tests failing on the clean simulator are reported as invalid and get no credit. rate = detected bugs / catalog bugs. Reported for the generated suite (headline), the hand-written gold suite (baseline) and their union.
- **pipeline_stats**: Per requirement: kept tests, dropped tests (failed validation), rejected planner choices, plan attempts (retries = attempts - 1), run status.
- **runtime**: Wall-clock seconds per evaluation phase and in total (machine dependent).
