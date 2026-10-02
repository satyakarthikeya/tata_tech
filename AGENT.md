# AGENT.md — Working rules for any coding agent on this repo

Read this file, `PROJECT.md`, and `SCOPE.md` before doing anything.

## How to work

1. **Autonomous.** The owner may be asleep. Never stop to ask questions. When something is ambiguous, choose the most reasonable option, log it in `DECISIONS.md` (decision + reason, one line), and continue.
2. **Read existing files first.** `docs/`, `data/bcm_spec.yaml`, and `data/requirements_seed.csv` hold earlier design work. Follow them. If one is wrong, build the correct thing and log the deviation.
3. **Phase by phase.** Finish, test, and commit each phase before starting the next. Stopping at any phase boundary must leave a working repo.
4. **Git:** run `git init` if needed. Commit after each phase as `phase N: <summary>`. Never rewrite history.
5. **Progress log:** append to `PROGRESS.md` after each phase: what was done, test status, timestamp.
6. **Honesty:** never fake results, hardcode metrics, weaken assertions to make tests pass, or delete failing tests. Report failures plainly.

## Correctness rules

- **The LLM never produces bytes** that reach a final test. Bytes come only from templates plus the rules engine.
- The **rules engine is the oracle**. The **simulator is a separate implementation** and must not import or call the rules engine. Their agreement is a key test.
- The NRC evaluation order lives in **one function** in `rules/nrc_order.py`, and each check has a comment citing its source (AUTOSAR Dcm SWS requirement ID, "udsoncan behaviour", or "design decision — see DECISIONS.md").
- Cross-check byte constants against `udsoncan` wherever `udsoncan` defines them.
- Never copy ISO 14229 text. Write protocol notes in your own words.

## Dependencies and offline rules

- **Allowed to install:** small pure-Python packages: pydantic, pyyaml, udsoncan, can-isotp, python-can, pytest, hypothesis, fastapi, uvicorn, httpx, langgraph, rank-bm25, ruff.
- **Never install unless already present** (`pip show` first): torch, transformers, sentence-transformers, chromadb, onnxruntime, llama-cpp-python, vllm. Never download model weights.
- If a pip install fails because of the network, don't retry in a loop. Fall back to an in-house or stdlib implementation (for example, BM25 written by hand, or a plain-Python pipeline instead of LangGraph) and log it.
- **Model-dependent modules use lazy imports** inside functions, so the package imports cleanly without them.
- Mark model-dependent tests with `@pytest.mark.needs_model`. They are skipped automatically unless `RUN_MODEL_TESTS=1`.

## Runtime switches

- `LLM_MODE=mock|ollama`: default `mock`; fall back to `mock` with a warning if Ollama is unreachable.
- `RETRIEVER=bm25|chroma`: default `bm25`; fall back to `bm25` if chromadb or embeddings are missing.
- Both are read from env vars through one `config.py`.

## Code style

- Python 3.11, type hints everywhere, pydantic models for all structured data
- Small modules, pure functions where possible, no global mutable state except in the simulator's ECU instance
- `ruff` clean; docstrings on public functions
- Tests mirror the package layout under `tests/`; prefer table-driven tests and `hypothesis` property tests

## Files the agent maintains

| File | Content |
|---|---|
| `PROGRESS.md` | Phase-by-phase log |
| `DECISIONS.md` | Every non-obvious choice and every deviation from docs |
| `MODEL_SETUP.md` | Exact steps to enable deferred model features |
| `FINAL_REPORT.md` | Done / partial / untested / deferred, test counts, eval numbers, known limitations, next steps |
| `README.md` | Setup, switches, how to run tests, eval, API and UI, ASCII architecture |
