# UDS reference notes (own-words summary)

These notes summarise, in our own words, the parts of the UDS (ISO 14229-style)
diagnostic protocol that this project implements. No text is copied from any
standard; this is a working explanation for engineers using this assistant.
Byte values (SIDs, NRCs) are public wire constants, not copyrighted prose.

General conventions used throughout:
- A **positive response** SID is the request SID plus 0x40 (e.g. 0x22 -> 0x62).
- A **negative response** is always three bytes: `7F <requested SID> <NRC>`.
- Many services take a **sub-function** byte right after the SID. For the
  services in this project's scope (0x10, 0x11, 0x31, 0x3E) bit 7 of that byte
  is the **suppress-positive-response bit**: if set and the result is
  positive, the ECU does the work but sends no response at all. Negative
  responses are never suppressed. For 0x19 and 0x27 the whole byte is treated
  as the sub-function instead (no suppress bit), so a set high bit there just
  makes the sub-function unrecognised.

## NRC evaluation order {#nrc-order}

Diagnostic servers check a request in a fixed order and stop at the first
failing check (see `uds_assistant/rules/nrc_order.py`):

1. Is the service (SID) supported by the ECU at all? If not: NRC 0x11
   (serviceNotSupported).
2. Is the service allowed in the currently active diagnostic session? If not:
   NRC 0x7F (serviceNotSupportedInActiveSession).
3. Is the message length/format valid for this service in general? If not:
   NRC 0x13 (incorrectMessageLengthOrInvalidFormat).
4. Is the sub-function supported by the service at all? If not: NRC 0x12
   (subFunctionNotSupported).
5. Is the sub-function allowed in the active session? If not: NRC 0x7E
   (subFunctionNotSupportedInActiveSession).
6. Service-specific checks, roughly in this order where they apply: is the
   identifier/routine/DTC known and allowed in this session (0x31
   requestOutOfRange), is security unlocked at the right level (0x33
   securityAccessDenied), are preconditions met (0x22
   conditionsNotCorrect), is the request in the right sequence (0x24
   requestSequenceError), is the value within range (0x31), is there an NVM
   fault (0x72 generalProgrammingFailure), is the result too big to send in
   one answer (0x14 responseTooLong).

Only after every check passes does the ECU do the work and send the positive
response (or, for a long-running operation, NRC 0x78 responsePending followed
later by the final response).

## NRCs in scope {#nrcs}

- **0x10 generalReject** — a generic catch-all negative response. This
  project's rules engine never produces it on its own; it is reserved for
  simulated bug injection (an ECU that misbehaves).
- **0x11 serviceNotSupported** — the SID itself is not implemented by any
  session on this ECU.
- **0x12 subFunctionNotSupported** — the SID is known, but this particular
  sub-function/mode byte is not one the service implements.
- **0x13 incorrectMessageLengthOrInvalidFormat** — the request is too short,
  too long, or an odd length where pairs are expected (e.g. DID lists).
- **0x14 responseTooLong** — the request is valid but the positive answer
  would not fit in the transport's maximum frame length.
- **0x22 conditionsNotCorrect** — the request is well-formed and allowed, but
  a runtime precondition (e.g. "vehicle must be stationary") is not met.
- **0x24 requestSequenceError** — the request arrived out of the expected
  order (e.g. sending a security key with no outstanding seed, or stopping a
  routine that was never started).
- **0x31 requestOutOfRange** — an unknown identifier/routine/DTC, or a known
  one with a value outside its allowed range.
- **0x33 securityAccessDenied** — the operation needs a security level that
  is not currently unlocked.
- **0x35 invalidKey** — a SecurityAccess key did not match the expected value
  for the outstanding seed.
- **0x36 exceedNumberOfAttempts** — too many consecutive invalid keys; the
  ECU now enforces a lockout delay.
- **0x37 requiredTimeDelayNotExpired** — a SecurityAccess request arrived
  while a previous lockout delay is still active.
