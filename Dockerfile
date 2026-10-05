# UDS assistant: one image, FastAPI + the HTML UI on port 8000. Ollama runs in its own container
# (see docker-compose.yml, NVIDIA GPU) or on the host (docker-compose.host-ollama.yml).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OLLAMA_HOST=http://ollama:11434 \
    OLLAMA_MODEL=qwen2.5:3b-instruct-q4_K_M \
    OLLAMA_TRUSTED_HOSTS=ollama \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed

WORKDIR /app

# Editable install: the code locates data/ and outputs/ relative to the source tree
# (REPO_ROOT = parents[2] of uds_assistant/api/app.py), so the repo must stay at /app.
COPY pyproject.toml README.md ./
COPY uds_assistant ./uds_assistant
RUN pip install -e ".[export]"

# Bake the BGE embedding model into the image so the app needs no internet at run time.
RUN python -c "from uds_assistant.rag.embedders import FastEmbedEmbedder; FastEmbedEmbedder()"

COPY data ./data
COPY docs ./docs
COPY scripts ./scripts
COPY outputs/eval_report.json outputs/eval_report.md ./outputs/
COPY outputs/exports ./outputs/exports
RUN mkdir -p outputs/chroma

EXPOSE 8000
VOLUME ["/app/outputs"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

CMD ["python", "-m", "uds_assistant.api", "--host", "0.0.0.0", "--port", "8000"]
