# Evaluation report — UDS test generation assistant

- **Generated:** 2026-10-02T21:21:46.279995+00:00 (git `1a9a02f57b11dd0b2b633ff9de627109c2afe9be`, uncommitted changes present)
- **LLM mode used:** `mock` (requested `mock`)
- **Agent engine:** `langgraph` · **Retriever:** `Bm25Retriever`
- **Template set:** `v1` (14 templates)
- **Inputs:** 15 seed requirements, 60 gold tests, 26 injectable simulator bugs

> **The ECU spec is synthetic.** `data/bcm_spec.yaml` describes a fictional Body Control Module written for this project in an OEM-like style; no real OEM document or ISO 14229 text is used. All numbers below are measured against the project's own simulator.
>
> **Mode:** these numbers are for `mode=mock`. In mock mode the LLM is a deterministic keyword/rule stand-in; numbers for `mode=ollama` (local Qwen2.5-3B) are **deferred / not run** (no model download in the offline build).

## Headline metrics

| Metric | mock | ollama |
|---|---|---|
| **Bug detection rate — generated suite** | **17/26 (65.4%)** | not run |
| Bug detection rate — gold baseline | 24/26 (92.3%) | not run |
| Bug detection rate — union | 25/26 (96.2%) | not run |
| Request validity | 265/268 (98.9%) | not run |
| Expected-response accuracy vs oracle (steps) | 268/268 (100.0%) | not run |
| Expected-response accuracy vs gold (exact overlap) | 22/22 (100.0%) | not run |
| Expected-response accuracy vs gold (shared-prefix steps) | 15/15 (100.0%) | not run |
| Generated tests passing on clean simulator | 101/101 (100.0%) | not run |
| Coverage (requirements with ≥1 test) | 15/15 (100.0%) | not run |
| Template reuse rate | 101/101 (100.0%) | not run |
| Citation validity | 460/460 (100.0%) | not run |

Generated tests: **101** (61 unique template instantiations; the same check can be generated for several requirements). P2/P2* wall-clock warnings on the clean run: 0.

## Bug detection per injected bug

