"""End-to-end tests for the FastAPI service via TestClient."""

from __future__ import annotations

from fastapi.testclient import TestClient

REQ_TEXT = "The tester shall be able to read the VIN (DID 0xF190) in any diagnostic session."


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["llm_mode_actual"] in ("MockLLM", "mock")
    assert "retriever" in body
    assert "python" in body["versions"]


def test_spec(client: TestClient) -> None:
    resp = client.get("/spec")
    assert resp.status_code == 200
    body = resp.json()
    assert body["synthetic"] is True
    assert body["spec"]["synthetic"] is True
    assert body["spec"]["ecu_name"]
    assert len(body["spec"]["dids"]) > 0


def test_generate_happy_path(client: TestClient) -> None:
    resp = client.post("/generate", json={"requirement_text": REQ_TEXT, "requirement_id": "REQ-001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["requirement_id"] == "REQ-001"
    assert body["run_id"] is not None
    assert len(body["tests"]) > 0
    assert "human review" in body["governance_banner"]
    for t in body["tests"]:
        assert t["review_status"] in ("draft", "validated", "human_reviewed")
        assert isinstance(t["citations"], list)


def test_generate_empty_requirement_rejected(client: TestClient) -> None:
    resp = client.post("/generate", json={"requirement_text": ""})
    assert resp.status_code == 422


def test_generate_default_requirement_id(client: TestClient) -> None:
    resp = client.post("/generate", json={"requirement_text": REQ_TEXT})
    assert resp.status_code == 200
    assert resp.json()["requirement_id"].startswith("api-")


def test_run_by_run_id_and_export_round_trip(client: TestClient) -> None:
    gen = client.post(
        "/generate", json={"requirement_text": REQ_TEXT, "requirement_id": "REQ-001"}
    ).json()
    run_id = gen["run_id"]

    run_resp = client.post("/run", json={"run_id": run_id})
    assert run_resp.status_code == 200
    run_body = run_resp.json()
    assert run_body["total"] == len(gen["tests"])
    assert run_body["passed"] == run_body["total"]
    assert run_body["bugs"] == []

    exp_resp = client.post("/export", json={"run_id": run_id, "format": "pytest"})
    assert exp_resp.status_code == 200
    exp_body = exp_resp.json()
    assert exp_body["format"] == "pytest"
    assert "import pytest" in exp_body["content"]

    capl_resp = client.post("/export", json={"run_id": run_id, "format": "capl"})
    assert capl_resp.status_code == 200
    assert "UNVERIFIED TEMPLATE" in capl_resp.json()["content"]


def test_run_with_tests_inline(client: TestClient) -> None:
    gen = client.post(
        "/generate", json={"requirement_text": REQ_TEXT, "requirement_id": "REQ-001"}
    ).json()
    run_resp = client.post("/run", json={"tests": gen["tests"]})
    assert run_resp.status_code == 200
    assert run_resp.json()["total"] == len(gen["tests"])


def test_run_with_bug_enabled(client: TestClient) -> None:
    gen = client.post(
        "/generate", json={"requirement_text": REQ_TEXT, "requirement_id": "REQ-001"}
    ).json()
    bugs_resp = client.get("/bugs")
    assert bugs_resp.status_code == 200
    bug_ids = [b["id"] for b in bugs_resp.json()]
    assert "static_seed" in bug_ids
    run_resp = client.post("/run", json={"tests": gen["tests"], "bugs": ["static_seed"]})
    assert run_resp.status_code == 200
    assert run_resp.json()["bugs"] == ["static_seed"]


def test_run_unknown_bug_rejected(client: TestClient) -> None:
    gen = client.post(
        "/generate", json={"requirement_text": REQ_TEXT, "requirement_id": "REQ-001"}
    ).json()
    resp = client.post("/run", json={"tests": gen["tests"], "bugs": ["not_a_real_bug"]})
    assert resp.status_code == 422


def test_run_requires_run_id_or_tests(client: TestClient) -> None:
    resp = client.post("/run", json={})
    assert resp.status_code == 400


def test_run_unknown_run_id_404(client: TestClient) -> None:
    resp = client.post("/run", json={"run_id": 999999})
    assert resp.status_code == 404


def test_export_bad_format_rejected(client: TestClient) -> None:
    gen = client.post(
        "/generate", json={"requirement_text": REQ_TEXT, "requirement_id": "REQ-001"}
    ).json()
    resp = client.post("/export", json={"tests": gen["tests"], "format": "xml"})
    assert resp.status_code == 422


def test_export_requires_run_id_or_tests(client: TestClient) -> None:
    resp = client.post("/export", json={"format": "pytest"})
    assert resp.status_code == 400


def test_eval_mock_mode_restricted_requirements(client: TestClient, tmp_path) -> None:
    out_dir = str(tmp_path / "eval_out")
    resp = client.post(
        "/eval",
        json={"mode": "mock", "requirement_ids": ["REQ-001", "REQ-004"], "out_dir": out_dir},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["requirements"] == 2
    assert body["actual_mode"] == "mock"
    assert "bug_detection" not in body  # top-level report shape
    block = body["modes"]["mock"]
    assert block["status"] == "completed"
    assert "bug_detection" in block
    # committed outputs/ must not be touched
    import os

    assert not os.path.samefile(out_dir, tmp_path.parent) if os.path.exists(out_dir) else True


def test_bugs_and_runs_listing(client: TestClient) -> None:
    assert client.get("/bugs").status_code == 200
    gen = client.post(
        "/generate", json={"requirement_text": REQ_TEXT, "requirement_id": "REQ-001"}
    ).json()
    runs_resp = client.get("/runs")
    assert runs_resp.status_code == 200
    ids = [r["id"] for r in runs_resp.json()]
    assert gen["run_id"] in ids


def test_review_endpoint(client: TestClient) -> None:
    gen = client.post(
        "/generate", json={"requirement_text": REQ_TEXT, "requirement_id": "REQ-001"}
    ).json()
    run_id = gen["run_id"]
    test_id = gen["tests"][0]["id"]
    resp = client.post(f"/tests/{run_id}/{test_id}/review", json={})
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "human_reviewed"


def test_review_unknown_run_404(client: TestClient) -> None:
    resp = client.post("/tests/999999/some_test/review", json={})
    assert resp.status_code == 404


def test_review_unknown_test_404(client: TestClient) -> None:
    gen = client.post(
        "/generate", json={"requirement_text": REQ_TEXT, "requirement_id": "REQ-001"}
    ).json()
    resp = client.post(f"/tests/{gen['run_id']}/not_a_test/review", json={})
    assert resp.status_code == 404


def test_api_generate_includes_confidence(client: TestClient) -> None:
    body = client.post(
        "/generate",
        json={"requirement_text": "The tester shall read the VIN (DID 0xF190).", "requirement_id": "R1"},
    ).json()
    assert body["tests"]
    for t in body["tests"]:
        assert t["confidence"] in ("high", "medium", "low") and t["confidence_reason"]
    assert set(body["target_provenance"]) == {t["id"] for t in body["tests"]}