- **0x72 generalProgrammingFailure** — a write or clear operation could not
  be committed to non-volatile memory.
- **0x78 responsePending** — the ECU needs more time than P2 allows; it sends
  this placeholder and the tester keeps waiting (bounded by P2*) for the real
  final response.
- **0x7E subFunctionNotSupportedInActiveSession** — the sub-function exists on
  the ECU but is not allowed from the session the tester is currently in.
- **0x7F serviceNotSupportedInActiveSession** — the service exists on the ECU
  but is not allowed from the session the tester is currently in.

## Timing: P2, P2*, S3 {#timing}

- **P2** is the normal maximum time the ECU is allowed to take to answer a
  request before the tester should consider it late, in milliseconds.
- **P2\*** (P2-star) is the extended maximum wait time that applies after the
  ECU has sent a 0x78 responsePending placeholder — it gives the ECU more
  room to finish a long-running operation (e.g. a routine or an NVM write)
  before the tester gives up.
- **S3** is the diagnostic session inactivity timeout. If no diagnostic
  request arrives within S3 milliseconds of the last one, the ECU
  automatically falls back to the default session, locks any unlocked
  security level, and clears any pending security seeds and routine status.
  Sending `TesterPresent` (0x3E) periodically is the standard way to keep a
  non-default session alive without doing real diagnostic work.
- A session's P2, P2* and S3 values are reported to the tester in the
  positive response to DiagnosticSessionControl (0x10).

## Security seed/key concept and lockout {#security-concept}

SecurityAccess (0x27) protects sensitive operations (writing calibration
data, running certain routines, entering programming session work) behind a
challenge-response unlock:

1. The tester requests a **seed** using an odd sub-function number specific to
   the security level it wants. The ECU generates a pseudo-random seed tied
   to that level and an internal counter, remembers it as "pending" for that
   level, and returns it.
