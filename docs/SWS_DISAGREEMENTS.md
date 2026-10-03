# Rules engine vs AUTOSAR Dcm SWS: disagreements

Source: AUTOSAR CP R24-11 "Specification of Diagnostic Communication Manager"
(`data/sources/AUTOSAR_CP_SWS_DiagnosticCommunicationManager.pdf`, not committed
because AUTOSAR's terms do not allow redistribution). Every SWS statement below is
paraphrased. None of it is quoted.

**Status:** these are documented, not fixed. Changing the oracle
(`uds_assistant/rules/nrc_order.py`) would also mean coordinated changes to the
independent simulator, `docs/behaviour_contract.md`, and the frozen gold and
template data. Where the engine and the SWS agree, the check in `nrc_order.py`
cites the SWS ID. Where they disagree, it points here and cites no ID.

The "ours" column was produced by running each example through
`rules.engine.evaluate` against `data/bcm_spec.yaml`. The "SWS" column is what the
SWS requirements imply.

**Confidence:**
- **high:** a normative requirement contradicts what we do.
- **medium:** the SWS order comes from listing order or section order, not from an explicit ordering rule.
- **none:** no observable effect with the current spec.

| # | Topic | Example request(s) | Ours | SWS | Confidence |
|---|---|---|---|---|---|
| D1 | Exact length (0x13) checked before subfunction support (0x12) | `11 05 00` | `7F 11 13` | `7F 11 12` | medium |
| D2 | 0x31: generic 0x12 check runs before routine-id lookup | `10 03`, `31 04 FF FF` | `7F 31 12` | `7F 31 31` | high |
| D3 | 0x2E: data length (0x13) checked before security (0x33) | `10 03`, `2E 01 00 01 02` (locked) | `7F 2E 13` | `7F 2E 33` | medium |
| D4 | 0x31: per-routine control type (0x12) and length (0x13) checked before security (0x33) | `10 02`, `31 02 02 03` (locked; routine 0x0203 has no stop) | `7F 31 12` | `7F 31 33` | medium |
| D5 | 0x37 also returned for sendKey | three bad keys → 0x36, then `27 02 00 00 00 00` | `7F 27 37` | no key comparison without a seed; 0x24 per the SWS's informative list | high |
| D6 | Suppress bit not masked for 0x19 / 0x27 | `10 03`, `27 81`; `19 82 FF` | `7F 27 12`; `7F 19 12` | handled as `27 01` / `19 02` with the positive response suppressed | high |
| D7 | 0x22 with several DIDs: strict all-or-nothing | `22 F1 90 FF FF` | `7F 22 31` | positive response for F190 only; unsupported DID skipped | high |
| D8 | Security re-locked on every positive 0x10 | `10 01` while in default | locks | locks only when leaving a non-default session | none |
| D9 | Request SIDs in the response range (0x40–0x7F, 0xC0–0xFF) | `50 01` | `7F 50 11` | no response if DcmRespondAllRequest = FALSE; 0x11 if TRUE | config choice |

## D1 — Generic order: length vs subfunction (and the DSD verification order)

- **SWS:**
  - SWS_Dcm_01535 sets the order of the DSD verifications: SID (0x11), then authentication, then session, then security, then mode rules.
  - The session step covers both the service (SWS_Dcm_00211, 0x7F) and the sub-service (SWS_Dcm_00616, 0x7E). The security step does the same (SWS_Dcm_00217 and SWS_Dcm_00617, 0x33).
  - The format checks come in a later section: sub-service configured (SWS_Dcm_00273, 0x12) and minimum length (SWS_Dcm_00696, 0x13).
  - Exact length and format checks belong to the service processor (SWS_Dcm_00272, 0x13), so they run after the DSD has accepted the subfunction.
  - The SWS is not fully consistent here: for 0x27, SWS_Dcm_00321 checks the request length first and the access type (0x12) after.
- **Ours:**
  - Order is 0x11 → 0x7F → 0x13 → 0x12 → 0x7E (PROJECT.md §5, [R-ORDER]).
  - Step 3 already applies the exact length for 0x10, 0x11, 0x14 and 0x3E.
- **Impact:**
  - A request with an unsupported subfunction *and* a wrong total length gets 0x13 from us. The SWS order gives 0x12. Examples: `11 05 00`, `3E 05 00`, `10 7F 00`.
  - Putting 0x7E before the format checks has no observable effect with this spec. We only produce 0x7E for configured 0x27 subfunctions, the 0x27 minimum length (2) always holds once a subfunction byte exists, and step 5b runs after 0x7E.
- **Recommended change:** keep only the minimum-length check at step 3, and move the exact-length checks for subfunction services after step 4. Update the simulator, the behaviour contract (§3/§4), and every gold case with an unsupported subfunction plus a wrong length together.

## D2 — RoutineControl: generic subfunction check

- **SWS:** SWS_Dcm_00273 explicitly leaves the generic "sub-service configured" (0x12) check out for 0x31. The service processor runs these checks:
  - routine supported (SWS_Dcm_00568, 0x31)
  - routine allowed in the session (SWS_Dcm_00570, 0x31)
  - routine allowed at the security level (SWS_Dcm_00571, 0x33)
  - stop or results configured for this routine (SWS_Dcm_00869, 0x12)
- **Ours:**
  - Step 4 rejects any control type other than 01, 02 or 03 with 0x12 before the routine identifier is looked up.
  - Only after that do 0x31 (identifier) and 0x12 (per-routine type, [R-ROUTINE-SUB]) follow.
- **Impact:** an invalid control type combined with an unknown or session-forbidden routine id gives 0x12 from us. The SWS gives 0x31.
- **Recommended change:** for SID 0x31, skip step 4 and check the control type after the routine id, session and security checks (see D4).

## D3 — WriteDataByIdentifier: length vs security

- **SWS:**
  - SWS_Dcm_00395 lists the 0x2E verifications in this order: DID supported (00467), write access (00468), session (00469), security (00470), data length (00473).
  - The length mismatch maps to 0x13 through SWS_Dcm_00272.
  - The order is inferred from the list. No requirement states it as an order.
- **Ours:** [R-LEN] puts the data-length check (step 6b') *before* security (6c).
- **Impact:** a wrong-length write to a secured DID while security is locked gets 0x13 from us. The SWS order gives 0x33.
- **Recommended change:** move step 6b' after 6c. Alternatively, keep the current order and record in DECISIONS.md that we deliberately differ from the SWS listing order.

## D4 — RoutineControl: per-routine type and length vs security

- **SWS:**
  - The verifications are listed as 00568 → 00570 → 00571 (security, 0x33). The per-routine subfunction check (00869, 0x12) comes after them.
  - The overall-length check (SWS_Dcm_01140, 0x13) has no position stated.
- **Ours:** routine id → session → per-routine type 0x12 ([R-ROUTINE-SUB]) → option length 0x13 → security 0x33.
- **Impact:** an unsupported control type, or a wrong option length, on a secured routine while security is locked gets 0x12 or 0x13 from us. The SWS listing order gives 0x33.
- **Recommended change:** move the security check directly after the session check. Decide on the length position together with D3.

## D5 — SecurityAccess: 0x37 on sendKey

- **SWS:**
  - SWS_Dcm_01350 requires 0x37 only for a *requestSeed* while the level's delay timer runs.
  - SWS_Dcm_00863 compares a key only after a successful seed request for that level. During the delay no seed can be issued, so a sendKey has no seed to compare against.
  - The SWS mentions 0x24 for that case, but only in an informative list.
- **Ours:** [R-SEC-LOCKOUT] checks the delay first for both seed and key, so a sendKey during the delay gets 0x37.
- **Impact:** a sendKey during the lockout delay gets 0x37 from us. The SWS gives 0x24 (sequence).
- **Recommended change:** restrict the delay check to seed requests and let the sendKey fall through to the existing pending-seed check (0x24).

## D6 — Suppress-positive bit for 0x19 and 0x27

- **SWS:**
  - SWS_Dcm_00201 strips bit 7 from the subfunction for every service configured with subfunctions (SWS_Dcm_00204).
  - SWS_Dcm_01411 accepts each configured sub-service with the bit either clear or set.
  - Under the SWS, SPRMIB applies to 0x19 and 0x27 as well.
- **Ours:** [R-SPRMIB] strips bit 7 only for 0x10, 0x11, 0x31 and 0x3E. So `27 81` and `19 82 FF` get 0x12.
- **Impact:** `27 81` (suppressed seed request, rarely useful) and `19 82` (suppressed DTC read) are rejected by us and processed silently by the SWS.
- **Recommended change:** honour SPRMIB for every service that has subfunctions. This needs the simulator, the behaviour contract (§"Subfunction byte"/§"Suppress bit"), and gold cases that use `27 81` or `19 82` to change at the same time.

## D7 — ReadDataByIdentifier with several DIDs

- **SWS:**
  - For DID supported (SWS_Dcm_00438), read access (SWS_Dcm_00433) and session (SWS_Dcm_00434), the SWS answers 0x31 only when *none* of the requested DIDs pass. Otherwise the passing DIDs are answered.
  - The security check (SWS_Dcm_00435, 0x33) is per DID and strict.
- **Ours:** [R-MULTI-DID] answers 0x31 if *any* requested DID is unknown or not readable in the session.
- **Impact:** a request that mixes valid and invalid DIDs gets 0x31 from us. The SWS gives a positive response with only the valid DIDs. A request with a single DID behaves the same in both.
- **Recommended change:** switch to the lenient rule: skip failing DIDs, and send 0x31 only when none pass. This needs the simulator, the behaviour contract, and the multi-DID gold cases to change together.

## D8 — Security reset on session change (no observable impact)

- **SWS:** SWS_Dcm_00139 resets security on two kinds of transition:
  - from a non-default session to any non-default session, including re-entering the same one;
  - from a non-default session to the default session, whether caused by 0x10 or by S3 timeout.

  A transition that starts in the default session does not reset security.
- **Ours:** [R-SESSION-RESET] locks security on *every* positive 0x10, and on 0x11.
- **Impact:** none with `data/bcm_spec.yaml`. No security level can be unlocked in the default session (levels 0x01 and 0x03 are allowed only in sessions 0x03 and 0x02), so security is already locked whenever a transition starts from the default session.
- **Recommended change:** none needed now. Revisit if a spec ever allows unlocking in the default session.

## D9 — SIDs in the response range (configuration choice)

- **SWS:** SWS_Dcm_00084 says that when DcmRespondAllRequest is FALSE, requests whose SID is in 0x40–0x7F or 0xC0–0xFF get no response. The parameter has no default value (ECUC_Dcm_00600).
- **Ours:** these SIDs get 0x11, the same as an unsupported service. That matches DcmRespondAllRequest = TRUE.
- **Impact:** none within that configuration.
- **Recommended change:** log the choice (DcmRespondAllRequest = TRUE) in DECISIONS.md. No code change.

## No SWS coverage (kept as design decisions)

- **Routine start/stop/results sequencing (0x24, [R-ROUTINE-SEQ]):** SWS_Dcm_01139 defers to ISO 14229-1 NRC handling and gives no Dcm-level rule.
- **0x2E value-range check (0x31, [R-RANGE]):** this is left to the application in the SWS.
- **0x72 on a failed DID write:** the SWS names 0x72 only for the BndM atomic-write path (SWS_Dcm_01585), so we do not cite it for the general NVM fault. The DTC-clear 0x72 is cited (SWS_Dcm_01060).
- **Strict ">" S3 comparison and the empty-request rule ([R-S3], [R-EMPTY]):** the SWS does not specify either.
