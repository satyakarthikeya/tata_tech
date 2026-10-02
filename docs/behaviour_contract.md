# BCM behaviour contract (prose)

This is the behavioural specification of the synthetic BCM (`data/bcm_spec.yaml`), written in prose.
Two implementations are built from it independently:

- the rules engine (`uds_assistant/rules/`)
- the simulator (`uds_assistant/simulator/`)

The simulator must be written from this document and the spec YAML only, and never from the rules code.

## Notation

- Byte values are hex.
- "len" means the total request length, including the SID.
- A negative response is always exactly `7F SID NRC`.
- A positive response starts with `SID+0x40`.

## State at power-on

**Session and security**
- The active session is 0x01.
- No security level is unlocked.
- Each security level starts with 0 failed attempts and no lockout deadline.
- No seeds are pending, and the ECU-wide seed counter is 0.

**Routines and DTCs**
- No routine has a status yet.
- Each DTC status starts at the spec's `initial_status`.
- The DTC number is the 3-byte value of its code. For example, "B10101" is 0xB10101.

**DIDs**
- Each DID value starts at its `default_value`.

**Environment**
- The vehicle speed is 0 kph. The vehicle counts as stationary when its speed is exactly 0.
- The NVM write fault flag is false.

**Clock**
- There is no last-request timestamp yet.
- Time is always injected by the caller. The ECU never reads the wall clock.

## Before evaluating each request

1. **S3 timeout:** if all three conditions hold, the ECU drops back to the default session. The conditions are:
   - the active session is not 0x01
   - a last-request timestamp exists
   - `now − last_request` is strictly greater than the active session's `s3_ms`, so exactly 5000 ms does not expire

   Dropping back means: go to session 0x01, lock security, clear pending seeds, and clear all routine status.
2. **Lockout expiry:** for each level, if a lockout deadline is set and `now ≥ deadline`, clear the deadline. The failed-attempt count is **not** reset.
3. **Empty request:** an empty request gets no response. The only state change is the clock.
4. **S3 restart:** every non-empty request sets `last_request = now`, whether it is answered positively or negatively.

## Subfunction byte

- For 0x10, 0x11, 0x31 and 0x3E, bit 7 is the suppress-positive-response bit. It is stripped from the subfunction and honoured.
- For 0x19 and 0x27 the whole byte is the subfunction. So `27 81` and `19 82` are answered with NRC 0x12.

## NRC evaluation order (the first failing check wins)

### 1. Service supported → 0x11

The SID must be in the union of all sessions' `allowed_services`. Otherwise the answer is 0x11.

### 2. Service allowed in the active session → 0x7F

| Session | Allowed services |
|---|---|
| default (0x01) | 10, 11, 14, 19, 22, 3E |
| programming (0x02) | 10, 11, 22, 27, 2E, 31, 3E |
| extended (0x03) | all nine services |

### 3. Generic length → 0x13

| Service | Length rule |
|---|---|
| 0x10, 0x11, 0x3E | exactly 2 |
| 0x14 | exactly 4 |
| 0x19, 0x27 | at least 2 |
| 0x22 | at least 3, and (len−1) even |
| 0x2E, 0x31 | at least 4 |

### 4. Subfunction supported → 0x12

| Service | Supported subfunctions |
|---|---|
| 0x10 | 01, 02, 03 |
| 0x11 | 01, 03 |
| 0x19 | 02 |
| 0x27 | 01, 02, 03, 04 |
| 0x31 | 01, 02, 03 |
| 0x3E | 00 |

### 5. Subfunction allowed in session → 0x7E

This step only applies to 0x27, using each security level's `allowed_sessions`:
- Level 1 (subfunctions 01/02) is allowed only in session 0x03.
- Level 3 (subfunctions 03/04) is allowed only in session 0x02.

### 5b. Subfunction-specific length → 0x13

| Request | Length rule |
|---|---|
| `19 02` | exactly 3 |
| 0x27 seed request | exactly 2 |
| 0x27 key | exactly 2 + seed_length (4) |

### 6. Service-specific checks

These are listed per service below.

## Services

### 0x10 DiagnosticSessionControl

- No NRCs beyond the generic checks.
- Response: `50 ss` followed by four timing bytes:
  - P2 in ms (2 bytes, big-endian)
  - P2* in 10 ms units (2 bytes, big-endian)

  Both come from the target session's timing. For example: `50 03 00 32 01 F4`.
- Every positive 0x10, including re-entering the current session:
  - locks security
  - clears pending seeds
  - clears routine status
- These are kept across a session change:
  - lockout counters
  - the seed counter
  - DID values
  - DTC statuses

### 0x11 ECUReset

- No NRCs beyond the generic checks.
- Response: `51 rr`.
- Effect: the session becomes 0x01, and everything 0x10 clears is cleared too.

### 0x14 ClearDiagnosticInformation

**Which DTCs are cleared**
- Group 0xFFFFFF sets every DTC status to 0x00.
- A value equal to one spec DTC number clears only that DTC.
- Any other value gets NRC 0x31.

**NVM fault**
- If the NVM write fault flag is set, the answer is NRC 0x72 and nothing is cleared.
- This check comes after the group check.

**Response:** `54`.

### 0x19 subfunction 02: ReadDTCInformation by status mask

