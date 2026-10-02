"""FastAPI service exposing the generate -> run -> eval -> export workflow.

Public API: :func:`uds_assistant.api.app.create_app`, module-level ``app``.
"""

from __future__ import annotations

from uds_assistant.api.app import app, create_app

__all__ = ["app", "create_app"]
