# Diagnostic Q&A evaluation (blind set `data/qa_eval.csv`)

- git hash: `3a8c4e36c4244b45fa0b300aa683d7cf2519eec4+dirty`
- timestamp (UTC): 2026-10-04 12:24:29

| metric | mock | ollama |
|---|---|---|
| answer accuracy (answerable) | 90.5% (19/21) | 90.5% (19/21) |
| citation correctness | 95.2% (20/21) | 90.5% (19/21) |
| citation precision | 80.6% (25/31) | 79.3% (23/29) |
| correct not-found (unanswerable) | 75% (3/4) | 75% (3/4) |
| false not-found (answerable) | 0 | 0 |
| LLM fallback events | 0 | 11 |
| seconds | 0.1 | 87.8 |

## Per-question: mock

| id | answerable | status | accurate | cited ok | missing facts | cited chunks | s |
|---|---|---|---|---|---|---|---|
| QA-001 | True | answered | yes | yes |  | ecu:did:VIN | 0.0 |
| QA-002 | True | answered | yes | yes |  | ecu:did:interior_lighting_brightness_pct | 0.0 |
| QA-003 | True | answered | yes | yes |  | ecu:did:coding_variant_id | 0.0 |
| QA-004 | True | answered | yes | yes |  | ecu:did:factory_reset_flag | 0.0 |
| QA-005 | True | answered | yes | yes |  | ecu:did:manufacturer_part_number | 0.0 |
| QA-006 | False | not_found | n/a | correct |  |  | 0.01 |
| QA-007 | True | answered | yes | yes |  | ecu:did:driver_door_lock_state | 0.0 |
| QA-008 | True | answered | yes | yes |  | ecu:did:wiper_sensitivity_level | 0.0 |
| QA-009 | True | answered | yes | yes |  | ecu:routine:nvm_factory_restore | 0.0 |
| QA-010 | True | answered | yes | yes |  | ecu:routine:lighting_self_test | 0.0 |
| QA-011 | True | answered | yes | yes |  | standard:nrcs | 0.0 |
| QA-012 | False | not_found | n/a | correct |  |  | 0.0 |
| QA-013 | True | answered | yes | yes |  | oem:oem-nrc-usage, standard:nrcs, standard:svc-0x2e | 0.01 |
| QA-014 | True | answered | yes | yes |  | standard:nrcs | 0.0 |
| QA-015 | True | answered | yes | yes |  | ecu:session:default, ecu:session:extended, ecu:session:programming | 0.0 |
| QA-016 | True | answered | yes | yes |  | ecu:session:extended | 0.0 |
| QA-017 | True | answered | yes | yes |  | ecu:security_level:extended_diag | 0.0 |
| QA-018 | False | answered | n/a | WRONG (answered) |  | ecu:security_level:extended_diag, project:0x27-securityaccess | 0.01 |
| QA-019 | True | answered | yes | yes |  | ecu:session:extended, ecu:session:programming | 0.0 |
| QA-020 | True | answered | yes | yes |  | ecu:did:vehicle_speed_kph | 0.0 |
| QA-021 | True | answered | yes | yes |  | oem:oem-nrc-usage, standard:nrcs, standard:svc-0x22 | 0.01 |
| QA-022 | True | answered | NO | NO | term=default session, term=locks security | project:REQ-015 | 0.0 |
| QA-023 | True | answered | NO | yes | term=negative responses are never suppressed | standard:svc-0x3e, standard:uds-reference-notes-own-words-summary | 0.0 |
| QA-024 | False | not_found | n/a | correct |  |  | 0.0 |
| QA-025 | True | answered | yes | yes |  | oem:oem-suppress-response, standard:nrcs, standard:uds-reference-notes-own-words-summary | 0.0 |

## Per-question: ollama

| id | answerable | status | accurate | cited ok | missing facts | cited chunks | s |
|---|---|---|---|---|---|---|---|
| QA-001 | True | answered | yes | yes |  | ecu:did:VIN | 9.09 |
| QA-002 | True | answered | yes | yes |  | ecu:did:interior_lighting_brightness_pct | 3.29 |
| QA-003 | True | answered | yes | yes |  | ecu:did:coding_variant_id | 3.53 |
| QA-004 | True | answered | yes | yes |  | ecu:did:factory_reset_flag | 3.29 |
| QA-005 | True | answered | yes | yes |  | ecu:did:manufacturer_part_number | 3.39 |
| QA-006 | False | not_found | n/a | correct |  |  | 0.01 |
| QA-007 | True | answered | yes | yes |  | ecu:did:driver_door_lock_state | 3.47 |
| QA-008 | True | answered | yes | yes |  | ecu:did:wiper_sensitivity_level | 3.45 |
| QA-009 | True | answered | yes | yes |  | ecu:routine:nvm_factory_restore | 3.44 |
| QA-010 | True | answered | yes | yes |  | ecu:routine:lighting_self_test | 3.4 |
| QA-011 | True | answered | yes | yes |  | standard:nrcs | 3.42 |
| QA-012 | False | not_found | n/a | correct |  |  | 0.0 |
| QA-013 | True | answered | yes | yes |  | oem:oem-nrc-usage, standard:nrcs | 4.37 |
| QA-014 | True | answered | yes | yes |  | standard:nrcs | 3.4 |
| QA-015 | True | answered | yes | yes |  | ecu:session:default, ecu:session:extended, ecu:session:programming | 3.41 |
| QA-016 | True | answered | yes | yes |  | ecu:session:extended | 3.29 |
| QA-017 | True | answered | yes | yes |  | ecu:security_level:extended_diag | 3.33 |
| QA-018 | False | answered | n/a | WRONG (answered) |  | project:0x27-securityaccess | 4.08 |
| QA-019 | True | answered | yes | yes |  | ecu:session:extended, ecu:session:programming | 3.24 |
| QA-020 | True | answered | yes | yes |  | ecu:did:vehicle_speed_kph | 3.19 |
| QA-021 | True | answered | yes | yes |  | project:0x22-readdatabyidentifier, standard:nrcs, standard:svc-0x22 | 5.53 |
| QA-022 | True | answered | NO | NO | term=default session, term=locks security | project:REQ-015 | 3.77 |
| QA-023 | True | answered | NO | NO | term=bit 7, term=no response, term=negative responses are never suppressed | project:subfunction-byte | 5.51 |
| QA-024 | False | not_found | n/a | correct |  |  | 0.0 |
| QA-025 | True | answered | yes | yes |  | project:notation, standard:nrcs, standard:uds-reference-notes-own-words-summary | 4.85 |
