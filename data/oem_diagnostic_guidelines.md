# Body Control Module Diagnostic Guidelines (OEM layer)

> **SYNTHETIC — written for this project, not a real OEM document.**
> It plays the role of an OEM's diagnostic policy for the synthetic BCM in `data/bcm_spec.yaml`.
> All numbers agree with that spec and with `docs/behaviour_contract.md`. The wording is original.

This guideline sits between the protocol reference (the `standard` layer) and the ECU spec (the `ecu` layer).
It says how this OEM expects its ECUs to use the protocol: which values to choose and which responses to prefer.

## Session timing policy {#oem-session-timing}

Every diagnostic session of the BCM (default 0x01, programming 0x02, extended 0x03) uses the same timing values.

- P2 server time: 50 ms. A tester should expect the first answer within this time.
- P2* extended server time: 5000 ms. It applies after a response-pending answer (NRC 0x78). It is reported in 10 ms units, so 5000 ms is sent as 500 (0x01F4).
- S3 server timeout: 5000 ms. A non-default session that sees no request for more than 5000 ms falls back to the default session. A gap of exactly 5000 ms does not expire it.
- Testers keep a non-default session alive with TesterPresent (0x3E 00) at an interval clearly shorter than S3. Half of S3, 2500 ms, is the recommended period.
- Falling back to the default session locks security and clears routine status. Lockout counters are kept.

## Security access policy {#oem-security-access}

The BCM has two security levels, and only one can be unlocked at a time.

- Level 0x01 (extended diagnostics): seed request 0x01, key 0x02, available only in the extended session. It protects writing the comfort DIDs and running the lighting and door routines.
- Level 0x03 (programming): seed request 0x03, key 0x04, available only in the programming session. It protects the coding DIDs, the factory reset flag, and the NVM factory restore routine.
- The seed is 4 bytes long. A new seed request replaces an older pending seed. An already unlocked level answers a seed request with an all-zero seed.
- Attempt counter: a level allows 3 failed key attempts. The first and second wrong key give NRC 0x35 (invalid key). The third wrong key gives NRC 0x36 (exceeded number of attempts) and starts the lockout.
- Lockout delay: 10000 ms (10 seconds). While it runs, a seed request for that level is refused with NRC 0x37 (required time delay not expired).
- After the delay the attempt counter is NOT reset. One more wrong key gives NRC 0x36 at once and starts the delay again. Only a correct key resets the counter.
- A key sent without a pending seed is answered with NRC 0x24 (request sequence error), and it is not counted as an attempt.
- Lockout state survives session changes, S3 fallback and ECU reset.
- Tools must not guess keys and must not retry in a loop after NRC 0x36 or 0x37.

## NRC usage policy {#oem-nrc-usage}

The BCM reports the first failing check, in a fixed order. Tools and tests should expect exactly this order.

1. Service not supported by the ECU in any session: NRC 0x11.
2. Service not allowed in the active session: NRC 0x7F.
3. Wrong total request length for the service: NRC 0x13.
4. Sub-function not supported: NRC 0x12 (not applied to RoutineControl).
5. Sub-function not allowed in the active session (SecurityAccess levels): NRC 0x7E.
6. Wrong length for a particular sub-function: NRC 0x13.
7. Service-specific checks, for example NRC 0x31 (request out of range), 0x33 (security access denied), 0x22 (conditions not correct), 0x24 (request sequence error).

Further rules:

- Use NRC 0x31 for an unknown, unreadable or unwritable DID, an unknown routine, and a value outside the allowed range. Use it for ReadDataByIdentifier only when no requested DID can be answered.
- A write of the wrong data length gets NRC 0x13 before the security check, so a locked ECU still reveals a length mistake first.
- Use NRC 0x33 only when the unlocked level is not exactly the level the DID or routine requires. Level 0x03 does not imply level 0x01.
- NRC 0x22 is for unmet conditions such as the vehicle not being stationary.
- NRC 0x72 (general programming failure) is only for a failed NVM write, in WriteDataByIdentifier and ClearDiagnosticInformation.
- NRC 0x78 (response pending) is used only for the start of a long-running routine, and exactly once.
- NRC 0x14 is used only when a response would be longer than the transport limit of 4095 bytes.
- NRC 0x10 is not used by a correct BCM.
- A negative response is always the three bytes 0x7F, the service id and the NRC.

## DID naming and range convention {#oem-did-convention}

- DIDs in 0xF100 to 0xF1FF identify the ECU: VIN (0xF190), part number (0xF187), serial number (0xF18C) and active session (0xF186). They are read-only and readable in every session.
- DIDs in 0x0100 to 0x01FF belong to the body functions. Block 0x0100 to 0x0101 is lighting, 0x0110 to 0x0111 door state, 0x0120 central locking, 0x0130 to 0x0131 wipers, 0x0140 vehicle signals, 0x0150 to 0x0160 service and coding data.
- Names are lower-case words joined by underscores, and a unit goes at the end when it applies, for example `interior_lighting_brightness_pct`.
- A writable DID states its legal value range, and a write outside that range is refused. Comfort DIDs are written in the extended session with level 0x01. Coding and service DIDs are written in the programming session with level 0x03.
- A DID whose write needs a vehicle condition names it, for example `vehicle_stationary` for the factory reset flag.

## Suppress positive response policy {#oem-suppress-response}

- The suppress bit is bit 7 of the sub-function byte. It is honoured for DiagnosticSessionControl, ECUReset, ReadDTCInformation, SecurityAccess, RoutineControl and TesterPresent.
- A suppressed request is processed exactly like the normal one. Only the positive answer is left out, and all state changes still happen.
- Negative responses are never suppressed. For example, 0x3E 81 gets a negative response with NRC 0x12.
- The only exception is the start of a long-running routine: the pending answer and the final positive answer are still sent.
- Testers use the bit for TesterPresent during keep-alive. They should not use it for requests whose answer they need to verify.

## ECU reset and NVM retention policy {#oem-ecu-reset-nvm}

- The BCM supports hard reset (0x01) and soft reset (0x03). Both end in the default session, with security locked, pending seeds dropped and routine status cleared.
- Retained across a reset: the failed-attempt counters and lockout deadlines, written DID values, and DTC status.
- DTC status is only cleared by ClearDiagnosticInformation. The group 0xFFFFFF clears all DTCs, and a single DTC number clears just that DTC.
- If the NVM has a write fault, a write or a clear is refused with NRC 0x72 and nothing is changed.
- The NVM factory restore routine (0x0203) needs the programming session and level 0x03. It has no stop control, and its start is answered with NRC 0x78 followed by the final answer.
