# UDS Diagnostics & Test Generation Assistant

A local assistant for Case Study 5: it turns a plain-English UDS (ISO 14229-style) requirement
into validated, cited test cases, runs them on an ECU simulator with injectable bugs, exports
them (pytest / CAPL), and answers cited diagnostic questions. Everything runs on your machine.

**The ECU spec is synthetic** (`data/bcm_spec.yaml`, a fictional Body Control Module). Core
rule: the LLM handles language only (parse the requirement, choose templates, phrase text); it
never produces a byte. Every byte, NRC and timing value comes from the deterministic rules engine.

## Before you run

1. Python 3.11+ and `python -m pip install -e ".[ui,export,dev]"` (`ui` = Streamlit, `export` = pytest, needed to run the exported test file, `dev` = pytest, httpx and ruff for the repository's own tests).
2. [Ollama](https://ollama.com) running, with the model pulled (**required, there is no offline fallback**):
   `ollama pull qwen2.5:3b-instruct-q4_K_M`. Without Ollama the API answers HTTP 503 and the UI
   shows "Start Ollama and pull qwen2.5:3b-instruct-q4_K_M". Details: [MODEL_SETUP.md](MODEL_SETUP.md).
3. The first run downloads the BGE embedding model (`BAAI/bge-small-en-v1.5`, via fastembed).

## Test

```bash
python -m pip install -e ".[ui,export,dev]"
python -m pytest            # the import / comparison tests: no Ollama, no model download, about 30 s
```

The suite in `tests/` covers the import feature (format, rules-engine validation, review gate, audit trail,
API, coverage comparison). The earlier, larger suite is in git tag `v1-full-archive`.

## Run

```bash
python -m uds_assistant.api                         # web UI + API: http://localhost:8000 (API docs at /docs)
python -m uds_assistant.eval.run_eval               # evaluation -> outputs/eval_report.md
python scripts/demo.py                              # terminal demo: requirement -> tests -> bug caught -> export
streamlit run uds_assistant/ui/streamlit_app.py     # the earlier Streamlit UI (still works)
```

**Docker (recommended for a demo).** Needs Docker Desktop (or Docker with the NVIDIA Container Toolkit for the GPU).

```bash
# Ollama already on this machine (uses your GPU): one container for the app
docker compose -f docker-compose.host-ollama.yml up --build      # http://localhost:8000
# Everything in containers, Ollama on the NVIDIA GPU (first start pulls about 2 GB of model)
docker compose up --build                                        # http://localhost:8000
```

The BGE embedding model is baked into the image; the app needs no internet at run time. The web UI is plain HTML and
JavaScript served by FastAPI (`uds_assistant/web/`, no build step).

## The tabs (web UI: Ask, Generate & Review, Run & Export; the Streamlit UI also has Results)

| Tab | What it does |
|---|---|
| **Ask** | question -> cited answer with a confidence badge; "not found" when the sources do not support an answer. Also a **Check a raw request** box: hex request + session + security state (+ optionally an observed ECU response to compare) -> decoded, structurally valid or not, expected bytes or NRC with the reason, match / mismatch, citations (`POST /validate`) |
| **Generate & Review** | requirement -> tests table -> preconditions, pass criteria, decoded steps, citations, approve / reject / comment / bulk approve (stored in the audit DB) |
| **Import & Compare** | upload a YAML file of existing UDS tests (`data/imports/` has synthetic examples) -> each test checked against the rules engine -> accepted / rules-engine mismatch / invalid table with reasons -> review the accepted ones on Generate & Review -> baseline coverage vs generated vs combined, newly covered items, Markdown download (`POST /import`, `POST /import/{id}/compare`). Format: [docs/IMPORT_FORMAT.md](docs/IMPORT_FORMAT.md). Web UI only (not in the Streamlit app) |
| **Run & Export** | approved tests only (a demo-only override exists, OFF by default) -> pick a bug (or none) -> run on the simulator -> pass/fail ("Bug caught by N tests") -> coverage table against the spec (uncovered items highlighted, Markdown download, `POST /coverage`) -> download pytest / CAPL |
| **Results** | the eight evaluation sections as cards from `outputs/eval_report.json` |

The sidebar shows the Ollama status (green / red) and the banner "Synthetic ECU spec — human
review required before real-hardware use."

## Architecture

```
specs (ECU spec, UDS notes, OEM guideline, requirements)
   -> ingest -> ChromaDB + BGE embeddings: 4 collections (standard / OEM / ECU / project)
requirement -> retrieve evidence -> LLM (Ollama): parse + plan tests (names, template ids only)
   -> rules engine validates and builds the exact request/response bytes
   -> structured TestCase (preconditions, steps, pass/fail, citations, confidence)
   -> engineer review -> export (pytest / CAPL) -> run on the ECU simulator -> report
question -> spec lookup + retrieval over the 4 collections -> verified phrasing -> cited answer
```

Retrieval layers: the four layers are four physical ChromaDB collections (`standard`, `oem`, `ecu`,
`project`; `rag/chroma.py`). **Test generation does not search OEM** (it reads standard, ECU and project
only); **Q&A searches all four.** Reason: OEM policy text must not silently change protocol-derived expected bytes.

Code layout: `protocol/` (SIDs, codec), `spec/`, `rules/` (the oracle), `simulator/` (independent
ECU + bugs), `testgen/` (templates, conformance sweep), `rag/`, `llm/`, `agent/` (pipeline),
`qa/`, `runner/`, `export/`, `importer/` (existing-test import), `store/` (SQLite audit), `api/`, `ui/`, `eval/`. Tour:
[docs/CODE_TOUR.md](docs/CODE_TOUR.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Settings (all optional environment variables): `OLLAMA_HOST` (default `http://localhost:11434`),
`OLLAMA_MODEL`, `OLLAMA_NUM_CTX` (4096), `OLLAMA_KEEP_ALIVE`, `FASTEMBED_CACHE_PATH`.
Docker: the single-container build and run were tested with the host's Ollama; the all-in-one compose with Ollama in a container is written but was not run to completion (see `outputs/END_TO_END_CHECK.md`).

## Importing existing tests

Teams usually already have tests. `POST /import` (or the **Import & Compare** tab) takes a small YAML file
([format](docs/IMPORT_FORMAT.md)), parses it strictly, and checks every test's expected bytes against the rules
engine; the file is never rewritten and no model is involved. Outcomes per test: `accepted`, `oracle_mismatch`
(your expected bytes disagree with the spec's rules, with both values shown) or `invalid`. Accepted tests are stored
with `origin: imported`, a provenance record (suite, file, SHA-256, your id and template name) and status
`validated`, **never approved**: a person approves them on Generate & Review, and only then can run or export use
them (same gate, same audit trail, same simulator-only export). The comparison report shows the imported suite's
baseline coverage (services, DIDs, routines, NRCs, sessions, security levels, timing cases), the generated suite's, the
union, and the items the generated tests newly cover. Fixtures are synthetic (`data/imports/`).

```bash
curl -s localhost:8000/import -H "Content-Type: application/json" \
  -d "$(python -c "import json;print(json.dumps({'filename':'legacy.yaml','content':open('data/imports/legacy_bcm_regression.yaml',encoding='utf-8').read()}))")"
curl -s -X POST localhost:8000/import/1/compare -H "Content-Type: application/json" -d "{}"   # JSON + Markdown
curl -s localhost:8000/import/1/compare.md -o import_coverage.md                              # download
```

## Responsible AI

- **The model never writes bytes.** The LLM parses, picks template ids and phrases prose; its schemas have no
  byte fields. Every request byte, response byte, NRC and timing value comes from the deterministic rules engine
  (`rules/`); the `validate` node checks byte provenance, re-checks each kept test against the oracle and checks citations.
- **Rules engine plus validator.** Each planned test is instantiated from an approved template, then re-validated
  against the rules engine (a test that does not validate is dropped); the runner replays tests on a separate
  simulator written independently of the rules engine.
- **Imported tests keep their provenance.** `origin: imported` is never rewritten to `generated`; imported tests are
  validated against the rules engine, enter as `validated` (never approved) and go through the same review gate and
  audit trail. Tests whose expected bytes disagree with the rules engine are reported, not stored as runnable.
- **Review gate.** Run and export use human-approved tests only (UI and API). Approving, rejecting and bulk
  approving are written to the audit trail. The "Include unreviewed tests (demo only)" override is OFF by default;
  `scripts/demo.py` and the evaluation use it explicitly.
- **Separate collections.** Standard, OEM, ECU and project knowledge live in four physical ChromaDB collections;
  every citation carries its layer. Test generation does not search OEM; Q&A searches all four.
- **Simulator only.** Exported pytest and CAPL carry the banner "FOR SIMULATOR OR APPROVED LAB BENCH ONLY. NEVER RUN
  AGAINST A PRODUCTION VEHICLE."; the pytest file refuses to run unless the CAN interface is `virtual` (or
  `UDS_ALLOW_LAB_BENCH=1`). The CAPL file is an unverified template.
- **Local only.** Ollama and ChromaDB run on your machine; the sidebar turns red if `OLLAMA_HOST` is not localhost,
  because data would then leave this machine.
- **Citations and refusal.** Answers and tests carry citations that are checked against real chunks (and quotes
  against chunk text); when the sources do not support an answer the app says "not found" instead of guessing.
- **Known limits.** The ECU spec is synthetic and there is no real ECU; one small local model; the oracle and the
  simulator were written by the same author from the same contract; small blind samples; confidence thresholds are
  not validated against correctness; a reviewer can approve everything in bulk; CAPL, Docker and a real-browser
  click-through were not verified (see `outputs/END_TO_END_CHECK.md`).

## Packaging

When zipping the project for hand-over, exclude `.venv`, `.hypothesis`, `outputs/chroma` and `*.sqlite`
(local environment, caches and audit databases; the Chroma index is rebuilt on first start).

## Results and limitations

[docs/RESULTS.md](docs/RESULTS.md) is the one-page evaluation (also `outputs/eval_report.md`),
mapped to the case-study success metrics in [docs/CASE_STUDY_COMPLIANCE.md](docs/CASE_STUDY_COMPLIANCE.md).

- The spec is synthetic and there is no real ECU; one small local model; small samples
  (15 blind bugs, 16 blind requirements, 25 blind questions).
- CAPL export is an unverified template, never compiled or run in CANoe.
- Imports: only YAML in the documented format, single ECU; the fixtures are synthetic, no real team's suite was
  imported; "automation template" names are recorded as provenance, not interpreted.
- The manual-time comparison for test design time is left for the owner to fill.
- Generated tests need human review before any real-hardware use.

*Full development history and test suite: git tag `v1-full-archive`.*
