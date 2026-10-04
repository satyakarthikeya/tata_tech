# Case Study 5 compliance matrix

Every Case 5 item, its status in this repo, and where the evidence is.

**Source of the item list.** The case-study PDF is not in the repository. The items below come from the Part E brief (`FINAL_PART_E.md`), `PROJECT.md`, `SCOPE.md` and the docs, so the wording is the repo's own reading of the case study (the seven workflow steps in particular are this project's pipeline written as steps, not a quotation). If the original document words an item differently, the status here still describes what the repo does.

**Status meanings.** *done* = built and tested, with the stated evidence; it may still carry a caveat in the note. *partial* = built, but measured only by a proxy, only on synthetic data, unverified outside the repo, or with a known gap. *out of scope* = not built, and named as out of scope in `SCOPE.md` or impossible here (no hardware, no CANoe, no public OEM specs).

**Run labels.** Numbers come from `docs/RESULTS.md`: Main eval 2026-10-04 (`1f0c293`), Q&A run 2026-10-04 (`9e66f7a`), timing run 2026-10-04 (`8357ec0`).

**Summary: 81 items: 48 done, 27 partial, 6 out of scope.**

Overall reading: the software chain (requirement to cited, validated tests to simulator results, plus cited Q&A) is built and measured on a synthetic ECU. What the repo cannot show is anything that needs a real OEM spec, a real ECU, CANoe or a human stopwatch.

## 1. Objectives

| # | Item | Status | Evidence and honest note |
|---|---|---|---|
| O1 | Cut the effort of writing diagnostic tests from requirements | partial | Generation works (`uds_assistant/agent/pipeline.py`, [RESULTS.md](RESULTS.md) section 5). Only tool-side time is measured (mock mean 0.217 s, ollama 19.36 s per requirement, timing run `8357ec0`); the manual comparison is **pending owner measurement** ([TEST_DESIGN_TIME.md](TEST_DESIGN_TIME.md)). Review time is not included. |
| O2 | Better coverage, especially negative and edge cases | partial | 15/15 seed requirements have tests; categories positive, negative, session, security, timing; the 1200-test conformance sweep (`uds_assistant/testgen/conformance.py`). Coverage is oracle-observable, not code coverage, and fresh-bug detection is 10/15 mock, 9/15 ollama, so gaps remain ([RESULTS.md](RESULTS.md) sections 2 and 5). |
| O3 | Faster access to diagnostic knowledge (cited answers) | done | `uds_assistant/qa/`, `POST /ask`, Ask tab. 25 blind questions: accuracy 90.5% (19/21), correct not-found 3/4 (Q&A run `9e66f7a`, `outputs/qa/qa_eval.md`). Misses QA-018, QA-022, QA-023; small sample. |
| O4 | Traceable, reviewable output | done | Citations on every test (`uds_assistant/rag/citations.py`), review status and decisions in SQLite (`uds_assistant/store/audit.py`), confidence with reason (`uds_assistant/agent/confidence.py`). Citation validity means the cited chunk exists, not that it justifies the test. |
| O5 | Runs locally, no data leaves the machine | done | Mock mode needs no network; Ollama is local (`uds_assistant/llm/`); no cloud API anywhere. Docker files exist but were not built (see T8). |

## 2. In-scope list (`SCOPE.md`)

