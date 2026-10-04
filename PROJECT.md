# PROJECT.md — UDS Diagnostics & Automated Test Generation Assistant

> Tata Tech Pulse final project · Case Study 5 · Solo build by Karthik

---

## Status (as of Part E, final)

The design below is implemented and evaluated in both `mock` and `ollama` modes. Part D added a requirement-independent conformance sweep, service grounding and a constrained planner, and measured on fresh v3 blind data. Part E made the results one consistent story, added cited Q&A, confidence indicators, a separate OEM retrieval layer, Docker files and a five-tab UI. Numbers here are copied from `docs/RESULTS.md` (which states the run behind each section) and `outputs/eval_report.json`; `FINAL_REPORT.md` is the honest summary and `docs/CASE_STUDY_COMPLIANCE.md` maps every case-study item to evidence.

- **Correctness (LLM-independent; Main eval 2026-10-04, `1f0c293`):** simulator vs rules engine 5000/5000, gold tests 60/60 on the bug-free simulator, udsoncan virtual-CAN sequence PASS (one happy path), 1200/1200 sweep tests pass on the clean simulator.
- **Bug detection (fresh v3, 15 bugs written blind after the Part D freeze; same run):** full output (requirement-driven tests plus the sweep) **10/15 mock, 9/15 ollama**. Requirement-driven tests alone 4/15 and 2/15; the sweep alone 9/15; gold 3/15. Five bugs are missed in both modes (no test applies the stimulus).
- **Requirement understanding (natural v3, n=16; same run):** ollama is better than mock (parsed F1 0.609 vs 0.407, category recall 70.0% vs 42.0%, precondition recall 89.7% vs 48.3%) but its precision is 0.596 with 19 false positives; mock precision 0.857, recall 0.267.
- **Cited Q&A (25 blind questions; Q&A run 2026-10-04, `9e66f7a`):** answer accuracy 90.5% (19/21) in both modes, correct not-found 3/4, citation correctness 95.2% mock / 90.5% ollama. Known misses: QA-018 (answered instead of refusing), QA-022 and QA-023 (retrieval misses).
- **Confidence:** high / medium / low plus a one-line reason on every Q&A answer and generated test (rules in `DECISIONS.md` E32-*). Mock distribution on the 15 seeds: 135 high, 71 medium, 0 low; the `low` level is only unit-tested.
- **UI:** five tabs (Ask, Generate & Review, Run on Simulator, Export, Results), headless-tested; never clicked through in a real browser.
- **Docker:** `Dockerfile`, `docker-compose.yml` (app + ollama), `.dockerignore`, `docs/DOCKER.md`: **written, not built here** (limited network).
- **Test design time:** protocol and tool-side timing done (mock mean 0.217 s, ollama 19.36 s per requirement, timing run `8357ec0`); the manual comparison is **pending owner measurement**.
- **Known limitations:** synthetic spec and simulator by the same team; one 3B model; small samples (one item moves a score by 4 to 7 points); CAPL never run in CANoe; no real ECU or hardware; SWS D1, D3, D4, D8, D9 open; the natural door-lock requirement did not produce the intended test pair.

### Components (final)

Protocol core, ECU spec, rules engine (oracle), independent simulator with 68 injectable bugs (26 in-sample, 12 + 15 + 15 held-out v1 to v3), 27 templates plus the 1200-test conformance sweep, 60 gold tests, retrieval with **four layers** (standard / OEM / ECU / project, layer-tagged citations; the generator uses only standard, ECU and project, Q&A uses all four), mock and ollama LLM layer, agent pipeline with **confidence annotation**, runner, evaluation with run provenance, pytest and CAPL exports, SQLite audit store, FastAPI (including `POST /ask`), **cited Q&A** (`qa/`), **five-tab Streamlit UI**, **Docker files**.

- **Freeze policy.** The Part C and Part D freezes (hash tables in `PROGRESS.md` and `FINAL_REPORT.md`) applied through D6 only. Part E legitimately changed code (Q&A, confidence, retrieval layers, UI); generator bytes were verified unchanged in E3.2 and E3.3 (mock output for the 15 seeds identical, 206 tests).
- **Python 3.13** (3.13.6) is what the project was built and tested on; code is kept 3.11-syntax-compatible.
- More: `docs/RECONCILIATION.md`, `docs/CODE_TOUR.md`, `docs/ARCHITECTURE.md`, `docs/RESULTS.md`, `docs/CASE_STUDY_COMPLIANCE.md`, `docs/DEMO_SCRIPT.md`, `docs/UI_CHECKLIST.md`, `docs/DOCKER.md`, `docs/TEST_DESIGN_TIME.md`, `outputs/partD/interpretation.md`.

