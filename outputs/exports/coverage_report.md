# Coverage report (generated tests, seed requirements)

77 tests. By category: negative 28, positive 28, security 7, session 5, timing 9.

Spec items with ZERO tests: 10. (NRC universe = the NRCs the rules engine can emit; the spec file lists none.)

## Services

| Item | Tests | Positive | Negative |
|---|---|---|---|
| 0x10 DiagnosticSessionControl | 51 | 50 | 4 |
| 0x11 EcuReset | 6 | 1 | 5 |
| 0x14 ClearDiagnosticInformation | 1 | 1 | 0 |
| 0x19 ReadDtcInformation | 4 | 1 | 3 |
| 0x22 ReadDataByIdentifier | 39 | 37 | 5 |
| 0x27 SecurityAccess | 21 | 20 | 5 |
| 0x2e WriteDataByIdentifier | 18 | 9 | 9 |
| 0x31 RoutineControl | 6 | 2 | 6 |
| 0x3e TesterPresent | 4 | 2 | 2 |

Zero tests: none

## DIDs

| Item | Tests | Positive | Negative |
|---|---|---|---|
| 0x0100 interior_lighting_brightness_pct | 11 | 8 | 3 |
| 0x0101 ambient_lighting_color_index | 3 | 3 | 0 |
| 0x0110 driver_door_lock_state | 3 | 3 | 1 |
| **0x0111 passenger_door_lock_state — UNCOVERED** | 0 | 0 | 0 |
| **0x0120 central_locking_auto_relock_enable — UNCOVERED** | 0 | 0 | 0 |
| 0x0130 wiper_sensitivity_level | 4 | 3 | 1 |
| **0x0131 wiper_auto_mode_enable — UNCOVERED** | 0 | 0 | 0 |
| **0x0140 vehicle_speed_kph — UNCOVERED** | 0 | 0 | 0 |
| 0x0150 factory_reset_flag | 6 | 2 | 4 |
| 0x0160 coding_variant_id | 1 | 0 | 1 |
| 0xf186 active_diagnostic_session | 6 | 6 | 0 |
| 0xf187 manufacturer_part_number | 5 | 5 | 1 |
| 0xf18c ecu_serial_number | 3 | 3 | 0 |
| 0xf190 VIN | 11 | 11 | 2 |

Zero tests: 0x0111 passenger_door_lock_state, 0x0120 central_locking_auto_relock_enable, 0x0131 wiper_auto_mode_enable, 0x0140 vehicle_speed_kph

## Routines

| Item | Tests | Positive | Negative |
|---|---|---|---|
| 0x0201 lighting_self_test | 4 | 0 | 4 |
| 0x0202 door_actuator_calibration | 2 | 2 | 2 |
| **0x0203 nvm_factory_restore — UNCOVERED** | 0 | 0 | 0 |

Zero tests: 0x0203 nvm_factory_restore

## NRCs

| Item | Tests |
|---|---|
| **0x11 serviceNotSupported — UNCOVERED** | 0 |
| 0x12 subFunctionNotSupported | 14 |
| 0x13 incorrectMessageLengthOrInvalidFormat | 3 |
| **0x14 responseTooLong — UNCOVERED** | 0 |
| 0x22 conditionsNotCorrect | 1 |
| 0x24 requestSequenceError | 2 |
| 0x31 requestOutOfRange | 7 |
| 0x33 securityAccessDenied | 3 |
| 0x35 invalidKey | 4 |
| 0x36 exceedNumberOfAttempts | 4 |
| 0x37 requiredTimeDelayNotExpired | 4 |
| **0x72 generalProgrammingFailure — UNCOVERED** | 0 |
| **0x78 requestCorrectlyReceivedResponsePending — UNCOVERED** | 0 |
| **0x7e subFunctionNotSupportedInActiveSession — UNCOVERED** | 0 |
| 0x7f serviceNotSupportedInActiveSession | 5 |

Zero tests: 0x11 serviceNotSupported, 0x14 responseTooLong, 0x72 generalProgrammingFailure, 0x78 requestCorrectlyReceivedResponsePending, 0x7e subFunctionNotSupportedInActiveSession

## Sessions

| Item | Tests |
|---|---|
| 0x01 default | 77 |
| 0x02 programming | 18 |
| 0x03 extended | 33 |

Zero tests: none

## Security levels

| Item | Tests |
|---|---|
| 0x01 extended_diag | 17 |
| 0x03 programming | 4 |

Zero tests: none
