from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from uds_assistant.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(repo_root=REPO_ROOT, db_path=tmp_path / "audit.sqlite")
    return TestClient(app)