---

## 1. The problem

UDS (Unified Diagnostic Services) is the protocol a diagnostic tester uses to talk to a car ECU: read data, write data, unlock security, run routines, clear fault codes. To test an ECU's diagnostics, an engineer must combine the generic protocol rules with OEM- and ECU-specific specs. They then hand-build request bytes, work out preconditions (session, security), predict positive and negative responses, and turn all of that into automation scripts.

This is slow and error-prone, and negative and edge-case coverage is usually weak.

## 2. What we build

A **local, offline-capable assistant** that turns a diagnostic requirement into **validated, executable test cases**. It then runs them against an ECU simulator and proves they catch real defects.

```
Requirement (plain English) + ECU diagnostic spec
        │
        ▼
  parse → retrieve evidence → plan tests → instantiate → validate → explain
  (LLM)      (RAG)             (LLM)       (templates)  (rules engine) (LLM)
        │
        ▼
  Structured test cases (with citations)
        │
        ├──► run on ECU simulator (with injectable bugs) → pass/fail, timing
        ├──► evaluation report (coverage, accuracy, bug-detection rate)
        └──► export: Python (udsoncan + pytest), CAPL templates
```

## 3. Core design principle

**The LLM handles language. Code handles correctness.**

- **LLM:** understands the requirement, chooses which test intents and templates apply, and writes the human explanation.
- **Deterministic code:** every byte, NRC, session rule, security rule, and timing value.
- LLM output never contains bytes that reach a final test. Bytes come only from templates and the rules engine.

Because of this, the system stays correct with a small 3B local model, and it runs fully without a model in **mock mode**.

## 4. Components

| # | Component | Responsibility |
|---|---|---|
| 1 | **Protocol core** (`protocol/`) | SIDs, NRC table, encode/decode, positive SID = SID + 0x40, negative = `7F SID NRC`, suppress-positive bit |
| 2 | **ECU spec** (`spec/`, `data/bcm_spec.yaml`) | Pydantic model of a Body Control Module: sessions, security levels, DIDs, routines, DTCs, timing (P2, P2*, S3) |
| 3 | **Rules engine** (`rules/`) | The oracle: (spec, state, request) → exact expected response + reason trace. Explicit NRC evaluation order |
| 4 | **ECU simulator** (`simulator/`) | Independent stateful ECU implementation, bug injection, in-process and virtual-CAN/ISO-TP transports |
| 5 | **Test model and templates** (`testgen/`) | `TestCase` schema, 27 reusable parameterized templates (originally planned 8–12; v1 14 + v2 9 + v3 4, frozen at the Part C freeze) |
| 6 | **Gold set** (`data/gold/`) | 60 hand-authored tests that must pass on the bug-free simulator |
| 7 | **Bug catalog** (`data/bugs/`) | 26 in-sample injectable faults (`bug_catalog.yaml`) + 12 held-out v1 faults (`heldout_catalog.yaml`, seen) + 15 held-out v2 faults (`heldout_v2_catalog.yaml`, fresh) |
| 8 | **Retrieval** (`rag/`) | Layered collections (standard / oem / ecu / project), citations. Backends: BM25 (offline) and ChromaDB + embeddings |
| 9 | **LLM layer** (`llm/`) | Pluggable: `mock` (deterministic), `ollama` (local Qwen2.5-3B Q4_K_M) |
| 10 | **Agent** (`agent/`) | LangGraph pipeline, with a plain-Python fallback using the same node functions |
| 11 | **Runner** (`runner/`) | Executes tests on the simulator, records pass/fail and timing |
| 12 | **Evaluation** (`eval/`) | Metrics and report |
| 13 | **Exports** (`export/`) | pytest/udsoncan scripts, CAPL templates |
| 14 | **Store** (`store/`) | SQLite audit trail: runs, tests, decisions, results |
| 15 | **API / UI** (`api/`, `ui/`) | FastAPI service (`/generate`, `/ask`, `/run`, ...), five-tab Streamlit UI |
| 16 | **Q&A** (`qa/`) | Cited diagnostic answers: deterministic spec lookup + layered retrieval + verified LLM phrasing, `not_found` when unsupported |
| 17 | **Confidence** (`agent/confidence.py`, `agent/annotate.py`) | high / medium / low plus reason for generated tests and Q&A answers |
| 18 | **Docker** (`Dockerfile`, `docker-compose.yml`, `docker/`) | App + Ollama services; written, not built here |

## 5. Protocol scope (MVP)

**Services:**

