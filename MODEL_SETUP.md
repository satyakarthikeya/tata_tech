# MODEL_SETUP.md — enabling the deferred model features

This project was built offline (slow internet, see `SCOPE.md` "Tonight's scope").
Everything that doesn't need a model is done and tested (`mode=mock`,
`RETRIEVER=bm25`). This file is the exact, verified-against-code procedure to
turn on the two deferred features later:

1. a real local LLM via **Ollama** (`LLM_MODE=ollama`)
2. semantic retrieval via **ChromaDB + sentence-transformers** (`RETRIEVER=chroma`)

Every env var, CLI flag and file path below was checked against the source
(`uds_assistant/config.py`, `uds_assistant/llm/client.py`,
`uds_assistant/rag/chroma.py`) — nothing here is guessed.

## 0. What the switches actually do

From `uds_assistant/config.py` (`get_config()`):

- `LLM_MODE` — `mock` (default) or `ollama`. Invalid values fall back to `mock` with a warning.
- `RETRIEVER` — `bm25` (default) or `chroma`. Invalid values fall back to `bm25` with a warning.

From `uds_assistant/llm/client.py`:

- `OLLAMA_HOST` — base URL, default `http://localhost:11434` (`ollama_base_url()`; a bare host/port gets `http://` prepended).
- `OLLAMA_MODEL` — model tag, default `qwen2.5:3b-instruct-q4_K_M` (`ollama_model()`).
- `get_llm()` (factory) probes `GET /api/tags` with a 2 s timeout before using `LLM_MODE=ollama`; if unreachable it warns and silently falls back to `MockLLM`. **If your eval report says `"LLM mode used: mock"` while you requested `ollama`, the probe failed — Ollama isn't actually reachable.**

From `uds_assistant/rag/chroma.py`:

- `ChromaRetriever` lazily imports `chromadb` and `sentence_transformers` only inside `__init__` (module imports cleanly without them).
- `DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"`.
- Uses `chromadb.PersistentClient(path=...)`; persisted DB defaults under `outputs/chroma/` (git-ignored).

## 1. Install Ollama

### Windows (PowerShell) — installer

```powershell
# Download and run the official Windows installer
Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile "$env:TEMP\OllamaSetup.exe"
Start-Process "$env:TEMP\OllamaSetup.exe" -Wait
```

### Windows — winget (alternative)

```powershell
winget install Ollama.Ollama
```

After install, Ollama runs as a background service on `http://localhost:11434`.
Open a **new** shell so `PATH` picks up the `ollama` CLI.

### Pull the model

```powershell
ollama pull qwen2.5:3b-instruct-q4_K_M
```

```bash
# bash (Git Bash) equivalent
ollama pull qwen2.5:3b-instruct-q4_K_M
```

This is a ~2 GB download — do this only when internet is fast (per `SCOPE.md`).

### Verify it's up and the model is present

```powershell
ollama list
curl.exe http://localhost:11434/api/tags
```

```bash
ollama list
curl http://localhost:11434/api/tags
```

`ollama list` should show `qwen2.5:3b-instruct-q4_K_M`. `curl .../api/tags`
should return JSON with that model in `"models"`. This is exactly the endpoint
`ollama_reachable()` probes.

## 2. Point the app at Ollama

Defaults already match a local install, so this step is only needed if you run
Ollama on a non-default host/port or a different model tag.

PowerShell:

```powershell
$env:OLLAMA_HOST = "http://localhost:11434"
$env:OLLAMA_MODEL = "qwen2.5:3b-instruct-q4_K_M"
$env:LLM_MODE = "ollama"
```

bash:

```bash
export OLLAMA_HOST="http://localhost:11434"
export OLLAMA_MODEL="qwen2.5:3b-instruct-q4_K_M"
export LLM_MODE="ollama"
```

## 3. Install the retrieval stack (ChromaDB + embeddings)

**Warning:** `sentence-transformers` pulls in `torch` (hundreds of MB). Only do
this with a fast connection.

```powershell
python -m pip install chromadb sentence-transformers
```

```bash
python -m pip install chromadb sentence-transformers
```

### Pre-download the embedding model