2. The tester computes a **key** from the seed using an algorithm that only
   legitimate testers (or this project's own documented synthetic algorithm)
   know, and sends the key back using the matching even sub-function number.
3. If the key matches, that security level becomes unlocked for the ECU (only
   one level can be unlocked at a time in this project's spec) and the
   failed-attempt counter for that level resets to zero.
4. If the key does not match, the failed-attempt counter increments and the
   pending seed is discarded (NRC 0x35). Once the counter reaches the
   configured maximum, the ECU additionally arms a **lockout delay**: further
   SecurityAccess requests for that level get NRC 0x36 immediately, and any
   request made while the delay is still counting down gets NRC 0x37. Only a
   subsequent *correct* key clears the counter and the lockout.
5. Lockout state is persistent across session changes, S3 timeouts and ECU
   resets — it is meant to resist a tester simply reconnecting to retry.

Each security level in this project's spec has its own seed length, maximum
attempt count, lockout delay, and the sessions from which it may be
requested at all.

## Services {#services}

### 0x10 DiagnosticSessionControl {#svc-0x10}

Switches the ECU between diagnostic sessions (e.g. default, programming,
extended). The sub-function selects the target session id. On success the
ECU answers `50 <session>` followed by the new session's P2 and P2* timing
values, and resets security (locks any unlocked level, clears pending
seeds) and any running-routine status, even if the tester re-enters the
session it was already in. No service-specific NRCs beyond the generic
order apply to 0x10 in this project's scope.

### 0x11 ECUReset {#svc-0x11}

Asks the ECU to reset (e.g. hard reset, soft reset). The sub-function
selects the reset type. On success the ECU answers `51 <type>` and then
behaves as if it powered back up: session returns to default, security
locks, pending seeds and routine status clear. No service-specific NRCs
beyond the generic order apply to 0x11 in this project's scope.

### 0x14 ClearDiagnosticInformation {#svc-0x14}

Clears stored DTC (fault code) status. The request carries a 3-byte "group"
value: the special group that means "all DTCs" clears every DTC's status,
and a value matching one specific DTC's own number clears only that DTC;
any other group value is out of range (NRC 0x31). If the ECU's simulated
non-volatile memory is in a fault state, the clear itself fails with NRC
0x72 (generalProgrammingFailure) instead of succeeding. On success the ECU
answers with the bare positive SID `54`.

### 0x19/0x02 ReadDTCInformation (reportDTCByStatusMask) {#svc-0x19}

Reports which DTCs currently have at least one status bit set in a
tester-supplied status mask. Only the "by status mask" sub-function
(0x02) is in scope; any other sub-function value is unsupported (NRC
0x12). The positive response echoes the status-availability mask the ECU
supports, then lists each matching DTC as its 3-byte number followed by
its 1-byte status. If listing every matching DTC would make the response
longer than the ECU's maximum response length, the ECU answers NRC 0x14
(responseTooLong) instead.

### 0x22 ReadDataByIdentifier {#svc-0x22}

Reads one or more data identifiers (DIDs) in a single request; the request
is simply a list of 2-byte DIDs. Each DID is checked independently: an
unknown DID, or a DID that is not readable from the current session, makes
the *entire* request fail with NRC 0x31 (requestOutOfRange) — one bad DID
in a list spoils the whole read. Duplicate DIDs in the same request are
allowed and are each answered separately. If the combined response would
exceed the transport's maximum length, the answer is NRC 0x14 instead. On
success the response is the positive SID followed by each DID and its
current value, in the order requested; some DIDs (like the currently
active session, or current vehicle speed) are computed live rather than
read from stored memory.

### 0x27 SecurityAccess {#svc-0x27}

Implements the seed/key unlock described above (see
[Security seed/key concept and lockout](#security-concept)). Odd
sub-functions request a seed for a specific security level; even
sub-functions send back a computed key for that level. Each level is only
reachable from specific sessions, so requesting the wrong level's
seed/key sub-function from the wrong session gives NRC 0x7E. Sending a key
with no outstanding seed for that level gives NRC 0x24
(requestSequenceError). A lockout delay still counting down gives NRC
0x37; the first wrong keys within the attempt budget give NRC 0x35; the
attempt that reaches the configured maximum gives NRC 0x36 and arms the
delay.

### 0x2E WriteDataByIdentifier {#svc-0x2e}

Writes a single DID's value. Checks, roughly in order: the DID must be
known and writable (not read-only) in the active session (otherwise NRC
0x31); the supplied data must be exactly the DID's defined length
(otherwise NRC 0x13); the correct security level for that DID must be
unlocked (otherwise NRC 0x33); any required runtime precondition for that
DID must hold (otherwise NRC 0x22); the value, read as a plain unsigned
integer, must fall inside the DID's allowed range (otherwise NRC 0x31);
and the ECU's simulated memory must not be in a fault state (otherwise NRC
0x72). On success the ECU stores the new value and answers `6E <DID>`
with no value echoed back.

### 0x31 RoutineControl {#svc-0x31}

Starts, stops, or requests the results of a named routine (a ECU-side
procedure such as a self-test or calibration). The routine id must be
known and allowed in the active session (otherwise NRC 0x31); the
requested operation (start/stop/results) must be one the routine supports
(otherwise NRC 0x12); the request length must match what that operation
expects, including any option-record bytes on start (otherwise NRC 0x13);
the routine's required security level must be unlocked (otherwise NRC
0x33); start additionally checks runtime preconditions (otherwise NRC
0x22); and the operation must make sense given the routine's current
status — e.g. starting a routine that is already running, or requesting
results before it was ever started, gives NRC 0x24
(requestSequenceError). A routine marked long-running answers its start
request with NRC 0x78 (responsePending) first and then a final positive
response once it completes, even if the suppress-positive bit was set on
the request.

### 0x3E TesterPresent {#svc-0x3e}

A keep-alive message with no payload beyond the sub-function byte. Its
only purpose is to reset the S3 inactivity timer so the ECU does not fall
back to the default session. The positive response is simply `7E 00`; it
is almost always sent with the suppress-positive bit set, since the
tester does not need to see the reply.
