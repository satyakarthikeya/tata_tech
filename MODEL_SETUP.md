# MODEL_SETUP.md — enabling the model features

This project was built offline first (see `SCOPE.md`): everything that doesn't
need a model works in `mode=mock` with `RETRIEVER=bm25`. In Part B the two model
features below were set up and **run for real** (Ollama 0.35.1 with
`qwen2.5:3b-instruct-q4_K_M` on an RTX 3050 Laptop GPU with 4 GB; chromadb 1.5.9
and fastembed 0.8.1 with `BAAI/bge-small-en-v1.5`). The `needs_model` tests
passed (13), the retrieval comparison and the full mock vs ollama evaluation
were run, and the results are in `outputs/eval_report.md` and
`docs/RESULTS.md`. This file is the procedure, checked against the code, to turn
the two features on:

1. a real local LLM via **Ollama** (`LLM_MODE=ollama`)
2. semantic retrieval via **ChromaDB + sentence-transformers** (`RETRIEVER=chroma`)

Every env var, CLI flag and file path below was checked against the source
(`uds_assistant/config.py`, `uds_assistant/llm/client.py`,
`uds_assistant/rag/chroma.py`, `uds_assistant/rag/embedders.py`) — nothing here is guessed.

## 0. What the switches actually do

From `uds_assistant/config.py` (`get_config()`):

- `LLM_MODE` — `mock` (default) or `ollama`. Invalid values fall back to `mock` with a warning.
- `RETRIEVER` — `bm25` (default) or `chroma`. Invalid values fall back to `bm25` with a warning.
- `EMBEDDER` — `fastembed` (default) or `sentence-transformers`. Invalid values fall back to `fastembed` with a warning.

From `uds_assistant/llm/client.py`:

- `OLLAMA_HOST` — base URL, default `http://localhost:11434` (`ollama_base_url()`; a bare host/port gets `http://` prepended).
- `OLLAMA_MODEL` — model tag, default `qwen2.5:3b-instruct-q4_K_M` (`ollama_model()`).
- `get_llm()` (factory) probes `GET /api/tags` with a 2 s timeout before using `LLM_MODE=ollama`; if unreachable it warns and silently falls back to `MockLLM`. **If your eval report says `"LLM mode used: mock"` while you requested `ollama`, the probe failed — Ollama isn't actually reachable.**

From `uds_assistant/rag/chroma.py` and `uds_assistant/rag/embedders.py`:

- `ChromaRetriever` imports `chromadb` and the embedder lazily (the module imports cleanly without them).
- `DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"`, embedded by `fastembed` (ONNX, CPU, no torch) by default.
- Uses `chromadb.PersistentClient(path=...)`; the store defaults to `outputs/chroma/` (git-ignored), one collection per embedder, cosine distance, and only changed chunks are re-embedded.
- The factory warns and falls back to BM25 if `chromadb` or the embedder is missing, or if building the store fails.

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

### 2b. Recommended settings for a 4 GB GPU (RTX 3050 Laptop class)

The verified setup is `qwen2.5:3b-instruct-q4_K_M` (~1.9 GB) on a 4 GB card.
The model plus a 4096-token KV cache fits in VRAM; the default 32768 context
would not. Settings come in two kinds.

**Ollama server variables** (read by the Ollama *server*, not by this app). They
only take effect if set **before the server starts**; setting them in a shell
after the Ollama app is already running does nothing.

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_FLASH_ATTENTION` | `1` | Flash attention: less memory per token of context |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Halves KV-cache size versus f16 (needs flash attention) |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Never keep a second model resident on a 4 GB card |

Windows (the Ollama tray app / service): set them persistently, then restart the app.

```powershell
setx OLLAMA_FLASH_ATTENTION 1
setx OLLAMA_KV_CACHE_TYPE q8_0
setx OLLAMA_MAX_LOADED_MODELS 1
# Quit Ollama from the system-tray icon (right-click -> Quit Ollama), or:
Get-Process ollama*, "ollama app" -ErrorAction SilentlyContinue | Stop-Process
# Start it again so it inherits the new variables (new shell or Start menu -> Ollama):
Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
```

`setx` only affects processes started afterwards, so restart the app from a
fresh shell or the Start menu. Alternative without the tray app (one-off, in the
same shell that runs the server):

```powershell
$env:OLLAMA_FLASH_ATTENTION = "1"; $env:OLLAMA_KV_CACHE_TYPE = "q8_0"; $env:OLLAMA_MAX_LOADED_MODELS = "1"
ollama serve
```

```bash
# Git Bash / Linux / macOS (stop any running server first)
OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_MAX_LOADED_MODELS=1 ollama serve
```

Note: `ollama.exe` is usually **not** on Git Bash's `PATH` (the installer adds it
to the Windows user PATH, which an already-open Git Bash may not see). Use
PowerShell for the CLI, call it by full path
(`"$LOCALAPPDATA/Programs/Ollama/ollama.exe"`), or just use the HTTP API
(`curl http://localhost:11434/api/tags`), which is all this project needs.

