# Imported-test baseline coverage (fixture suite vs this run's generated tests)

Synthetic ECU spec (`data/bcm_spec.yaml`). Static coverage of the tests' own steps; nothing here was executed. Imported tests are the user's existing suite (not AI-generated); generated tests come from the assistant's pipeline. Both need human review before they run; simulator or approved lab bench only.

Imported 14 tests, generated 77 tests, combined 91.

## Summary (items touched / items in the spec)

| Kind | Imported (baseline) | Generated | Combined | Newly covered by generated |
|---|---|---|---|---|
| Services | 6/9 | 9/9 | 9/9 | 3 |
| DIDs | 5/14 | 10/14 | 10/14 | 5 |
| Routines | 0/3 | 2/3 | 2/3 | 2 |
| NRCs | 6/15 | 10/15 | 11/15 | 5 |
| Sessions | 2/3 | 3/3 | 3/3 | 1 |
| Security levels | 1/2 | 2/2 | 2/2 | 1 |
| Timing cases | 2/5 | 3/5 | 4/5 | 2 |

## Newly covered (zero imported tests, at least one generated test)

- **Services:** 0x14 ClearDiagnosticInformation; 0x19 ReadDtcInformation; 0x31 RoutineControl
- **DIDs:** 0x0101 ambient_lighting_color_index; 0x0110 driver_door_lock_state; 0x0130 wiper_sensitivity_level; 0x0150 factory_reset_flag; 0x0160 coding_variant_id
- **Routines:** 0x0201 lighting_self_test; 0x0202 door_actuator_calibration
- **NRCs:** 0x22 conditionsNotCorrect; 0x24 requestSequenceError; 0x36 exceedNumberOfAttempts; 0x37 requiredTimeDelayNotExpired; 0x7f serviceNotSupportedInActiveSession
- **Sessions:** 0x02 programming
- **Security levels:** 0x03 programming
- **Timing cases:** Wait shorter than S3 keeps the session; Security delay timer (wait, then 0x27 after a 0x36 / 0x37 NRC)

## Covered only by imported tests

- **NRCs:** 0x11 serviceNotSupported
- **Timing cases:** P2 response-time limit (send step with max_response_time_ms)

## Still uncovered by the combined suite

- **DIDs:** 0x0111 passenger_door_lock_state; 0x0120 central_locking_auto_relock_enable; 0x0131 wiper_auto_mode_enable; 0x0140 vehicle_speed_kph
- **Routines:** 0x0203 nvm_factory_restore
- **NRCs:** 0x14 responseTooLong; 0x72 generalProgrammingFailure; 0x78 requestCorrectlyReceivedResponsePending; 0x7e subFunctionNotSupportedInActiveSession
- **Timing cases:** Response pending (7F xx 78, then the final response)

## Per-item tests (imported / generated / combined)

### Services

| Item | Imported | Generated | Combined |
|---|---|---|---|
| 0x10 DiagnosticSessionControl | 7 | 51 | 58 |
| 0x11 EcuReset | 1 | 6 | 7 |
| 0x14 ClearDiagnosticInformation (new) | 0 | 1 | 1 |
| 0x19 ReadDtcInformation (new) | 0 | 4 | 4 |
| 0x22 ReadDataByIdentifier | 8 | 39 | 47 |
| 0x27 SecurityAccess | 2 | 21 | 23 |
| 0x2e WriteDataByIdentifier | 2 | 18 | 20 |
| 0x31 RoutineControl (new) | 0 | 6 | 6 |
| 0x3e TesterPresent | 1 | 4 | 5 |

### DIDs

| Item | Imported | Generated | Combined |
|---|---|---|---|
| 0x0100 interior_lighting_brightness_pct | 2 | 11 | 13 |
| 0x0101 ambient_lighting_color_index (new) | 0 | 3 | 3 |
| 0x0110 driver_door_lock_state (new) | 0 | 3 | 3 |
| 0x0111 passenger_door_lock_state | 0 | 0 | 0 |
| 0x0120 central_locking_auto_relock_enable | 0 | 0 | 0 |
| 0x0130 wiper_sensitivity_level (new) | 0 | 4 | 4 |
| 0x0131 wiper_auto_mode_enable | 0 | 0 | 0 |
| 0x0140 vehicle_speed_kph | 0 | 0 | 0 |
| 0x0150 factory_reset_flag (new) | 0 | 6 | 6 |
| 0x0160 coding_variant_id (new) | 0 | 1 | 1 |
| 0xf186 active_diagnostic_session | 2 | 6 | 8 |
| 0xf187 manufacturer_part_number | 1 | 5 | 6 |
| 0xf18c ecu_serial_number | 1 | 3 | 4 |
| 0xf190 VIN | 2 | 11 | 13 |

### Routines

| Item | Imported | Generated | Combined |
|---|---|---|---|
| 0x0201 lighting_self_test (new) | 0 | 4 | 4 |
| 0x0202 door_actuator_calibration (new) | 0 | 2 | 2 |
| 0x0203 nvm_factory_restore | 0 | 0 | 0 |

### NRCs

| Item | Imported | Generated | Combined |
|---|---|---|---|
| 0x11 serviceNotSupported | 1 | 0 | 1 |
| 0x12 subFunctionNotSupported | 1 | 14 | 15 |
| 0x13 incorrectMessageLengthOrInvalidFormat | 1 | 3 | 4 |
| 0x14 responseTooLong | 0 | 0 | 0 |
| 0x22 conditionsNotCorrect (new) | 0 | 1 | 1 |
| 0x24 requestSequenceError (new) | 0 | 2 | 2 |
| 0x31 requestOutOfRange | 1 | 7 | 8 |
| 0x33 securityAccessDenied | 1 | 3 | 4 |
| 0x35 invalidKey | 1 | 4 | 5 |
| 0x36 exceedNumberOfAttempts (new) | 0 | 4 | 4 |
| 0x37 requiredTimeDelayNotExpired (new) | 0 | 4 | 4 |
| 0x72 generalProgrammingFailure | 0 | 0 | 0 |
| 0x78 requestCorrectlyReceivedResponsePending | 0 | 0 | 0 |
| 0x7e subFunctionNotSupportedInActiveSession | 0 | 0 | 0 |
| 0x7f serviceNotSupportedInActiveSession (new) | 0 | 5 | 5 |

### Sessions

| Item | Imported | Generated | Combined |
|---|---|---|---|
| 0x01 default | 14 | 77 | 91 |
| 0x02 programming (new) | 0 | 18 | 18 |
| 0x03 extended | 6 | 33 | 39 |

### Security levels

| Item | Imported | Generated | Combined |
|---|---|---|---|
| 0x01 extended_diag | 2 | 17 | 19 |
| 0x03 programming (new) | 0 | 4 | 4 |

### Timing cases

| Item | Imported | Generated | Combined |
|---|---|---|---|
| P2 response-time limit (send step with max_response_time_ms) | 1 | 0 | 1 |
| Response pending (7F xx 78, then the final response) | 0 | 0 | 0 |
| S3 timeout drops a non-default session | 1 | 12 | 13 |
| Wait shorter than S3 keeps the session (new) | 0 | 1 | 1 |
| Security delay timer (wait, then 0x27 after a 0x36 / 0x37 NRC) (new) | 0 | 4 | 4 |
