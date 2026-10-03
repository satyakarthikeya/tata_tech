# PROJECT.md — UDS Diagnostics & Automated Test Generation Assistant

> Tata Tech Pulse final project · Case Study 5 · Solo build by Karthik

---

## Status (as of Part A)

The original design below is implemented and tested in `mock` mode; the numbers here are copied from `outputs/eval_report.md` / `.json` (see `FINAL_REPORT.md` for the honest summary).

- **Mock mode: done. Ollama mode: pending Part B** (no model download in the offline build; every ollama cell reads "pending Part B").
- **Templates: 23, frozen.** v1 had 14; the 9 generic v2 templates were added in Phase 7 *after* inspecting which in-sample bugs v1 missed, so in-sample detection is optimistic. Templates (and gold tests) are now frozen at `uds_assistant/testgen` tree hash `9a121b2742c5f85fa48fd4f5340caf3b85979c67`.
- **Headline bug-detection number is held-out:** generated suite **3/12 (25.0%)**, gold 3/12 (25.0%), union 5/12 (41.7%) on 12 held-out bugs written by a subagent that could not see templates, gold, eval, LLM or agent code. The in-sample 26-bug number (generated 25/26, 96.2%) is secondary and labelled "in-sample (templates tuned on these)".
- **Natural requirements:** 20 labelled requirements (`data/requirements_natural.csv`; 8 dev / 12 test) measure requirement understanding; the test split is the main number.
- **AUTOSAR SWS citations:** the rules engine cites 38 distinct AUTOSAR CP R24-11 Dcm SWS IDs; 9 documented disagreements (D1-D9) are in `docs/SWS_DISAGREEMENTS.md` and are **not fixed**. The SWS PDF is git-ignored and not redistributed; SWS tests skip without a local copy.
- **Python 3.13** (3.13.6) is what the project was built and tested on; code is kept 3.11-syntax-compatible.
- More: `docs/RECONCILIATION.md` (no older doc set found), `docs/CODE_TOUR.md`, `docs/ARCHITECTURE.md`, `docs/RESULTS.md`, `docs/DEMO_SCRIPT.md`.

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
| 5 | **Test model and templates** (`testgen/`) | `TestCase` schema, 23 reusable parameterized templates (originally planned 8–12; v1 14 + v2 9, frozen) |
| 6 | **Gold set** (`data/gold/`) | 60 hand-authored tests that must pass on the bug-free simulator |
| 7 | **Bug catalog** (`data/bugs/`) | 26 in-sample injectable faults (`bug_catalog.yaml`) + 12 held-out faults (`heldout_catalog.yaml`) |
| 8 | **Retrieval** (`rag/`) | Layered collections (standard / ecu_spec / project), citations. Backends: BM25 (offline) and ChromaDB + embeddings |
| 9 | **LLM layer** (`llm/`) | Pluggable: `mock` (deterministic), `ollama` (local Qwen2.5-3B Q4_K_M) |
| 10 | **Agent** (`agent/`) | LangGraph pipeline, with a plain-Python fallback using the same node functions |
| 11 | **Runner** (`runner/`) | Executes tests on the simulator, records pass/fail and timing |
| 12 | **Evaluation** (`eval/`) | Metrics and report |
| 13 | **Exports** (`export/`) | pytest/udsoncan scripts, CAPL templates |
| 14 | **Store** (`store/`) | SQLite audit trail: runs, tests, decisions, results |
| 15 | **API / UI** (`api/`, `ui/`) | FastAPI service, Streamlit engineering UI |

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

1. Rules cite the AUTOSAR Dcm SWS (R24-11; 38 distinct SWS IDs cited, 9 documented disagreements in `docs/SWS_DISAGREEMENTS.md`) or are logged as design decisions.
2. Every encoded request must round-trip identically through `udsoncan`.
3. Every gold test must pass on the bug-free simulator.
4. The simulator and the rules engine are written independently and must agree on 100% of randomized requests.

The ECU spec is **synthetic, in a realistic OEM style**, and this is stated openly in all reports. ISO 14229 text is never copied.

