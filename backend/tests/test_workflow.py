
from app.main import run_case_workflow


def test_run_case_workflow_returns_review_for_unknown_major_failure():
    result = run_case_workflow()

    assert result["case_id"].startswith("CASE-")
    assert result["termination_status"] == "NEEDS_REVIEW"
    assert result["authority_decision"] == "REQUIRE_HUMAN"
    assert result["review_reason_code"] == "MISSING_FAULT_EVIDENCE"
    assert result["review_owner"] == "retail-operations"
    assert result["trace_events"] >= 6