| # | Item | Status | Evidence and honest note |
|---|---|---|---|
| S1 | UDS services 0x10, 0x11, 0x14, 0x19 (0x02), 0x22, 0x27, 0x2E, 0x31, 0x3E | done | `uds_assistant/protocol/`, `uds_assistant/rules/`, `tests/protocol/`; bytes cross-checked against `udsoncan` (`tests/protocol/test_udsoncan_crosscheck.py`). |
| S2 | One synthetic Body Control Module spec | done | `data/bcm_spec.yaml`, `uds_assistant/spec/schema.py`. Hand-authored synthetic data, not extracted from a PDF ([PROJECT.md](../PROJECT.md) section 6). |
| S3 | Deterministic rules engine as the single source of truth | partial | `uds_assistant/rules/engine.py`, `uds_assistant/rules/nrc_order.py` (one NRC-order function, each check cited). Five AUTOSAR SWS disagreements are still open: D1, D3, D4, D8, D9 ([SWS_DISAGREEMENTS.md](SWS_DISAGREEMENTS.md)). |
| S4 | Independent simulator with 15+ injectable bugs | done | `uds_assistant/simulator/` (never imports `rules/`, `tests/simulator/test_independence.py`); 68 bugs in four catalogs under `data/bugs/` (26 in-sample, 12 + 15 + 15 held-out). |
| S5 | Gold test set of 40 to 60 hand-authored tests | done | `data/gold/gold_tests.yaml`, 60/60 pass on the clean simulator (Main eval `1f0c293`). |
| S6 | Pipeline parse, retrieve, plan, instantiate, validate, explain | done | `uds_assistant/agent/` (LangGraph plus plain-Python fallback); byte provenance 613/613 mock, 552/552 ollama, 1200/1200 sweep. |
| S7 | Test categories positive, negative, session, security, timing | done | Coverage table in [RESULTS.md](RESULTS.md) / `outputs/eval_report.md`. Timing is checked in-process by wall clock only (`DECISIONS.md` RUN-TIMING). |
| S8 | Layered retrieval with citations (standard / OEM / ECU / project) | done | `uds_assistant/rag/layers.py`, `data/oem_diagnostic_guidelines.md` (synthetic), `tests/rag/test_layers.py`. The generator uses only standard, ECU and project (`DECISIONS.md` E33-NO-OEM-IN-GEN). |
| S9 | Evaluation report: validity, accuracy, coverage, reuse, citation validity, bug detection | done | `outputs/eval_report.md` / `.json`, `uds_assistant/eval/`. Accuracy and reuse are circular or 100% by construction and labelled as proxies. |
| S10 | Exports to Python (udsoncan + pytest) and CAPL | partial | `uds_assistant/export/pytest_export.py` (exported files ran green: 206 and 73 passed); `uds_assistant/export/capl_export.py` is an **unverified template**, never compiled or run in CANoe. |
| S11 | SQLite audit trail, FastAPI service, Streamlit UI | done | `uds_assistant/store/`, `uds_assistant/api/app.py`, `uds_assistant/ui/`. UI tested headless only; never clicked through in a real browser ([UI_CHECKLIST.md](UI_CHECKLIST.md) is the manual procedure). |
| S12 | Local LLM (Qwen2.5-3B Q4_K_M via Ollama) plus mock mode | done | `uds_assistant/llm/`; evaluated end to end ([RESULTS.md](RESULTS.md) sections 2 to 4). One small model only, on a 4 GB GPU. |

## 3. Functional capabilities

