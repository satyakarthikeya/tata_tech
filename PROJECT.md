# PROJECT.md — UDS Diagnostics & Automated Test Generation Assistant

> Tata Tech Pulse final project · Case Study 5 · Solo build by Karthik

This is the simplified release (git branch `simple`): one LLM backend (Ollama), one retriever
(ChromaDB + BGE embeddings), four UI tabs and one evaluation command. The earlier full version
(mock LLM, BM25, large test suite, development history) is the git tag `v1-full-archive`.
Current numbers are in `docs/RESULTS.md`; limits are listed in section 8.

---

## 1. The problem

UDS (Unified Diagnostic Services) is the protocol a diagnostic tester uses to talk to a car ECU: read data, write data, unlock security, run routines, clear fault codes. To test an ECU's diagnostics, an engineer must combine the generic protocol rules with OEM- and ECU-specific specs. They then hand-build request bytes, work out preconditions (session, security), predict positive and negative responses, and turn all of that into automation scripts.

This is slow and error-prone, and negative and edge-case coverage is usually weak.

## 2. What we build

A **local assistant** (Ollama + ChromaDB, nothing leaves the machine) that turns a diagnostic requirement into **validated, executable test cases**. It then runs them against an ECU simulator and measures how many injected defects they catch.

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
        ├──► evaluation report (eight sections, `python -m uds_assistant.eval.run_eval`)
        └──► export: Python (udsoncan + pytest), CAPL templates
```

## 3. Core design principle

**The LLM handles language. Code handles correctness.**

- **LLM:** understands the requirement, chooses which test intents and templates apply, and writes the human explanation.
- **Deterministic code:** every byte, NRC, session rule, security rule, and timing value.
- LLM output never contains bytes that reach a final test. Bytes come only from templates and the rules engine.

Because of this, the system stays correct with a small 3B local model.

## 4. Components

| # | Component | Responsibility |
|---|---|---|
| 1 | **Protocol core** (`protocol/`) | SIDs, NRC table, encode/decode, positive SID = SID + 0x40, negative = `7F SID NRC`, suppress-positive bit |
| 2 | **ECU spec** (`spec/`, `data/bcm_spec.yaml`) | Pydantic model of a synthetic Body Control Module: sessions, security levels, DIDs, routines, DTCs, timing (P2, P2*, S3) |
| 3 | **Rules engine** (`rules/`) | The oracle: (spec, state, request) -> exact expected response + reason trace, explicit NRC evaluation order |
| 4 | **ECU simulator** (`simulator/`) | Independent stateful ECU, bug injection, in-process and virtual-CAN/ISO-TP transports |
| 5 | **Test model and templates** (`testgen/`) | `TestCase` schema, 27 approved parameterized templates, requirement-independent conformance sweep |
| 6 | **Gold set** (`data/gold/`) | 60 hand-authored tests that must pass on the bug-free simulator |
| 7 | **Bug catalogs** (`data/bugs/`) | 26 in-sample faults (`bug_catalog.yaml`) and the 15-fault blind v3 set (`heldout_v3_catalog.yaml`) |
| 8 | **Retrieval** (`rag/`) | ChromaDB + `BAAI/bge-small-en-v1.5` (fastembed); four collections (standard / OEM / ECU / project); citations. The standard layer adds one chunk per AUTOSAR SWS requirement (id, page, section, release) when a local PDF is present (`rag/autosar.py`), else uses the own-words notes |
| 9 | **LLM layer** (`llm/`) | Ollama, `qwen2.5:3b-instruct-q4_K_M`; all prompts in `llm/prompts.py`; required, no fallback |
| 10 | **Agent** (`agent/`) | LangGraph pipeline (plain-Python fallback engine with the same nodes), grounding, confidence |
| 11 | **Q&A** (`qa/`) | Cited answers: deterministic spec lookup + retrieval + verified LLM phrasing; `not_found` when unsupported |
| 12 | **Runner / exports / store** | Run suites on the simulator; pytest and CAPL exports; SQLite audit trail |
| 13 | **API / UI / eval** | FastAPI, four-tab Streamlit UI, one evaluation command |

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

1. Rules cite the AUTOSAR Dcm SWS (R24-11; the PDF is git-ignored and not redistributable) or are logged as design decisions. The cited ids are also data in `rules/sws_map.py` (own-words summary, keywords, `verified`); each stays `verified=False` until `python -m uds_assistant.rules.verify_sws_map` finds it, with its keywords, in a local copy of the PDF.
2. Every encoded request round-trips identically through `udsoncan`.
3. Every gold test passes on the bug-free simulator.
4. The simulator and the rules engine are written independently and must agree on randomized requests.

The ECU spec is **synthetic, in a realistic OEM style**, and this is stated in every report. It is hand-authored YAML, not extracted from a PDF (real OEM specs are confidential); the OEM guideline `data/oem_diagnostic_guidelines.md` is synthetic too. ISO 14229 text is never copied.

## 7. Evaluation

`python -m uds_assistant.eval.run_eval` writes `outputs/eval_report.md` and `.json` (copied to `docs/RESULTS.md`) with the eight sections of the case study's success metrics: correctness (sanity), generation accuracy, coverage, reuse rate, defect detection (blind v3 bug set: generated tests + conformance sweep), requirement understanding (natural v3), Q&A quality, and test design time; plus section 9 (imported-suite baseline) and section 10 (standard sources: SWS PDF or notes, SWS ids verified, and how many rules-engine NRC decisions are backed by an SWS id, `eval/sws_eval.py`). The blind sets were written without seeing templates or code and are not tuned on. Every number is measured in the run that wrote the report.

## 8. Limitations

Synthetic spec and simulator written by the same author; no real ECU or hardware; one small local model; small samples (15 bugs, 16 requirements, 25 questions, so one item moves a score by 4 to 7 points); CAPL export never compiled or run in CANoe; the manual-time row of the test-design-time metric is left for the owner to fill.

## 9. Governance (from the case study)

- Every output carries citations and a review status.
- Generated tests require human review before execution on real hardware; the UI shows this.
- The audit trail records every run and decision in SQLite.
- Standard, OEM, ECU, and project knowledge are kept in separate collections.
- Everything runs locally, so no data leaves the machine.

## 10. Tech stack

Python 3.13 (code stays 3.11-compatible), pydantic, pyyaml, udsoncan, can-isotp, python-can (virtual bus), fastapi, uvicorn, langgraph, chromadb, fastembed, streamlit (optional `ui` extra), Ollama. Settings are environment variables: `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX` (default 4096), `OLLAMA_KEEP_ALIVE` (default `10m`), `FASTEMBED_CACHE_PATH`.
