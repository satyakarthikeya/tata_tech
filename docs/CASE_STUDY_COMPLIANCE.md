# Case Study 5 compliance matrix

Every case-study item, its status in this repository, and where the evidence is. Numbers are not copied here:
they live in [RESULTS.md](RESULTS.md) (the evaluation of the run it names), so this file cannot drift from them.

**Source of the item list.** The case-study PDF is not in the repository; the items are this project's own reading of
it (the pipeline and the success metrics in particular), so check them against the PDF.

**Status.** *done* = built and run, with the stated evidence (it may carry a caveat). *partial* = built, but measured
by a proxy, only on synthetic data, unverified outside the repository, or with a known gap. *out of scope* = not built.

## 1. Pipeline

| Step | Status | Evidence and honest note |
|---|---|---|
| Ingest specs (standard, OEM, ECU, project) into ChromaDB + BGE embeddings | partial | `uds_assistant/rag/ingest.py`, `chroma.py`; four collections. The ECU spec and OEM guideline are **synthetic** hand-authored data; PDF/ODX extraction is out of scope (real OEM specs are confidential). |
| Retrieve evidence with citations | done | `rag/layers.py`, `rag/citations.py`; every citation is checked against a real chunk (RESULTS section 2). Existence is checked, not that the text justifies the test. |
| LLM (Ollama) parses the requirement and plans tests | done | `agent/nodes.py` (`parse`, `plan`), `llm/`; model `qwen2.5:3b-instruct-q4_K_M`. One small model; precision of target identification is the weak point (RESULTS section 6). |
| Rules engine validates and builds the exact bytes | done | `rules/` (one NRC-order function, each check cited), `testgen/templates*.py`, `agent/nodes.py` (`validate`). The LLM schemas have no byte fields. |
| Structured test case with preconditions, steps, pass/fail, citations | done | `testgen/model.py`; confidence with a reason on every generated test (`agent/confidence.py`). |
| Engineer review | partial | Approve / reject / comment in the Generate & Review tab, stored in the SQLite audit trail (`ui/state.py`, `store/audit.py`). Review is recorded and displayed but not technically enforced. |
| Export to Python (pytest) and CAPL | partial | `export/pytest_export.py`: the exported file was run (pass count in `outputs/END_TO_END_CHECK.md`). `export/capl_export.py` is an **unverified template**, never compiled or run in CANoe. |
| Run on an ECU simulator and report | done | `simulator/` (independent of `rules/`, 68 injectable bug hooks), `runner/suite.py`, Run & Export tab. Simulator only: no real ECU, HIL rig or CANoe. |
| Cited diagnostic Q&A | done | `qa/`, `POST /ask`, Ask tab; refuses with "not found" when the sources do not support an answer (RESULTS section 7). |

## 2. Success metrics of the case study (RESULTS sections 2 to 8)

| Metric | Status | Evidence and honest note |
|---|---|---|
| Generation accuracy | partial | Section 2: well-formed requests and clean-pass rate. Both are 100% largely **by construction** (the bytes come from the oracle); the independent evidence is section 1 (simulator vs rules engine, gold tests, udsoncan). Same author and contract for engine, simulator and gold. |
| Coverage | partial | Section 3: tests per type and requirements covered. Oracle-observable coverage only, not code coverage. |
| Reuse rate | partial | Section 4: share of tests built from the 27 approved templates; **100% by construction**, so it shows catalog breadth, not saved effort. |
| Defect detection | done | Section 5 on the blind v3 bug set (15 bugs written without seeing templates or code, never tuned on): generated tests alone, the conformance sweep alone and both; missed bugs are listed. Small set, synthetic simulator. |
| Requirement understanding | done | Section 6 on 16 blind natural requirements: target F1, category recall, precondition recall. Small sample (one item moves a score by several points). |
| Q&A quality | done | Section 7 on 25 blind questions: answer accuracy, citation correctness, correct "not found". |
| Test design time | partial | Section 8: tool time per requirement is measured; the **manual-time comparison is left for the owner** ([TEST_DESIGN_TIME.md](TEST_DESIGN_TIME.md)). Review time is not included. |

## 3. Objectives, risks and governance

| Item | Status | Evidence and honest note |
|---|---|---|
| Cut the effort of writing diagnostic tests | partial | Generation works end to end (`scripts/demo.py`); the effort saving itself is unmeasured until the manual time is filled in. |
| Better coverage, especially negative and edge cases | partial | Negative, session, security and timing tests plus the 1200-test conformance sweep; gaps remain (missed bugs in section 5). |
| Runs locally, no data leaves the machine | done | Ollama and ChromaDB run locally; no cloud API anywhere. Ollama is **required** (no offline stand-in). |
| LLM hallucination producing wrong test bytes | done | The LLM never produces bytes; byte provenance is checked on every test ([ARCHITECTURE.md](ARCHITECTURE.md)). This shows provenance, not that the oracle is right. |
| Wrong expected results from a wrong oracle | partial | Triangulation (section 1 of RESULTS); five known AUTOSAR SWS disagreements are documented in the archive tag and in `rules/nrc_order.py` comments. |
| Mixing standard, OEM, ECU and project knowledge | done | Four separate collections with the layer on every chunk and citation. |
| Unsafe use of generated tests on real hardware | partial | Banner, review status and "approved only" filters; no technical gate, and no hardware was used. |
| Over-trust in answers | partial | Citations, "not found" refusal and confidence badges; confidence thresholds were not validated against correctness. |
| Audit trail of runs and decisions | done | `store/audit.py` (SQLite). |
| Real ECU, CANoe, multiple ECUs, past test cases as input | out of scope | One synthetic Body Control Module; only a virtual CAN bus was used. |
| Docker packaging | partial | `Dockerfile`, `docker-compose.yml` (app + ollama): **written, not built here**. |