| # | Item | Status | Evidence and honest note |
|---|---|---|---|
| F1 | Understand a plain-English requirement (targets, preconditions) | partial | `uds_assistant/agent/nodes.py` (`parse`), grounding in `uds_assistant/agent/grounding.py`. Natural v3 (n=16): ollama parsed F1 0.609, precision 0.596 with 19 false positives; mock F1 0.407 ([RESULTS.md](RESULTS.md) section 3). The natural door-lock requirement did not yield the intended test pair ([FINAL_REPORT.md](../FINAL_REPORT.md), Known limitations). |
| F2 | Retrieve evidence from the spec and notes with citations | done | `uds_assistant/rag/` (BM25 default; Chroma + fastembed compared, no clear winner). Citation validity 967/967 mock, 353/353 ollama. |
| F3 | Generate positive, negative, session, security and timing tests | done | `uds_assistant/testgen/templates*.py` (27 templates), conformance sweep. Bytes come only from templates and the rules engine. |
| F4 | Predict the expected response deterministically | partial | Oracle in `uds_assistant/rules/`; simulator agreement 5000/5000, udsoncan virtual-CAN PASS (one happy path). Same author and contract for engine, simulator and gold, and SWS D1, D3, D4, D8, D9 open. |
| F5 | Validate every generated test automatically | done | `check_test` / `validate` in `uds_assistant/agent/nodes.py` (schema, byte provenance, oracle agreement, citations), `tests/agent/`. |
| F6 | Explain each test in prose | done | `explain` node; ollama batches omit entries (123 fallback events in the main run, model omissions, no score effect: `outputs/partD/interpretation.md`). |
| F7 | Run tests on a simulator with injected bugs and report pass/fail | done | `uds_assistant/runner/suite.py`, Run on Simulator tab; bug matrix in `outputs/eval_report.md`. |
| F8 | Confidence indicator per test and per answer | done | `uds_assistant/agent/confidence.py`, `uds_assistant/agent/annotate.py`, `tests/agent/test_confidence.py`. Lightly validated: mock 135 high / 71 medium / 0 low on the 15 seeds; `low` only unit-tested. |
| F9 | Cited diagnostic Q&A with refusal when unsupported | done | `uds_assistant/qa/`, `tests/qa/`, `uds_assistant/eval/qa_eval.py`. Known misses QA-018, QA-022, QA-023. |
| F10 | Human review (approve, reject, comment) | done | Generate & Review tab, `uds_assistant/ui/state.py`, `POST /tests/{run_id}/{test_id}/review`. Reject and comment are decision-log entries, not store statuses (`DECISIONS.md` E4-REVIEW). |
| F11 | Coverage analytics | partial | Oracle-observable coverage only (sweep phases 1 and 2: 1034/1034 and 1336/2038 items); no code coverage, no per-requirement gap dashboard. |
| F12 | Multiple ECUs / variants | out of scope | One synthetic BCM by design (`SCOPE.md`). |

## 4. Workflow steps 1 to 7

| # | Item | Status | Evidence and honest note |
|---|---|---|---|
| W1 | Ingest requirement and ECU spec | partial | Requirements as text or CSV (`data/requirements_seed.csv`, natural v1 to v3), spec as hand-authored YAML (`data/bcm_spec.yaml`). PDF or ODX spec extraction is out of scope: no public OEM spec exists. |
| W2 | Parse the requirement into targets and preconditions | partial | As F1: works, precision is the weak point on fresh phrasing. |
| W3 | Retrieve layered knowledge with citations | done | As F2 and S8. |
| W4 | Plan and instantiate tests from templates | done | `uds_assistant/agent/nodes.py` (`plan`, `instantiate`), `uds_assistant/agent/options.py`; planner choices rejected: 0 on every set in the Part D run (no ablation for why). |
| W5 | Validate against the oracle and check provenance | done | As F5. |
| W6 | Human review before use | partial | Review status and decisions are recorded and shown, the UI states it, and "Approved tests only" is available for run and export. It is optional: nothing blocks running or exporting unreviewed tests, and there is no hardware to gate. |
| W7a | Execute on a simulator and report | done | As F7; results in `outputs/eval_report.md`. |
| W7b | Execute on a real ECU, HIL rig or CANoe | out of scope | `SCOPE.md`: real ECUs, vehicles and CAN hardware are out of scope; only a virtual bus was used. |
| W7c | Export for downstream tools | partial | As S10: pytest done, CAPL unverified. |

## 5. Inputs and outputs