| SID | Service |
|---|---|
| 0x10 | DiagnosticSessionControl |
| 0x11 | ECUReset |
| 0x14 | ClearDiagnosticInformation |
| 0x19 | ReadDTCInformation (subfunction 0x02) |
| 0x22 | ReadDataByIdentifier |
| 0x27 | SecurityAccess |
| 0x2E | WriteDataByIdentifier |
| 0x31 | RoutineControl |
| 0x3E | TesterPresent |

**NRCs:** 0x10, 0x11, 0x12, 0x13, 0x14, 0x22, 0x24, 0x31, 0x33, 0x35, 0x36, 0x37, 0x72, 0x78, 0x7E, 0x7F.

**NRC evaluation order** (implemented in one function, every step cited):

1. Service supported → else 0x11
2. Service allowed in active session → else 0x7F
3. Message length / format → else 0x13
4. Subfunction supported → else 0x12
5. Subfunction allowed in session → else 0x7E
6. Service-specific checks: identifier supported (0x31), identifier allowed in session (0x31), security (0x33), conditions (0x22), sequence (0x24), value range (0x31)

**Security:** a synthetic, documented seed/key algorithm, with a max-attempts lockout (0x36) and a delay (0x37).

**Timing:** P2 / P2* response deadlines, S3 session timeout returning the ECU to the default session.

## 6. Data

All data is small and self-authored. Correctness comes from **triangulation**, not volume:

1. Rules cite the AUTOSAR Dcm SWS (R24-11; 38 distinct SWS IDs cited, 9 documented disagreements in `docs/SWS_DISAGREEMENTS.md`, 4 fixed in Part C and 5 open) or are logged as design decisions.
2. Every encoded request must round-trip identically through `udsoncan`.
3. Every gold test must pass on the bug-free simulator.
4. The simulator and the rules engine are written independently and must agree on 100% of randomized requests.

The ECU spec is **synthetic, in a realistic OEM style**, and this is stated openly in all reports. ISO 14229 text is never copied.

**Spec provenance.** `data/bcm_spec.yaml` is hand-authored structured data (synthetic, OEM-style). It was **not** extracted from a PDF or any real OEM document. Real OEM diagnostic specifications (ODX/CDD files, diagnostic requirement documents) are confidential and none are publicly available, so the project writes its own spec in the shape such documents have. PDF/ODX extraction is therefore out of scope; the parser in `uds_assistant/spec/` loads and validates this YAML. The OEM guideline `data/oem_diagnostic_guidelines.md` is likewise synthetic and marked as such.

## 7. Evaluation metrics

> **Historical (Part C, report version 3, git `942f438`).** The table below is the Part C report, kept for the record. The current results (Part D/E: fresh v3 sets, conformance sweep, Q&A) are in `docs/RESULTS.md`, each section labelled with its run.

The original metric list (request validity, expected-response accuracy, coverage, template reuse, citation validity, bug detection, gold baseline) is retained in `outputs/eval_report.md`, but several of them were circular or in-sample, so the headline is a table whose first two rows are fresh. Numbers are exactly those in `outputs/eval_report.md` (report version 3; modes `mock` and `ollama`, one invocation).

| Metric | mock | ollama |
|---|---|---|
| **1. Held-out v2 bug detection, FRESH (15 bugs; HEADLINE = generated)** | **generated 2/15 (13.3%)**, gold 5/15 (33.3%), union 5/15 (33.3%) | **generated 2/15 (13.3%)**, gold 5/15 (33.3%), union 5/15 (33.3%) |
| **2. Natural v2 requirement understanding, FRESH (test2, n=16)** | parsed exact 0/16, P/R/F1 1.000/0.225/0.367; exercised F1 0.450; category recall 48.0% micro; precondition recall 55.6% micro; fallback/nothing 7/16 (6 excl. empty-label rows) | parsed exact 4/16, P/R/F1 0.565/0.796/0.661 (3-run mean 0.565/0.796/0.661); exercised F1 0.583 (mean 0.602, range 0.583-0.611); category recall 74.0% micro (mean 75.3%, range 74.0%-76.0%); precondition recall 77.8% micro (mean 82.7%, range 77.8%-85.2%) |
| 3. Simulator <-> rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 4. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 5. udsoncan virtual-CAN sequence | PASS | same (LLM-independent) |
| 6. Coverage (seed requirements) | positive 43, negative 77, session 25, security 30, timing 31; 15/15 requirements with at least 1 test | positive 26, negative 18, session 9, security 9, timing 4; 15/15 requirements with at least 1 test |
| 7. Citation validity | 967/967 (100.0%) | 315/315 (100.0%) |
| **SEEN** 8. Held-out v1 bug detection (12 bugs; templates designed against these misses) | generated 10/12 (83.3%), gold 3/12 (25.0%), union 11/12 (91.7%) | generated 5/12 (41.7%), gold 3/12 (25.0%), union 6/12 (50.0%) |
| **SEEN** 9. Natural v1 test split (n=12) | parsed exact 5/12, P/R/F1 0.933/0.560/0.700; exercised F1 0.425; category recall 67.9%; precondition recall 80.0% | parsed exact 3/12, P/R/F1 0.500/0.840/0.627; exercised F1 0.416; category recall 82.1%; precondition recall 73.3% |
| **In-sample (templates tuned on these)** 10. 26-bug detection | generated 25/26 (96.2%), gold 24/26 (92.3%), union 26/26 (100.0%) | generated 19/26 (73.1%), gold 24/26 (92.3%), union 26/26 (100.0%) |

