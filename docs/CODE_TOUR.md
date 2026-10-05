# Code tour

A map of the repository for a new reader. Package root: `uds_assistant/`. Start with the pipeline
(`agent/pipeline.py`), then follow one requirement through it.

## Words you will meet

- **UDS**: Unified Diagnostic Services, the request/response protocol a tester uses to talk to a car ECU.
  A request starts with a service id (SID, for example `0x22` ReadDataByIdentifier); the ECU answers with
  SID + 0x40 (positive) or `7F SID NRC` (negative, with a negative response code).
- **DID / routine / DTC**: a data identifier (readable or writable value), a routine (a function the tester can
  start), a diagnostic trouble code (a stored fault).
- **Oracle**: `rules/`, a pure function that says what the ECU must answer. **Simulator**: `simulator/`, a second,
  independently written ECU used to run tests (with injectable bugs).
- **RAG**: retrieval-augmented generation: fetch relevant text first, then let the model answer from it.
- **Template**: a reusable, parameterized test recipe. The LLM picks a template and an option index; code builds the bytes.

## The data flow

```
requirement -> agent/pipeline.py: parse -> retrieve -> plan -> instantiate -> validate -> explain -> annotate
            -> TestCase objects (testgen/model.py) -> runner/ on simulator/ -> export/ (pytest, CAPL)
question    -> qa/answer.py -> cited answer or not_found
```

## Package by package

| Package | What it does | Start reading |
|---|---|---|
| `protocol/` | SIDs and NRC constants, request builders, encode/decode, the synthetic seed/key algorithm | `constants.py`, `codec.py` |
| `spec/` | Pydantic schema and loader for the ECU spec (`data/bcm_spec.yaml`, synthetic BCM) | `schema.py` |
| `rules/` | The oracle. `nrc_order.py` is the single place where negative outcomes are decided, each check cites a `DECISIONS.md` tag or an AUTOSAR SWS id | `engine.py`, `nrc_order.py` |
| `simulator/` | Independent ECU (never imports `rules/`), 68 injectable bug hooks, in-process and virtual-CAN transports | `ecu.py`, `services.py`, `bugs.py` |
| `testgen/` | `TestCase` model; 27 approved templates (`templates*.py`); requirement-independent conformance sweep (`conformance.py`) | `model.py`, `templates.py` |
| `rag/` | `ingest.py` builds chunks; `chroma.py` + `embedders.py` is the ChromaDB/BGE retriever; `layers.py` searches the four layers; `citations.py` validates citations | `ingest.py`, `chroma.py` |
| `llm/` | `client.py` Ollama client with retries and schema validation; `base.py` the output schemas (no byte fields); `prompts.py` all prompt text; `factory.py` raises if Ollama is down | `base.py`, `prompts.py` |
| `agent/` | `pipeline.py` runner (LangGraph or plain loop); `nodes.py` the six nodes; `options.py` the enumerated choices offered to the LLM; `grounding.py` drops identifiers the text does not support; `confidence.py` / `annotate.py` | `nodes.py` |
| `qa/` | `lookup.py` deterministic facts; `answer.py` retrieval + verified phrasing; `text.py` helpers | `answer.py` |
| `runner/` | Runs tests on the simulator, timing, bug-detection matrix | `suite.py` |
| `export/` | `pytest_export.py` (raw-byte pytest file), `capl_export.py` (unverified CAPL template) | `pytest_export.py` |
| `store/` | SQLite audit trail: runs, tests, decisions, results | `audit.py` |
| `api/` | FastAPI app: `/health /spec /generate /ask /run /export /bugs /runs` and the review endpoint | `app.py` |
| `ui/` | `streamlit_app.py` wires four tabs; `state.py`, `bugs.py`, `examples.py`, `env.py` hold the logic | `streamlit_app.py` |
| `eval/` | `run_eval.py` the one evaluation command; `metrics.py`, `understanding.py`, `qa_eval.py`, `agreement.py`, `can_check.py`, `trace.py` | `run_eval.py` |

`scripts/demo.py` is the terminal demo. `data/` holds the spec, the seed requirements (15), the blind natural v3
requirements (16), the gold tests (60), the bug catalogs, the blind Q&A questions (25), the OEM guideline and
the UDS reference notes.

## The pipeline, node by node

1. **parse** (`nodes.parse`): the LLM names services, DIDs, routines, sessions and levels from the requirement
   (schema `ParsedRequirement`). Identifiers not in the spec are dropped; `grounding.py` then drops anything the
   text gives no evidence for (a 3B model copies identifiers from the prompt's examples).
2. **retrieve**: searches standard, ECU and project chunks for evidence to cite.
3. **plan**: a compact, ranked shortlist of template options (`options.py`) is shown to the LLM, which returns
   `(template_id, option_index)` pairs; constrained decoding limits the reply to the offered choices.
4. **instantiate**: templates build the steps; every expected response is computed by the rules engine.
5. **validate**: schema, byte provenance (steps equal a fresh instantiation), oracle re-check and citations.
   Failures are dropped and fed back to the planner (at most 2 retries).
6. **explain**: the LLM writes a short rationale per test. **annotate**: confidence plus written-vs-inferred targets.

## Questions a reviewer may ask

1. *What if Ollama is down?* `get_llm()` raises `OllamaUnavailableError`; the API returns 503, the UI shows "Start
   Ollama and pull qwen2.5:3b-instruct-q4_K_M". There is no offline fallback.
2. *Can the LLM put a wrong byte into a test?* No: its schemas have no byte fields, and validation compares every
   step with a fresh template instantiation. It can still choose the wrong template, which the evaluation measures.
3. *Why a shortlist instead of the full template menu?* A 3B model with a 4096-token window cannot take 27
   templates with all options plus the requirement.
4. *Why two ECU implementations?* To triangulate: if the oracle and the independently written simulator agree on
   thousands of random requests, a single-implementation bug is unlikely (a shared misreading is still possible).
5. *Is it deterministic?* Ollama runs at temperature 0 and seed 0, but its output is not guaranteed bit-identical.
6. *How is confidence computed?* `agent/confidence.py`: start at high, lose a level per fired signal (inferred
   target, weak retrieval below cosine 0.5, rejections or retries, grounding drops, LLM call failures).
7. *How does Q&A avoid inventing facts?* Deterministic spec lookup first; the LLM only rephrases, and its text is
   rejected if a looked-up value is missing, a number is new, or a quote is not a substring of its chunk.

## Where the evaluation lives

`python -m uds_assistant.eval.run_eval` runs the pipeline on the 15 seed requirements and the 16 blind natural
requirements, the 25 blind questions, the blind v3 bug set (generated tests + conformance sweep) and the sanity
checks, then writes `outputs/eval_report.md` / `.json` (copied to `docs/RESULTS.md`) and the exported pytest and CAPL
files in `outputs/exports/`. See [RESULTS.md](RESULTS.md) for the numbers and [ARCHITECTURE.md](ARCHITECTURE.md)
for the diagrams. The earlier full version, including its test suite and development history, is git tag
`v1-full-archive`.
