"""HTTP layer: upload, review gate, run, export, compare and download. No Ollama needed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import ROOT
from uds_assistant.api.app import create_app
from uds_assistant.testgen.conformance import build_conformance_suite


@pytest.fixture
def client(tmp_path):
    app = create_app(repo_root=ROOT, db_path=tmp_path / "audit.sqlite")
    with TestClient(app) as c:
        c.app_state = app.state
        yield c


def _upload(client, text, name="legacy.yaml"):
    return client.post("/import", json={"filename": name, "content": text})


def test_import_returns_outcomes_and_banner(client, errors_text):
    r = _upload(client, errors_text, "e.yaml")
    assert r.status_code == 200
    body = r.json()
    assert (body["total"], body["accepted"], body["oracle_mismatch"], body["invalid"]) == (8, 2, 2, 4)
    assert "not AI-generated" in body["governance_banner"]
    assert {o["status"] for o in body["outcomes"]} == {"accepted", "oracle_mismatch", "invalid"}


def test_bad_file_is_422(client):
    r = _upload(client, "format_version: 9\ntests: [{}]")
    assert r.status_code == 422 and "format_version" in r.json()["detail"]


def test_imported_tests_are_validated_with_provenance_and_listed(client, regression_text):
    run_id = _upload(client, regression_text).json()["run_id"]
    tests = client.get(f"/runs/{run_id}/tests").json()["tests"]
    assert len(tests) == 14
    t = tests[0]["test"]
    assert t["origin"] == "imported" and t["review_status"] == "validated"
    assert t["provenance"]["source_file"] == "legacy.yaml"
    assert [i["run_id"] for i in client.get("/imports").json()] == [run_id]
    assert client.get(f"/import/{run_id}").json()["accepted"] == 14
    assert client.get("/import/999").status_code == 404


def test_review_is_required_before_run_and_export(client, regression_text):
    run_id = _upload(client, regression_text).json()["run_id"]
    assert client.post("/run", json={"run_id": run_id}).status_code == 409
    assert client.post("/export", json={"run_id": run_id, "format": "pytest"}).status_code == 409
    ok = client.post(f"/runs/{run_id}/tests/LEG-001/review",
                     json={"action": "approve", "comment": "checked"})
    assert ok.status_code == 200 and ok.json()["review_label"] == "human_reviewed"
    run = client.post("/run", json={"run_id": run_id}).json()
    assert run["total"] == 1 and run["passed"] == 1
    exp = client.post("/export", json={"run_id": run_id, "format": "pytest"}).json()
    assert "NEVER RUN AGAINST A PRODUCTION VEHICLE" in exp["content"]
    views = client.get(f"/runs/{run_id}/tests").json()["tests"]
    log = next(v for v in views if v["test"]["id"] == "LEG-001")["review_log"]
    assert log == [{"action": "approved", "comment": "checked"}]


def test_compare_against_generated_run_and_download(client, regression_text, spec):
    imp = _upload(client, regression_text).json()["run_id"]
    store = client.app_state.store
    gen = store.start_run("REQ-X", "text", "ollama", "chroma")
    for t in build_conformance_suite(spec).tests[:300]:
        store.record_test(gen, t)
    r = client.post(f"/import/{imp}/compare", json={"generated_run_id": gen})
    assert r.status_code == 200
    body = r.json()
    assert body["comparison"]["tests"]["imported"] == 14
    assert "generated run" in body["generated_source"]
    assert "## Newly covered" in body["markdown"]
    md = client.get(f"/import/{imp}/compare.md", params={"generated_run_id": gen})
    assert md.status_code == 200 and "attachment" in md.headers["content-disposition"]
    assert md.text == body["markdown"]


def test_compare_defaults_to_all_generated_runs_and_rejects_bad_ids(client, regression_text):
    imp = _upload(client, regression_text).json()["run_id"]
    r = client.post(f"/import/{imp}/compare", json={})
    assert r.status_code == 200 and r.json()["comparison"]["tests"]["generated"] == 0
    assert client.post(f"/import/{imp}/compare", json={"generated_run_id": imp}).status_code == 422
    assert client.post(f"/import/{imp}/compare", json={"generated_run_id": 999}).status_code == 404
    assert client.post("/import/999/compare", json={}).status_code == 404


def test_format_endpoint_serves_docs_and_example(client):
    body = client.get("/import/format").json()
    assert body["format_version"] == 1
    assert "format_version: 1" in body["example"]
    assert "IMPORT_FORMAT" in body["documentation"] or "Import format" in body["documentation"]
