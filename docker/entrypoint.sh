#!/bin/sh
# Start the FastAPI service in the background and Streamlit in the foreground.
set -e

python -m uds_assistant.api --host 0.0.0.0 --port 8000 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' INT TERM EXIT

exec streamlit run uds_assistant/ui/streamlit_app.py \
    --server.address 0.0.0.0 --server.port 8501 --server.headless true \
    --browser.gatherUsageStats false
