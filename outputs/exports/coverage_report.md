# Coverage report

12 tests. By category: negative 4, positive 5, session 3.

Spec items with ZERO tests: 34. (NRC universe = the NRCs the rules engine can emit; the spec file lists none.)

## Services

| Item | Tests | Positive | Negative |
|---|---|---|---|
| 0x10 DiagnosticSessionControl | 6 | 4 | 2 |
| 0x11 EcuReset | 3 | 2 | 1 |
| **0x14 ClearDiagnosticInformation — UNCOVERED** | 0 | 0 | 0 |
| **0x19 ReadDtcInformation — UNCOVERED** | 0 | 0 | 0 |
| 0x22 ReadDataByIdentifier | 4 | 3 | 1 |
| **0x27 SecurityAccess — UNCOVERED** | 0 | 0 | 0 |
| **0x2e WriteDataByIdentifier — UNCOVERED** | 0 | 0 | 0 |
| **0x31 RoutineControl — UNCOVERED** | 0 | 0 | 0 |
| **0x3e TesterPresent — UNCOVERED** | 0 | 0 | 0 |

Zero tests: 0x14 ClearDiagnosticInformation, 0x19 ReadDtcInformation, 0x27 SecurityAccess, 0x2e WriteDataByIdentifier, 0x31 RoutineControl, 0x3e TesterPresent

## DIDs

| Item | Tests | Positive | Negative |
|---|---|---|---|
| **0x0100 interior_lighting_brightness_pct — UNCOVERED** | 0 | 0 | 0 |
| **0x0101 ambient_lighting_color_index — UNCOVERED** | 0 | 0 | 0 |
| **0x0110 driver_door_lock_state — UNCOVERED** | 0 | 0 | 0 |
| **0x0111 passenger_door_lock_state — UNCOVERED** | 0 | 0 | 0 |
| **0x0120 central_locking_auto_relock_enable — UNCOVERED** | 0 | 0 | 0 |
| **0x0130 wiper_sensitivity_level — UNCOVERED** | 0 | 0 | 0 |
| **0x0131 wiper_auto_mode_enable — UNCOVERED** | 0 | 0 | 0 |
| **0x0140 vehicle_speed_kph — UNCOVERED** | 0 | 0 | 0 |
| **0x0150 factory_reset_flag — UNCOVERED** | 0 | 0 | 0 |
| **0x0160 coding_variant_id — UNCOVERED** | 0 | 0 | 0 |
| **0xf186 active_diagnostic_session — UNCOVERED** | 0 | 0 | 0 |
| 0xf187 manufacturer_part_number | 1 | 1 | 0 |
| 0xf18c ecu_serial_number | 1 | 1 | 0 |
| 0xf190 VIN | 2 | 2 | 0 |

Zero tests: 0x0100 interior_lighting_brightness_pct, 0x0101 ambient_lighting_color_index, 0x0110 driver_door_lock_state, 0x0111 passenger_door_lock_state, 0x0120 central_locking_auto_relock_enable, 0x0130 wiper_sensitivity_level, 0x0131 wiper_auto_mode_enable, 0x0140 vehicle_speed_kph, 0x0150 factory_reset_flag, 0x0160 coding_variant_id, 0xf186 active_diagnostic_session

## Routines

| Item | Tests | Positive | Negative |
|---|---|---|---|
| **0x0201 lighting_self_test — UNCOVERED** | 0 | 0 | 0 |
| **0x0202 door_actuator_calibration — UNCOVERED** | 0 | 0 | 0 |
| **0x0203 nvm_factory_restore — UNCOVERED** | 0 | 0 | 0 |

Zero tests: 0x0201 lighting_self_test, 0x0202 door_actuator_calibration, 0x0203 nvm_factory_restore

## NRCs

| Item | Tests |
|---|---|
| **0x11 serviceNotSupported — UNCOVERED** | 0 |
| 0x12 subFunctionNotSupported | 2 |
| 0x13 incorrectMessageLengthOrInvalidFormat | 1 |
| **0x14 responseTooLong — UNCOVERED** | 0 |
| **0x22 conditionsNotCorrect — UNCOVERED** | 0 |
| **0x24 requestSequenceError — UNCOVERED** | 0 |
| 0x31 requestOutOfRange | 1 |
| **0x33 securityAccessDenied — UNCOVERED** | 0 |
| **0x35 invalidKey — UNCOVERED** | 0 |
| **0x36 exceedNumberOfAttempts — UNCOVERED** | 0 |
| **0x37 requiredTimeDelayNotExpired — UNCOVERED** | 0 |
| **0x72 generalProgrammingFailure — UNCOVERED** | 0 |
| **0x78 requestCorrectlyReceivedResponsePending — UNCOVERED** | 0 |
| **0x7e subFunctionNotSupportedInActiveSession — UNCOVERED** | 0 |
| **0x7f serviceNotSupportedInActiveSession — UNCOVERED** | 0 |

Zero tests: 0x11 serviceNotSupported, 0x14 responseTooLong, 0x22 conditionsNotCorrect, 0x24 requestSequenceError, 0x33 securityAccessDenied, 0x35 invalidKey, 0x36 exceedNumberOfAttempts, 0x37 requiredTimeDelayNotExpired, 0x72 generalProgrammingFailure, 0x78 requestCorrectlyReceivedResponsePending, 0x7e subFunctionNotSupportedInActiveSession, 0x7f serviceNotSupportedInActiveSession

## Sessions

| Item | Tests |
|---|---|
| 0x01 default | 12 |
| 0x02 programming | 1 |
| 0x03 extended | 3 |

Zero tests: none

## Security levels

| Item | Tests |
|---|---|
| **0x01 extended_diag — UNCOVERED** | 0 |
| **0x03 programming — UNCOVERED** | 0 |

Zero tests: 0x01 extended_diag, 0x03 programming
