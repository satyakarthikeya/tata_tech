# MODEL_SETUP.md — Ollama and the embedding model

Both are **required**. There is no mock LLM and no BM25 fallback: if Ollama is down, the API
answers HTTP 503 and the UI shows "Start Ollama and pull qwen2.5:3b-instruct-q4_K_M".

- **LLM:** Ollama with `qwen2.5:3b-instruct-q4_K_M` (about 2 GB). Developed and evaluated on an
  RTX 3050 Laptop GPU with 4 GB.
- **Retrieval:** ChromaDB with `BAAI/bge-small-en-v1.5` embeddings via `fastembed` (ONNX, CPU, no
  torch). Both Python packages are installed by `pip install -e ".[ui]"`.

## 1. Install Ollama and pull the model

```powershell
winget install Ollama.Ollama          # or the installer from https://ollama.com/download
ollama pull qwen2.5:3b-instruct-q4_K_M
curl.exe http://localhost:11434/api/tags      # the model must be listed
```

After install Ollama runs as a background service on `http://localhost:11434`. Open a new shell so
the `ollama` CLI is on `PATH` (Git Bash often does not see it; the HTTP API is all this project
needs). `/api/tags` is the exact endpoint the app probes.

## 2. Settings the app reads

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Server URL (a bare host:port gets `http://`) |
| `OLLAMA_MODEL` | `qwen2.5:3b-instruct-q4_K_M` | Model tag |
| `OLLAMA_NUM_CTX` | `4096` | `num_ctx` sent with every request (fits a 4 GB GPU; the evaluated setting) |
| `OLLAMA_KEEP_ALIVE` | `10m` | How long Ollama keeps the model loaded |
| `FASTEMBED_CACHE_PATH` | `~/.cache/uds_assistant/fastembed` | Where the BGE model is cached |

Every request sends `temperature: 0`, `seed: 0` and `stream: false`; structured calls (parse, plan)
also send the pydantic JSON schema as `format`. The model never produces bytes.

### Recommended server settings for a 4 GB GPU

The model plus a 4096-token KV cache fits in VRAM; the default 32768 context would not. These are
read by the Ollama **server**, so set them before it starts:

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_FLASH_ATTENTION` | `1` | less memory per token of context |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | halves the KV cache (needs flash attention) |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | never keep a second model resident |

```powershell
setx OLLAMA_FLASH_ATTENTION 1; setx OLLAMA_KV_CACHE_TYPE q8_0; setx OLLAMA_MAX_LOADED_MODELS 1
# quit Ollama from the tray icon, then start it again from a new shell or the Start menu
```

## 3. Embedding model and the vector store

The first run downloads `BAAI/bge-small-en-v1.5` (needs network once; offline afterwards). The store
is `outputs/chroma/` (git-ignored): cosine distance, four Chroma collections (standard, OEM, ECU, project,
one per layer); only new or changed chunks are re-embedded. An older shared-collection store is dropped and
rebuilt automatically on first start.

```bash
python -c "from uds_assistant.rag.embedders import FastEmbedEmbedder; FastEmbedEmbedder()"   # pre-download
```

## 4. Check everything

```bash
python scripts/demo.py                       # one requirement, end to end (about 30 s)
python -m uds_assistant.eval.run_eval        # full evaluation, about 30 minutes on a laptop GPU
```

## Troubleshooting

- **503 / "Ollama is not reachable"** — start the service (`ollama serve` if it does not run in the
  background) and make sure `OLLAMA_HOST` matches its port; confirm with `curl .../api/tags`.
- **Model missing** — `ollama pull qwen2.5:3b-instruct-q4_K_M`; `ollama list` should show it.
- **Slow or truncated answers** — keep `OLLAMA_NUM_CTX` at 4096 on a 4 GB card; the pipeline budgets
  its prompts for that window and records any "prompt likely truncated" event.
- **Embedding download fails or hangs** — it needs network once; set `FASTEMBED_CACHE_PATH` to a
  directory that already holds the model to go fully offline.
- **`ollama pull` stalls** — re-run the same command; Ollama resumes partial layers.
- **Windows firewall prompt** — allow Ollama on private networks; it only binds `localhost:11434`.
