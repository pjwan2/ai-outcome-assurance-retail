from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.auth import DEFAULT_DEV_TOKEN
from app.db import DATABASE_URL, engine

DB_PATH = Path(DATABASE_URL.removeprefix("sqlite:///"))
AUTH_HEADERS = {"Authorization": f"Bearer {DEFAULT_DEV_TOKEN}"}


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


def test_create_case_requires_auth(client):
    resp = client.post("/api/cases")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error_code"] == "MISSING_BEARER_TOKEN"

    resp = client.post("/api/cases", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["error_code"] == "INVALID_TOKEN"


def test_case_lifecycle_and_review_flow(client):
    created = client.post("/api/cases", headers=AUTH_HEADERS).json()
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
    assert all(t["state_after_hash"] for t in trace)

    verify_resp = client.get(f"/api/cases/{case_id}/trace/verify").json()
    assert verify_resp["chain_verified"] is True
    assert verify_resp["event_count"] == len(trace)

    reviews = client.get("/api/reviews").json()
    assert any(r["case_id"] == case_id for r in reviews)
    review = next(r for r in reviews if r["case_id"] == case_id)

    unauthenticated_decision = client.post(
        f"/api/reviews/{review['review_id']}/decision",
        json={"decision": "REQUEST_MORE_EVIDENCE", "idempotency_key": "key-0"},
    )
    assert unauthenticated_decision.status_code == 401

    decision_resp = client.post(
        f"/api/reviews/{review['review_id']}/decision",
        headers=AUTH_HEADERS,
        json={
            "decision": "REQUEST_MORE_EVIDENCE",
            "notes": "escalate to manufacturer",
            "idempotency_key": "key-1",
        },
    )
    assert decision_resp.status_code == 200
    assert decision_resp.json()["status"] == "DECIDED"
    assert decision_resp.json()["reviewer_id"] == "demo-reviewer"

    replay = client.post(f"/api/cases/{case_id}/replay", headers=AUTH_HEADERS)
    assert replay.status_code == 200
    assert replay.json()["status"] == "NEEDS_REVIEW"


def test_list_case_fixtures_and_run_a_non_hero_case(client):
    fixtures = client.get("/api/case-fixtures").json()["case_ids"]
    assert set(fixtures) >= {"CASE-RET-001", "CASE-RET-002", "CASE-RET-003", "CASE-RET-004"}

    # CASE-RET-003 has a minor/cosmetic fault assessment: major failure resolves to
    # FALSE and the refund is deterministically DENIED without needing human review.
    created = client.post("/api/cases", headers=AUTH_HEADERS, json={"case_id": "CASE-RET-003"}).json()
    assert created["case_id"] == "CASE-RET-003"
    assert created["status"] == "COMPLETED"

    authority = client.get("/api/cases/CASE-RET-003/authority").json()
    assert authority[-1]["decision"] == "DENY"

    resp = client.post("/api/cases", headers=AUTH_HEADERS, json={"case_id": "CASE-DOES-NOT-EXIST"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "CASE_FIXTURE_NOT_FOUND"


def test_wrong_role_cannot_decide_review(client):
    created = client.post("/api/cases", headers=AUTH_HEADERS).json()
    case_id = created["case_id"]
    review = next(r for r in client.get("/api/reviews").json() if r["case_id"] == case_id)

    wrong_role_headers = {"Authorization": "Bearer wrong-role-token"}
    import app.auth as auth_module

    auth_module._TOKEN_MAP["wrong-role-token"] = auth_module.Principal("mallory", "finance-ops")
    try:
        resp = client.post(
            f"/api/reviews/{review['review_id']}/decision",
            headers=wrong_role_headers,
            json={"decision": "APPROVE_ESCALATION", "idempotency_key": "key-x"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["error_code"] == "ROLE_NOT_PERMITTED"
    finally:
        del auth_module._TOKEN_MAP["wrong-role-token"]


def test_evaluation_and_release_endpoints(client):
    eval_resp = client.post("/api/evaluations/run")
    assert eval_resp.status_code == 200
    body = eval_resp.json()
    assert body["total_cases"] == 28

    fetched = client.get(f"/api/evaluations/{body['evaluation_id']}")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["dataset_version"] == body["dataset_version"]
    assert fetched_body["environment"] == "dev"
    assert set(fetched_body["per_agent_slice"].keys()) == {
        "AGENT-SUPERVISOR-V1",
        "AGENT-RETRIEVAL-V1",
        "AGENT-CRITIC-V1",
    }

    release = client.get("/api/releases/latest")
    assert release.status_code == 200
    assert release.json()["decision"] == "PASS"
    assert release.json()["regression_fixture_check"]["decision"] == "BLOCK"
    assert set(release.json()["agent_definition_ids"]) == {
        "AGENT-SUPERVISOR-V1",
        "AGENT-RETRIEVAL-V1",
        "AGENT-CRITIC-V1",
    }


def test_agent_definitions_and_agent_runs_endpoints(client):
    definitions = client.get("/api/agent-definitions").json()
    assert {d["agent_id"] for d in definitions} == {
        "AGENT-SUPERVISOR-V1",
        "AGENT-RETRIEVAL-V1",
        "AGENT-CRITIC-V1",
    }
    assert all(d["provider"] == "DETERMINISTIC" for d in definitions)

    created = client.post("/api/cases", headers=AUTH_HEADERS).json()
    case_id = created["case_id"]

    runs = client.get(f"/api/cases/{case_id}/agent-runs").json()
    assert len(runs) == 3
    by_agent = {r["agent_id"]: r for r in runs}
    supervisor = by_agent["AGENT-SUPERVISOR-V1"]
    retrieval = by_agent["AGENT-RETRIEVAL-V1"]
    critic = by_agent["AGENT-CRITIC-V1"]

    assert supervisor["parent_run_id"] is None
    assert retrieval["parent_run_id"] == supervisor["agent_run_id"]
    assert critic["parent_run_id"] == supervisor["agent_run_id"]
    assert all(r["stage"] == "INVESTIGATE" for r in runs)
    assert all(r["termination_status"] == "COMPLETED" for r in runs)
    assert len(retrieval["steps"]) == 1
    assert retrieval["steps"][0]["tool_name"] == "fixture_lexical_search"

    missing = client.get("/api/cases/CASE-DOES-NOT-EXIST/agent-runs")
    assert missing.status_code == 404
    assert missing.json()["detail"]["error_code"] == "CASE_NOT_FOUND"


def test_evidence_endpoint_includes_relevance_score(client):
    created = client.post("/api/cases", headers=AUTH_HEADERS).json()
    evidence = client.get(f"/api/cases/{created['case_id']}/evidence").json()
    assert evidence
    assert all("relevance_score" in e and isinstance(e["relevance_score"], float) for e in evidence)


def test_guardrails_endpoint_returns_report_after_case_run(client):
    missing = client.get("/api/cases/CASE-DOES-NOT-EXIST/guardrails")
    assert missing.status_code == 404
    assert missing.json()["detail"]["error_code"] == "CASE_NOT_FOUND"

    created = client.post("/api/cases", headers=AUTH_HEADERS).json()
    case_id = created["case_id"]

    report = client.get(f"/api/cases/{case_id}/guardrails")
    assert report.status_code == 200
    body = report.json()
    assert body["case_id"] == case_id
    assert body["ungrounded_count"] == 0
    assert body["summary_sentences"]
    assert all(s["grounded"] for s in body["summary_sentences"])
    assert isinstance(body["relevance_scores"], dict) and body["relevance_scores"]