**Client variables** (read by this project's `OllamaClient`):

| Variable | Default | Meaning |
|---|---|---|
| `LLM_MODE` | `mock` | Set to `ollama` to use the real model |
| `OLLAMA_HOST` | `http://localhost:11434` | Server URL |
| `OLLAMA_MODEL` | `qwen2.5:3b-instruct-q4_K_M` | Model tag |
| `OLLAMA_NUM_CTX` | `4096` | `num_ctx` sent with every request |
| `OLLAMA_KEEP_ALIVE` | `10m` | `keep_alive` sent with every request |

Every request also sends `temperature: 0` and `seed: 0` (parse, plan and explain
alike: reproducible runs, and the explain prose is short), `stream: false`, and,
for structured calls (parse, plan), the pydantic JSON schema as `format`.

Smoke test against the real model (5 seed requirements, writes
`outputs/ollama_smoke.json`):

```bash
python scripts/ollama_smoke.py
```

## 3. Install the retrieval stack (ChromaDB + fastembed)

This is what was installed and run in Part B (no torch needed):

```bash
python -m pip install chromadb fastembed
```

`fastembed` pulls in `onnxruntime`. The optional `sentence-transformers` path
(`EMBEDDER=sentence-transformers`) would also pull in `torch` (hundreds of MB);
it is implemented but was **not installed or run**.

### Pre-download the embedding model

The first `ChromaRetriever()` construction downloads the ONNX export of
`BAAI/bge-small-en-v1.5` (384 dimensions) through fastembed into
`~/.cache/uds_assistant/fastembed` (override with `FASTEMBED_CACHE_PATH`). To
pre-warm the cache explicitly:

```bash
python -c "from fastembed import TextEmbedding; import os; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir=os.path.expanduser('~/.cache/uds_assistant/fastembed'))"
```

### Switch the retriever on

PowerShell:

```powershell
$env:RETRIEVER = "chroma"; $env:EMBEDDER = "fastembed"
```

bash:

```bash
export RETRIEVER="chroma" EMBEDDER="fastembed"
```

Measured result (BM25 vs Chroma on the 19 scorable natural requirements): neither
is clearly better, so the default stays `bm25` (`docs/RESULTS.md`).

## 4. Run the model-dependent tests

Tests that need a real model/embeddings are marked `@pytest.mark.needs_model`
and are skipped by default. Set `RUN_MODEL_TESTS=1` to run them (with Ollama
running with the model pulled, and `chromadb`/`fastembed` installed; they use the GPU and take a few minutes):

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

`needs_model` tests include `tests/rag/test_chroma.py`, `tests/eval/test_retrieval_compare.py` and, for Ollama, the real-server
smoke tests in `tests/llm/test_client.py`, `tests/llm/test_client_options.py` (one
parse call returns a valid `ParsedRequirement`) and `tests/agent/test_instrumentation.py`
(the pipeline completes in ollama mode); the rest of the suite runs unconditionally
against mock/bm25. Last recorded run (after Part C): 13 passed in 123.61s. To run just the LLM/agent ones: `RUN_MODEL_TESTS=1 python -m pytest -m needs_model -v tests/llm tests/agent`.

## 5. Run the evaluation in Ollama mode and compare

A plain `--mode ollama` run takes about 19 minutes in Part B (roughly 30 s per
requirement over 35 requirements). After Part C, with batched explain, the full
command below (35 old requirements, 16 fresh natural-v2 requirements, two extra
noise runs, before/after table) took about 31 minutes (1854 s; mean 21.4 s per
requirement) and uses the GPU. Do not run it while the
GPU is busy with something else.

```powershell
python -m uds_assistant.eval.run_eval --mode ollama --noise-runs 3 --before-after
```

```bash
python -m uds_assistant.eval.run_eval --mode ollama --noise-runs 3 --before-after
```

`--mode ollama` also runs `mock` in the same invocation (`--no-mock-compare`
turns that off), so both columns of `outputs/eval_report.{json,md}` come from the
same inputs, templates and retriever. Ollama-mode test exports go to
`outputs/exports/ollama/` and `outputs/generated_tests_ollama.yaml`. To keep the
committed report untouched, add `--out <dir>`. The run exits with code 2 if any
generated test fails the byte-provenance check. If the run falls back to mock
(see the report's `"LLM mode used"` line, `mode_fallback`, and the fallback
events section), the comparison is meaningless; fix the Ollama connection first
(`ollama list` / `curl` check above) and re-run.

Recorded result (the committed report): on the held-out TEST split the 3B model
did not beat the mock on any headline metric; see `docs/RESULTS.md` and
`outputs/eval_interpretation.md`.

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
  takes effect if `chromadb` and the chosen embedder (`fastembed` by default) are
  importable and the store builds; otherwise the factory warns and falls back to
  `Bm25Retriever`. Confirm with `python -m pip show chromadb fastembed`.
- **Embedding download fails/hangs** — network access is needed once to cache
  `BAAI/bge-small-en-v1.5`; after that it's offline. If the download
  can't complete, stay on `RETRIEVER=bm25` (fully offline, already tested).
- **`ollama pull` is slow or stalls** — resume by re-running the same pull
  command; Ollama resumes partial layers.
- **Windows firewall prompt on first Ollama run** — allow it on "Private
  networks"; it only needs to bind `localhost:11434`.
