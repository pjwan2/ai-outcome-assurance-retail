from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import Principal, require_auth
from app.db import Base, SessionLocal, engine
from app.evaluation import run_evaluation
from app.models import TraceEvent
from app.orm_models import CaseORM, ReviewTaskORM
from app.persistence import (
    persist_case_run,
    persist_evaluation_run,
    persist_release_record,
)
from app.release_gate import run_regression_release_gate, run_release_gate
from app.reviews import ReviewAlreadyDecidedError, decide_review
from app.services.workflow import (
    list_available_case_ids,
    run_case_pipeline,
    run_case_workflow,
    verify_trace_chain,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="AI Outcome Assurance", lifespan=lifespan)

# Local-demo CORS: the operator UI (Vite dev server) runs on a different port
# than the API, so browsers issue CORS preflight requests for every mutating
# call. Wide open here because this is a same-machine offline demo with no
# auth and no real user data — see docs/security.md.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class ErrorResponse(BaseModel):
    error_code: str
    message: str


def _error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error_code": error_code, "message": message})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(CaseORM.__table__.select().limit(1))
    return {"status": "ok"}


@app.get("/case-demo")
def case_demo() -> JSONResponse:
    return JSONResponse(content=run_case_workflow())


def _case_to_dict(case: CaseORM) -> dict:
    return {
        "case_id": case.case_id,
        "order_ref": case.order_ref,
        "seller_ref": case.seller_ref,
        "product_ref": case.product_ref,
        "risk_band": case.risk_band,
        "status": case.status,
        "state_version": case.state_version,
        "source_refs": case.source_refs,
        "created_at": case.created_at.isoformat() if case.created_at else None,
    }


class CreateCaseRequest(BaseModel):
    case_id: str = "CASE-RET-001"


@app.get("/api/case-fixtures")
def list_case_fixtures() -> dict:
    """Case IDs with a runnable, versioned fixture. There is no free-text
    case intake in this prototype — every case is one of these."""
    return {"case_ids": list_available_case_ids()}


@app.post("/api/cases", status_code=201)
def create_case(
    body: CreateCaseRequest = CreateCaseRequest(),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_auth),
) -> dict:
    """Runs the deterministic pipeline for the requested fixture case_id
    (default the hero case) and persists the resulting case."""
    if body.case_id not in list_available_case_ids():
        raise _error(404, "CASE_FIXTURE_NOT_FOUND", f"No runnable fixture for case_id {body.case_id}")
    artifacts = run_case_pipeline(case_id=body.case_id)
    case_row = persist_case_run(db, artifacts)
    return _case_to_dict(case_row)


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)) -> dict:
    case = db.get(CaseORM, case_id)
    if case is None:
        raise _error(404, "CASE_NOT_FOUND", f"No case with id {case_id}")
    return _case_to_dict(case)


@app.post("/api/cases/{case_id}/run")
def run_and_persist_case(
    case_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_auth)
) -> dict:
    if case_id not in list_available_case_ids():
        raise _error(404, "CASE_FIXTURE_NOT_FOUND", f"No runnable fixture for case_id {case_id}")
    artifacts = run_case_pipeline(case_id=case_id)
    case_row = persist_case_run(db, artifacts)
    return _case_to_dict(case_row)


@app.get("/api/cases/{case_id}/evidence")
def get_case_evidence(case_id: str, db: Session = Depends(get_db)) -> list[dict]:
    case = db.get(CaseORM, case_id)
    if case is None:
        raise _error(404, "CASE_NOT_FOUND", f"No case with id {case_id}")
    return [
        {
            "evidence_id": e.evidence_id,
            "source_id": e.source_id,
            "locator": e.locator,
            "excerpt": e.excerpt,
            "excerpt_kind": e.excerpt_kind,
            "authority_status": e.authority_status,
            "entity_binding_status": e.entity_binding_status,
            "support_status": e.support_status,
            "validation_reasons": e.validation_reasons,
        }
        for e in case.evidence
    ]