Part C comparison extras (same report): planner choices rejected on the 35 old requirements 0 (mock) vs 15 (ollama; 10 before Part C), on v2 0 vs 12; parsed precision / false positives on v2 1.000 / 0 vs 0.565 / 30; explain LLM calls per requirement 0.89 (mock) vs 1.00 (ollama, 4.51 before); wall-clock per requirement mean / p95 0.27 s / 0.46 s (mock) vs 21.37 s / 28.52 s (ollama; 30.79 s / 43.41 s before); byte provenance 511/511 vs 418/418; SWS disagreements open 5 (9 before). Retrieval, BM25 vs Chroma, test split (n=11): hit@1 27.3% vs 18.2%, hit@3 63.6% vs 63.6%, MRR 0.506 vs 0.458.

Secondary and appendix labels: the in-sample row is optimistic and non-independent; the v1 rows are seen; expected-response accuracy versus the oracle is 100% by construction (circular) and appears only in the appendix of the report; template reuse is 100% by construction (byte-identical re-instantiation).

Requirement-understanding detail (per split and per requirement), the held-out per-bug tables with the reason for each miss, the before/after table, the noise check, and metric definitions are in `outputs/eval_report.md`, `outputs/partC/before_after.md` and `outputs/partC/interpretation.md`. The Streamlit UI shows the same tables from the JSON report.

Each LLM-dependent metric is reported separately for `mock` and `ollama` modes. The mock is deterministic. For ollama, the parsed numbers were identical across three noise runs on natural v2, while exercised F1, category recall and precondition recall varied (ranges above); three runs is a small sample, and the sets are small (15 bugs, 16 requirements).

## 8. Tech stack

- **Always available (lightweight):** Python 3.13 (built and tested on 3.13.6; code stays 3.11-syntax-compatible), pydantic, pyyaml, udsoncan, can-isotp, python-can (virtual bus), pytest, hypothesis, fastapi, uvicorn, langgraph, rank-bm25 or an in-house BM25.
- **Needs downloads (model phase, Part B; installed and run):** Ollama + `qwen2.5:3b-instruct-q4_K_M`, chromadb, and fastembed (ONNX) with `BAAI/bge-small-en-v1.5`. torch and sentence-transformers are not installed; the sentence-transformers embedder is an optional, unrun code path. (streamlit is installed and the UI is tested headless.)
- **Runtime switches:**
  - `LLM_MODE=mock|ollama` (default `mock`)
  - `RETRIEVER=bm25|chroma` (default `bm25`)
  - `EMBEDDER=fastembed|sentence-transformers` (default `fastembed`)
  - `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX` (default 4096), `OLLAMA_KEEP_ALIVE` (default `10m`)

## 9. Governance (from the case study)

- Every output carries citations and a review status.
- Generated tests require human review before execution on real hardware; the UI shows this.
- The audit trail records every run and decision in SQLite.
- Standard, OEM, ECU, and project knowledge are kept in separate collections.
- Everything runs locally, so no data leaves the machine.

## 10. Roadmap (mirrors the case study's phases)

| Phase | Name | Content |
|---|---|---|
| 1 | Knowledge Pilot | Protocol core, spec, retrieval with citations; cited Q&A (`POST /ask`, Part E) |
| 2 | Test Generation | Rules engine, templates, gold set, agent pipeline |
| 3 | Automation | Simulator, runner, bug injection, exports, evaluation |
| 4 | Scale | Real LLM evaluation (done, Part B), ChromaDB embeddings (done, Part B), tabbed UI (Part E), Docker files (written, not built). Multi-ECU specs: not done (one synthetic BCM). Coverage analytics: oracle-observable coverage only (sweep), not code coverage |
