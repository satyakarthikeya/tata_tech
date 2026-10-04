# UDS Diagnostics & Automated Test Generation Assistant

A local, offline-capable assistant that turns a plain-English UDS (Unified
Diagnostic Services, ISO 14229-style) requirement into validated, executable
test cases, runs them against an independent ECU simulator with injectable
bugs, answers cited diagnostic questions, and reports how many bugs the
generated suite catches.

**The ECU spec is synthetic.** `data/bcm_spec.yaml` describes a fictional Body
Control Module, hand-authored as structured data in an OEM-spec style (not
extracted from a PDF; no public OEM spec exists). The OEM guideline
`data/oem_diagnostic_guidelines.md` is synthetic too. No ISO 14229 text is
copied anywhere. See `DECISIONS.md` for every design choice and `AGENT.md` for
the working rules.

**Core principle:** the LLM handles language (parsing the requirement, choosing
templates, phrasing explanations and answers); it never produces a byte that
reaches a test. Every byte, NRC and timing value comes from the deterministic
rules engine (the oracle) and the test templates. The system therefore works
with a 3B local model and fully without a model in **mock mode** (the default).

## Status (Part E, final)

One headline per area. All numbers come from `docs/RESULTS.md`, which states
the run (date and git hash) behind each section; the honest summary is
[`FINAL_REPORT.md`](FINAL_REPORT.md).

| Area | Headline | Run |
|---|---|---|
| Correctness (LLM-independent) | simulator vs rules engine 5000/5000; gold 60/60 on the clean simulator; udsoncan virtual-CAN sequence PASS (one happy path) | Main eval 2026-10-04, `1f0c293` |
| Bug detection (fresh v3, 15 bugs) | full output (generated + conformance sweep) **10/15 mock, 9/15 ollama**; requirement-driven tests alone 4/15 and 2/15; the sweep alone 9/15 | Main eval 2026-10-04, `1f0c293` |
| Requirement understanding (natural v3, n=16) | ollama better than mock: parsed F1 0.609 vs 0.407, category recall 70.0% vs 42.0%; ollama precision only 0.596 (19 false positives) | Main eval 2026-10-04, `1f0c293` |
| Cited Q&A (25 blind questions) | answer accuracy 90.5% (19/21) in both modes; correct not-found 3/4; known misses QA-018, QA-022, QA-023 | Q&A run 2026-10-04, `9e66f7a` |
| UI | five-tab Streamlit UI, headless-tested; never clicked through in a real browser | E4 |

Not done or not measured: Docker is **written, not built here**; the manual
vs tool test-design-time comparison is **pending owner measurement**; CAPL
exports never ran in CANoe; no real ECU; one small model; samples are small
(15 bugs, 16 requirements, 25 questions). The natural door-lock requirement did
not yield the intended test pair (FINAL_REPORT, Known limitations).
[`docs/CASE_STUDY_COMPLIANCE.md`](docs/CASE_STUDY_COMPLIANCE.md) maps every
case-study item to done / partial / out of scope with evidence.

## Quick start (local)

```bash
python -m pip install -e ".[ui]"      # pure-Python deps + Streamlit; no model, no GPU
python scripts/demo.py                # about 2 s, mock, offline terminal tour
streamlit run uds_assistant/ui/streamlit_app.py   # the UI
python -m uds_assistant.api           # FastAPI on http://localhost:8000 (docs at /docs)
```

Python 3.13 was used to build and test (code stays 3.11-syntax-compatible).
Dependencies are in `pyproject.toml`; `uvicorn` is needed by the API. A real
local LLM (Ollama) and semantic retrieval (Chroma + fastembed) are optional;
step-by-step in [`MODEL_SETUP.md`](MODEL_SETUP.md).

## Quick start (Docker)

Written, **not built or run in this environment** (limited network), so treat
it as untested. Two services: `app` (FastAPI on 8000 and Streamlit on 8501,
started by `docker/entrypoint.sh`) and `ollama` (the official image, port 11434).

```bash
docker compose up -d --build
docker compose exec ollama ollama pull qwen2.5:3b-instruct-q4_K_M
```

- UI http://localhost:8501; API http://localhost:8000 (`/docs`, `/health`).
- Default `LLM_MODE=mock` needs no model. After the pull: `LLM_MODE=ollama docker compose up -d`
  (or put it in a `.env` file). The app reaches Ollama at `http://ollama:11434`
  and falls back to the mock with a warning if it is unreachable.
