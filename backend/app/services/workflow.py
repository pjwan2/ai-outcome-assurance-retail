"""Deterministic CASE -> INVESTIGATE -> VALIDATE -> RESOLVE -> AUTHORISE -> RECONCILE
pipeline for the synthetic laptop-refund hero case.

This is the offline, deterministic vertical slice described in the AI Outcome
Assurance implementation prompt. No model calls are made; every claim and
authority decision is produced by typed application code so the run is fully
reproducible.

This module is the thin orchestrator: each stage's actual logic lives in a
sibling module (`app.services.validate`, `.resolve`, `.authorise`) plus
`app.agents` for INVESTIGATE and `app.guardrails` for the non-authoritative
guardrail report — `run_case_pipeline` below just calls them in order and
records the trace.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.agents import InvestigationResult, SupervisorPlanner
from app.budget import BudgetExceededError, RunBudget
from app.guardrails import run_guardrails
from app.models import (
    AgentHandoff,
    AgentRun,
    AgentStep,
    AuthorityDecision,
    AuthorityRecord,
    Claim,
    Evidence,
    GuardrailReport,
    Outcome,
    ReviewTask,
    SourceSnapshot,
    TerminationStatus,
    TraceEvent,
)
from app.services.authorise import POLICY_VERSION, authorise_case
from app.services.fixtures import (
    UnknownCaseError,
    list_available_case_ids,
    load_case_fixture,
    load_fixture,
)
from app.services.resolve import resolve_claims
from app.services.trace import TraceRecorder, verify_trace_chain
from app.services.validate import validate_evidence
from app.state_machine import CaseStatus

__all__ = [
    "CaseArtifacts",
    "UnknownCaseError",
    "list_available_case_ids",
    "load_case_fixture",
    "run_case_pipeline",
    "run_case_workflow",
    "verify_trace_chain",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


_SUPERVISOR = SupervisorPlanner()


def _investigate(
    case: dict[str, Any], sources: list[dict[str, Any]], trace: TraceRecorder, budget: RunBudget
) -> InvestigationResult:
    """Delegate to the SupervisorPlanner (app.agents), which orchestrates a
    RetrievalAgent (candidate lookup) and a CriticAgent (independent binding
    review) under this case's INVESTIGATE stage, producing durable
    AgentRun/AgentStep/AgentHandoff records.

    Candidates are unverified: VALIDATE decides whether they are admissible
    evidence (ADR-0001). The retrieval agent's fixture lookup consumes one
    unit of the run's tool-call budget; exhausting it raises
    BudgetExceededError (app.agents.InvestigationBudgetExceeded, a subclass
    carrying the partial agent-run records for audit).
    """
    return _SUPERVISOR.run(case, sources, trace, budget)


def _create_review_task(case: dict[str, Any], authority: AuthorityRecord, trace: TraceRecorder) -> ReviewTask | None:
    """Create a review task only when the authority decision requires one.
    A DENY on a resolved (non-UNKNOWN) claim is a valid controlled outcome
    that does not need human review."""
    if authority.decision != AuthorityDecision.REQUIRE_HUMAN:
        trace.record("AUTHORISE", "REVIEW_NOT_REQUIRED", evidence_ids=[])
        return None

    primary_reason = (
        "MISSING_FAULT_EVIDENCE" if "FAULT_STATUS_UNKNOWN" in authority.reason_codes else authority.reason_codes[0]
    )
    ordered_reasons = [primary_reason] + [r for r in authority.reason_codes if r != primary_reason]
    task = ReviewTask(
        review_id=f"REVIEW-{case['case_id']}",
        case_id=case["case_id"],
        status="PENDING",
        reason_codes=ordered_reasons,
        assigned_role="retail-operations",
        reviewer_id=None,
        reviewer_decision=None,
        reviewer_notes=None,
    )
    trace.record("AUTHORISE", "REVIEW_TASK_CREATED", evidence_ids=[])
    return task


def _reconcile(case: dict[str, Any], authority: AuthorityRecord, trace: TraceRecorder) -> Outcome:
    outcome = Outcome(
        outcome_id=f"OUTCOME-{case['case_id']}-1",
        case_id=case["case_id"],
        attempt_id=f"ATTEMPT-{case['case_id']}-1",
        intended_action=authority.proposed_action,
        observed_result="PENDING_HUMAN_REVIEW",
        reconciliation_status="PENDING",
        mismatch_reason=None,
    )
    trace.record("RECONCILE", "OUTCOME_RECORDED")
    return outcome


class CaseArtifacts:
    """Raw typed objects produced by one deterministic pipeline run, before
    they are serialised for the API or persisted to the database."""

    def __init__(
        self,
        case: dict[str, Any],
        snapshots: list[SourceSnapshot],
        evidence: list[Evidence],
        claims: list[Claim],
        authority: AuthorityRecord,
        review: ReviewTask | None,
        outcome: Outcome,
        termination_status: TerminationStatus,
        trace_events: list[TraceEvent],
        agent_runs: list[AgentRun] | None = None,
        agent_steps: list[AgentStep] | None = None,
        agent_handoffs: list[AgentHandoff] | None = None,
        guardrail_report: GuardrailReport | None = None,
    ) -> None:
        self.case = case
        self.snapshots = snapshots
        self.evidence = evidence
        self.claims = claims
        self.authority = authority
        self.review = review
        self.outcome = outcome
        self.termination_status = termination_status
        self.trace_events = trace_events
        self.agent_runs = agent_runs or []
        self.agent_steps = agent_steps or []
        self.agent_handoffs = agent_handoffs or []
        self.guardrail_report = guardrail_report


def run_case_pipeline(
    case: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    budget: RunBudget | None = None,
    case_id: str | None = None,
) -> CaseArtifacts:
    """Run the deterministic pipeline end to end and return the raw typed
    artifacts (case, evidence, claims, authority, review, outcome, trace).

    Defaults to the hero-case fixture (CASE-RET-001). Pass `case_id` to run
    any other fixture from `list_available_case_ids()`, or pass `case`/
    `sources` explicitly to run the rules against an ad hoc fixture, e.g. an
    evaluation or adversarial-test case. Use `run_case_workflow` for a
    JSON-serialisable summary of the default hero case, or
    `app.persistence.persist_case_run` to write artifacts to the database.
    If `budget` is exhausted, the run terminates with
    TerminationStatus.CONTROL_BLOCKED rather than raising — a stopped
    workflow is a valid controlled outcome."""
    if case is None:
        case, loaded_sources = load_case_fixture(case_id or "CASE-RET-001")
        if sources is None:
            sources = loaded_sources
    if sources is None:
        sources = load_fixture("source_manifest.json")["sources"]
    if budget is None:
        budget = RunBudget()

    trace = TraceRecorder(case["case_id"])
    trace.record("CASE", "CASE_CREATED")
    case_status = CaseStatus.CREATED
    case_status = trace.transition(case_status, CaseStatus.INVESTIGATING)

    try:
        investigation = _investigate(case, sources, trace, budget)
    except BudgetExceededError as exc:
        trace.record("INVESTIGATE", "BUDGET_EXCEEDED", tool_name="fixture_lexical_search")
        return CaseArtifacts(
            case=case,
            snapshots=[],
            evidence=[],
            claims=[],
            authority=AuthorityRecord(
                authority_id=f"AUTH-{case['case_id']}",
                case_id=case["case_id"],
                proposed_action="NONE",
                decision=AuthorityDecision.REQUIRE_HUMAN,
                reason_codes=["BUDGET_EXCEEDED", str(exc.resource).upper()],
                required_role="retail-operations",
                expires_at=_now() + timedelta(days=7),
                policy_version=POLICY_VERSION,
            ),
            review=None,
            outcome=Outcome(
                outcome_id=f"OUTCOME-{case['case_id']}-1",
                case_id=case["case_id"],
                attempt_id=f"ATTEMPT-{case['case_id']}-1",
                intended_action="NONE",
                observed_result="BUDGET_EXCEEDED",
                reconciliation_status="NOT_ATTEMPTED",
                mismatch_reason=None,
            ),
            termination_status=TerminationStatus.CONTROL_BLOCKED,
            trace_events=trace.events,
            agent_runs=getattr(exc, "agent_runs", []),
        )

    candidates = investigation.candidates
    snapshots, evidence = validate_evidence(case, candidates, trace)
    case_status = trace.transition(case_status, CaseStatus.EVIDENCE_VALIDATED)

    claims = resolve_claims(case, evidence, trace)
    case_status = trace.transition(case_status, CaseStatus.CLAIMS_RESOLVED)

    # Guardrails read only `claims`/`evidence` and produce a report the
    # operator can see — `authorise_case` below is untouched by this call and
    # still reads only `claims`, so guardrail findings structurally cannot
    # influence the authority decision (ADR-0006, mirroring ADR-0001/0003).
    guardrail_report = run_guardrails(case, evidence, claims, trace)

    authority = authorise_case(case, claims, trace)
    case_status = trace.transition(case_status, CaseStatus.AUTHORITY_EVALUATED)

    review = _create_review_task(case, authority, trace)
    outcome = _reconcile(case, authority, trace)

    if review is not None:
        case_status = trace.transition(case_status, CaseStatus.NEEDS_REVIEW)
        termination_status = TerminationStatus.NEEDS_REVIEW
    else:
        case_status = trace.transition(case_status, CaseStatus.READY_TO_RECONCILE)
        case_status = trace.transition(case_status, CaseStatus.COMPLETED)
        termination_status = TerminationStatus.COMPLETED

    trace.record("RECONCILE", "CASE_TERMINATED")

    return CaseArtifacts(
        case=case,
        snapshots=snapshots,
        evidence=evidence,
        claims=claims,
        authority=authority,
        review=review,
        outcome=outcome,
        termination_status=termination_status,
        trace_events=trace.events,
        agent_runs=investigation.agent_runs,
        agent_steps=investigation.agent_steps,
        agent_handoffs=investigation.agent_handoffs,
        guardrail_report=guardrail_report,
    )


def run_case_workflow() -> dict[str, Any]:
    """Run the deterministic hero-case pipeline end to end and return a
    JSON-serialisable summary suitable for the API and tests."""
    artifacts = run_case_pipeline()
    case, evidence, claims, authority, review, outcome, termination_status, trace_events = (
        artifacts.case,
        artifacts.evidence,
        artifacts.claims,
        artifacts.authority,
        artifacts.review,
        artifacts.outcome,
        artifacts.termination_status,
        artifacts.trace_events,
    )

    return {
        "case_id": case["case_id"],
        "termination_status": termination_status.value,
        "authority_decision": authority.decision.value,
        "proposed_action": authority.proposed_action,
        "authority_reason_codes": authority.reason_codes,
        "review_reason_code": review.reason_codes[0] if review else None,
        "review_owner": review.assigned_role if review else None,
        "claims": [
            {
                "claim_type": c.claim_type,
                "status": c.status.value,
                "reason_codes": c.reason_codes,
                "evidence_ids": c.evidence_ids,
            }
            for c in claims
        ],
        "evidence": [
            {
                "evidence_id": e.evidence_id,
                "source_id": e.source_id,
                "authority_status": e.authority_status,
                "entity_binding_status": e.entity_binding_status,
                "support_status": e.support_status,
                "validation_reasons": e.validation_reasons,
            }
            for e in evidence
        ],
        "outcome": {
            "intended_action": outcome.intended_action,
            "observed_result": outcome.observed_result,
            "reconciliation_status": outcome.reconciliation_status,
        },
        "trace_events": len(trace_events),
        "trace": [{"sequence": t.sequence, "stage": t.stage, "event_type": t.event_type} for t in trace_events],
    }