| # | Item | Status | Evidence and honest note |
|---|---|---|---|
| IO1 | Input: diagnostic spec documents (PDF, ODX, CDD) | out of scope | Replaced by structured synthetic data (`data/bcm_spec.yaml`); real OEM specs are confidential ([PROJECT.md](../PROJECT.md) section 6). |
| IO2 | Input: standard (ISO 14229 / AUTOSAR) knowledge | partial | Own-words notes in `data/sources/uds_reference_notes.md`; no ISO text copied by rule (`AGENT.md`). The AUTOSAR SWS PDF is used only for citation checks and is git-ignored. |
| IO3 | Input: OEM guidelines | partial | Synthetic `data/oem_diagnostic_guidelines.md` ingested into its own layer; shows the mechanism, not real OEM content. |
| IO4 | Input: natural-language requirements | done | `data/requirements_seed.csv`, `data/requirements_natural*.csv`. |
| IO5 | Input: past test cases and defect history | out of scope | Not in the `SCOPE.md` in-scope list and not built. The gold tests and bug catalogs are evaluation data, not generation input. |
| IO6 | Output: structured test cases with citations and confidence | done | `uds_assistant/testgen/model.py`, `outputs/generated_tests.yaml`. |
| IO7 | Output: executable scripts (pytest, CAPL) | partial | pytest done; CAPL unverified template. |
| IO8 | Output: evaluation and results reports | done | `outputs/eval_report.md`, [RESULTS.md](RESULTS.md), [FINAL_REPORT.md](../FINAL_REPORT.md). |
| IO9 | Output: cited answers | done | `POST /ask`, Ask tab. |
| IO10 | Output: audit trail | done | `uds_assistant/store/audit.py`, `outputs/ui_audit.sqlite`, `outputs/api_audit.sqlite`. |

## 6. Technology stack

