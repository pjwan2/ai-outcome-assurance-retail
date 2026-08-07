from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.db import DATABASE_URL, engine

DB_PATH = Path(DATABASE_URL.removeprefix("sqlite:///"))


@pytest.fixture()
def client():
    engine.dispose()
    if DB_PATH.exists():
        try:
            DB_PATH.unlink()
        except PermissionError:
            pass
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()
    if DB_PATH.exists():
        try:
            DB_PATH.unlink()
        except PermissionError:
            pass


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_case_lifecycle_and_review_flow(client):
    created = client.post("/api/cases").json()
    case_id = created["case_id"]
    assert created["status"] == "NEEDS_REVIEW"

    claims = client.get(f"/api/cases/{case_id}/claims").json()
    by_type = {c["claim_type"]: c["status"] for c in claims}
    assert by_type["MAJOR_FAILURE_ESTABLISHED"] == "UNKNOWN"
    assert by_type["AUTO_REFUND_PERMITTED"] == "FALSE"

    authority = client.get(f"/api/cases/{case_id}/authority").json()
    assert authority[-1]["decision"] == "REQUIRE_HUMAN"

    trace = client.get(f"/api/cases/{case_id}/trace").json()
    assert len(trace) >= 6

    reviews = client.get("/api/reviews").json()
    assert any(r["case_id"] == case_id for r in reviews)
    review = next(r for r in reviews if r["case_id"] == case_id)

    decision_resp = client.post(
        f"/api/reviews/{review['review_id']}/decision",
        json={
            "reviewer_id": "reviewer-1",
            "decision": "REQUEST_MORE_EVIDENCE",
            "notes": "escalate to manufacturer",
            "idempotency_key": "key-1",
        },
    )
    assert decision_resp.status_code == 200
    assert decision_resp.json()["status"] == "DECIDED"

    replay = client.post(f"/api/cases/{case_id}/replay")
    assert replay.status_code == 200
    assert replay.json()["status"] == "NEEDS_REVIEW"


def test_evaluation_and_release_endpoints(client):
    eval_resp = client.post("/api/evaluations/run")
    assert eval_resp.status_code == 200
    body = eval_resp.json()
    assert body["total_cases"] == 28

    fetched = client.get(f"/api/evaluations/{body['evaluation_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["dataset_version"] == body["dataset_version"]

    release = client.get("/api/releases/latest")
    assert release.status_code == 200
    assert release.json()["decision"] == "PASS"
    assert release.json()["regression_fixture_check"]["decision"] == "BLOCK"