@app.get("/api/cases/{case_id}/claims")
def get_case_claims(case_id: str, db: Session = Depends(get_db)) -> list[dict]:
    case = db.get(CaseORM, case_id)
    if case is None:
        raise _error(404, "CASE_NOT_FOUND", f"No case with id {case_id}")
    return [
        {
            "claim_id": c.claim_id,
            "claim_type": c.claim_type,
            "status": c.status.value,
            "evidence_ids": c.evidence_ids,
            "counter_evidence_ids": c.counter_evidence_ids,
            "rule_version": c.rule_version,
            "reason_codes": c.reason_codes,
        }
        for c in case.claims
    ]


@app.get("/api/cases/{case_id}/authority")
def get_case_authority(case_id: str, db: Session = Depends(get_db)) -> list[dict]:
    case = db.get(CaseORM, case_id)
    if case is None:
        raise _error(404, "CASE_NOT_FOUND", f"No case with id {case_id}")
    return [
        {
            "authority_id": a.authority_id,
            "proposed_action": a.proposed_action,
            "decision": a.decision.value,
            "reason_codes": a.reason_codes,
            "required_role": a.required_role,
            "policy_version": a.policy_version,
        }
        for a in case.authority_records
    ]


@app.get("/api/cases/{case_id}/trace")
def get_case_trace(case_id: str, db: Session = Depends(get_db)) -> list[dict]:
    case = db.get(CaseORM, case_id)
    if case is None:
        raise _error(404, "CASE_NOT_FOUND", f"No case with id {case_id}")
    return [
        {
            "sequence": t.sequence,
            "stage": t.stage,
            "event_type": t.event_type,
            "tool_name": t.tool_name,
            "evidence_ids": t.evidence_ids,
            "argument_hash": t.argument_hash,
            "result_hash": t.result_hash,
            "state_before_hash": t.state_before_hash,
            "state_after_hash": t.state_after_hash,
            "timestamp": t.timestamp.isoformat() if t.timestamp else None,
        }
        for t in case.trace_events
    ]


@app.get("/api/cases/{case_id}/trace/verify")
def verify_case_trace(case_id: str, db: Session = Depends(get_db)) -> dict:
    """Recompute the trace's hash chain from its stored events and confirm
    nothing was inserted, reordered, or edited after the fact."""
    case = db.get(CaseORM, case_id)
    if case is None:
        raise _error(404, "CASE_NOT_FOUND", f"No case with id {case_id}")
    ordered = sorted(case.trace_events, key=lambda t: t.sequence)
    events = [
        TraceEvent(
            trace_id=t.trace_id,
            case_id=t.case_id,
            sequence=t.sequence,
            stage=t.stage,
            event_type=t.event_type,
            tool_name=t.tool_name,
            argument_hash=t.argument_hash,
            result_hash=t.result_hash,
            state_before_hash=t.state_before_hash,
            state_after_hash=t.state_after_hash,
            evidence_ids=t.evidence_ids,
            timestamp=t.timestamp,
        )
        for t in ordered
    ]
    return {"case_id": case_id, "event_count": len(events), "chain_verified": verify_trace_chain(case_id, events)}


@app.post("/api/cases/{case_id}/replay")
def replay_case(
    case_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_auth)
) -> dict:
    """Re-run the deterministic pipeline for this case from the same
    versioned fixtures and persist the replayed artifacts. Because the
    pipeline is deterministic, the replayed claims/authority decision must
    match the original run for the same rule/fixture version."""
    case = db.get(CaseORM, case_id)
    if case is None:
        raise _error(404, "CASE_NOT_FOUND", f"No case with id {case_id}")
    artifacts = run_case_pipeline(case_id=case_id)
    case_row = persist_case_run(db, artifacts)
    return _case_to_dict(case_row)


@app.get("/api/reviews")
def list_reviews(db: Session = Depends(get_db)) -> list[dict]:
    reviews = db.query(ReviewTaskORM).all()
    return [_review_to_dict(r) for r in reviews]


def _review_to_dict(r: ReviewTaskORM) -> dict:
    return {
        "review_id": r.review_id,
        "case_id": r.case_id,
        "status": r.status,
        "reason_codes": r.reason_codes,
        "assigned_role": r.assigned_role,
        "reviewer_id": r.reviewer_id,
        "reviewer_decision": r.reviewer_decision,
        "reviewer_notes": r.reviewer_notes,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
    }


