# SCOPE.md — What is and isn't in this project

## In scope (full project)

- UDS services 0x10, 0x11, 0x14, 0x19 (0x02), 0x22, 0x27, 0x2E, 0x31, 0x3E
- One synthetic Body Control Module (BCM) ECU spec: about 12–15 DIDs, 2–3 routines, a few DTCs, 3 sessions, 1–2 security levels
- A deterministic rules engine as the single source of truth for expected responses
- An independent ECU simulator with 15+ injectable bugs
- A gold test set of 40–60 hand-authored tests
- Test generation pipeline: parse → retrieve → plan → instantiate → validate → explain
- Test categories: positive, negative, session, security, timing
- Retrieval with citations over layered collections (standard / ecu_spec / project)
- Evaluation report covering request validity, response accuracy, coverage, template reuse, citation validity, and bug detection rate
- Exports to Python (udsoncan + pytest) and CAPL templates
- SQLite audit trail, FastAPI service, Streamlit UI
- Local LLM (Qwen2.5-3B Q4_K_M via Ollama) plus a deterministic mock mode

## Out of scope

- Real ECUs, real vehicles, real CAN hardware (virtual bus only)
- Real OEM diagnostic specs (none are public); the spec is synthetic and declared as such
- Copying ISO 14229 text
- Fine-tuning or training any model
- Paid or cloud LLM APIs
- DoIP (UDS over Ethernet), OBD-II, flashing (0x34/0x36/0x37 download), 0x29 authentication
- Verifying CAPL in CANoe (not available); CAPL output is labeled "template"
- Multi-user auth and enterprise IAM
- Large models (more than 4 GB VRAM)

---

## Tonight's scope: OFFLINE BUILD (slow internet)

**Constraint:** no model downloads. Only small pip packages, and only if pip works.

### Do tonight

- Everything that doesn't need a model: protocol, spec, rules engine, simulator, bugs, gold set, templates, BM25 retrieval, mock LLM, agent pipeline, runner, evaluation (mock mode), exports, SQLite store, FastAPI.
- **Write** the model-dependent code (Ollama client, ChromaDB + embeddings retriever, Streamlit UI) with lazy imports. Test only what can be tested without the model, such as request formatting through monkeypatching.
- Write `MODEL_SETUP.md`: exact steps and commands to enable the model features later.

### Do NOT do tonight

- `ollama pull`, Hugging Face downloads, `sentence-transformers` model downloads
- Installing heavy packages: `torch`, `transformers`, `sentence-transformers`, `chromadb`, `onnxruntime`, `llama-cpp-python`, `vllm`. Use them only if `pip show` says they're already installed.
- Running evaluation in `ollama` mode
- `streamlit` install is optional: install it only if pip is responsive. Otherwise write the UI code and leave it untested.

### Deferred to the "model day" (fast internet)

1. Install Ollama, pull `qwen2.5:3b-instruct-q4_K_M`
2. Install `sentence-transformers`, `chromadb`, and download `bge-small-en-v1.5`
3. Run the tests marked `@pytest.mark.needs_model`
4. Run the evaluation in `ollama` mode and compare it with `mock`
5. Run the Streamlit UI end to end

## Success criteria (tonight)

- `pytest` passes; tests needing a model are marked and skipped, not deleted
- `python -m uds_assistant.eval.run_eval --mode mock` produces a real report with a bug-detection rate
- The simulator and the rules engine agree on 100% of randomized requests
- All gold tests pass on the bug-free simulator
- A `udsoncan` client completes a full sequence over the virtual CAN bus
- `FINAL_REPORT.md` honestly lists what's done, what's untested, and what's deferred
