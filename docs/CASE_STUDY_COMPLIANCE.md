# Case Study 5 compliance matrix

Source: *Automotive Engineering AI: Standard Project Case Study Document*, v1.0, Case Study 5 "UDS Diagnostics and
Automated Test Generation Assistant" (sections 3 and 6 to 13). Each item below is quoted from that section by name and
mapped to the exact file, function or UI element, with a strict status and one line of evidence. Numbers live in
[RESULTS.md](RESULTS.md) (the evaluation of the run it names), so this file cannot drift from them.

**Status.** *met* = built and run, with the evidence stated (it may carry a caveat). *partial* = built, but measured by
a proxy, only on synthetic data, unverified outside the repository, or with a known gap. *not done* = not built.

**Overall.** The software chain the case study describes (cited Q&A, request validation, test generation with
preconditions and pass criteria, positive and negative coverage, pytest export, comparison and reporting, coverage report,
review gate) is built and measured **on a synthetic ECU**. What it does not do: read real specification documents (PDF,
ODX), read tests in any format other than the documented YAML (no CAPL, vTESTstudio or Excel; automation-template
names are kept as provenance, not interpreted), isolate projects or users, or touch a real ECU, CANoe or a
human stopwatch.

## A. Section 6, Functional Capabilities (7)

| # | Capability (PDF wording) | Where | Status | Evidence |
|---|---|---|---|---|
| 1 | Natural language diagnostic knowledge search | `qa/answer.py: answer_question`, `POST /ask`, Ask tab | met | 25 blind questions: answer accuracy, citation correctness and correct "not found" in RESULTS section 7. Searches four layers; refuses when unsupported. |
| 2 | Service, subfunction, DID, RID, NRC, session, and security guidance | `qa/lookup.py` (deterministic facts for DID, routine, NRC, service, security level, timing), `qa/check_request.py` (decodes service / subfunction / DID / RID) | partial | Facts are generated from the spec, not by the model. Subfunction guidance comes from the raw-request decoder and the standard notes; no Q&A question set targets subfunctions specifically. |
| 3 | Request structure validation | `qa/check_request.py: check_request`, `POST /validate`, "Check a raw request" box in the Ask tab | met | Reports structurally valid or not (unknown service, subfunction or bad length), the expected bytes or NRC with the rules engine's own reason, and citations. Synthetic BCM only. |
| 4 | Test case generation with preconditions and pass/fail criteria | `testgen/model.py: TestCase`, `testgen/criteria.py`, Generate & Review tab | met | `preconditions` and `pass_criteria` are derived deterministically for generated tests, the sweep and the gold set; shown per test, in the pytest docstring and CAPL comments. They describe the test: timing is enforced only where a step sets `max_response_time_ms`. |
| 5 | Positive and negative coverage generation | `testgen/templates*.py` (27 templates), `testgen/conformance.py`, `eval/coverage.py` | met | Positive, negative, session, security and timing tests (RESULTS section 3); spec items still without a generated test are listed by the coverage report. |
| 6 | Automation template export | `export/pytest_export.py: render_pytest`, `export/capl_export.py: render_capl`, Run & Export tab | partial | pytest was run (in-process and over a virtual CAN bus). The CAPL file is an **unverified template**, never compiled or run in CANoe. |
| 7 | Response comparison and reporting | `runner/suite.py` (exact-byte comparison per step, first failing step, timing), Run & Export tab, `check_request(actual_response=...)` / "Observed ECU response" field | partial | Compares expected bytes with the simulator's response, and a user-typed ECU response with the prediction (match or mismatch). It cannot read a response from a real ECU or CANoe log. |

## B. Section 8, Expected Outputs (7)

| # | Output (PDF wording) | Where | Status | Evidence |
|---|---|---|---|---|
| 1 | Diagnostic guidance with citations | Ask tab, `POST /ask`; citations on every test | met | Citations are checked against real chunks and quotes against chunk text; existence is checked, not that the text justifies the claim. |
| 2 | Validated request template | `testgen/templates.py` (27 templates build requests from `protocol/builders.py`), `POST /validate` | met | Every request in a test is built by a template and re-validated against the rules engine (`agent/nodes.py: validate`). |
| 3 | Expected positive response | `rules/engine.py: evaluate` | met | Every expected positive response is computed by the rules engine; agreement with the independent simulator is measured (RESULTS section 1). |
| 4 | Negative-response scenarios | negative, session and security templates; NRC coverage in the coverage report | met | NRC order is one function with cited checks; the report shows which NRCs have tests. |
| 5 | Structured test case | `testgen/model.py: TestCase` | met | Id, title, requirement ids, category, preconditions, steps, pass criteria, citations, review status, explanation, confidence. |
| 6 | Automation script template | pytest and CAPL exports (as capability 6) | partial | pytest met; CAPL unverified. |
| 7 | Coverage report | `eval/coverage.py: coverage_report`, Run & Export table and Markdown download, `POST /coverage`, `outputs/exports/coverage_report.md`, section of `eval_report.md` | met | Per service, DID, routine, NRC, session and security level: tests touching it, positive / negative split, items with zero tests. Spec-item coverage, not code coverage; the NRC list is the set the rules engine can emit. |

