"""PRD section 19 adversarial tests. Validators and the authority engine are
never mocked here; only provider API calls would be mocked (none are used in
this offline suite).
"""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.authority_enforcement import UnauthorisedActionError, enforce_action
from app.budget import RunBudget
from app.db import Base
from app.models import AuthorityDecision
from app.orm_models import ReviewTaskORM
from app.reconcile import reconcile_observed_result
from app.reviews import ReviewAlreadyDecidedError, decide_review
from app.services.workflow import run_case_pipeline
from app.state_machine import CaseStatus, InvalidTransitionError, validate_transition
from app.tools import InvalidToolArgumentsError, UnknownToolError, validate_tool_call

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "app" / "fixtures"
SOURCES = {s["source_id"]: s for s in json.loads((FIXTURES_DIR / "eval_sources.json").read_text())["sources"]}


def _case(case_id: str, source_refs: list[str], **overrides) -> dict:
    base = json.loads((FIXTURES_DIR / "synthetic_case.json").read_text())
    base["case_id"] = case_id
    base["source_refs"] = source_refs
    base.update(overrides)
    return base


def _sources_for(refs: list[str]) -> list[dict]:
    return [SOURCES[r] for r in refs]


# 1. Wrong seller with otherwise similar policy text
def test_wrong_seller_fails_safe_to_require_human():
    case = _case("ADV-01", ["SRC-KOGAN-GUARANTEE", "SRC-ACCC-RIGHTS"], seller_ref="SELLER-FRAUD")
    artifacts = run_case_pipeline(case, _sources_for(case["source_refs"]))
    assert artifacts.authority.decision == AuthorityDecision.REQUIRE_HUMAN
    order_claim = next(c for c in artifacts.claims if c.claim_type == "ORDER_AND_SELLER_VERIFIED")
    assert order_claim.status.value == "FALSE"
    assert "WRONG_SELLER_BINDING" in order_claim.reason_codes


# 2. Wrong order binding
def test_wrong_order_fails_safe_to_require_human():
    case = _case("ADV-02", ["SRC-KOGAN-GUARANTEE", "SRC-ACCC-RIGHTS"], order_ref="ORD-FRAUD")
    artifacts = run_case_pipeline(case, _sources_for(case["source_refs"]))
    assert artifacts.authority.decision == AuthorityDecision.REQUIRE_HUMAN


# 3. Stale or mismatched source version
def test_stale_source_is_rejected_as_evidence():
    case = _case("ADV-03", ["SRC-KOGAN-STALE", "SRC-ACCC-RIGHTS"])
    artifacts = run_case_pipeline(case, _sources_for(case["source_refs"]))
    stale_evidence = next(e for e in artifacts.evidence if e.source_id == "SRC-KOGAN-STALE")
    assert "SOURCE_STALE_OR_OUT_OF_TIME" in stale_evidence.validation_reasons
    assert artifacts.authority.decision == AuthorityDecision.REQUIRE_HUMAN


def test_source_version_mismatch_is_rejected():
    case = _case(
        "ADV-03B",
        ["SRC-KOGAN-WRONGVERSION", "SRC-ACCC-RIGHTS"],
        expected_source_versions={"SRC-KOGAN-WRONGVERSION": "v1"},
    )
    artifacts = run_case_pipeline(case, _sources_for(case["source_refs"]))
    ev = next(e for e in artifacts.evidence if e.source_id == "SRC-KOGAN-WRONGVERSION")
    assert "SOURCE_VERSION_MISMATCH" in ev.validation_reasons


# 4. Missing exact locator
def test_missing_locator_is_rejected():
    case = _case("ADV-04", ["SRC-KOGAN-NO-LOCATOR", "SRC-ACCC-RIGHTS"])
    artifacts = run_case_pipeline(case, _sources_for(case["source_refs"]))
    ev = next(e for e in artifacts.evidence if e.source_id == "SRC-KOGAN-NO-LOCATOR")
    assert "LOCATOR_NOT_FOUND" in ev.validation_reasons


# 5. Fabricated evidence ID
def test_fabricated_source_reference_yields_no_candidate():
    case = _case("ADV-05", ["SRC-DOES-NOT-EXIST"])
    artifacts = run_case_pipeline(case, [])
    assert artifacts.evidence == []
    assert artifacts.authority.decision == AuthorityDecision.REQUIRE_HUMAN


# 6. Prompt injection inside retrieved content
def test_prompt_injection_content_is_flagged_but_never_changes_authority():
    case = _case("ADV-06", ["SRC-INJECTION", "SRC-ACCC-RIGHTS"])
    artifacts = run_case_pipeline(case, _sources_for(case["source_refs"]))
    injected = next(e for e in artifacts.evidence if e.source_id == "SRC-INJECTION")
    assert "PROMPT_INJECTION_CONTENT" in injected.validation_reasons
    assert artifacts.authority.decision != AuthorityDecision.ALLOW
    assert artifacts.authority.decision == AuthorityDecision.REQUIRE_HUMAN


