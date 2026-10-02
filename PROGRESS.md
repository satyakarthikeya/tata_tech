# PROGRESS.md

## Step 0 — Orientation & plan (2026-10-03T00:57:17+05:30)

**Environment:** Python 3.13.6 (docs specify 3.11 — see DECISIONS.md). Git initialised.
Pre-installed: pydantic 2.13, httpx 0.28. Installed in one pip attempt (succeeded): pyyaml, udsoncan 1.26.1, can-isotp 2.0.7, python-can 4.6.1, pytest, hypothesis, fastapi, uvicorn, langgraph, rank-bm25 (numpy present), ruff.
Heavy packages (torch, transformers, sentence-transformers, chromadb, onnxruntime, llama-cpp-python, vllm): all absent — not installed. streamlit absent (optional, try in Phase 8).
`docs/`, `data/bcm_spec.yaml`, `data/requirements_seed.csv` referenced by AGENT.md do **not exist** — authored from scratch (see DECISIONS.md).

**Plan** (package `uds_assistant/`, tests under `tests/` mirroring layout; commit `phase N: …` after each):
1. Protocol core + ECU spec (BCM yaml, seed/key + lockout), codec/udsoncan cross-check tests
2. Rules engine oracle, single NRC-order function with citations, 60+ table-driven tests
3. Independent simulator (no rules import), 15+ bug catalog, in-process + virtual CAN/ISO-TP transports, hypothesis agreement test, udsoncan client sequence
4. TestCase model, 8–12 templates, 40–60 gold tests verified on simulator
5. Layered BM25 retrieval with citations; Chroma backend lazy/needs_model
6. Mock LLM, Ollama client (monkeypatched tests), agent pipeline (LangGraph + plain fallback), SQLite store
7. Runner, mock-mode evaluation report (json+md), pytest/udsoncan + CAPL exports
8. FastAPI + TestClient tests, Streamlit UI
9. MODEL_SETUP.md, README.md, FINAL_REPORT.md, ruff, final pytest, commit

**Execution:** each phase delegated sequentially to a subagent (Sonnet for routine phases, Opus for oracle/simulator/agent), then verified by the orchestrator (pytest + ruff) before commit.
