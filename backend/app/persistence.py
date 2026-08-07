"""Persist deterministic pipeline artifacts (app.services.workflow.CaseArtifacts)
to the relational schema in app.orm_models.

Re-running the same case replaces its prior rows in a single transaction and
bumps `state_version`, rather than silently overwriting fields in place, so a
stale writer can be detected by comparing versions before it commits.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.orm_models import (
    AuthorityRecordORM,
    CaseORM,
    ClaimORM,
    EvaluationRunORM,
    EvidenceORM,
    OutcomeORM,
    ReleaseRecordORM,
    ReviewTaskORM,
    SourceSnapshotORM,
    TraceEventORM,
)
from app.services.workflow import CaseArtifacts


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def persist_case_run(session: Session, artifacts: CaseArtifacts) -> CaseORM:
    case_id = artifacts.case["case_id"]

    for snapshot in artifacts.snapshots:
        existing = session.get(SourceSnapshotORM, snapshot.source_id)
        if existing is None:
            session.add(
                SourceSnapshotORM(
                    source_id=snapshot.source_id,
                    url=snapshot.url,
                    title=snapshot.title,
                    source_class=snapshot.source_class,
                    retrieved_at=snapshot.retrieved_at,
                    effective_at=snapshot.effective_at,
                    content_hash=snapshot.content_hash,
                    version=snapshot.version,
                    allowed_for_evidence=snapshot.allowed_for_evidence,
                )
            )

    existing_case = session.get(CaseORM, case_id)
    next_version = existing_case.state_version + 1 if existing_case else 1
    if existing_case is not None:
        session.delete(existing_case)
        session.flush()

    case_row = CaseORM(
        case_id=case_id,
        as_of=_parse_dt(artifacts.case["as_of"]),
        order_ref=artifacts.case["order_ref"],
        seller_ref=artifacts.case["seller_ref"],
        product_ref=artifacts.case["product_ref"],
        risk_band=artifacts.case["risk_band"],
        status=artifacts.termination_status.value,
        source_refs=artifacts.case["source_refs"],
        state_version=next_version,
    )
    session.add(case_row)

    for e in artifacts.evidence:
        session.add(
            EvidenceORM(
                evidence_id=e.evidence_id,
                case_id=case_id,
                source_id=e.source_id,
                source_version=None,
                locator=e.locator,
                excerpt=e.excerpt,
                excerpt_kind=e.excerpt_kind,
                content_hash=e.content_hash,
                authority_status=e.authority_status,
                entity_binding_status=e.entity_binding_status,
                support_status=e.support_status,
                validation_reasons=e.validation_reasons,
            )
        )

    for c in artifacts.claims:
        session.add(
            ClaimORM(
                claim_id=c.claim_id,
                case_id=case_id,
                claim_type=c.claim_type,
                status=c.status,
                evidence_ids=c.evidence_ids,
                counter_evidence_ids=c.counter_evidence_ids,
                rule_version=c.rule_version,
                reason_codes=c.reason_codes,
            )
        )

    authority = artifacts.authority
    session.add(
        AuthorityRecordORM(
            authority_id=authority.authority_id,
            case_id=case_id,
            proposed_action=authority.proposed_action,
            decision=authority.decision,
            reason_codes=authority.reason_codes,
            required_role=authority.required_role,
            expires_at=authority.expires_at,
            policy_version=authority.policy_version,
        )
    )

    review = artifacts.review
    if review is not None:
        session.add(
            ReviewTaskORM(
                review_id=review.review_id,
                case_id=case_id,
                status=review.status,
                reason_codes=review.reason_codes,
                assigned_role=review.assigned_role,
                reviewer_id=review.reviewer_id,
                reviewer_decision=review.reviewer_decision,
                reviewer_notes=review.reviewer_notes,
            )
        )

    outcome = artifacts.outcome
    session.add(
        OutcomeORM(
            outcome_id=outcome.outcome_id,
            case_id=case_id,
            attempt_id=outcome.attempt_id,
            intended_action=outcome.intended_action,
            observed_result=outcome.observed_result,
            reconciliation_status=outcome.reconciliation_status,
            mismatch_reason=outcome.mismatch_reason,
        )
    )

    for t in artifacts.trace_events:
        session.add(
            TraceEventORM(
                trace_id=t.trace_id,
                case_id=case_id,
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
        )

    session.commit()
    return case_row


def get_case(session: Session, case_id: str) -> CaseORM | None:
    return session.get(CaseORM, case_id)


def persist_evaluation_run(session: Session, evaluation_id: str, evaluation: dict) -> EvaluationRunORM:
    row = EvaluationRunORM(
        evaluation_id=evaluation_id,
        dataset_version=evaluation["dataset_version"],
        total_cases=evaluation["total_cases"],
        critical_positive_total=evaluation["critical_positive_total"],
        critical_positive_recovered=evaluation["critical_positive_recovered"],
        critical_recall=evaluation["critical_recall"],
        critical_recall_wilson_lower_bound_95=evaluation["critical_recall_wilson_lower_bound_95"],
        false_authorisation_count=evaluation["false_authorisation_count"],
        wrong_entity_evidence_admitted_count=evaluation["wrong_entity_evidence_admitted_count"],
        prompt_injection_altered_decision_count=evaluation["prompt_injection_altered_decision_count"],
        per_slice=evaluation["per_slice"],
    )
    session.add(row)
    session.commit()
    return row


def persist_release_record(
    session: Session, release_id: str, release: dict, evaluation_id: str | None
) -> ReleaseRecordORM:
    row = ReleaseRecordORM(
        release_id=release_id,
        config_name=release["config_name"],
        decision=release["decision"],
        reason_codes=release["reason_codes"],
        thresholds_version=release["thresholds_version"],
        dataset_version=release["dataset_version"],
        evaluation_id=evaluation_id,
    )
    session.add(row)
    session.commit()
    return row
