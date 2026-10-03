# UDS Diagnostics & Automated Test Generation Assistant

A local, offline-capable assistant that turns a plain-English UDS (Unified
Diagnostic Services, ISO 14229-style) requirement into validated, executable
test cases, runs them against an independent ECU simulator with injectable
bugs, and reports how many real bugs the generated suite catches.

**The ECU spec is synthetic.** `data/bcm_spec.yaml` describes a fictional Body
Control Module authored from scratch for this project, in an OEM-spec style.
No real OEM document and no ISO 14229 text is copied anywhere in this repo —
see `DECISIONS.md` for every design choice and `AGENT.md` for the working
rules this project was built under.

**Status.** Part A (honest evaluation: held-out bugs, natural requirements,
SWS citations) and Part B (real-model evaluation) are both done. The local
Qwen2.5-3B model (Ollama) and Chroma retrieval (fastembed embeddings) were run
for real and compared with the deterministic mock. **Headline:** on the
held-out TEST split (n=12) the 3B model did **not** beat the mock on any
headline metric: it has higher parsed-target recall (0.880 vs 0.560) but much
lower precision (0.512 vs 0.933), held-out bug detection is 3/12 for both, and
it is about 120x slower (30.8 s vs 0.25 s mean per requirement). **Mock stays
the default.** Details: [`docs/RESULTS.md`](docs/RESULTS.md).

**Core principle:** the LLM handles language (parsing the requirement,
choosing which templates/tests apply, writing the human explanation); it never
produces a byte that reaches a test. Every byte, NRC and timing value comes
from the deterministic rules engine (the oracle) and the test templates. This
is why the system works correctly with a 3B local model, and runs completely
without any model in **mock mode**.

## Quick setup

```bash
python -m pip install -e .
# optional, for the Streamlit UI:
python -m pip install -e ".[ui]"
```

This installs the pinned pure-Python dependencies from `pyproject.toml`:
`pydantic`, `pyyaml`, `udsoncan`, `can-isotp`, `python-can`, `rank-bm25`,
`fastapi`, `httpx`, `langgraph`. Everything above works fully offline with no
model and no GPU.

The two heavier, optional features (a real local LLM via Ollama, semantic
retrieval via ChromaDB + fastembed embeddings) need extra packages and a model
download. They are documented step by step in
**[`MODEL_SETUP.md`](MODEL_SETUP.md)**; both have been run and evaluated (see
Evaluation), but neither is required for anything else in this README.

## Runtime switches

Environment variables, read by `uds_assistant/config.py` (first three) and
`uds_assistant/llm/client.py` / `uds_assistant/rag/` (the rest):

