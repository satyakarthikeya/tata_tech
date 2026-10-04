## Docker

Two services: `app` (FastAPI on 8000 plus the Streamlit UI on 8501, started by
`docker/entrypoint.sh`) and `ollama` (the local LLM server, port 11434).

```bash
docker compose up -d --build
docker compose exec ollama ollama pull qwen2.5:3b-instruct-q4_K_M
```

- UI: http://localhost:8501
- API: http://localhost:8000 (interactive docs at http://localhost:8000/docs, health at `/health`)

### Switching the LLM

The default is `LLM_MODE=mock` (deterministic, needs no model). After pulling the model:

```bash
LLM_MODE=ollama docker compose up -d
```

(or set `LLM_MODE=ollama` in a `.env` file next to `docker-compose.yml`). The app reaches
Ollama at `OLLAMA_HOST=http://ollama:11434`; if it is unreachable the app warns and falls
back to the mock. `RETRIEVER=chroma` is also available (chromadb and fastembed are in
the image; the embedding model downloads on first use and needs network access).
Results and the audit database persist in the `app_outputs` volume; models in `ollama_data`.

### GPU

CPU works but is slow. For an NVIDIA GPU, install the NVIDIA Container Toolkit on the
host, then uncomment the `deploy.resources.reservations.devices` block under `ollama`
in `docker-compose.yml` and re-run `docker compose up -d`.

Written, not built or tested in this environment (limited network).
