# UDS assistant: FastAPI (8000) + Streamlit (8501) in one image.
# Written, not built or tested in this environment (limited network).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LLM_MODE=mock \
    RETRIEVER=bm25 \
    EMBEDDER=fastembed \
    OLLAMA_HOST=http://ollama:11434 \
    OLLAMA_MODEL=qwen2.5:3b-instruct-q4_K_M \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed

WORKDIR /app

# Editable install: the code locates data/ and outputs/ relative to the source tree
# (REPO_ROOT = parents[2] of uds_assistant/api/app.py), so the repo must stay at /app.
# uvicorn is not in pyproject.toml but the API needs it; chromadb + fastembed enable
# RETRIEVER=chroma (model weights download on first use, needs network then).
COPY pyproject.toml README.md ./
COPY uds_assistant ./uds_assistant
RUN pip install -e ".[ui]" uvicorn chromadb fastembed

COPY data ./data
COPY docs ./docs
COPY scripts ./scripts
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN mkdir -p outputs .cache/fastembed && chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000 8501
VOLUME ["/app/outputs"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
