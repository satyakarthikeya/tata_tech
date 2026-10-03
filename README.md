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

**Status.** Part A (honest evaluation), Part B (real-model evaluation) and
Part C (fixes, then a fresh blind evaluation) are done. The local Qwen2.5-3B
model (Ollama) and Chroma retrieval (fastembed embeddings) were run for real and
compared with the deterministic mock. **Headline (fresh v2 data, written blind
after the Part C freeze):** held-out v2 bug detection is **2/15 (13.3%) for the
generated suite in both modes** (gold 5/15, union 5/15), so the coverage
templates added in Part C did not transfer from the seen v1 bugs to fresh ones.
On 16 fresh natural requirements the model is better than the mock at
requirement understanding (parsed F1 0.661 vs 0.367, category recall 74.0% vs
48.0%, precondition recall 77.8% vs 55.6%), but its precision is 0.565 with 30
false positives (the mock's precision is 1.000, its recall 0.225). The precision
fix did not work; explain batching did (1.00 LLM call per requirement, mean
latency 21.37 s vs 30.79 s). The v1 and in-sample numbers are seen or tuned on
and are not evidence. **Mock stays the default.** Details:
[`docs/RESULTS.md`](docs/RESULTS.md),
[`outputs/partC/interpretation.md`](outputs/partC/interpretation.md).

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
**1167 passed, 14 skipped in 303.53s (0:05:03)**. The 14 skips are the 13 `needs_model` tests plus 1 UI test that only applies to an old version 2 report. The `needs_model` tests are skipped
automatically unless `RUN_MODEL_TESTS=1`. To run them (needs Ollama running with
the model pulled, and fastembed + chromadb installed; see `MODEL_SETUP.md`; they
use the GPU and take a few minutes):

```bash
RUN_MODEL_TESTS=1 python -m pytest -m needs_model -v      # bash
```

```powershell
$env:RUN_MODEL_TESTS = "1"; python -m pytest -m needs_model -v   # PowerShell
```

Result of the `needs_model` run (real Ollama server and Chroma/fastembed, after
the Part C evaluation): **13 passed, 1168 deselected in 123.61s (0:02:03)**.
`RUN_MODEL_TESTS=1 pytest` (everything, model tests included) also works.

Tests mirror the package layout under `tests/` (one subdirectory per package:
`protocol/`, `rules/`, `simulator/`, `testgen/`, `rag/`, `llm/`, `agent/`,
`runner/`, `eval/`, `export/`, `store/`, `api/`, `ui/`, `spec/`).

## Evaluation

```bash
python -m uds_assistant.eval.run_eval --mode mock      # fast, offline
python -m uds_assistant.eval.run_eval --mode ollama --noise-runs 3 --before-after   # about 31 minutes, uses the GPU; also runs mock
```

`--mode ollama` runs the mock in the same invocation (`--no-mock-compare`
turns that off), so both columns come from the same inputs, templates and
retriever. `--noise-runs N` repeats the natural-v2 run N times in ollama mode
(run 1 feeds the tables; the report lists every run with mean and range; the
mock runs once plus a second run that must be identical). `--before-after`
writes `outputs/partC/before_after.md` from the frozen pre-Part C baseline.
`--rerender` rebuilds the report from stored JSON without recomputing anything.
It exits with code 2 if any generated test fails the byte-provenance check.
Regenerates `outputs/eval_report.json` and `outputs/eval_report.md` (report
version 3): the fresh v2 rows first, then simulator/rules agreement, gold on the
clean simulator, udsoncan virtual-CAN sequence, coverage, citation validity, the
seen (v1) and in-sample rows labelled as such, the noise check, retrieval
comparison and freeze verification. Add `--skip-can` to skip the udsoncan
virtual-CAN check (fast runs only).

**Headline (report version 3, both modes, one invocation).**

| Metric | mock | ollama |
|---|---|---|
| **Held-out v2 bug detection, FRESH (15 bugs): generated / gold / union** | 2/15 / 5/15 / 5/15 | 2/15 / 5/15 / 5/15 |
| **Natural v2, FRESH (n=16): parsed P / R / F1** | 1.000 / 0.225 / 0.367 | 0.565 / 0.796 / 0.661 |
| Natural v2, FRESH: parsed exact | 0/16 | 4/16 |
| Natural v2, FRESH: category recall / precondition recall (run 1) | 48.0% / 55.6% | 74.0% / 77.8% |
| Natural v2, ollama 3-run mean (range): category / precondition recall | - | 75.3% (74.0%-76.0%) / 82.7% (77.8%-85.2%) |
| Natural v2, FRESH: parsed false positives | 0 | 30 (25 services, 5 DIDs) |
| Planner choices rejected (35 old requirements / v2) | 0 / 0 | 15 / 12 |
| Mean wall-clock per requirement (35 old requirements) | 0.27 s | 21.37 s |
| Byte provenance (all generated tests, all runs) | 511/511 | 418/418 |
| SEEN: held-out v1 generated (12 bugs) | 10/12 | 5/12 |
| In-sample (tuned on): generated (26 bugs) | 25/26 | 19/26 |

Reading it honestly: the generated suite catches only 2 of 15 fresh bugs in
both modes (11 misses have no generated test applying the stimulus, 2 apply it
but cannot see the bug); the model helps requirement understanding on fresh
phrasing but invents targets (mostly services, which the grounding check does
not cover), so the precision fix did not work; rejected planner choices rose and
normalisation fired 0 times; explain batching cut latency from 30.79 s to
21.37 s. The v1 held-out numbers are SEEN (the Part C templates were designed
against those misses) and the in-sample numbers are tuned on: neither is
evidence of improvement. Caveats: n=15 and n=16, one model, a synthetic spec,
bugs written by an LLM, three ollama noise runs, five SWS disagreements still
open. Retrieval: neither BM25 nor Chroma is clearly better on 19 queries (test
split hit@3 63.6% for both), so BM25 stays the default. See
`outputs/eval_report.md` for all numbers, [`docs/RESULTS.md`](docs/RESULTS.md)
for the walkthrough (including the before/after table, the noise check and the
list of missed bugs), [`outputs/partC/before_after.md`](outputs/partC/before_after.md),
[`outputs/partC/interpretation.md`](outputs/partC/interpretation.md) and
`FINAL_REPORT.md` for the honest summary and caveats.

Quick tour of the whole system: `python scripts/demo.py` (about 2 seconds, mock,
offline; see [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)). Useful flags:
`--req REQ-010`, `--bug <id>` (any bug id from the in-sample, held-out v1 and
held-out v2 catalogs), `--text "..."`, `--offline` (load pre-generated tests),
`--full-eval` (mock-only re-run into a temp folder, about 65 s) and
`--llm ollama`.

The demo also has an ollama segment: `python scripts/demo.py --llm ollama`
(about 21 s per requirement in the recorded run; falls back to the mock with a
printed warning if Ollama is not reachable). The demo script has a pre-recorded
fallback for when Ollama is slow or down.

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

An engineering UI over the same pipeline (generate → review → run → export; the bug picker offers `[in-sample]`, `[held-out v1, seen]` and `[held-out v2, fresh]` bugs, and after generating it shows which LLM backend actually ran). The evaluation section reads `outputs/eval_report.json` (versions 2 and 3) and `outputs/partC/before_after.md` and shows the freeze status, the fresh v2 headline, the noise check, the before/after table, the side-by-side mock | ollama comparison, latency, rejections/retries, fallback and truncation events, byte-provenance counts, and the BM25 vs Chroma retrieval comparison (`n/a` for anything an older report lacks). It has only been tested headless (AppTest); the manual click-through procedure is [`docs/UI_CHECKLIST.md`](docs/UI_CHECKLIST.md) and has not been done in a real browser.
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
  testgen/    TestCase model, 27 parameterized templates (set v3), gold-test execution
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
  bugs/bug_catalog.yaml   26 injectable simulator bugs (in-sample)
  bugs/heldout_catalog.yaml     12 held-out v1 bugs (SEEN)
  bugs/heldout_v2_catalog.yaml  15 held-out v2 bugs (FRESH, written blind after the Part C freeze)
  requirements_natural.csv      20 natural v1 requirements (8 dev / 12 test, SEEN)
  requirements_natural_v2.csv   16 natural v2 requirements (split test2, FRESH)
  sources/                hand-written UDS reference notes (no ISO text copied)
docs/
  behaviour_contract.md   plain-language ECU behaviour spec the simulator is built from
outputs/
  eval_report.{json,md}            current evaluation report: mock and ollama side by side (report version 3, template set v3)
  partC/before_after.md            before/after Part C table
  partC/interpretation.md          written interpretation of the Part C results
  partC/baseline_before_partC.json frozen pre-Part C baseline
  partC/mock_equivalence.json      evidence that C1 left the mock output unchanged
  partC/eval_run.log               log of the real C5b run
  eval_interpretation.md           Part B interpretation (historical)
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
  were 9 known disagreements with the SWS, listed in
  `docs/SWS_DISAGREEMENTS.md`; D2, D5, D6 and D7 were fixed in Part C and
  D1, D3, D4, D8 and D9 are still open.
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
- [`outputs/partC/interpretation.md`](outputs/partC/interpretation.md) — Part C interpretation: what improved, what did not, and why (Part B: [`outputs/eval_interpretation.md`](outputs/eval_interpretation.md))
- [`outputs/partC/before_after.md`](outputs/partC/before_after.md) — before/after Part C table with comparability notes
- [`docs/UI_CHECKLIST.md`](docs/UI_CHECKLIST.md) — manual click-through checklist for the Streamlit UI (not yet done in a real browser)
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) — demo script (`python scripts/demo.py`), with an optional ollama segment and a recorded fallback
- [`docs/SWS_DISAGREEMENTS.md`](docs/SWS_DISAGREEMENTS.md) — rules engine vs AUTOSAR Dcm SWS (D1–D9: D2, D5, D6, D7 fixed in Part C; D1, D3, D4, D8, D9 open)
- [`docs/RECONCILIATION.md`](docs/RECONCILIATION.md) — search for an older doc set (none found)
- [`FINAL_REPORT.md`](FINAL_REPORT.md) — honest done/untested/not-done breakdown, Part A, B and C changes, test counts, eval numbers, limitations, next steps