| Variable | Values | Default | Effect |
|---|---|---|---|
| `LLM_MODE` | `mock`, `ollama` | `mock` | `mock` = deterministic keyword/rule stand-in LLM, no network. `ollama` = local Qwen2.5-3B via Ollama; falls back to `mock` with a warning if unreachable (check the report's "LLM mode used" line and the fallback events). |
| `RETRIEVER` | `bm25`, `chroma` | `bm25` | `bm25` = lexical retrieval, no model. `chroma` = ChromaDB with `BAAI/bge-small-en-v1.5` embeddings; falls back to `bm25` with a warning if the packages are missing. Chroma store: `outputs/chroma` (git-ignored). |
| `EMBEDDER` | `fastembed`, `sentence-transformers` | `fastembed` | Embedding backend for `RETRIEVER=chroma`. `fastembed` runs the model as ONNX on the CPU (no torch). `sentence-transformers` is an optional path that is not installed here and was not run. Model cache: `~/.cache/uds_assistant/fastembed` (`FASTEMBED_CACHE_PATH` overrides). |
| `OLLAMA_HOST` | URL | `http://localhost:11434` | Ollama server. |
| `OLLAMA_MODEL` | model tag | `qwen2.5:3b-instruct-q4_K_M` | Model used in ollama mode. |
| `OLLAMA_NUM_CTX` | integer | `4096` | Context window sent to Ollama. 4096 fits a 4 GB GPU and is the setting that was evaluated. The prompt-budgeting and truncation detection are sized from it. |
| `OLLAMA_KEEP_ALIVE` | duration | `10m` | How long Ollama keeps the model loaded between calls. |

An invalid value for `LLM_MODE`, `RETRIEVER` or `EMBEDDER` falls back to its
default and prints a warning instead of crashing. Ollama server-side settings
for a 4 GB GPU (flash attention, q8_0 KV cache) are in `MODEL_SETUP.md` 2b.

Examples (bash; PowerShell users use `$env:NAME = "value"`):

```bash
RETRIEVER=chroma EMBEDDER=fastembed python -m uds_assistant.api   # semantic retrieval
LLM_MODE=ollama streamlit run uds_assistant/ui/streamlit_app.py   # real local model in the UI
python scripts/demo.py --llm ollama                               # demo with the real model (falls back to mock with a warning)
```

## Running the tests

```bash
python -m pytest -q
```

Current result on this machine (Python 3.13.6, Windows, default run):
**912 passed, 13 skipped in 218.26s (0:03:38)**. The skipped tests are the `needs_model` tests, skipped
automatically unless `RUN_MODEL_TESTS=1`. To run them (needs Ollama running with
the model pulled, and fastembed + chromadb installed; see `MODEL_SETUP.md`; they
use the GPU and take a few minutes):

```bash
RUN_MODEL_TESTS=1 python -m pytest -m needs_model -v      # bash
```

```powershell
$env:RUN_MODEL_TESTS = "1"; python -m pytest -m needs_model -v   # PowerShell
```

Last recorded result for that run (Part B, B4): **13 passed**.
`RUN_MODEL_TESTS=1 pytest` (everything, model tests included) also works.

Tests mirror the package layout under `tests/` (one subdirectory per package:
`protocol/`, `rules/`, `simulator/`, `testgen/`, `rag/`, `llm/`, `agent/`,
`runner/`, `eval/`, `export/`, `store/`, `api/`, `ui/`, `spec/`).

## Evaluation

```bash
python -m uds_assistant.eval.run_eval --mode mock      # fast, offline
python -m uds_assistant.eval.run_eval --mode ollama    # ~19 minutes, uses the GPU; also runs mock
```

`--mode ollama` runs the mock in the same invocation (`--no-mock-compare`
turns that off), so both columns come from the same inputs, templates and
retriever. It exits with code 2 if any generated test fails the byte-provenance
check. Regenerates `outputs/eval_report.json` and `outputs/eval_report.md`: a 7-row
headline table (simulator/rules agreement, gold on clean simulator, udsoncan
virtual-CAN sequence, **held-out bug detection**, requirement understanding,
coverage, citation validity), plus in-sample bug detection, request validity
and metric definitions. Add `--skip-can` to skip the udsoncan virtual-CAN check
(fast runs only).

**Headline (report version 2, both modes, one invocation).** On the
held-out TEST split (n=12 requirements) the local 3B model did **not** beat the
deterministic mock on any headline metric:

| Metric | mock | ollama |
|---|---|---|
| Held-out bug detection, generated (12 bugs) | 3/12 (25.0%) | 3/12 (25.0%) |
| Parsed-target precision / recall / F1 (test split) | 0.933 / 0.560 / 0.700 | 0.512 / 0.880 / 0.647 |
| Parsed exact match (test split) | 5/12 | 4/12 |
| Category recall / precondition recall (test split) | 67.9% / 80.0% | 64.3% / 73.3% |
| Planner choices rejected (35 requirements) | 0 | 10 |
| Mean wall-clock per requirement | 0.25 s | 30.8 s |
| Byte provenance (all generated tests) | 343/343 | 158/158 |

Ollama has higher parsed recall but much lower precision because it invents
identifiers; held-out detection is equal (the same three bugs; both suites use
the same templates); it is about 120x slower. **So mock stays the default.**
Caveats: n=12, GPU nondeterminism of about +-0.05 F1, prompts tuned on only 8
dev rows, and a 24-option plan shortlist forced by the 4096-token context.
The in-sample number (generated 25/26 mock, 21/26 ollama) is secondary: the
templates were tuned on those bugs. Retrieval: neither BM25 nor Chroma is
clearly better on 19 queries (test split hit@3 63.6% for both), so BM25 stays
the default. See `outputs/eval_report.md` for all numbers,
[`docs/RESULTS.md`](docs/RESULTS.md) for the walkthrough, and
`FINAL_REPORT.md` for the honest summary and caveats.

Quick tour of the whole system: `python scripts/demo.py` (see
[`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)).

The demo also has an ollama segment: `python scripts/demo.py --llm ollama`
(about 30 s per requirement; falls back to the mock with a printed warning if
Ollama is not reachable). The demo script has a pre-recorded fallback for when
Ollama is slow or down.

## API

```bash
python -m uds_assistant.api
# --host, --port, --reload also accepted
```

Runs the FastAPI service with uvicorn (`uds_assistant/api/app.py:create_app()`,
served as `uds_assistant.api.app:app`). Endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness/config check |
| GET | `/spec` | the loaded ECU spec summary |
| POST | `/generate` | run the agent pipeline on a requirement → generated tests |
| POST | `/run` | execute tests (by `run_id` or inline) on the simulator |
| POST | `/eval` | run the evaluation pipeline (writes to a temp dir by default, not `outputs/`) |
| POST | `/export` | render pytest/udsoncan or CAPL exports |
| GET | `/bugs` | the injectable bug catalog |
| GET | `/runs` | audit trail of past runs |
| POST | `/tests/{run_id}/{test_id}/review` | mark a generated test reviewed/accepted/rejected |

(The review endpoint takes `run_id` *and* `test_id`, not just a test id — see
`DECISIONS.md` `[API-REVIEW-PATH]` for why, this is a deliberate deviation
from a flatter path.)

## UI

```bash
streamlit run uds_assistant/ui/streamlit_app.py
```

An engineering UI over the same pipeline (generate → review → run → export; the bug picker offers in-sample and held-out bugs). The evaluation section reads `outputs/eval_report.json` and shows the side-by-side mock | ollama headline table, requirement understanding per mode on the test split, held-out detection per mode, latency, rejections/retries, fallback and truncation events, byte-provenance counts, and the BM25 vs Chroma retrieval comparison (`n/a` for anything an older report lacks),
calling `agent.run_pipeline` / `runner.run_suite` / `export.render_*` directly
rather than over HTTP, with its own audit trail (`outputs/ui_audit.sqlite`).

## Exports

Generated (or gold) test suites can be rendered to:

- **Python / pytest / udsoncan** (`uds_assistant/export/pytest_export.py`) —
  one test function per `TestCase`; runs in-process by default, or against a
  virtual-CAN ISO-TP bus via `UDS_EXPORT_TRANSPORT=can` (tests with a
  time-advance step are skipped in CAN mode — see Known limitations in
  `FINAL_REPORT.md`).
- **CAPL** (`uds_assistant/export/capl_export.py`) — explicitly labeled
  `UNVERIFIED TEMPLATE — not compiled or run in CANoe` (no CANoe license
  available).

## Repository layout

```
uds_assistant/
  protocol/   SIDs, NRC table, codec (encode/decode), seed/key security math, request builders
  spec/       Pydantic ECU-spec schema + loader (data/bcm_spec.yaml)
  rules/      The oracle: (spec, state, request) -> exact response + reason trace
              rules/nrc_order.py = the single NRC-evaluation-order function
  simulator/  Independent ECU implementation (does not import rules/), bug catalog,
              in-process + virtual-CAN/ISO-TP transports
  testgen/    TestCase model, 23 parameterized templates, gold-test execution
  rag/        BM25 (offline) + Chroma/fastembed retrieval, retrieval comparison, citations
  llm/        Pluggable LLM: mock (deterministic) and ollama (local Qwen2.5-3B); all prompts in llm/prompts.py (frozen at B3 revision 8)
  agent/      LangGraph pipeline (+ plain-Python fallback) over shared node functions
  runner/     Executes test suites on the simulator, records pass/fail + timing
  eval/       Metrics + report generation (outputs/eval_report.{json,md}), byte-provenance check
  export/     pytest/udsoncan and CAPL exporters
  store/      SQLite audit trail (runs, tests, decisions, results)
  api/        FastAPI service
  ui/         Streamlit engineering UI
data/
  bcm_spec.yaml           synthetic BCM ECU spec
  requirements_seed.csv   15 seed requirements
  gold/gold_tests.yaml    60 hand-authored gold tests
  bugs/bug_catalog.yaml   26 injectable simulator bugs
  sources/                hand-written UDS reference notes (no ISO text copied)
docs/
  behaviour_contract.md   plain-language ECU behaviour spec the simulator is built from
outputs/
  eval_report.{json,md}            current evaluation report: mock and ollama side by side (report version 2, template set v2)
  eval_interpretation.md           written interpretation of the comparison
  ollama_smoke.json                early 5-requirement real-model smoke run (B2, before the plan-context fix)
  prompt_tuning/                   dev-split-only prompt tuning revisions (B3)
  eval_report_baseline_v1.{json,md} evaluation report from template set v1, for before/after
tests/      mirrors uds_assistant/ package-for-package
```

## Architecture

```
  Requirement (plain English, data/requirements_seed.csv)
  + ECU diagnostic spec (data/bcm_spec.yaml)
            |
            v
    +-------------------------------------------------------------+
    |                    agent/ pipeline (LLM = language only)     |
    |                                                               |
    |   parse --> retrieve --> plan --> instantiate --> validate -->explain
    |   (LLM)     (rag/)       (LLM)    (testgen/        (byte-      (LLM)
    |                                    templates.py,   provenance
    |                                    rules engine     re-check)
    |                                    called inline)
    +-------------------------------------------------------------+
            |
            v
     Structured TestCase objects (bytes from templates/rules engine, with citations)
            |
      +-----+--------------------------------+
      |                                       |
      v                                       v
  runner/ executes on simulator/        eval/ computes metrics against TWO
  (bug-free AND once per injected bug)  independent ground truths:
      |                                       |
      v                                       v
  pass/fail + timing per test      (a) rules/ oracle  (b) data/gold/ hand-written tests
      |                                       |
      +-------------------+-------------------+
                           v
              "triangulation": rules engine (oracle) <--agreement test--> simulator
                               generated suite        <--overlap/prefix--> gold suite
                           |
                           v
            outputs/eval_report.{json,md}: coverage, validity, accuracy,
            template reuse, citation validity, bug-detection rate
                           |
                           v
            export/: pytest+udsoncan scripts (run on virtual CAN or in-process)
                      CAPL templates (unverified, no CANoe)
                           |
                           v
            store/: SQLite audit trail   api/ FastAPI   ui/ Streamlit
```

**Why triangulation, not volume** (see `PROJECT.md` §6): the rules engine and
the simulator are two *independently written* implementations of the same ECU
behaviour (the simulator never imports `uds_assistant.rules` — enforced by an
AST check in `tests/simulator/test_independence.py`) and a hypothesis-based
property test (`tests/simulator/test_agreement.py`) checks they agree
byte-for-byte on randomized request sequences. Separately, 60 gold tests were
hand-authored from `docs/behaviour_contract.md` (not generated) and must pass
on the bug-free simulator. Request bytes are also cross-checked against
`udsoncan`'s own encoding wherever it defines the same constants
(`tests/protocol/test_udsoncan_crosscheck.py`), and a `udsoncan` client runs a
full session over a virtual CAN / ISO-TP bus
(`tests/simulator/test_transport.py::test_udsoncan_full_sequence`). See
`FINAL_REPORT.md` for exactly which of these checks are independent versus
circular by construction.

## Governance notes

- Every non-obvious design choice and every deviation from `PROJECT.md` /
  `SCOPE.md` is logged in `DECISIONS.md`, one line per decision, tagged
  (e.g. `[R-ORDER]`, `[S-INDEP]`, `[EVAL-TPL-V2]`) so a specific NRC rule or
  test can point at the reasoning behind it.
- Each check in `rules/nrc_order.py` cites a `DECISIONS.md` tag. Where the
  AUTOSAR CP R24-11 Dcm SWS actually states the same behaviour, it also cites
  the `SWS_Dcm_xxxxx` ID (38 distinct IDs, each verified against the local PDF
  by `tests/rules/test_sws_citations.py`). The PDF is git-ignored, so keep a
  local copy in `data/sources/`; without it, those tests are skipped. There
  are 9 known disagreements with the SWS, listed in
  `docs/SWS_DISAGREEMENTS.md` and not yet fixed.
- No ISO 14229 text is copied anywhere; protocol notes in
  `data/sources/uds_reference_notes.md` are written from scratch.
- The LLM (mock or Ollama) never emits bytes that reach a test — see "Core
  principle" above and `DECISIONS.md [L-NO-BYTES]`.

## Further reading

- [`PROJECT.md`](PROJECT.md) — what this project is and why
- [`SCOPE.md`](SCOPE.md) — in/out of scope, tonight's offline-build scope and success criteria
- [`AGENT.md`](AGENT.md) — the working rules this repo was built under
- [`PROGRESS.md`](PROGRESS.md) — phase-by-phase build log
- [`DECISIONS.md`](DECISIONS.md) — every non-obvious decision and deviation
- [`MODEL_SETUP.md`](MODEL_SETUP.md) — exact steps to enable Ollama + ChromaDB/fastembed (both verified by running them in Part B)
- [`docs/CODE_TOUR.md`](docs/CODE_TOUR.md) — guided tour of the code
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — architecture
- [`docs/RESULTS.md`](docs/RESULTS.md) — results walkthrough, including the mock vs ollama comparison
- [`outputs/eval_interpretation.md`](outputs/eval_interpretation.md) — where the LLM helped and where it did not
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) — demo script (`python scripts/demo.py`), with an optional ollama segment and a recorded fallback
- [`docs/SWS_DISAGREEMENTS.md`](docs/SWS_DISAGREEMENTS.md) — rules engine vs AUTOSAR Dcm SWS (D1–D9, documented, not fixed)
- [`docs/RECONCILIATION.md`](docs/RECONCILIATION.md) — search for an older doc set (none found)
- [`FINAL_REPORT.md`](FINAL_REPORT.md) — honest done/untested/not-done breakdown, Part A and Part B changes, test counts, eval numbers, limitations, next steps