# 7. Contradictory evidence
def test_contradictory_fault_assessments_resolve_to_unknown():
    case = _case(
        "ADV-07",
        ["SRC-KOGAN-GUARANTEE", "SRC-ACCC-RIGHTS", "SRC-FAULT-CONTRA-A", "SRC-FAULT-CONTRA-B"],
    )
    artifacts = run_case_pipeline(case, _sources_for(case["source_refs"]))
    major_failure = next(c for c in artifacts.claims if c.claim_type == "MAJOR_FAILURE_ESTABLISHED")
    assert major_failure.status.value == "UNKNOWN"
    assert "CONTRADICTION_PRESENT" in major_failure.reason_codes


# 8. Missing fault assessment
def test_missing_fault_assessment_keeps_major_failure_unknown():
    case = _case("ADV-08", ["SRC-KOGAN-GUARANTEE", "SRC-ACCC-RIGHTS"])
    artifacts = run_case_pipeline(case, _sources_for(case["source_refs"]))
    major_failure = next(c for c in artifacts.claims if c.claim_type == "MAJOR_FAILURE_ESTABLISHED")
    assert major_failure.status.value == "UNKNOWN"


# 9. Model proposes an unknown tool
def test_unknown_tool_is_rejected():
    with pytest.raises(UnknownToolError):
        validate_tool_call("delete_all_records", {"case_id": "X"})


# 10. Model proposes extra tool arguments
def test_extra_tool_arguments_are_rejected():
    with pytest.raises(InvalidToolArgumentsError):
        validate_tool_call("fixture_lexical_search", {"case_id": "X", "unexpected_field": "value"})


# 11. Invalid state transition
def test_invalid_state_transition_fails_closed():
    with pytest.raises(InvalidTransitionError):
        validate_transition(CaseStatus.CREATED, CaseStatus.COMPLETED)


def test_valid_state_transition_succeeds():
    validate_transition(CaseStatus.CREATED, CaseStatus.INVESTIGATING)


# 12. Retry of a non-idempotent action / 14. Review decision replay/idempotency
def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_review_decision_replay_is_idempotent():
    review = ReviewTaskORM(
        review_id="REVIEW-ADV-12",
        case_id="ADV-12",
        status="PENDING",
        reason_codes=["MISSING_FAULT_EVIDENCE"],
        assigned_role="retail-operations",
    )
    decide_review(review, "reviewer-1", "REQUEST_MORE_EVIDENCE", "please escalate", "key-abc")
    assert review.status == "DECIDED"

    # replay with the same idempotency key: no error, no re-mutation conflict
    decide_review(review, "reviewer-1", "REQUEST_MORE_EVIDENCE", "please escalate", "key-abc")
    assert review.reviewer_decision == "REQUEST_MORE_EVIDENCE"


def test_conflicting_second_review_decision_is_rejected():
    review = ReviewTaskORM(
        review_id="REVIEW-ADV-12B",
        case_id="ADV-12B",
        status="PENDING",
        reason_codes=["MISSING_FAULT_EVIDENCE"],
        assigned_role="retail-operations",
    )
    decide_review(review, "reviewer-1", "REQUEST_MORE_EVIDENCE", None, "key-1")
    with pytest.raises(ReviewAlreadyDecidedError):
        decide_review(review, "reviewer-2", "REJECT_ROUTE", None, "key-2")


# 13. Budget exhaustion
def test_budget_exhaustion_produces_control_blocked_termination():
    case = _case("ADV-13", ["SRC-KOGAN-GUARANTEE", "SRC-ACCC-RIGHTS"])
    artifacts = run_case_pipeline(case, _sources_for(case["source_refs"]), budget=RunBudget(max_tool_calls=0))
    assert artifacts.termination_status.value == "CONTROL_BLOCKED"
    assert "BUDGET_EXCEEDED" in artifacts.authority.reason_codes
    assert artifacts.review is None


# 15. Intended outcome differs from observed result
def test_outcome_mismatch_is_recorded_not_silently_overwritten():
    case = _case("ADV-15", ["SRC-KOGAN-GUARANTEE", "SRC-ACCC-RIGHTS"])
    artifacts = run_case_pipeline(case, _sources_for(case["source_refs"]))
    reconciled = reconcile_observed_result(artifacts.outcome, "REVIEWER_REJECTED_ROUTE")
    assert reconciled.reconciliation_status == "MISMATCH"
    assert reconciled.mismatch_reason is not None
    assert reconciled.intended_action == artifacts.outcome.intended_action


# 16. Attempted auto-refund when authority is REQUIRE_HUMAN
def test_auto_refund_blocked_when_authority_requires_human():
    case = _case("ADV-16", ["SRC-KOGAN-GUARANTEE", "SRC-ACCC-RIGHTS"])
    artifacts = run_case_pipeline(case, _sources_for(case["source_refs"]))
    assert artifacts.authority.decision == AuthorityDecision.REQUIRE_HUMAN
    with pytest.raises(UnauthorisedActionError):
        enforce_action(artifacts.authority, "AUTO_REFUND")
