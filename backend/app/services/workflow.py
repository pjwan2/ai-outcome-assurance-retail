"""Deterministic CASE -> INVESTIGATE -> VALIDATE -> RESOLVE -> AUTHORISE -> RECONCILE
pipeline for the synthetic laptop-refund hero case.

This is the offline, deterministic vertical slice described in the AI Outcome
Assurance implementation prompt. No model calls are made; every claim and
authority decision is produced by typed application code so the run is fully
reproducible.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.budget import BudgetExceededError, RunBudget
from app.models import (
    AuthorityDecision,
    AuthorityRecord,
    Claim,
    ClaimStatus,
    Evidence,
    Outcome,
    ReviewTask,
    SourceSnapshot,
    TerminationStatus,
    TraceEvent,
)
from app.state_machine import CaseStatus, validate_transition
from app.tools import validate_tool_call

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
RULE_VERSION = "rules-v2"
POLICY_VERSION = "authority-policy-v1"
STALE_SOURCE_MAX_AGE_DAYS = 365
INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "system:",
    "set decision",
    "set authority",
    "disregard the above",
    "you are now",
)


def _load_fixture(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _valid_bindings() -> list[dict[str, str]]:
    return _load_fixture("case_registry.json")["valid_bindings"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _TraceRecorder:
    """Accumulates ordered TraceEvent records for one case run as a hash
    chain: each event's `state_after_hash` folds in the previous event's
    hash, its own content, and (for tool calls) an argument hash. Replaying
    the same fixture through `verify_trace_chain` must reproduce the same
    chain — any inserted, reordered, or edited event breaks it.
    """

    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        self._sequence = 0
        self._chain_hash = _sha256(f"CASE:{case_id}")
        self.events: list[TraceEvent] = []

    def record(
        self,
        stage: str,
        event_type: str,
        *,
        tool_name: str | None = None,
        evidence_ids: list[str] | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        self._sequence += 1
        evidence_ids = evidence_ids or []
        state_before_hash = self._chain_hash
        argument_hash = _sha256(json.dumps(arguments, sort_keys=True)) if arguments is not None else None
        result_payload = json.dumps(
            {
                "sequence": self._sequence,
                "stage": stage,
                "event_type": event_type,
                "tool_name": tool_name,
                "evidence_ids": evidence_ids,
            },
            sort_keys=True,
        )
        result_hash = _sha256(result_payload)
        state_after_hash = _sha256(state_before_hash + result_hash + (argument_hash or ""))
        self._chain_hash = state_after_hash

        self.events.append(
            TraceEvent(
                trace_id=f"TRACE-{self.case_id}-{self._sequence:03d}",
                case_id=self.case_id,
                sequence=self._sequence,
                stage=stage,
                event_type=event_type,
                tool_name=tool_name,
                argument_hash=argument_hash,
                result_hash=result_hash,
                state_before_hash=state_before_hash,
                state_after_hash=state_after_hash,
                evidence_ids=evidence_ids,
                timestamp=_now(),
            )
        )

    def transition(self, current: CaseStatus, target: CaseStatus) -> CaseStatus:
        """Validate and record a CaseStatus transition. Fails closed:
        raises InvalidTransitionError (not caught here) on an illegal
        transition rather than recording it."""
        validate_transition(current, target)
        self.record("STATE", "STATE_TRANSITION", arguments={"from": current.value, "to": target.value})
        return target


def verify_trace_chain(case_id: str, events: list[TraceEvent]) -> bool:
    """Recompute the hash chain for a stored/replayed trace and confirm it
    matches what was recorded. Returns False if any event was altered,
    reordered, inserted, or removed."""
    chain_hash = _sha256(f"CASE:{case_id}")
    for event in sorted(events, key=lambda e: e.sequence):
        if event.state_before_hash != chain_hash:
            return False
        result_payload = json.dumps(
            {
                "sequence": event.sequence,
                "stage": event.stage,
                "event_type": event.event_type,
                "tool_name": event.tool_name,
                "evidence_ids": event.evidence_ids,
            },
            sort_keys=True,
        )
        expected_result_hash = _sha256(result_payload)
        if event.result_hash != expected_result_hash:
            return False
        expected_state_after = _sha256(chain_hash + expected_result_hash + (event.argument_hash or ""))
        if event.state_after_hash != expected_state_after:
            return False
        chain_hash = expected_state_after
    return True


def _investigate(
    case: dict[str, Any], sources: list[dict[str, Any]], trace: _TraceRecorder, budget: RunBudget
) -> list[dict[str, Any]]:
    """Return candidate source material bound to the case's declared source_refs.

    Candidates are unverified: VALIDATE decides whether they are admissible
    evidence. Each fixture lookup consumes one unit of the run's tool-call
    budget; exhausting it raises BudgetExceededError.
    """
    budget.consume_tool_call()
    tool_args = {"case_id": case["case_id"], "query": None}
    validate_tool_call("fixture_lexical_search", tool_args)
    trace.record(
        "INVESTIGATE", "CANDIDATE_SEARCH_STARTED", tool_name="fixture_lexical_search", arguments=tool_args
    )
    candidates = [s for s in sources if s["source_id"] in case["source_refs"]]
    trace.record(
        "INVESTIGATE",
        "CANDIDATES_RETURNED",
        tool_name="fixture_lexical_search",
        evidence_ids=[c["source_id"] for c in candidates],
    )
    return candidates


def _validate(
    case: dict[str, Any], candidates: list[dict[str, Any]], trace: _TraceRecorder
) -> tuple[list[SourceSnapshot], list[Evidence]]:
    """Verify source authority, version/date, case binding, locator and
    hash integrity for each candidate. Retrieved excerpt text is treated as
    untrusted data: it is scanned for injection markers but injection
    markers only add a reason code, they never change authority/entity/
    support status or any downstream rule/authority behaviour."""
    snapshots: list[SourceSnapshot] = []
    evidence: list[Evidence] = []
    expected_versions: dict[str, str] = case.get("expected_source_versions", {})
    as_of = datetime.fromisoformat(case["as_of"].replace("Z", "+00:00"))

    for cand in candidates:
        snapshot = SourceSnapshot(
            source_id=cand["source_id"],
            url=cand["url"],
            title=cand["title"],
            source_class=cand["source_class"],
            retrieved_at=datetime.fromisoformat(cand["retrieved_at"].replace("Z", "+00:00")),
            effective_at=(
                datetime.fromisoformat(cand["effective_at"]).replace(tzinfo=timezone.utc)
                if cand.get("effective_at")
                else None
            ),
            content_hash=cand["content_hash"],
            version=cand["version"],
            allowed_for_evidence=cand["allowed_for_evidence"],
        )
        snapshots.append(snapshot)

        reasons: list[str] = []

        authority_status = "VALID" if snapshot.allowed_for_evidence else "INVALID"
        if not snapshot.allowed_for_evidence:
            reasons.append("SOURCE_NOT_ALLOWED")

        entity_binding_status = "VALID" if cand["source_id"] in case["source_refs"] else "INVALID"
        if entity_binding_status == "INVALID":
            reasons.append("WRONG_CASE_BINDING")

        expected_version = expected_versions.get(cand["source_id"])
        if expected_version and expected_version != snapshot.version:
            reasons.append("SOURCE_VERSION_MISMATCH")

        if snapshot.effective_at and (as_of - snapshot.effective_at).days > STALE_SOURCE_MAX_AGE_DAYS:
            reasons.append("SOURCE_STALE_OR_OUT_OF_TIME")

        if cand.get("tampered_hash"):
            reasons.append("HASH_MISMATCH")

        locator = cand.get("locator") or cand.get("excerpt_kind")
        if not cand.get("excerpt") or not locator:
            reasons.append("LOCATOR_NOT_FOUND")

        support_status = "SUPPORTED" if cand.get("excerpt") and "LOCATOR_NOT_FOUND" not in reasons else "UNSUPPORTED"
        if support_status == "UNSUPPORTED" and "LOCATOR_NOT_FOUND" not in reasons:
            reasons.append("CLAIM_NOT_SUPPORTED")

        excerpt_lower = cand.get("excerpt", "").lower()
        if any(marker in excerpt_lower for marker in INJECTION_MARKERS):
            reasons.append("PROMPT_INJECTION_CONTENT")

        ev = Evidence(
            evidence_id=f"EVID-{cand['source_id']}",
            case_id=case["case_id"],
            source_id=cand["source_id"],
            locator=f"{cand.get('excerpt_kind', 'unknown')}:{cand['source_id']}",
            excerpt=cand.get("excerpt", ""),
            excerpt_kind=cand.get("excerpt_kind", "paraphrase"),
            content_hash=cand["content_hash"],
            authority_status=authority_status,
            entity_binding_status=entity_binding_status,
            support_status=support_status,
            validation_reasons=reasons,
        )
        evidence.append(ev)
        trace.record(
            "VALIDATE",
            "EVIDENCE_VALIDATED" if not reasons else "EVIDENCE_REJECTED",
            evidence_ids=[ev.evidence_id],
        )

    fault_sources = {
        c["source_id"]: c for c in candidates if c["source_class"] == "fault_assessment"
    }
    conclusions = {c.get("fault_conclusion") for c in fault_sources.values() if c.get("fault_conclusion")}
    if len(conclusions) > 1:
        for e in evidence:
            if e.source_id in fault_sources:
                e.validation_reasons.append("CONTRADICTION_PRESENT")

    return snapshots, evidence


_NON_BLOCKING_REASONS = {"PROMPT_INJECTION_CONTENT"}


def _admitted(evidence: list[Evidence]) -> list[Evidence]:
    """Evidence is admissible only if it has no blocking validation reason.
    PROMPT_INJECTION_CONTENT is recorded but never blocks admission or
    changes downstream rule/authority behaviour — untrusted content is data,
    not an instruction."""
    return [
        e
        for e in evidence
        if e.authority_status == "VALID"
        and e.entity_binding_status == "VALID"
        and e.support_status == "SUPPORTED"
        and not (set(e.validation_reasons) - _NON_BLOCKING_REASONS)
    ]


def _resolve(case: dict[str, Any], evidence: list[Evidence], trace: _TraceRecorder) -> list[Claim]:
    """Apply versioned deterministic rules to admitted evidence only."""
    admitted = _admitted(evidence)
    admitted_ids = [e.evidence_id for e in admitted]
    event = case["event"]

    claims: list[Claim] = []

    def add_claim(
        claim_type: str,
        status: ClaimStatus,
        reason_codes: list[str],
        evidence_ids: list[str],
        counter_evidence_ids: list[str] | None = None,
    ) -> None:
        claim = Claim(
            claim_id=f"CLAIM-{case['case_id']}-{claim_type}",
            case_id=case["case_id"],
            claim_type=claim_type,
            status=status,
            evidence_ids=evidence_ids,
            counter_evidence_ids=counter_evidence_ids or [],
            rule_version=RULE_VERSION,
            reason_codes=reason_codes,
        )
        claims.append(claim)
        trace.record(
            "RESOLVE", "CLAIM_RESOLVED", evidence_ids=evidence_ids + (counter_evidence_ids or [])
        )

    binding_match = any(
        b["order_ref"] == case["order_ref"]
        and b["seller_ref"] == case["seller_ref"]
        and b["product_ref"] == case["product_ref"]
        for b in _valid_bindings()
    )
    binding_reasons: list[str] = []
    if not binding_match:
        if not any(b["order_ref"] == case["order_ref"] for b in _valid_bindings()):
            binding_reasons.append("WRONG_ORDER_BINDING")
        if not any(b["seller_ref"] == case["seller_ref"] for b in _valid_bindings()):
            binding_reasons.append("WRONG_SELLER_BINDING")
        if not any(b["product_ref"] == case["product_ref"] for b in _valid_bindings()):
            binding_reasons.append("WRONG_PRODUCT_BINDING")
        if not binding_reasons:
            binding_reasons.append("WRONG_ORDER_BINDING")
    add_claim(
        "ORDER_AND_SELLER_VERIFIED",
        ClaimStatus.TRUE if binding_match else ClaimStatus.FALSE,
        ["ORDER_SELLER_PRODUCT_MATCH_REGISTRY"] if binding_match else binding_reasons,
        [],
    )
    add_claim(
        "PUBLIC_SOURCE_VALID",
        ClaimStatus.TRUE if admitted else ClaimStatus.UNKNOWN,
        ["SOURCE_ADMITTED"] if admitted else ["NO_ADMITTED_SOURCE"],
        admitted_ids,
    )
    add_claim(
        "SELLER_RESPONSE_RECORDED",
        ClaimStatus.TRUE if event.get("seller_response") else ClaimStatus.UNKNOWN,
        ["SELLER_RESPONSE_PRESENT"],
        [],
    )

    escalation_evidence = [e for e in admitted if e.source_id == "SRC-KOGAN-GUARANTEE"]
    add_claim(
        "MARKETPLACE_ESCALATION_PATH_SUPPORTED",
        ClaimStatus.TRUE if escalation_evidence else ClaimStatus.UNKNOWN,
        ["RETAILER_POLICY_ADMITTED"] if escalation_evidence else ["ESCALATION_SOURCE_MISSING"],
        [e.evidence_id for e in escalation_evidence],
    )

    contradictory = any("CONTRADICTION_PRESENT" in e.validation_reasons for e in evidence)
    # Contradictory fault sources are excluded from `admitted` (they carry a blocking reason),
    # but the contradiction itself — and which sources disagree — must still be visible on the
    # claim, so pull fault-shaped evidence from the full validated set when a contradiction exists.
    fault_pool = evidence if contradictory else admitted
    fault_evidence = [
        e
        for e in fault_pool
        if "major failure" in e.excerpt.lower() or "minor" in e.excerpt.lower() or "cosmetic" in e.excerpt.lower()
    ]

    # Split fault evidence into "supports major failure" vs "supports minor/cosmetic" so a
    # contradiction carries explicit counter-evidence IDs, not just a flag.
    major_supporting = [e for e in fault_evidence if "major failure" in e.excerpt.lower()]
    minor_supporting = [e for e in fault_evidence if "minor" in e.excerpt.lower() or "cosmetic" in e.excerpt.lower()]

    add_claim(
        "FAULT_ASSESSMENT_AVAILABLE",
        ClaimStatus.TRUE if fault_evidence and not contradictory else ClaimStatus.FALSE,
        ["FAULT_ASSESSMENT_ADMITTED"] if fault_evidence and not contradictory else ["NO_FAULT_ASSESSMENT_EVIDENCE"],
        [e.evidence_id for e in fault_evidence],
    )

    if contradictory:
        major_failure_status = ClaimStatus.UNKNOWN
        major_failure_reasons = ["CONTRADICTION_PRESENT"]
        major_failure_evidence = [e.evidence_id for e in major_supporting]
        major_failure_counter_evidence = [e.evidence_id for e in minor_supporting]
    elif not fault_evidence:
        major_failure_status = ClaimStatus.UNKNOWN
        major_failure_reasons = ["FAULT_ASSESSMENT_UNAVAILABLE"]
        major_failure_evidence = []
        major_failure_counter_evidence = []
    elif minor_supporting:
        major_failure_status = ClaimStatus.FALSE
        major_failure_reasons = ["FAULT_ASSESSMENT_CONFIRMS_MINOR_FAULT"]
        major_failure_evidence = [e.evidence_id for e in minor_supporting]
        major_failure_counter_evidence = []
    elif major_supporting:
        major_failure_status = ClaimStatus.TRUE
        major_failure_reasons = ["FAULT_ASSESSMENT_CONFIRMS_MAJOR_FAILURE"]
        major_failure_evidence = [e.evidence_id for e in major_supporting]
        major_failure_counter_evidence = []
    else:
        major_failure_status = ClaimStatus.UNKNOWN
        major_failure_reasons = ["FAULT_ASSESSMENT_INCONCLUSIVE"]
        major_failure_evidence = []
        major_failure_counter_evidence = []

    add_claim(
        "MAJOR_FAILURE_ESTABLISHED",
        major_failure_status,
        major_failure_reasons,
        major_failure_evidence,
        counter_evidence_ids=major_failure_counter_evidence,
    )

    add_claim(
        "AUTO_REFUND_PERMITTED",
        ClaimStatus.FALSE,
        ["REFUND_NOT_AUTO_APPROVABLE_BY_POLICY"],
        [],
    )

    human_review_required = major_failure_status != ClaimStatus.FALSE
    add_claim(
        "HUMAN_REVIEW_REQUIRED",
        ClaimStatus.TRUE if human_review_required else ClaimStatus.FALSE,
        ["FAULT_STATUS_UNKNOWN_OR_MAJOR", "REFUND_REQUESTED"] if human_review_required else ["FAULT_RESOLVED_AS_MINOR"],
        [],
    )

    return claims


def _authorise(case: dict[str, Any], claims: list[Claim], trace: _TraceRecorder) -> AuthorityRecord:
    """Deterministic authority gate. Never an LLM prompt; the model cannot
    approve its own action. AUTO_REFUND_PERMITTED is always FALSE by policy
    — the system never auto-authorises a refund, only ALLOW/DENY/REQUIRE_HUMAN
    for the *proposed* investigative/escalation action."""
    by_type = {c.claim_type: c for c in claims}
    order_verified = by_type["ORDER_AND_SELLER_VERIFIED"].status
    major_failure = by_type["MAJOR_FAILURE_ESTABLISHED"].status
    escalation = by_type["MARKETPLACE_ESCALATION_PATH_SUPPORTED"].status

    if order_verified == ClaimStatus.FALSE:
        decision = AuthorityDecision.REQUIRE_HUMAN
        proposed_action = "ESCALATE_BINDING_MISMATCH"
        reason_codes = list(by_type["ORDER_AND_SELLER_VERIFIED"].reason_codes)
    elif major_failure == ClaimStatus.UNKNOWN:
        decision = AuthorityDecision.REQUIRE_HUMAN
        proposed_action = "REQUEST_FAULT_EVIDENCE_AND_ESCALATE"
        reason_codes = ["FAULT_STATUS_UNKNOWN", "REFUND_REQUIRES_REVIEW"]
    elif major_failure == ClaimStatus.TRUE:
        decision = AuthorityDecision.REQUIRE_HUMAN
        proposed_action = "ESCALATE_FOR_REFUND"
        reason_codes = ["MAJOR_FAILURE_CONFIRMED", "REFUND_REQUIRES_REVIEW"]
    else:
        decision = AuthorityDecision.DENY
        proposed_action = "DENY_REFUND"
        reason_codes = ["MAJOR_FAILURE_NOT_ESTABLISHED"]

    if escalation in (ClaimStatus.TRUE, ClaimStatus.UNKNOWN) and decision == AuthorityDecision.REQUIRE_HUMAN:
        reason_codes.append("ESCALATION_PATH_AVAILABLE")

    record = AuthorityRecord(
        authority_id=f"AUTH-{case['case_id']}",
        case_id=case["case_id"],
        proposed_action=proposed_action,
        decision=decision,
        reason_codes=reason_codes,
        required_role="retail-operations",
        expires_at=_now() + timedelta(days=7),
        policy_version=POLICY_VERSION,
    )
    trace.record("AUTHORISE", "AUTHORITY_DECIDED")
    return record


def _create_review_task(case: dict[str, Any], authority: AuthorityRecord, trace: _TraceRecorder) -> ReviewTask | None:
    """Create a review task only when the authority decision requires one.
    A DENY on a resolved (non-UNKNOWN) claim is a valid controlled outcome
    that does not need human review."""
    if authority.decision != AuthorityDecision.REQUIRE_HUMAN:
        trace.record("AUTHORISE", "REVIEW_NOT_REQUIRED", evidence_ids=[])
        return None

    primary_reason = (
        "MISSING_FAULT_EVIDENCE"
        if "FAULT_STATUS_UNKNOWN" in authority.reason_codes
        else authority.reason_codes[0]
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


def _reconcile(case: dict[str, Any], authority: AuthorityRecord, trace: _TraceRecorder) -> Outcome:
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


def run_case_pipeline(
    case: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    budget: RunBudget | None = None,
) -> CaseArtifacts:
    """Run the deterministic pipeline end to end and return the raw typed
    artifacts (case, evidence, claims, authority, review, outcome, trace).

    Defaults to the hero-case fixtures. Pass `case`/`sources` explicitly to
    run the same rules against another fixture, e.g. an evaluation or
    adversarial-test case. Use `run_case_workflow` for a JSON-serialisable
    summary of the default hero case, or `app.persistence.persist_case_run`
    to write artifacts to the database. If `budget` is exhausted, the run
    terminates with TerminationStatus.CONTROL_BLOCKED rather than raising —
    a stopped workflow is a valid controlled outcome."""
    if case is None:
        case = _load_fixture("synthetic_case.json")
    if sources is None:
        sources = _load_fixture("source_manifest.json")["sources"]
    if budget is None:
        budget = RunBudget()

    trace = _TraceRecorder(case["case_id"])
    trace.record("CASE", "CASE_CREATED")
    case_status = CaseStatus.CREATED
    case_status = trace.transition(case_status, CaseStatus.INVESTIGATING)

    try:
        candidates = _investigate(case, sources, trace, budget)
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
        )

    snapshots, evidence = _validate(case, candidates, trace)
    case_status = trace.transition(case_status, CaseStatus.EVIDENCE_VALIDATED)

    claims = _resolve(case, evidence, trace)
    case_status = trace.transition(case_status, CaseStatus.CLAIMS_RESOLVED)

    authority = _authorise(case, claims, trace)
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
        "trace": [
            {"sequence": t.sequence, "stage": t.stage, "event_type": t.event_type}
            for t in trace_events
        ],
    }
