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

Deferred, heavier features (a real local LLM via Ollama, semantic retrieval
via ChromaDB + sentence-transformers) are documented step by step in
**[`MODEL_SETUP.md`](MODEL_SETUP.md)** and are not required for anything in
this README.

## Runtime switches

Two environment variables, read once by `uds_assistant/config.py`:

| Variable | Values | Default | Effect |
|---|---|---|---|
| `LLM_MODE` | `mock`, `ollama` | `mock` | `mock` = deterministic keyword/rule stand-in LLM, no network. `ollama` = local Qwen2.5-3B via Ollama; falls back to `mock` with a warning if unreachable. |
| `RETRIEVER` | `bm25`, `chroma` | `bm25` | `bm25` = hand-rolled/`rank-bm25` lexical retrieval, no model. `chroma` = ChromaDB + `BAAI/bge-small-en-v1.5` embeddings; falls back to `bm25` if the packages aren't importable. |

An invalid value for either falls back to its default and prints a warning
instead of crashing.

## Running the tests

```bash
python -m pytest -q
```

Current result on this machine (Python 3.13.6, Windows): **753 passed, 2
skipped** (`needs_model` tests, skipped automatically). Model-dependent tests
are marked `@pytest.mark.needs_model`; to run them once Ollama/ChromaDB are
set up (see `MODEL_SETUP.md`):

```bash
RUN_MODEL_TESTS=1 python -m pytest -m needs_model -v
```

Tests mirror the package layout under `tests/` (one subdirectory per package:
`protocol/`, `rules/`, `simulator/`, `testgen/`, `rag/`, `llm/`, `agent/`,
`runner/`, `eval/`, `export/`, `store/`, `api/`, `ui/`, `spec/`).

## Evaluation

```bash
python -m uds_assistant.eval.run_eval --mode mock
```

Regenerates `outputs/eval_report.json` and `outputs/eval_report.md` — coverage,
request validity, expected-response accuracy (vs the oracle, vs the
independent simulator, vs the hand-written gold set), template reuse, citation
validity, and **bug-detection rate** (each of the 26 catalog bugs enabled
alone, generated suite vs gold suite vs their union). See
`outputs/eval_report.md` for the full current numbers and metric definitions,
and `FINAL_REPORT.md` for the honest headline summary and caveats (in
particular: the bug-detection number for the generated suite is **not an
independent measurement** — see that file).

Run in Ollama mode (after `MODEL_SETUP.md` steps) and compare:

```bash
LLM_MODE=ollama python -m uds_assistant.eval.run_eval --mode ollama --out outputs/ollama
```

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

An engineering UI over the same pipeline (generate → review → run → export),
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
  rag/        BM25 (offline) + Chroma (lazy, needs_model) retrieval, citations
  llm/        Pluggable LLM: mock (deterministic) and ollama (local Qwen2.5-3B)
  agent/      LangGraph pipeline (+ plain-Python fallback) over shared node functions
  runner/     Executes test suites on the simulator, records pass/fail + timing
  eval/       Metrics + report generation (outputs/eval_report.{json,md})
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
  eval_report.{json,md}            current (mock, template set v2) evaluation report
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
- No AUTOSAR Dcm SWS document was reachable offline; `rules/nrc_order.py`
  cites `"udsoncan behaviour"` or a `DECISIONS.md` tag for every check instead
  of a fabricated SWS requirement ID.
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
- [`MODEL_SETUP.md`](MODEL_SETUP.md) — exact steps to enable Ollama + ChromaDB
- [`FINAL_REPORT.md`](FINAL_REPORT.md) — honest done/untested/not-done breakdown, test counts, eval numbers, limitations, next steps