The first `ChromaRetriever()` construction downloads `BAAI/bge-small-en-v1.5`
from the Hugging Face Hub via `sentence_transformers.SentenceTransformer`. To
pre-warm the cache explicitly:

```powershell
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"
```

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"
```

### Switch the retriever on

PowerShell:

```powershell
$env:RETRIEVER = "chroma"
```

bash:

```bash
export RETRIEVER="chroma"
```

## 4. Run the model-dependent tests

Tests that need a real model/embeddings are marked `@pytest.mark.needs_model`
and are skipped by default. Set `RUN_MODEL_TESTS=1` to run them (with Ollama
running and `chromadb`/`sentence-transformers` installed):

PowerShell:

```powershell
$env:RUN_MODEL_TESTS = "1"
python -m pytest -m needs_model -v
```

bash:

```bash
RUN_MODEL_TESTS=1 python -m pytest -m needs_model -v
```

Then run the full suite once more to confirm nothing regressed:

```bash
python -m pytest -q
```

Only 2 tests were marked `needs_model` as of Phase 9 (`tests/rag/test_chroma.py`
and the Ollama-reachability path); the rest of the suite already runs
unconditionally against mock/bm25.

## 5. Run the evaluation in Ollama mode and compare

```powershell
$env:LLM_MODE = "ollama"
python -m uds_assistant.eval.run_eval --mode ollama --out outputs/ollama
```

```bash
LLM_MODE=ollama python -m uds_assistant.eval.run_eval --mode ollama --out outputs/ollama
```

This writes `outputs/ollama/eval_report.{json,md}` without touching the
committed mock-mode report at `outputs/eval_report.{json,md}`. Compare the two
reports' headline tables side by side — bug-detection rate, request validity,
coverage, citation validity. If the Ollama run falls back to mock (see the
report's `"LLM mode used"` line and `modes.mode_fallback`), the comparison is
meaningless; fix the Ollama connection first (`ollama list` / `curl` check
above) and re-run.

## 6. Run the Streamlit UI end to end

```bash
streamlit run uds_assistant/ui/streamlit_app.py
```

(`streamlit` is already installed in this environment as the `ui` optional
extra — `pip install -e ".[ui]"` on a fresh machine.) The UI calls
`agent.run_pipeline` / `runner.run_suite` / `export.render_*` directly (no HTTP
hop — see `DECISIONS.md` `[UI-NO-HTTP]`) and writes its own audit trail to
`outputs/ui_audit.sqlite`. With `LLM_MODE=ollama` and `RETRIEVER=chroma` set
beforehand (steps 2 and 3), generating a test from a requirement in the UI
will use the real model/embeddings instead of mock/bm25.

## Troubleshooting

- **Eval report says `"LLM mode used: mock"` when you asked for `ollama`** —
  the `GET /api/tags` reachability probe failed (`ollama_reachable()`).
  Check `ollama list` runs, the service is running (`ollama serve` if it's not
  running as a background service), and `OLLAMA_HOST` matches the port Ollama
  listens on.
- **`run_eval --mode ollama` silently used mock** — check the JSON report's
  `modes.ollama.actual_mode` / `mode_fallback` fields and the printed warning
  text; this is the designed fallback behaviour (`DECISIONS.md [EVAL-MODES]`,
  `[L-FALLBACK]`), not a bug.
- **Retriever silently used bm25 instead of chroma** — `RETRIEVER=chroma` only
  takes effect if `chromadb`/`sentence_transformers` are importable; if either
  import fails inside `ChromaRetriever.__init__`, the factory falls back to
  `Bm25Retriever`. Confirm with `python -m pip show chromadb
  sentence-transformers`.
- **Embedding download fails/hangs** — Hugging Face Hub access is needed once
  to cache `BAAI/bge-small-en-v1.5`; after that it's offline. If the download
  can't complete, stay on `RETRIEVER=bm25` (fully offline, already tested).
- **`ollama pull` is slow or stalls** — resume by re-running the same pull
  command; Ollama resumes partial layers.
- **Windows firewall prompt on first Ollama run** — allow it on "Private
  networks"; it only needs to bind `localhost:11434`.
