# UDS Diagnostics & Test Generation Assistant

A local assistant for Case Study 5: it turns a plain-English UDS (ISO 14229-style) requirement
into validated, cited test cases, runs them on an ECU simulator with injectable bugs, exports
them (pytest / CAPL), and answers cited diagnostic questions. Everything runs on your machine.

**The ECU spec is synthetic** (`data/bcm_spec.yaml`, a fictional Body Control Module). Core
rule: the LLM handles language only (parse the requirement, choose templates, phrase text); it
never produces a byte. Every byte, NRC and timing value comes from the deterministic rules engine.

## Before you run

1. Python 3.11+ and `python -m pip install -e ".[ui]"`.
2. [Ollama](https://ollama.com) running, with the model pulled (**required, there is no offline fallback**):
   `ollama pull qwen2.5:3b-instruct-q4_K_M`. Without Ollama the API answers HTTP 503 and the UI
   shows "Start Ollama and pull qwen2.5:3b-instruct-q4_K_M". Details: [MODEL_SETUP.md](MODEL_SETUP.md).
3. The first run downloads the BGE embedding model (`BAAI/bge-small-en-v1.5`, via fastembed).

## Run

```bash
streamlit run uds_assistant/ui/streamlit_app.py     # the UI (http://localhost:8501)
python -m uds_assistant.api                         # the API (http://localhost:8000/docs)
python -m uds_assistant.eval.run_eval               # evaluation -> outputs/eval_report.md
python scripts/demo.py                              # terminal demo: requirement -> tests -> bug caught -> export
```

## The four tabs

| Tab | What it does |
|---|---|
| **Ask** | question -> cited answer with a confidence badge; "not found" when the sources do not support an answer |
| **Generate & Review** | requirement -> tests table -> decoded steps, citations, approve / reject / comment (stored in the audit DB) |
| **Run & Export** | pick a bug (or none) -> run on the simulator -> pass/fail ("Bug caught by N tests") -> download pytest / CAPL |
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
`qa/`, `runner/`, `export/`, `store/` (SQLite audit), `api/`, `ui/`, `eval/`. Tour:
[docs/CODE_TOUR.md](docs/CODE_TOUR.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Settings (all optional environment variables): `OLLAMA_HOST` (default `http://localhost:11434`),
`OLLAMA_MODEL`, `OLLAMA_NUM_CTX` (4096), `OLLAMA_KEEP_ALIVE`, `FASTEMBED_CACHE_PATH`.
Docker (`Dockerfile`, `docker-compose.yml`: app + ollama) is written but was not built here.

## Results and limitations

[docs/RESULTS.md](docs/RESULTS.md) is the one-page evaluation (also `outputs/eval_report.md`),
mapped to the case-study success metrics in [docs/CASE_STUDY_COMPLIANCE.md](docs/CASE_STUDY_COMPLIANCE.md).

- The spec is synthetic and there is no real ECU; one small local model; small samples
  (15 blind bugs, 16 blind requirements, 25 blind questions).
- CAPL export is an unverified template, never compiled or run in CANoe.
- The manual-time comparison for test design time is left for the owner to fill.
- Generated tests need human review before any real-hardware use.

*Full development history and test suite: git tag `v1-full-archive`.*