## C. Section 7, High-Level Workflow (7 steps)

| # | Step (PDF wording) | Where | Status | Evidence |
|---|---|---|---|---|
| 1 | Ingest authorized UDS, OEM, ECU, and project specifications | `rag/ingest.py` | partial | Ingests own-words UDS notes, a synthetic OEM guideline, the ECU spec YAML, and requirements plus the behaviour contract. No PDF, ODX or CDD ingestion. |
| 2 | Extract services, parameters, preconditions, and response rules | `spec/schema.py`, `data/bcm_spec.yaml` | partial | The spec is **hand-structured** YAML, not extracted from documents; the rules are written code. |
| 3 | Store embedded chunks in project-specific local collections | `rag/chroma.py` | partial | Four physical Chroma collections (standard, OEM, ECU, project layers), local. One project only: no per-project or per-user isolation. |
| 4 | Accept a diagnostic requirement or engineer query | Generate & Review tab, Ask tab, `POST /generate`, `POST /ask` | met | Plain English in, run recorded in the audit DB. |
| 5 | Retrieve relevant evidence and apply deterministic validation rules | `agent/nodes.py` (`retrieve`, `validate`), `rules/` | met | Retrieval then rules-engine validation; the model never writes bytes. |
| 6 | Generate a structured test case and optional automation template | `agent/pipeline.py: run_pipeline`, exports | met | End to end on a local 3B model, about 20 s per requirement. |
| 7 | Require engineer review before controlled execution | `testgen/review_gate.py`, Generate & Review review panel, Run & Export | met | Run and export use approved tests only by default (UI and API); bulk approve and a demo-only override exist and are labelled. An app-level gate, not a technical lock. Imported tests use the same gate: they enter as `validated` and `tests/test_import_api.py` checks that `/run` and `/export` answer 409 until a person approves. |

## D. Section 11, Indicative Success Metrics (5)

| Metric (PDF wording) | Status | Evidence |
|---|---|---|
| Test design time: average time to create reviewed diagnostic test cases | partial | Tool time per requirement is measured (RESULTS section 8). The **manual baseline and review time are not done**: they need a person with a stopwatch ([TEST_DESIGN_TIME.md](TEST_DESIGN_TIME.md)). |
| Generation accuracy: accepted request and response structures | partial | RESULTS section 2: well-formed requests and clean-pass rate, both near 100% **by construction** (the oracle builds the bytes). The independent evidence is section 1 (simulator vs rules engine, gold tests, udsoncan on a virtual bus), by one author from one contract. |
| Coverage improvement: positive, negative, session, security, timing | partial | The import feature measures this against an **existing suite** as the baseline: `POST /import/{id}/compare` and RESULTS section 9 give imported vs generated vs combined coverage and the newly covered services, DIDs, routines, NRCs, sessions, security levels and timing cases. The baseline in RESULTS is a synthetic fixture, not a real team's tests. Earlier proxy: `python scripts/coverage_baseline.py`: the 60 hand-written gold tests touch 42 of 46 spec items (3 DIDs and NRC 0x14 untouched); the 1200-test conformance sweep touches 46 of 46. The seed-requirement generated tests touch fewer items than the gold set (RESULTS coverage section). The baseline is hand-written by the same author, not an independent team's existing tests. |
| Reuse rate: share of generated tests based on approved templates | partial | RESULTS section 4; 100% by construction, so it shows catalog breadth, not saved effort. |
| Defect detection: confirmed ECU issues found through generated cases | partial | RESULTS section 5 on a blind 15-bug set written without seeing templates or code. These are **injected simulator bugs**, not confirmed issues in a real ECU; missed bugs are listed. |

## E. Section 12, Key Risks and Controls (4)