| # | Item | Status | Evidence and honest note |
|---|---|---|---|
| T1 | Python, pydantic | done | `pyproject.toml`; built and tested on Python 3.13.6. |
| T2 | Local LLM via Ollama | done | `uds_assistant/llm/client.py`; `qwen2.5:3b-instruct-q4_K_M`. One small model; no larger model tried. |
| T3 | Vector retrieval (ChromaDB + embeddings) | done | `uds_assistant/rag/chroma.py` with fastembed `BAAI/bge-small-en-v1.5`; BM25 stays default. `EMBEDDER=sentence-transformers` never run; no end-to-end generation run with `RETRIEVER=chroma`. |
| T4 | Agent orchestration (LangGraph) | done | `uds_assistant/agent/graph.py`, plain-Python fallback with identical results. |
| T5 | FastAPI service | done | `uds_assistant/api/app.py`, `tests/api/`. |
| T6 | Streamlit UI | done | `uds_assistant/ui/`, `tests/ui/`; headless only. |
| T7 | pytest, udsoncan, python-can virtual CAN | done | `uds_assistant/export/pytest_export.py`, `uds_assistant/eval/can_check.py`, `tests/simulator/test_transport.py`. |
| T8 | Docker packaging | partial | `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `docker/entrypoint.sh`, [DOCKER.md](DOCKER.md): **written, not built here** (limited network). |
| T9 | Vector CANoe / CAPL toolchain | out of scope | No CANoe license; CAPL is an unverified template (`SCOPE.md`). |
| T10 | Cloud or paid LLM APIs | out of scope | `SCOPE.md`. |

## 7. Success metrics

| # | Item | Status | Evidence and honest note |
|---|---|---|---|
| M1 | Test design time | partial | Tool side measured (timing run `8357ec0`); protocol and blank results table in [TEST_DESIGN_TIME.md](TEST_DESIGN_TIME.md); manual comparison **pending owner measurement**. |
| M2 | Generation accuracy | partial | Proxy: generated send-steps equal to the oracle 691/691 mock, 226/226 ollama, circular by construction. Independent evidence is simulator vs rules 5000/5000, gold 60/60, udsoncan PASS ([RESULTS.md](RESULTS.md) sections 1 and 5). |
| M3 | Coverage | partial | 15/15 seed requirements covered; sweep 1034/1034 and 1336/2038 items; oracle-observable only. |
| M4 | Reuse rate | partial | Proxy: 206/206 mock and 73/73 ollama tests come from the template catalog (100% by construction); says nothing about real engineer reuse. |
| M5 | Defect detection | done | Fresh v3: full output 10/15 mock, 9/15 ollama; requirement-driven 4/15 and 2/15; sweep 9/15 (Main eval `1f0c293`). Small set (15 bugs, written by a language model, on a simulator). |

## 8. Risks and controls

| # | Item | Status | Evidence and honest note |
|---|---|---|---|
| R1 | LLM hallucination producing wrong test bytes | done | The LLM never produces bytes; byte-provenance check on every test; guards in [ARCHITECTURE.md](ARCHITECTURE.md). Shows provenance, not correctness of the bytes. |
| R2 | Mixing standard, OEM, ECU and project knowledge | done | Four separate collections, layer on every chunk and citation (`uds_assistant/rag/layers.py`). |
| R3 | Wrong expected results from a wrong oracle | partial | Triangulation (simulator agreement, gold, udsoncan) in [RESULTS.md](RESULTS.md) section 1; SWS D1, D3, D4, D8, D9 open; engine, simulator and gold share one contract and author. |
| R4 | Unsafe use of generated tests on real hardware | partial | Human-review status, banner in the UI, synthetic-only claim, optional "approved only" filters. No technical gate, and no hardware was used. |
| R5 | Confidential data leaving the machine | done | Local-only design; no cloud calls. |
| R6 | Non-determinism and model drift | partial | Mock default (deterministic), ollama temperature 0 and seed 0, three-run noise check (parsed numbers identical, exercised F1 range 0.462 to 0.472); ollama output is not bit-deterministic (Q&A fallback events 12 to 13 between runs). |
| R7 | Over-trust in answers | partial | Citations, `not_found` refusal, confidence badges. QA-018 shows a refusal miss; confidence thresholds were not fitted or validated against correctness. |
| R8 | Small-model limits | partial | Measured and reported (precision 0.596; 30-option shortlist forced by 4096 context); no larger model tried. |

## 9. Phases 1 to 4

| # | Item | Status | Evidence and honest note |
|---|---|---|---|
| P1 | Phase 1, Knowledge Pilot: protocol core, spec, retrieval with citations, cited Q&A | done | `uds_assistant/protocol/`, `uds_assistant/spec/`, `uds_assistant/rag/`, `uds_assistant/qa/` (Q&A added in Part E). Synthetic spec. |
| P2 | Phase 2, Test Generation: rules engine, templates, gold set, agent pipeline | done | `uds_assistant/rules/`, `uds_assistant/testgen/`, `data/gold/`, `uds_assistant/agent/`. |
| P3 | Phase 3, Automation: simulator, runner, bug injection, exports, evaluation | partial | All built on the simulator; CAPL unverified; no real ECU, HIL or CANoe execution. |
| P4 | Phase 4, Scale: real-LLM evaluation, embeddings, UI, multi-ECU, analytics | partial | Real-LLM evaluation, Chroma embeddings and the tabbed UI done; Docker written, not built; multi-ECU specs not done (one BCM); analytics limited to oracle-observable coverage. |

## 10. Governance principle

| # | Item | Status | Evidence and honest note |
|---|---|---|---|
| G1 | Every output carries citations and a review status | done | Citations and `review_status` on tests (`uds_assistant/testgen/model.py`); answers carry citations; citation validity is existence, not justification. |
| G2 | Human review before real-hardware execution | partial | Recorded and displayed (UI banner, Approve/Reject, audit DB) but not technically enforced; nothing runs on hardware. |
| G3 | Audit trail of runs and decisions | done | `uds_assistant/store/audit.py`, `tests/store/`. |
| G4 | Separate knowledge collections | done | As R2. |
| G5 | Everything runs locally | done | As R5. |
| G6 | Honest reporting: results labelled by run, seen vs fresh data | done | Run provenance in `outputs/eval_report.md` (`uds_assistant/eval/run_provenance.py`), History section, seen/fresh labels, [FINAL_REPORT.md](../FINAL_REPORT.md). |