| Bug | Category | Generated | Generated detecting tests | Gold | Gold detecting tests |
|---|---|---|---|---|---|
| `nrc_order_did_before_session` | nrc_order | **no** | 0: - | yes | 1: `gold_write_unknown_did_default_session` |
| `nrc_order_security_before_length` | nrc_order | yes | 5: `req_005__tpl_write_badlen_0100`, `req_006__tpl_write_badlen_0101`, `req_007__tpl_write_badlen_0130` (+2 more) | yes | 1: `gold_write_wrong_length` |
| `general_reject_instead_of_0x12` | format | yes | 23: `req_003__tpl_unsupported_subfunction_10_01`, `req_003__tpl_unsupported_subfunction_10_03`, `req_004__tpl_unsupported_subfunction_10_02` (+20 more) | yes | 4: `gold_session_unsupported_sub`, `gold_ecu_reset_bad_sub`, `gold_dtc_read_bad_sub` (+1 more) |
| `security_not_reset_on_session_change` | session | **no** | 0: - | yes | 1: `gold_security_relocked_on_session_reentry` |
| `s3_timeout_never_fires` | timing | yes | 13: `req_001__tpl_s3_timeout_02`, `req_001__tpl_s3_timeout_03`, `req_002__tpl_s3_timeout_02` (+10 more) | yes | 1: `gold_s3_timeout_reverts` |
| `s3_timeout_off_by_one` | timing | **no** | 0: - | yes | 1: `gold_s3_no_timeout_at_exactly_s3ms` |
| `lockout_after_extra_attempt` | security | yes | 6: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_007__tpl_security_lockout_01` (+3 more) | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_ignored` | security | yes | 6: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_007__tpl_security_lockout_01` (+3 more) | yes | 1: `gold_security_lockout_after_3` |
| `lockout_delay_never_expires` | timing | yes | 6: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_007__tpl_security_lockout_01` (+3 more) | **no** | 0: - |
| `accepts_any_key` | security | yes | 6: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_007__tpl_security_lockout_01` (+3 more) | yes | 3: `gold_security_wrong_key_once`, `gold_security_lockout_after_3`, `gold_security_wrong_level_unlock` |
| `seed_not_consumed` | sequence | **no** | 0: - | **no** | 0: - |
| `static_seed` | security | yes | 6: `req_005__tpl_security_lockout_01`, `req_006__tpl_security_lockout_01`, `req_007__tpl_security_lockout_01` (+3 more) | yes | 1: `gold_security_lockout_after_3` |
| `write_ignores_value_range` | data | yes | 5: `req_005__tpl_write_oor_0100`, `req_006__tpl_write_oor_0101`, `req_007__tpl_write_oor_0130` (+2 more) | yes | 2: `gold_write_out_of_range_wiper`, `gold_write_out_of_range_brightness` |
| `readonly_did_writable` | data | **no** | 0: - | yes | 1: `gold_write_readonly_did` |
| `write_length_off_by_one` | format | yes | 5: `req_005__tpl_write_badlen_0100`, `req_006__tpl_write_badlen_0101`, `req_007__tpl_write_badlen_0130` (+2 more) | yes | 1: `gold_write_wrong_length` |
| `write_positive_sid_wrong` | format | yes | 4: `req_005__tpl_write_secured_0100`, `req_006__tpl_write_secured_0101`, `req_007__tpl_write_secured_0130` (+1 more) | yes | 5: `gold_write_secured_positive_lighting`, `gold_write_secured_positive_ambient_color`, `gold_write_coding_variant` (+2 more) |
| `session_response_missing_timing` | format | yes | 72: `req_001__tpl_read_did_positive_f190_02`, `req_001__tpl_read_did_positive_f190_03`, `req_001__tpl_s3_timeout_02` (+69 more) | yes | 35: `gold_read_vin_extended`, `gold_session_to_extended`, `gold_session_back_default` (+32 more) |
| `suppress_bit_ignored` | format | yes | 6: `req_003__tpl_suppress_positive_10_01`, `req_003__tpl_suppress_positive_10_03`, `req_004__tpl_suppress_positive_10_02` (+3 more) | yes | 2: `gold_tester_present_suppressed`, `gold_ecu_reset_suppressed` |
| `negative_response_suppressed` | format | **no** | 0: - | yes | 1: `gold_tester_present_bad_sub_not_suppressed` |
| `routine_stop_without_start` | sequence | yes | 2: `req_011__tpl_routine_sequence_0201`, `req_012__tpl_routine_sequence_0202` | yes | 1: `gold_routine_stop_before_start` |
| `condition_ignored` | data | yes | 1: `req_009__tpl_condition_not_met_did_0150` | yes | 2: `gold_routine_door_cal_condition_fail`, `gold_write_factory_reset_flag_moving` |
| `dtc_clear_ignores_group` | data | **no** | 0: - | yes | 2: `gold_dtc_clear_specific`, `gold_dtc_clear_unknown_group` |
| `dtc_clear_noop` | data | yes | 3: `req_014__tpl_dtc_read_clear_B10101`, `req_014__tpl_dtc_read_clear_B10205`, `req_014__tpl_dtc_read_clear_B10310` | yes | 2: `gold_dtc_clear_all`, `gold_dtc_clear_specific` |
| `multi_did_read_first_only` | data | **no** | 0: - | yes | 2: `gold_read_partnum_serial_multi`, `gold_duplicate_did_read` |
| `missing_response_pending` | timing | **no** | 0: - | yes | 1: `gold_routine_nvm_restore_long_running` |
| `dtc_read_ignores_mask` | data | yes | 3: `req_014__tpl_dtc_read_clear_B10101`, `req_014__tpl_dtc_read_clear_B10205`, `req_014__tpl_dtc_read_clear_B10310` | yes | 4: `gold_dtc_read_default`, `gold_dtc_set_and_read`, `gold_dtc_clear_all` (+1 more) |

Invalid tests (fail on the clean simulator, excluded from credit): generated 0, gold 0.
Detected only by the generated suite: lockout_delay_never_expires. Only by gold: nrc_order_did_before_session, security_not_reset_on_session_change, s3_timeout_off_by_one, readonly_did_writable, negative_response_suppressed, dtc_clear_ignores_group, multi_did_read_first_only, missing_response_pending. Undetected by both: seed_not_consumed.

## Coverage (generated tests per category per requirement)

| Requirement | positive | negative | session | security | timing | total |
|---|---|---|---|---|---|---|
| REQ-001 | 3 | 1 | 0 | 0 | 2 | 6 |
| REQ-002 | 6 | 1 | 0 | 0 | 2 | 9 |
| REQ-003 | 2 | 2 | 0 | 0 | 1 | 5 |
| REQ-004 | 1 | 1 | 0 | 0 | 1 | 3 |
| REQ-005 | 1 | 5 | 2 | 1 | 1 | 10 |
| REQ-006 | 1 | 5 | 2 | 1 | 1 | 10 |
| REQ-007 | 1 | 3 | 2 | 1 | 1 | 8 |
| REQ-008 | 1 | 3 | 2 | 1 | 1 | 8 |
| REQ-009 | 0 | 5 | 3 | 1 | 1 | 10 |
| REQ-010 | 0 | 2 | 1 | 1 | 0 | 4 |
| REQ-011 | 0 | 3 | 1 | 0 | 0 | 4 |
| REQ-012 | 0 | 4 | 2 | 0 | 0 | 6 |
| REQ-013 | 0 | 3 | 0 | 0 | 0 | 3 |
| REQ-014 | 3 | 2 | 2 | 0 | 0 | 7 |
| REQ-015 | 3 | 3 | 0 | 0 | 2 | 8 |
| **total** | 22 | 43 | 17 | 6 | 13 | 101 |

Categories present: 100.0%; requirements covered by ≥2 categories: 14/15.

## Request validity

- Send steps: 268; decodable: 268; not rejected with a format NRC (0x11/0x12/0x13): 237 (unadjusted rate 88.4%).
- Intentional format probes (NRC in the template's `intended_nrcs`): 28. Adjusted validity: **98.9%**.

## Expected-response accuracy

- Oracle re-run: 268/268 (100.0%) steps; 101/101 (100.0%) tests. (Expected bytes are produced by the oracle, so this is a consistency check, not an independent accuracy measure.)
- Independent simulator (clean): 100.0% of generated tests pass.
- Gold, exact overlap: 22 generated/gold pairs with identical step sequences; agreement 100.0%.
- Gold, shared prefix: 15 distinct send steps reached by an identical prefix in both suites; agreement 100.0%.

## Template reuse and citations

- Templates used: 14/14; per template: `condition_not_met` 2, `dtc_read_clear` 3, `read_did_positive` 9, `read_did_wrong_session_or_unknown` 2, `routine_sequence` 2, `s3_timeout_reverts_session` 13, `security_invalid_key_lockout` 6, `service_not_in_session` 17, `suppress_positive_response` 6, `unsupported_subfunction` 23, `write_did_invalid_length` 5, `write_did_out_of_range` 5, `write_did_secured_positive` 4, `write_did_without_security` 4
- Citations: 460/460 valid; tests with ≥1 valid citation: 100.0%.

## Pipeline statistics

| Requirement | tests | dropped | rejected | plan attempts | status |
|---|---|---|---|---|---|
| REQ-001 | 6 | 0 | 0 | 1 | completed |
| REQ-002 | 9 | 0 | 0 | 1 | completed |
| REQ-003 | 5 | 0 | 0 | 1 | completed |
| REQ-004 | 3 | 0 | 0 | 1 | completed |
| REQ-005 | 10 | 0 | 0 | 1 | completed |
| REQ-006 | 10 | 0 | 0 | 1 | completed |
| REQ-007 | 8 | 0 | 0 | 1 | completed |
| REQ-008 | 8 | 0 | 0 | 1 | completed |
| REQ-009 | 10 | 0 | 0 | 1 | completed |
| REQ-010 | 4 | 0 | 0 | 1 | completed |
| REQ-011 | 4 | 0 | 0 | 1 | completed |
| REQ-012 | 6 | 0 | 0 | 1 | completed |
| REQ-013 | 3 | 0 | 0 | 1 | completed |
| REQ-014 | 7 | 0 | 0 | 1 | completed |
| REQ-015 | 8 | 0 | 0 | 1 | completed |

Totals: 101 kept, 0 dropped, 0 rejected, 0 re-plans, 0 failed runs.

## Exports

- `exports/generated_tests_test.py`
- `exports/gold_tests_test.py`
- `exports/generated_tests.can`
- `exports/gold_tests.can`
- Ran `generated_tests_test.py` (transport `inprocess`) with pytest in a subprocess: **PASSED** — `101 passed in 0.87s` (3.35 s).
- CAPL files (`*.can`) are **UNVERIFIED TEMPLATES — not compiled or run in CANoe**.

## Runtime

| Phase | seconds |
|---|---|
| setup | 1.668 |
| generation | 2.317 |
| execution_and_bug_matrix | 11.218 |
| metrics | 0.128 |
| exports | 3.825 |
| total | 19.157 |

## Metric definitions

- **request_validity**: Over every send step of every generated test: the request is replayed through the rules-engine oracle in sequence (same set-up and time steps). A request counts as well-formed if (a) protocol.codec.decode_request decodes it and (b) the oracle does not reject it with a format NRC (0x11 serviceNotSupported, 0x12 subFunctionNotSupported, 0x13 incorrectMessageLengthOrInvalidFormat), unless that NRC is listed in the template's declared intended_nrcs (a deliberate malformed-request probe such as write_did_invalid_length -> 0x13). rate = well-formed / send steps. The unadjusted rate (no intent exemption) is reported alongside.
- **expected_response_accuracy**: oracle: share of generated send steps whose expected response frames equal a fresh rules-engine re-run of the test (and share of whole tests with zero mismatches). simulator: share of generated tests passing on the bug-free independent simulator. gold: (1) exact overlap = generated tests whose full step sequence (requests and set-up/time steps, ignoring expected responses) is identical to a gold test; agreement = identical expected responses on every step. (2) shared-prefix overlap = every distinct send step reached by an identical step prefix from power-on in both a generated and a gold test (deduplicated by prefix); agreement = identical expected frames for that step.
- **coverage**: Number of generated tests per category (positive/negative/session/security/timing) per requirement. rate = requirements with >= 1 generated test / requirements; category_presence = categories with >= 1 test across the suite / 5.
- **template_reuse_rate**: Share of generated tests whose template_id is a registered template AND whose steps are byte-identical to a fresh instantiation of that template with the test's stored parameters (independent re-check of byte provenance).
- **citation_validity**: Share of all citations attached to generated tests for which rag.citations.citation_is_valid is true against the evaluation corpus (source+ref exists; a quote must appear verbatim and its hex identifiers must belong to the chunk).
- **bug_detection_rate**: Each catalog bug is enabled alone in a fresh simulator per test. A bug is detected if >= 1 test that passes on the clean simulator fails with the bug enabled. Tests failing on the clean simulator are reported as invalid and get no credit. rate = detected bugs / catalog bugs. Reported for the generated suite (headline), the hand-written gold suite (baseline) and their union.
- **pipeline_stats**: Per requirement: kept tests, dropped tests (failed validation), rejected planner choices, plan attempts (retries = attempts - 1), run status.
- **runtime**: Wall-clock seconds per evaluation phase and in total (machine dependent).