@app.get("/api/reviews/{review_id}")
def get_review(review_id: str, db: Session = Depends(get_db)) -> dict:
    review = db.get(ReviewTaskORM, review_id)
    if review is None:
        raise _error(404, "REVIEW_NOT_FOUND", f"No review with id {review_id}")
    return _review_to_dict(review)


class ReviewDecisionRequest(BaseModel):
    decision: str
    notes: str | None = None
    idempotency_key: str


@app.post("/api/reviews/{review_id}/decision")
def post_review_decision(
    review_id: str,
    body: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_auth),
) -> dict:
    """Reviewer identity comes from the authenticated bearer token, never
    from a client-supplied field — a caller cannot decide a review as
    someone else. The caller's role must also match the review's
    assigned_role."""
    review = db.get(ReviewTaskORM, review_id)
    if review is None:
        raise _error(404, "REVIEW_NOT_FOUND", f"No review with id {review_id}")
    if principal.role != review.assigned_role:
        raise _error(
            403,
            "ROLE_NOT_PERMITTED",
            f"Role '{principal.role}' cannot decide a review assigned to '{review.assigned_role}'",
        )
    try:
        decide_review(review, principal.reviewer_id, body.decision, body.notes, body.idempotency_key)
    except ReviewAlreadyDecidedError as exc:
        raise _error(409, "REVIEW_ALREADY_DECIDED", str(exc)) from exc
    db.commit()
    return _review_to_dict(review)


@app.post("/api/evaluations/run")
def run_evaluation_endpoint(db: Session = Depends(get_db)) -> dict:
    evaluation = run_evaluation()
    evaluation_id = f"EVAL-{uuid.uuid4().hex[:12]}"
    persist_evaluation_run(db, evaluation_id, evaluation)
    return {"evaluation_id": evaluation_id, **{k: v for k, v in evaluation.items() if k != "results"}}


@app.get("/api/evaluations/{evaluation_id}")
def get_evaluation(evaluation_id: str, db: Session = Depends(get_db)) -> dict:
    from app.orm_models import EvaluationRunORM

    row = db.get(EvaluationRunORM, evaluation_id)
    if row is None:
        raise _error(404, "EVALUATION_NOT_FOUND", f"No evaluation with id {evaluation_id}")
    return {
        "evaluation_id": row.evaluation_id,
        "dataset_version": row.dataset_version,
        "total_cases": row.total_cases,
        "critical_positive_total": row.critical_positive_total,
        "critical_positive_recovered": row.critical_positive_recovered,
        "critical_recall": row.critical_recall,
        "critical_recall_wilson_lower_bound_95": row.critical_recall_wilson_lower_bound_95,
        "false_authorisation_count": row.false_authorisation_count,
        "wrong_entity_evidence_admitted_count": row.wrong_entity_evidence_admitted_count,
        "prompt_injection_altered_decision_count": row.prompt_injection_altered_decision_count,
        "per_slice": row.per_slice,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@app.get("/api/releases/latest")
def get_latest_release(db: Session = Depends(get_db)) -> dict:
    """Runs R1 and R2 fresh and persists both as release records, returning
    the R1 (candidate) decision as the latest release."""
    r1_evaluation = run_evaluation(disable_entity_binding_check=False)
    r1 = run_release_gate()
    r1_eval_id = f"EVAL-{uuid.uuid4().hex[:12]}"
    persist_evaluation_run(db, r1_eval_id, r1_evaluation)
    r1_release_id = f"RELEASE-{uuid.uuid4().hex[:12]}"
    persist_release_record(db, r1_release_id, r1, r1_eval_id)

    r2_evaluation = run_evaluation(disable_entity_binding_check=True)
    r2 = run_regression_release_gate()
    r2_eval_id = f"EVAL-{uuid.uuid4().hex[:12]}"
    persist_evaluation_run(db, r2_eval_id, r2_evaluation)
    r2_release_id = f"RELEASE-{uuid.uuid4().hex[:12]}"
    persist_release_record(db, r2_release_id, r2, r2_eval_id)

    return {"release_id": r1_release_id, **r1, "regression_fixture_check": {"release_id": r2_release_id, **r2}}
