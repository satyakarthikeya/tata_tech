# Evaluation report

Run: 2026-10-05 16:07 UTC | git `8427c50` | model `qwen2.5:3b-instruct-q4_K_M` (num_ctx 4096) | retriever: ChromaDB + BAAI/bge-small-en-v1.5 (fastembed) | 15 seed requirements | runtime 738.4 s

Synthetic ECU spec. Every number is measured in this run. The LLM never produces bytes; the rules engine builds them.

| # | Metric | Result |
|---|---|---|
| 1 | Simulator vs rules engine agreement | 5000/5000 requests identical |
| 1 | Gold tests passing on clean simulator | 60/60 |
| 1 | udsoncan over virtual CAN | pass |
| 2 | Valid requests (well-formed send steps) | 237/237 = 100% |
| 2 | Generated tests passing on the clean simulator | 79/79 = 100% |
| 2 | Citations resolving to a real chunk | 384/384 |
| 3 | Tests by type | positive 26, negative 31, session 5, security 8, timing 9 |
| 3 | Requirements with at least one test | 15/15 |
| 4 | Reuse rate (tests built from approved templates) | 79/79 = 100% (27 templates) |
| 5 | Blind-set bugs caught (generated tests + sweep) | 9/15 |
| 5 | ... generated tests alone (79 tests) | 2/15 |
| 5 | ... conformance sweep alone (1200 tests) | 9/15 |
| 6 | Target identification F1 (precision / recall) | 62% (62% / 62%) |
| 6 | Category recall | 72% |
| 6 | Precondition recall (derived from steps) | 90% |
| 6 | Precondition recall (real `preconditions` field) | 79% |
| 7 | Answer accuracy | 19/21 = 90% |
| 7 | Citation correctness | 19/21 = 90% |
| 7 | Correct "not found" | 3/4 |
| 8 | Tool time per requirement (mean / median / max) | 20.3 s / 19.2 s / 27.0 s (n=15) |
| 8 | Manual time per requirement | owner to fill (see docs/TEST_DESIGN_TIME.md) |

**Missed blind-set bugs (6):** `session_switch_keeps_pending_seed` (session), `lockout_expiry_resets_attempt_count` (security), `nrc_order_subfunction_before_length` (nrc_order), `read_did_speed_not_clamped` (data), `dtc_clear_single_clears_neighbour` (data), `dtc_read_reports_masked_status` (data).

## Spec coverage (`coverage_report`, items touched / items in `data/bcm_spec.yaml`)

- Generated tests (seed requirements) (79 tests): service 9/9; did 10/14; routine 2/3; nrc 10/15; session 3/3; security level 2/2.
- Conformance sweep (1200 tests): service 9/9; did 14/14; routine 3/3; nrc 15/15; session 3/3; security level 2/2.
- Zero tests in the generated set: did: 0x0111 passenger_door_lock_state, 0x0120 central_locking_auto_relock_enable, 0x0131 wiper_auto_mode_enable, 0x0140 vehicle_speed_kph; routine: 0x0203 nvm_factory_restore; nrc: 0x11 serviceNotSupported, 0x14 responseTooLong, 0x72 generalProgrammingFailure, 0x78 requestCorrectlyReceivedResponsePending, 0x7e subFunctionNotSupportedInActiveSession.
- Full per-item table with positive/negative split: `outputs/exports/coverage_report.md`.

Notes: (2) a request is well-formed if it decodes and the rules engine does not reject it with a format NRC (except deliberate malformed-request probes). (5) A bug counts as caught when a test that passes on the clean simulator fails with the bug injected; the blind v3 set was written without seeing templates or code. (6) Natural v3: 16 blind requirements; preconditions are derived from the generated steps and, separately, read from each test's `preconditions` field. (7) Blind questions in `data/qa_eval.csv`. (8) Tool time includes the local 3B model on this machine.