- Response: `59 02 FF`, followed by `DTC(3 bytes) status` for each DTC whose `status & mask ≠ 0`.
- DTCs are listed in spec order.
- The reported status is `status & 0xFF`, where 0xFF is the availability mask.
- NRC 0x14 if the response would be longer than `max_response_length` (4095).

### 0x22 ReadDataByIdentifier

**Checks for each DID, in request order**
- Unknown DID → 0x31.
- Session not in the DID's `read_sessions` → 0x31.
- One bad DID fails the whole request.
- Duplicate DIDs are allowed.

**Length check (after the DID checks)**
- If `1 + Σ(2 + DID length) > 4095`, the answer is NRC 0x14.

**Response**
- `62`, then `DID(2 bytes) value` for each DID in request order.
- Two DIDs are read live from state:
  - F186 returns the current session byte.
  - 0140 returns `min(vehicle_speed, 255)`.
- All other DIDs return their stored value.

### 0x27 SecurityAccess

Both levels use seed_length 4, max_attempts 3 and delay_ms 10000.

**1. Delay check**
- If this level's delay is active (`now < deadline`), the answer is NRC 0x37.
- This applies to both seed and key requests.

**2. Seed request (odd subfunction)**
- If this level is already unlocked: respond `67 ss 00 00 00 00` and change no state.
- Otherwise derive the seed with `derive_seed(level, counter, 4)` from `uds_assistant.protocol.security`:
  - byte i = `(0x5A + 0x3B·level + 0x9D·counter + 0x71·i) mod 256`
  - if every byte comes out 0, set the last byte to 01

  Then:
  - The counter is ECU-wide and is never reset. It increments after each non-zero seed is issued.
  - The new seed is stored as this level's pending seed, replacing any older one.
  - Respond `67 ss <seed>`.

**3. Key (even subfunction)**
- If this level has no pending seed, the answer is NRC 0x24.
- Otherwise compare the key with `compute_key(seed, level)` from `uds_assistant.protocol.security`.
- **Wrong key:**
  - Increment the failed-attempt count and consume the pending seed.
  - If the new count is at least max_attempts: respond NRC 0x36 and set `deadline = now + delay_ms`.
  - Otherwise respond NRC 0x35.
  - After the delay expires the count stays at 3, so the next wrong key gives 0x36 straight away and re-arms the delay.
- **Correct key:**
  - The unlocked level becomes this level. Only one level can be unlocked at a time.
  - Reset the count to 0, clear the deadline, and consume the pending seed.
  - Respond `67 kk`.

**Lockout lifetime**
- Lockout state survives session changes, S3 timeout and ECU reset.
- Only a correct key resets it.

### 0x2E WriteDataByIdentifier

Checks, in this order:

1. Unknown DID → 0x31.
2. Read-only DID (empty `write_sessions`) → 0x31.
3. Active session not in the DID's `write_sessions` → 0x31.
4. Data length ≠ DID length → 0x13. This comes before the security check.
5. Unlocked level ≠ the DID's `write_security_level` → 0x33. The level must match exactly; there is no hierarchy between levels.
6. A required condition is not met → 0x22:
   - `vehicle_stationary` means the speed is 0.
   - Unknown condition names count as not met.
7. The value, read as an unsigned big-endian integer, is outside the inclusive `value_range` → 0x31.
8. The NVM write fault flag is set → 0x72, and nothing is written.
9. Otherwise store the value and respond `6E DID`.

### 0x31 RoutineControl

**Checks, in this order**

1. Unknown routine → 0x31.
2. Active session not in the routine's sessions → 0x31.
3. Subfunction not in the routine's `allowed_subfunctions` → 0x12.
4. Wrong length → 0x13:
   - start must be exactly 4 + `option_record_length`
   - stop and results must be exactly 4
5. Unlocked level ≠ the routine's `security_level` (exact match) → 0x33.
6. Conditions not met → 0x22. Checked on start only.
7. Sequence → 0x24:
   - start while the routine is RUNNING
   - stop while it is not RUNNING
   - results when it has never been started since the last session change, reset or S3 timeout
   - A restart after STOPPED or COMPLETED is allowed.

**Routine status byte**

| Value | Meaning |
|---|---|
| 00 | never started |
| 01 | running |
| 02 | completed |
| 03 | stopped |

**Responses**
- start: `71 01 RID 01`
- stop: `71 02 RID 03`
- results: `71 03 RID <status>`

**Long-running routines (`long_running: true`)**
- A start returns two responses:
  1. `7F 31 78`
  2. `71 01 RID 02`
- The routine completes immediately (status 02).
- The final positive response is sent even when the suppress bit is set.
- Exactly one 0x78 is sent.

### 0x3E TesterPresent

- Response: `7E 00`.
- `3E 80` produces no response.

## Suppress bit

- When the outcome is positive and the suppress bit is set, no response is sent. The state change still happens.
- Negative responses are never suppressed. For example, `3E 81` gives `7F 3E 12`.

## How the remaining NRCs are used

- **0x10:** never produced by a correct ECU. It is reserved for bug injection.
- **0x72:** only from 0x2E and 0x14 when the NVM write fault flag is set.
- **0x78:** only on the start of a long-running routine.
- **0x14:** only for 0x22 and 0x19 responses longer than `max_response_length`.
