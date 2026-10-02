"""``python -m uds_assistant.api`` — run the FastAPI service with uvicorn.

Not executed by the test suite (it blocks forever); tests use
``fastapi.testclient.TestClient`` against ``create_app()`` instead.
"""

from __future__ import annotations

import argparse


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(prog="python -m uds_assistant.api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run("uds_assistant.api.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