| Risk | Recommended control (PDF) | Status | Evidence |
|---|---|---|---|
| Incorrect diagnostic message generation | Apply deterministic protocol rules and expert review | met | Rules engine builds every byte; review gate on run and export. Caveat: if the oracle is wrong, tests are wrong; it is triangulated, not independently certified. |
| Misinterpretation of OEM-specific behavior | Separate standard, OEM, ECU, and project collections | met | Four physical collections; generation does not search OEM (OEM text must not silently change protocol-derived bytes), Q&A searches all four. The OEM content is synthetic. |
| Unsafe execution sequence | Execute only in approved test environments with safeguards | met | "FOR SIMULATOR OR APPROVED LAB BENCH ONLY" banners; the exported pytest refuses a non-virtual CAN interface unless `UDS_ALLOW_LAB_BENCH=1`. No real vehicle or bench was used. |
| Standards licensing violation | Use authorized source documents and access controls | partial | Own-words notes only; the AUTOSAR SWS PDF is git-ignored and not shipped. No access control or user accounts. |

## F. Section 3, Scope, and Section 8, Inputs

| Item | Status | Evidence |
|---|---|---|
| In scope: approved standard and OEM knowledge retrieval | met | Ask tab, four layers, citations. |
| In scope: UDS service and parameter guidance; request-message construction | met | `qa/lookup.py`, `protocol/builders.py`, `POST /validate`. |
| In scope: positive and negative test generation; expected-response validation | met | Capabilities 4 and 5. |
| In scope: export to Python, CANoe, CAPL, or approved frameworks | partial | pytest (python-can + udsoncan virtual bus) met; CAPL unverified; no other framework. |
| Out of scope: execution against production vehicles without controls | respected | Simulator and virtual CAN only; guard and banners. |
| Out of scope: use of unauthorized standards content | respected | See the licensing row above. |
| Out of scope: unreviewed automatic acceptance of ECU behavior | respected | Expected values come from the rules engine, never from observing an ECU; review gate. |
| Input: authorized UDS, OEM, ECU specifications | partial | Synthetic stand-ins (see workflow steps 1 and 2). |
| Input: requirements | met | Plain-English requirements; 15 seed and 16 blind natural ones. |
| Input: **existing tests** | partial | `importer/`, `POST /import`, Import & Compare tab, [IMPORT_FORMAT.md](IMPORT_FORMAT.md): a documented YAML format; every test is checked with the `TestCase` schema and the rules engine (`accepted` / `oracle_mismatch` / `invalid`), stored as `origin: imported` with provenance (file, SHA-256, id), status `validated` (never auto-approved), same review gate and audit trail. Evidence: `tests/` (33 tests), RESULTS section 9. Caveat: the fixtures are synthetic and written for this project; no real team's suite was imported; only single-ECU request/response tests. |
| Input: **automation templates** | partial | A test may name the user's own template (`template:`); it is stored as provenance and shown in the UI but not interpreted, and no CAPL / vTESTstudio / other tool format is read. The tool's own pytest / CAPL export is the only automation template it produces. |

## G. Not done, stated plainly

- Ingesting real specification documents (PDF, ODX, CDD) and extracting rules from them; the spec is hand-structured YAML.
- Reading existing tests in other formats (CAPL, vTESTstudio, Excel) or interpreting a user's automation templates; the YAML import covers tests only, and its fixtures are synthetic (no real team's suite was imported).
- Project isolation, authentication and role-based access (the common architecture lists them; this pilot has no login by design).
- Graph / traceability store (Neo4j); traceability here is requirement ids and citations in the SQLite audit trail.
- A real ECU, HIL rig, CANoe, multiple ECUs; CAPL compiled or run in CANoe; reading real ECU responses for comparison.
- The manual test-design-time baseline; confirmation of defects on a real ECU; validation of the confidence thresholds.
- Docker: the single-container build and run were tested with the host's Ollama and GPU; the all-in-one stack that also runs Ollama in a container was not run to completion (see `outputs/END_TO_END_CHECK.md`).
- A real-browser click-through by a person (the web UI was driven in headless Edge, the Streamlit UI through `AppTest`).

## H. Interface note

The case study names Streamlit as the reference interface and allows a Flask web UI. This repository now serves a plain
HTML / JavaScript front end from FastAPI (`uds_assistant/web/`, no build step, no CDN) and keeps the earlier Streamlit app
(`uds_assistant/ui/streamlit_app.py`) working.
