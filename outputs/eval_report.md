# Evaluation report — UDS test generation assistant

- **Generated:** 2026-10-03T05:33:24.789329+00:00 (git `d4f06b0b3f652d071732624e8b15d8babe5b5013`, uncommitted changes present)
- **LLM mode used:** `mock` (requested `mock`)
- **Agent engine:** `langgraph` · **Retriever:** `Bm25Retriever`
- **Template set:** `v2` (23 templates)
- **Inputs:** 15 seed requirements, 20 labelled natural requirements, 60 gold tests, 12 held-out + 26 in-sample injectable simulator bugs

> **The ECU spec is synthetic.** `data/bcm_spec.yaml` describes a fictional Body Control Module written for this project in an OEM-like style; no real OEM document or ISO 14229 text is used. All numbers below are measured against the project's own simulator.
>
> **Mode:** LLM-dependent numbers are for `mode=mock`. In mock mode the LLM is a deterministic keyword/rule stand-in; numbers for `mode=ollama` (local Qwen2.5-3B) are **pending Part B / not run** (no model download in the offline build).

> **Template set v2:** v1 + 9 generic templates (multi-DID read, write to read-only DID, session change re-locks security, key replay, DTC clear specific/unknown group, negative response with suppress bit, S3 keep-alive boundary, NRC priority session-before-identifier, routine start+results incl. 0x78) and a fix so routine starts carry the spec'd option record. Added in Phase 7 AFTER inspecting which catalog bugs v1 missed; the same author wrote the bug catalog, so v2 detection is an optimistic, non-independent number.

## Headline metrics

| Metric | mock | ollama |
|---|---|---|
| 1. Simulator ↔ rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 2. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 3. udsoncan virtual-CAN sequence (session → seed/key → read → write → read-back) | PASS | same (LLM-independent) |
| **4. Held-out bug detection (12 bugs; HEADLINE = generated)** | **generated 3/12 (25.0%)** · gold 3/12 (25.0%) · union 5/12 (41.7%) | pending Part B |
| 5. Requirement understanding (natural requirements) | test split (n=12): target exact match parsed 5/12 (F1 0.700), exercised 2/12 (F1 0.449); category recall 67.9% micro / 69.7% macro; precondition recall 80.0% micro / 75.0% macro; fallback/nothing 3/12 (2 excl. NAT-020-style empty-label rows) | pending Part B |
| 6. Coverage (seed requirements; tests per category) | positive 36, negative 70, session 21, security 18, timing 26; requirements with ≥1 test 15/15 (100.0%) | pending Part B |
| 7. Citation validity | 774/774 (100.0%) | pending Part B |

Rows 1-3 and the gold number in row 4 do not depend on the LLM; row 4 generated/union and rows 5-7 do. The self-consistency check (expected responses vs the oracle that produced them) is in the appendix, and the in-sample 26-bug detection is a secondary section, because the templates were tuned on those bugs.

Generated tests (seed requirements): **171** (94 unique template instantiations); 171/171 (100.0%) pass on the clean simulator; P2/P2* wall-clock warnings: 0.

## Held-out bug detection (12 bugs, not seen when templates/gold were written)

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

### Missed held-out bugs — generated suite

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

## Requirement understanding (natural requirements)

Source: `data/requirements_natural.csv` (20 labelled rows). Each requirement was run through the agent pipeline (`mode=mock`, Bm25Retriever). **The TEST split is the main number.** Ollama: pending Part B.

| Split | n | Targets exact (parsed) | Parsed P / R / F1 | Targets exact (exercised) | Exercised P / R / F1 | Category recall micro / macro | Precondition recall micro / macro | Fallback / nothing |
|---|---|---|---|---|---|---|---|---|
| **test** | 12 | 5/12 (41.7%) | 0.933 / 0.560 / 0.700 | 2/12 (16.7%) | 0.312 / 0.800 / 0.449 | 19/28 (67.9%) / 69.7% | 12/15 (80.0%) / 75.0% | 3 (2 excl. empty-label rows) |
| dev | 8 | 4/8 (50.0%) | 1.000 / 0.706 / 0.828 | 0/8 (0.0%) | 0.333 / 0.941 / 0.492 | 14/22 (63.6%) / 60.4% | 9/9 (100.0%) / 100.0% | 1 (1 excl. empty-label rows) |
| all | 20 | 9/20 (45.0%) | 0.963 / 0.619 / 0.754 | 2/20 (10.0%) | 0.321 / 0.857 / 0.468 | 33/50 (66.0%) / 65.8% | 21/24 (87.5%) / 83.3% | 4 (3 excl. empty-label rows) |

### Per requirement

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

## Secondary: in-sample bug detection (26 bugs — templates tuned on these)

Scope: in-sample (templates tuned on these). Generated 25/26 (96.2%), gold 24/26 (92.3%), union 26/26 (100.0%). This is an optimistic, non-independent number: template set v2 was written after seeing which of these bugs v1 missed, by the same author as the catalog.

### Before / after template additions (in-sample)

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

### Bug detection per injected bug (in-sample)

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

## Coverage (generated tests per category per seed requirement)

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
- Intentional format probes (NRC in the template's `intended_nrcs`): 41. Adjusted validity: **445/445 (100.0%)**.

## Template reuse and citations

- Template reuse: 171/171 (100.0%); templates used: 23/23; per template: `condition_not_met` 2, `dtc_clear_specific_keeps_others` 3, `dtc_read_clear` 3, `negative_response_with_suppress_bit` 13, `nrc_priority_session_over_identifier` 11, `read_did_positive` 9, `read_did_wrong_session_or_unknown` 2, `read_multiple_dids` 9, `routine_sequence` 2, `routine_start_results` 2, `s3_keepalive_boundary` 13, `s3_timeout_reverts_session` 13, `security_invalid_key_lockout` 6, `seed_replay_rejected` 6, `service_not_in_session` 21, `session_change_relocks_security` 6, `suppress_positive_response` 6, `unsupported_subfunction` 23, `write_did_invalid_length` 5, `write_did_out_of_range` 5, `write_did_secured_positive` 4, `write_did_without_security` 4, `write_readonly_did` 3
- Citations: 774/774 valid; tests with ≥1 valid citation: 100.0%.

## Pipeline statistics (seed requirements)

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
- Ran `generated_tests_test.py` (transport `inprocess`) with pytest in a subprocess: **PASSED** — `171 passed in 1.11s` (4.03 s).
- CAPL files (`*.can`) are **UNVERIFIED TEMPLATES — not compiled or run in CANoe**.

## Runtime

| Phase | seconds |
|---|---|
| setup | 2.168 |
| generation | 5.18 |
| requirement_understanding | 5.464 |
| execution_and_bug_matrix | 24.896 |
| heldout_bug_matrix | 0.52 |
| simulator_rules_agreement | 0.515 |
| udsoncan_virtual_can | 0.408 |
| metrics | 0.232 |
| exports | 4.82 |
| total | 44.204 |

## Appendix: Self-consistency check (circular by construction)

Expected bytes in generated tests are produced by the rules-engine oracle, so agreement with a fresh oracle re-run is a consistency check, not an independent accuracy measure. Kept here for completeness; it is not a headline metric.

- Expected-response accuracy vs oracle: 445/445 (100.0%) steps; 171/171 (100.0%) tests.
- Independent simulator (clean): 100.0% of generated tests pass.
- Gold, exact overlap: 25/25 (100.0%) generated/gold pairs with identical step sequences agree.
- Gold, shared prefix: 18/18 (100.0%) distinct send steps reached by an identical prefix in both suites agree.

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