## 7. Evaluation metrics

The original metric list (request validity, expected-response accuracy, coverage, template reuse, citation validity, bug detection, gold baseline) is retained in `outputs/eval_report.md`, but several of them were circular or in-sample, so the headline is now a 7-row table. Numbers are exactly those in `outputs/eval_report.md` (mode `mock`).

| Metric | mock | ollama |
|---|---|---|
| 1. Simulator <-> rules-engine agreement (seeded random sample, live) | 5000/5000 (100.0%) | same (LLM-independent) |
| 2. Gold tests passing on the bug-free simulator | 60/60 (100.0%) | same (LLM-independent) |
| 3. udsoncan virtual-CAN sequence | PASS | same (LLM-independent) |
| **4. Held-out bug detection (12 bugs; HEADLINE = generated)** | **generated 3/12 (25.0%)**, gold 3/12 (25.0%), union 5/12 (41.7%) | pending Part B |
| 5. Requirement understanding (natural requirements, test split n=12) | target exact match parsed 5/12 (F1 0.700), exercised 2/12 (F1 0.449); category recall 67.9% micro / 69.7% macro; precondition recall 80.0% micro / 75.0% macro; fallback/nothing 3/12 | pending Part B |
| 6. Coverage (seed requirements) | positive 36, negative 70, session 21, security 18, timing 26; 15/15 requirements with at least 1 test | pending Part B |
| 7. Citation validity | 774/774 (100.0%) | pending Part B |

Secondary and appendix numbers:

| Metric | Value | Label |
|---|---|---|
| In-sample bug detection (26 bugs): generated / gold / union | 25/26 (96.2%) / 24/26 (92.3%) / 26/26 (100.0%) | **in-sample (templates tuned on these)**; optimistic, non-independent |
| In-sample baseline, template set v1 (14 templates), generated | 17/26 (65.4%) | before the Phase 7 additions |
| Request validity (adjusted for intentional format probes) | 445/445 (100.0%); unadjusted 404/445 (90.8%) | |
| Expected-response accuracy vs oracle | 445/445 (100.0%) | **self-consistency, circular by construction**; appendix only |
| Template reuse | 171/171 (100.0%) | true by construction (byte-identical re-instantiation) |

Requirement-understanding detail (per split and per requirement), the held-out per-bug table with reasons for each miss, and metric definitions are in `outputs/eval_report.md`. The Streamlit UI shows the headline table, the held-out table and the understanding results.

Each LLM-dependent metric is reported separately for `mock` and `ollama` modes; the `ollama` column is pending Part B.

## 8. Tech stack

- **Always available (lightweight):** Python 3.13 (built and tested on 3.13.6; code stays 3.11-syntax-compatible), pydantic, pyyaml, udsoncan, can-isotp, python-can (virtual bus), pytest, hypothesis, fastapi, uvicorn, langgraph, rank-bm25 or an in-house BM25.
- **Needs downloads (model phase, Part B):** Ollama + `qwen2.5:3b-instruct-q4_K_M`, sentence-transformers + `BAAI/bge-small-en-v1.5`, chromadb. (streamlit is installed and the UI is tested headless.)
- **Runtime switches:**
  - `LLM_MODE=mock|ollama` (default `mock`)
  - `RETRIEVER=bm25|chroma` (default `bm25`)

## 9. Governance (from the case study)

- Every output carries citations and a review status.
- Generated tests require human review before execution on real hardware; the UI shows this.
- The audit trail records every run and decision in SQLite.
- Standard, OEM, ECU, and project knowledge are kept in separate collections.
- Everything runs locally, so no data leaves the machine.

## 10. Roadmap (mirrors the case study's phases)

| Phase | Name | Content |
|---|---|---|
| 1 | Knowledge Pilot | Protocol core, spec, retrieval with citations |
| 2 | Test Generation | Rules engine, templates, gold set, agent pipeline |
| 3 | Automation | Simulator, runner, bug injection, exports, evaluation |
| 4 | Scale | Real LLM evaluation, ChromaDB embeddings, UI, multi-ECU specs, coverage analytics |