- `RETRIEVER=chroma` works in the image (chromadb and fastembed installed; the
  embedding model downloads on first use and needs network access).
- `outputs/` is a volume (`app_outputs`), models are in `ollama_data`. The image
  does not copy the committed `outputs/` reports, so the Results tab shows
  "no report" until `run_eval` is run inside the container.
- NVIDIA GPU: install the NVIDIA Container Toolkit, then uncomment the
  `deploy.resources.reservations.devices` block under `ollama` in
  `docker-compose.yml`. CPU works but is slow.

## The UI (five tabs)

`streamlit run uds_assistant/ui/streamlit_app.py`. The sidebar selects the LLM
mode and retriever (an unavailable Ollama or Chroma is removed and the radio
disabled, with the reason) and shows the governance banner once ("Synthetic ECU
spec. Human review required before any real-hardware execution.").

| Tab | What it does |
|---|---|
| **Ask** | question box, answer, confidence badge (high / medium / low plus reason), expandable citations (layer, source, quote); "not found in the approved sources" when the evidence does not support an answer |
| **Generate & Review** | empty requirement box with a "load example" dropdown (4 examples incl. a natural-language door-lock one); results table (id, category, confidence, review status); selecting a test shows decoded steps (hex request to expected response with a readable line, for example `2E 20 01 01 -> 7F 2E 33 (securityAccessDenied)`), citations, explanation, and which targets were written in the text vs inferred; approve / reject / comment stored in the audit DB |
| **Run on Simulator** | pick a bug (in-sample, held-out v1, v2, v3) or none; run selected or approved tests; pass/fail table with the first failing step decoded; "Bug caught by N tests" or "Bug not caught" |
| **Export** | download the pytest file and the CAPL template (labelled unverified) |
| **Results** | six headline cards from `outputs/eval_report.json`, each with run date and git hash; noise checks, freeze hashes, per-requirement tables and history are in collapsed expanders; degrades gracefully without a report |

Logic lives in `uds_assistant/ui/` modules; `streamlit_app.py` only wires the
tabs. Headless-tested with AppTest (`tests/ui`); manual click-through:
[`docs/UI_CHECKLIST.md`](docs/UI_CHECKLIST.md); 7-minute demo path:
[`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md). The UI calls the pipeline directly
(no HTTP) and keeps its own audit DB (`outputs/ui_audit.sqlite`).

## API

```bash
python -m uds_assistant.api       # --host, --port, --reload also accepted
```

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness/config check |
| GET | `/spec` | the loaded ECU spec summary |
| POST | `/generate` | run the agent pipeline on a requirement; tests carry `confidence` and `confidence_reason`, plus written/inferred target provenance |
| POST | `/ask` | cited diagnostic Q&A: body `{question, mode?}`; returns `{answer, citations[{chunk_id, layer, source, quote}], confidence, confidence_reason, status (answered / not_found), fallback_events, llm_mode}` |
| POST | `/run` | execute tests (by `run_id` or inline) on the simulator |
| POST | `/eval` | run the evaluation pipeline (temp dir by default, not `outputs/`) |
| POST | `/export` | render pytest/udsoncan or CAPL exports |
| GET | `/bugs` | the injectable bug catalog |
| GET | `/runs` | audit trail of past runs |
| POST | `/tests/{run_id}/{test_id}/review` | mark a generated test reviewed (needs `run_id` and `test_id`; `DECISIONS.md` `[API-REVIEW-PATH]`) |

Q&A answers come only from retrieved chunks and spec lookups. Deterministic
facts (session, security level, length, read/write access of a DID or routine,
NRC meanings, timing) are looked up from the parsed spec and the LLM only
phrases them; its phrasing is verified and replaced by the template answer if
a value is missing or invented. Unknown entities and weak evidence give
`not_found` rather than a guess.

## Runtime switches

Environment variables (`uds_assistant/config.py`, `llm/client.py`, `rag/`):

| Variable | Values | Default | Effect |
|---|---|---|---|
| `LLM_MODE` | `mock`, `ollama` | `mock` | `mock` = deterministic stand-in, no network. `ollama` = local Qwen2.5-3B; falls back to `mock` with a warning if unreachable. |
| `RETRIEVER` | `bm25`, `chroma` | `bm25` | `chroma` = ChromaDB + `BAAI/bge-small-en-v1.5`; falls back to `bm25` if the packages are missing. Store: `outputs/chroma` (git-ignored). |
| `EMBEDDER` | `fastembed`, `sentence-transformers` | `fastembed` | Backend for `RETRIEVER=chroma`; `sentence-transformers` was never run here. |
| `OLLAMA_HOST` | URL | `http://localhost:11434` | Ollama server. |
| `OLLAMA_MODEL` | tag | `qwen2.5:3b-instruct-q4_K_M` | Model in ollama mode. |
| `OLLAMA_NUM_CTX` | integer | `4096` | Context window (fits a 4 GB GPU; the evaluated setting). |
| `OLLAMA_KEEP_ALIVE` | duration | `10m` | How long Ollama keeps the model loaded. |
| `UDS_EVAL_REPORT`, `UDS_UI_AUDIT_DB` | paths | repo defaults | Point the UI at another report or audit DB (used by tests). |

An invalid value for `LLM_MODE`, `RETRIEVER` or `EMBEDDER` falls back to its
default with a warning. Examples: `LLM_MODE=ollama streamlit run uds_assistant/ui/streamlit_app.py`,
`RETRIEVER=chroma python -m uds_assistant.api`.

## Running the tests, eval and timing

```bash
python -m ruff check .
python -m pytest -q                                     # full suite, about 15 minutes
RUN_MODEL_TESTS=1 python -m pytest -m needs_model -q    # needs Ollama + model (PowerShell: $env:RUN_MODEL_TESTS = "1"; ...)
python -m uds_assistant.eval.run_eval --mode mock       # fast, offline report
python -m uds_assistant.eval.run_eval --mode ollama --noise-runs 3 --before-after   # about 39 minutes, uses the GPU; also runs mock
python -m uds_assistant.eval.qa_eval --modes mock,ollama                            # blind Q&A eval (data/qa_eval.csv)
python scripts/time_generation.py --modes mock,ollama --repeats 3                   # tool-side generation time
```

Test counts and the run they come from are in `FINAL_REPORT.md` ("Test
counts"). The `needs_model` tests are skipped unless `RUN_MODEL_TESTS=1`.
`run_eval` writes `outputs/eval_report.{json,md}` (every section labelled with
its run; Part C/D before/after tables only under History); `--rerender`
rebuilds the report from stored JSON without recomputing; `--skip-can` skips
the virtual-CAN check; it exits with code 2 if any generated test fails the
byte-provenance check. Test-design-time protocol:
[`docs/TEST_DESIGN_TIME.md`](docs/TEST_DESIGN_TIME.md).

## Exports

- **Python / pytest / udsoncan** (`export/pytest_export.py`): one test per
  `TestCase`; runs in-process, or on a virtual-CAN ISO-TP bus with
  `UDS_EXPORT_TRANSPORT=can` (tests with a time-advance step are skipped there).
- **CAPL** (`export/capl_export.py`): labelled `UNVERIFIED TEMPLATE`, never
  compiled or run in CANoe (no license).

## Architecture

```
 Requirement (plain English) + ECU spec (data/bcm_spec.yaml, synthetic)
        |
        v
 +--------------------- agent/ pipeline (LLM = language only) -------------------+
 | parse -> retrieve -> plan -> instantiate -> validate -> explain -> annotate    |
 | (LLM)    (rag/,      (LLM)   (testgen/      (schema, byte   (LLM)   (confidence|
 |          core layers          templates;     provenance,             + written/ |
 |          only)                rules engine   oracle, cites)          inferred)  |
 +--------------------------------------------------------------------------------+
        |                                           ^ rag/ layers: standard | ecu | project
        v
 TestCase objects (bytes from templates + rules engine, citations, confidence)
        |
   +----+-----------------------+----------------------------+
   v                            v                            v
 runner/ -> simulator/      eval/ metrics, report        export/ pytest, CAPL
 (clean + one bug at        (outputs/eval_report.*,      store/ SQLite audit trail
  a time; never imports      run provenance)
  rules/)

 Question --> qa/ : spec lookup (deterministic) + rag/ search_layers over
              standard | OEM | ECU | project --> verified phrasing --> cited answer
              or not_found, with confidence        (POST /ask, UI Ask tab)

 api/ FastAPI (/generate /ask /run /eval /export ...)   ui/ Streamlit (5 tabs)
 docker/ + Dockerfile + docker-compose.yml (app + ollama; written, not built)
```

Triangulation (does the oracle deserve trust?): the rules engine and the
simulator are two independently written implementations (the simulator never
imports `uds_assistant.rules`, enforced by `tests/simulator/test_independence.py`)
that must agree on randomized requests; 60 hand-authored gold tests must pass on
the clean simulator; request bytes are cross-checked against `udsoncan`, which
also drives a full session over a virtual CAN bus. These share one author and one
contract, so a shared misreading is invisible; see `FINAL_REPORT.md`. Full diagram:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Repository layout

```
uds_assistant/
  protocol/   SIDs, NRC table, codec, seed/key math, request builders
  spec/       Pydantic ECU-spec schema + loader (data/bcm_spec.yaml)
  rules/      The oracle; rules/nrc_order.py = the single NRC-order function
  simulator/  Independent ECU (does not import rules/), bug catalog, in-process + virtual-CAN transports
  testgen/    TestCase model, 27 templates, conformance sweep (1200 tests), gold execution
  rag/        BM25 + Chroma/fastembed retrieval; four layers (standard/oem/ecu/project), layer-tagged citations
  llm/        mock (deterministic) and ollama (Qwen2.5-3B); all prompts in llm/prompts.py
  agent/      pipeline (LangGraph + plain fallback), grounding, confidence rules, annotate
  qa/         cited diagnostic Q&A (lookup, answer, confidence, models)
  runner/     runs suites on the simulator, pass/fail + timing
  eval/       metrics, report, blind Q&A scorer, run provenance, freeze check
  export/     pytest/udsoncan and CAPL exporters
  store/      SQLite audit trail
  api/        FastAPI service
  ui/         Streamlit tabs + split logic modules
data/         spec, requirements (seed, natural v1-v3), gold tests, bug catalogs, qa_eval.csv, OEM guideline, sources/
docs/         ARCHITECTURE, CODE_TOUR, RESULTS, CASE_STUDY_COMPLIANCE, DOCKER, TEST_DESIGN_TIME, UI_CHECKLIST, DEMO_SCRIPT, ...
scripts/      demo.py, time_generation.py, gen_gold.py, tune_dev.py, ollama_smoke.py
docker/       entrypoint.sh (plus Dockerfile and docker-compose.yml at the root)
outputs/      eval_report.{json,md}, qa/, timing/, partC/, partD/
tests/        mirrors uds_assistant/ package-for-package
```

## Governance

- Every non-obvious design choice and deviation is logged in `DECISIONS.md`, one tagged line each.
- Each check in `rules/nrc_order.py` cites a `DECISIONS.md` tag or an AUTOSAR CP R24-11 Dcm SWS ID (38 distinct IDs verified against a local PDF that is git-ignored; those tests skip without it). 9 disagreements with the SWS are listed in `docs/SWS_DISAGREEMENTS.md`: D2, D5, D6, D7 fixed, D1, D3, D4, D8, D9 open.
- Standard, OEM, ECU and project knowledge live in separate retrieval layers; the generator uses only the standard, ECU and project layers (`DECISIONS.md` E33-NO-OEM-IN-GEN), Q&A uses all four.
- Generated tests need human review before any real-hardware execution; the UI says so and records review decisions in the audit DB.
- Everything runs locally; no data leaves the machine.

## Further reading

- [`PROJECT.md`](PROJECT.md) (what and why, final status), [`SCOPE.md`](SCOPE.md), [`AGENT.md`](AGENT.md)
- [`FINAL_REPORT.md`](FINAL_REPORT.md): honest done / partial / not done, Part D completion, Part E changes, test counts
- [`docs/RESULTS.md`](docs/RESULTS.md): one-page results; [`outputs/eval_report.md`](outputs/eval_report.md): full report
- [`docs/CASE_STUDY_COMPLIANCE.md`](docs/CASE_STUDY_COMPLIANCE.md): case-study item to evidence matrix
- [`docs/CODE_TOUR.md`](docs/CODE_TOUR.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/DOCKER.md`](docs/DOCKER.md)
- [`docs/TEST_DESIGN_TIME.md`](docs/TEST_DESIGN_TIME.md), [`docs/UI_CHECKLIST.md`](docs/UI_CHECKLIST.md), [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)
- [`PROGRESS.md`](PROGRESS.md) (phase log), [`DECISIONS.md`](DECISIONS.md), [`MODEL_SETUP.md`](MODEL_SETUP.md)
- Historical: [`outputs/partC/`](outputs/partC/), [`outputs/partD/before_after.md`](outputs/partD/before_after.md), [`outputs/partD/interpretation.md`](outputs/partD/interpretation.md), [`docs/SWS_DISAGREEMENTS.md`](docs/SWS_DISAGREEMENTS.md)
