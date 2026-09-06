"""Persist deterministic pipeline artifacts (app.services.workflow.CaseArtifacts)
to the relational schema in app.orm_models.

Re-running the same case replaces its prior rows in a single transaction and
bumps `state_version`, rather than silently overwriting fields in place, so a
stale writer can be detected by comparing versions before it commits.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.agents import REGISTERED_AGENTS
from app.orm_models import (
    AgentDefinitionORM,
    AgentHandoffORM,
    AgentRunORM,
    AgentStepORM,
    AuthorityRecordORM,
    CaseORM,
    ClaimORM,
    EvaluationRunORM,
    EvidenceORM,
    GuardrailReportORM,
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

    # Same atomic-upsert reasoning as the agent-definitions registry below:
    # a check-then-insert here races under concurrent requests for the same
    # source_id (e.g. two overlapping runs of the same fixture case), and
    # the source_snapshots table is shared across every case, not scoped to
    # this one — a plain `get()`-then-`add()` was confirmed to raise
    # sqlite3.IntegrityError under React 18 StrictMode's double-invoked
    # mount effect (two concurrent POST /api/cases for the same hero case).
    for snapshot in artifacts.snapshots:
        session.execute(
            sqlite_insert(SourceSnapshotORM)
            .values(
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
            .on_conflict_do_nothing(index_elements=["source_id"])
        )

    # `INSERT ... ON CONFLICT DO NOTHING` rather than `get()`-then-`add()`:
    # the registry is a small, fixed set of rows touched by every single
    # persisted run, so a check-then-insert here is a real, easily-hit race
    # under concurrent requests (two overlapping `POST /api/cases` — e.g.
    # React 18 StrictMode double-invoking its mount effect in dev — both see
    # "not present yet" and both try to insert, and the loser gets a raw
    # UNIQUE-constraint IntegrityError instead of a handled outcome). The
    # atomic upsert removes the race instead of narrowing its window.
    for defn in REGISTERED_AGENTS:
        session.execute(
            sqlite_insert(AgentDefinitionORM)
            .values(
                agent_id=defn.agent_id,
                name=defn.name,
                role=defn.role.value,
                provider=defn.provider.value,
                config_hash=defn.config_hash,
                model_name=defn.model_name,
                model_version=defn.model_version,
                prompt_version=defn.prompt_version,
                is_active=defn.is_active,
            )
            .on_conflict_do_nothing(index_elements=["agent_id"])
        )

    existing_case = session.get(CaseORM, case_id)
    next_version = existing_case.state_version + 1 if existing_case else 1
    if existing_case is not None:
        # AgentHandoffORM rows aren't reachable through an ORM relationship
        # from Case, so the `cascade="all, delete-orphan"` on Case.agent_runs
        # won't clean them up on replay — delete them explicitly rather than
        # relying on SQLite's FK ondelete=CASCADE, which is off by default.
        old_run_ids = [r.agent_run_id for r in existing_case.agent_runs]
        if old_run_ids:
            session.query(AgentHandoffORM).filter(AgentHandoffORM.parent_run_id.in_(old_run_ids)).delete(
                synchronize_session=False
            )
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
                relevance_score=e.relevance_score,
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

    for run in artifacts.agent_runs:
        session.add(
            AgentRunORM(
                agent_run_id=run.agent_run_id,
                case_id=case_id,
                agent_id=run.agent_id,
                parent_run_id=run.parent_run_id,
                stage=run.stage,
                max_tool_calls=run.max_tool_calls,
                max_steps=run.max_steps,
                max_wall_clock_seconds=run.max_wall_clock_seconds,
                tool_calls_used=run.tool_calls_used,
                steps_used=run.steps_used,
                termination_status=run.termination_status.value if run.termination_status else None,
                termination_reason_codes=run.termination_reason_codes,
                token_usage_prompt=run.token_usage_prompt,
                token_usage_completion=run.token_usage_completion,
                cost_usd=run.cost_usd,
                started_at=run.started_at,
                ended_at=run.ended_at,
            )
        )

    for step in artifacts.agent_steps:
        session.add(
            AgentStepORM(
                step_id=step.step_id,
                agent_run_id=step.agent_run_id,
                sequence=step.sequence,
                step_type=step.step_type,
                tool_name=step.tool_name,
                tool_input_hash=step.tool_input_hash,
                tool_output_hash=step.tool_output_hash,
                candidate_evidence_ids=step.candidate_evidence_ids,
                latency_ms=step.latency_ms,
                timestamp=step.timestamp,
            )
        )

    for handoff in artifacts.agent_handoffs:
        session.add(
            AgentHandoffORM(
                handoff_id=handoff.handoff_id,
                parent_run_id=handoff.parent_run_id,
                child_run_id=handoff.child_run_id,
                from_agent_id=handoff.from_agent_id,
                to_agent_id=handoff.to_agent_id,
                delegated_task=handoff.delegated_task,
                reason_codes=handoff.reason_codes,
                created_at=handoff.created_at,
            )
        )

    report = artifacts.guardrail_report
    if report is not None:
        session.add(
            GuardrailReportORM(
                report_id=report.report_id,
                case_id=case_id,
                input_findings=[asdict(f) for f in report.input_findings],
                relevance_scores=report.relevance_scores,
                summary_sentences=[asdict(s) for s in report.summary_sentences],
                ungrounded_count=report.ungrounded_count,
                created_at=report.generated_at,
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
        code_version=evaluation.get("code_version"),
        environment=evaluation.get("environment", "dev"),
        provider_versions=evaluation.get("provider_versions"),
        per_agent_slice=evaluation.get("per_agent_slice"),
        baseline_evaluation_id=evaluation.get("baseline_evaluation_id"),
        mean_retrieval_relevance=evaluation.get("mean_retrieval_relevance"),
        groundedness_pass_rate=evaluation.get("groundedness_pass_rate"),
        pii_redaction_count=evaluation.get("pii_redaction_count"),
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
        approved_by=release.get("approved_by"),
        approved_at=release.get("approved_at"),
        approval_notes=release.get("approval_notes"),
        rollback_of=release.get("rollback_of"),
        agent_definition_ids=release.get("agent_definition_ids", []),
    )
    session.add(row)
    session.commit()
    return row
