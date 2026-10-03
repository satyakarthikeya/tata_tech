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

- Six services have a subfunction byte (the byte right after the SID): 0x10, 0x11, 0x19, 0x27, 0x31 and 0x3E.
- For **all six**, bit 7 of that byte is the suppress-positive-response bit (SPRMIB). Before any check runs:
  - the subfunction value is the byte with bit 7 cleared (`byte & 0x7F`);
  - the suppress flag is bit 7 (`byte & 0x80 ≠ 0`).
- Every rule below that names a subfunction uses this 7-bit value. So `27 81` is handled exactly as `27 01`, `27 82 …` as `27 02 …`, `19 82 FF` as `19 02 FF`, `31 81 …` as `31 01 …`, `3E 80` as `3E 00`.
- Positive responses that echo the subfunction echo the 7-bit value (bit 7 clear), e.g. `67 01 …`, never `67 81 …`. (This only matters for the final response after a 0x78, see 0x31; all other suppressed positives are not sent.)
- What the suppress flag does is defined in the "Suppress bit" section.
- The other services (0x14, 0x22, 0x2E) have no subfunction and no suppress bit; their second byte is data.

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

The subfunction here is the 7-bit value (suppress bit already removed).

| Service | Supported subfunctions |
|---|---|
| 0x10 | 01, 02, 03 |
| 0x11 | 01, 03 |
| 0x19 | 02 |
| 0x27 | 01, 02, 03, 04 |
| 0x3E | 00 |

**This step is not applied to 0x31.** For RoutineControl the control type is checked only per routine, inside the 0x31 checks (step 3 of the 0x31 list), i.e. *after* the routine identifier and the routine's session have been checked. Examples (extended session, security locked):
- `31 04 FF FF` (bad type, unknown routine) → `7F 31 31`
- `31 05 02 03` (bad type, routine 0203 not allowed in extended) → `7F 31 31`
- `31 04 02 01` (bad type, known routine allowed in extended) → `7F 31 12`

### 5. Subfunction allowed in session → 0x7E

This step only applies to 0x27, using each security level's `allowed_sessions`:
- Level 1 (subfunctions 01/02) is allowed only in session 0x03.
- Level 3 (subfunctions 03/04) is allowed only in session 0x02.

### 5b. Subfunction-specific length → 0x13

| Request | Length rule |
|---|---|
| 0x19 subfunction 02 (`19 02` or `19 82`) | exactly 3 |
| 0x27 seed request (odd subfunction, with or without bit 7) | exactly 2 |
| 0x27 key (even subfunction, with or without bit 7) | exactly 2 + seed_length (4) |

For example `19 82` (no mask byte) → `7F 19 13`, and `27 81 00` → `7F 27 13`.

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
- `19 82 mm` is the same request with the positive response suppressed: no response is sent. Negative outcomes (e.g. `19 81 FF` → `7F 19 12`, `19 82` → `7F 19 13`) are still sent.

### 0x22 ReadDataByIdentifier

The request carries a list of 2-byte DIDs (the generic length step already guarantees at least one DID and a whole number of DIDs). There is no limit on the number of DIDs per request (the spec configures none); only the response length (below) bounds it.

**Which DIDs are answered (lenient multi-DID rule)**

Each entry of the list is judged on its own; a duplicate DID is simply judged (and answered) once per occurrence. An entry is **answered** only if both hold:
1. the DID exists in the spec (otherwise the entry is "unsupported"), and
2. the active session is in the DID's `read_sessions` (an empty `read_sessions` means never readable).

Entries that fail either condition are **silently skipped**: they produce no bytes in the response and no NRC by themselves.

**NRCs, in this order**
1. If **no** entry passes condition 1 (every requested DID is unknown) → NRC 0x31.
2. If **no** entry passes both conditions (some DIDs exist, but none is readable in the active session) → NRC 0x31.
3. Compute the positive response length from the answered entries only: `1 + Σ(2 + DID length)` over answered entries (duplicates counted each time; skipped entries count 0). If it is greater than `max_response_length` (4095) → NRC 0x14.

There is no read security in this spec, so 0x33 never occurs for 0x22. Reading never changes state (other than the S3 restart every request causes).

**Response**
- `62`, then `DID(2 bytes) value` for each answered entry, in request order (duplicates repeated).
- Two DIDs are read live from state:
  - F186 returns the current session byte.
  - 0140 returns `min(vehicle_speed, 255)`.
- All other DIDs return their stored value.

**Examples** (default session unless stated)

| Request | Response | Why |
|---|---|---|
| `22 F1 90 12 34` | `62 F1 90 <VIN 17 bytes>` | 1234 unknown → skipped |
| `22 12 34 F1 86` | `62 F1 86 01` | skipped entry may come first |
| `22 12 34 56 78` | `7F 22 31` | no DID exists |
| `22 12 34 12 34` | `7F 22 31` | duplicates of an unknown DID |
| `22 01 50` | `7F 22 31` | 0150 readable only in extended |
| `22 01 50 F1 86` | `62 F1 86 01` | 0150 skipped (session) |
| `22 12 34 01 50` | `7F 22 31` | one unknown, one not readable → none answered |
| `22 01 00 12 34 01 00 01 50` | `62 01 00 32 01 00 32` | duplicates answered twice; bad entries skipped |
| `22 01 60 FF FF 01 00` | `62 01 60 00 01 01 00 32` | request order kept |
| extended: `22 01 50 12 34` | `62 01 50 00` | |
| `22` + `F1 90` ×216 | `7F 22 14` | 1 + 216·19 = 4105 > 4095 |
| `22` + `F1 90` ×215 + `12 34` | `62` + (`F1 90 <VIN>`) ×215 | 4086 bytes; the skipped DID adds nothing |
| `22 12 34` + `F1 90` ×216 | `7F 22 14` | |

### 0x27 SecurityAccess

Both levels use seed_length 4, max_attempts 3 and delay_ms 10000.

"Level" means the security level whose `seed_subfunction` or `key_subfunction` equals the 7-bit subfunction (01/02 → level 1, 03/04 → level 3). The generic steps 4, 5 and 5b (0x12, 0x7E, 0x13) have already passed.

**1. Delay check — seed requests only**
- For a **seed request** (odd subfunction): if this level's delay is active (`now < deadline`), the answer is NRC 0x37. No state changes.
- A **key** (even subfunction) is **never** answered 0x37. It skips this check and goes straight to the key handling in point 3, even while the delay runs.

**2. Seed request (odd subfunction)**
- If this level is already unlocked: respond `67 ss 00 00 00 00` and change no state.
- Otherwise derive the seed with `derive_seed(level, counter, 4)` from `uds_assistant.protocol.security`:
  - byte i = `(0x5A + 0x3B·level + 0x9D·counter + 0x71·i) mod 256`
  - if every byte comes out 0, set the last byte to 01

  Then:
  - The counter is ECU-wide and is never reset. It increments after each non-zero seed is issued.
  - The new seed is stored as this level's pending seed, replacing any older one.
  - Respond `67 ss <seed>`.

**3. Key (even subfunction)** — the same rules apply whether or not this level's delay is active.
- If this level has no pending seed, the answer is NRC 0x24. Nothing else changes: the failed-attempt count is **not** incremented and the deadline is **not** changed or re-armed.
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

**Key during the delay.** The delay is armed only by the wrong key that consumed this level's pending seed, and while it runs every seed request for the level is refused with 0x37. So over the wire a key sent during the delay always finds no pending seed and gets **0x24**, with no state change (no attempt counted, deadline unchanged). Examples, extended session, after three wrong keys at t=0 (count 3, deadline 10000):
- `27 02 00 00 00 00` at t=1000 → `7F 27 24` (count stays 3, deadline stays 10000)
- `27 02 9A 06 8F 73` at t=1000 → `7F 27 24`
- `27 01` at t=5000, even after such a key → `7F 27 37`
- `27 01` at t=10000 → positive seed (the key during the delay did not extend it)
- then a wrong key → `7F 27 36` (count was still 3, so the limit is reached again and the delay re-arms)

(If a state were ever constructed with a pending seed during the delay, the key would simply be compared as above: wrong → count+1, 0x36, deadline re-armed from now; right → unlock.)

**Suppress bit on 0x27**
- `27 81` / `27 83` are seed requests with the positive response suppressed: every check and every state effect is exactly as for `27 01` / `27 03` (a non-zero seed is issued, stored as the pending seed, and the seed counter increments; for an already-unlocked level the all-zero seed changes nothing), but **no response is sent**.
- `27 82 <key>` / `27 84 <key>` are keys with the positive response suppressed: a correct key unlocks the level (same state effects as `27 02`), and no response is sent.
- Negative responses are always sent: e.g. `27 85` → `7F 27 12`, `27 83` in extended → `7F 27 7E`, `27 81` during the delay → `7F 27 37`, `27 82 <wrong key>` → `7F 27 35`/`36` (attempt counted), `27 82 …` with no pending seed → `7F 27 24`.

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

The generic step 4 (subfunction supported) is **not** applied to 0x31, so any control-type value (7-bit, after removing the suppress bit) reaches these checks.

**Checks, in this order**

1. Unknown routine → 0x31. (Regardless of the control type: `31 04 FF FF` → `7F 31 31`.)
2. Active session not in the routine's sessions → 0x31. (Regardless of the control type.)
3. Control type not one of 01 (start), 02 (stop), 03 (results), or not in the routine's `allowed_subfunctions` → 0x12. This is the only 0x12 check for 0x31; e.g. `31 00 02 01`, `31 04 02 01`, `31 80 02 01` in extended → `7F 31 12`, and it comes before the length and security checks (`31 04 02 01 FF` → `7F 31 12`).
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

Applies to every service with a subfunction: 0x10, 0x11, 0x19, 0x27, 0x31, 0x3E (see "Subfunction byte").

- When the outcome is positive and the suppress bit is set, no response is sent. The state change still happens exactly as without the bit.
- Negative responses are never suppressed. For example, `3E 81` gives `7F 3E 12`.
- Exception: a long-running 0x31 start (see 0x31) sends `7F 31 78` and then its final positive response even when the bit is set.

| Service | Suppressed example | Response | State effect still applied |
|---|---|---|---|
| 0x10 | `10 83` | none | session → 03, security locked, seeds/routines cleared |
| 0x11 | `11 81` | none | reset to default session |
| 0x19 | `19 82 FF` | none | none (read only) |
| 0x27 | `27 81` | none | seed issued and stored as pending, counter +1 |
| 0x27 | `27 82 <correct key>` | none | level unlocked, count reset, seed consumed |
| 0x31 | `31 81 02 01` | none | routine 0201 RUNNING |
| 0x31 | `31 81 02 03` (long-running) | `7F 31 78`, `71 01 02 03 02` | routine 0203 COMPLETED |
| 0x3E | `3E 80` | none | none |

## How the remaining NRCs are used

- **0x10:** never produced by a correct ECU. It is reserved for bug injection.
- **0x72:** only from 0x2E and 0x14 when the NVM write fault flag is set.
- **0x78:** only on the start of a long-running routine.
- **0x14:** only for 0x22 and 0x19 responses longer than `max_response_length`.
