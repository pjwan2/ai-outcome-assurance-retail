"""AUTHORISE: the deterministic authority gate (ADR-0003). Never an LLM
prompt — reads only typed Claim objects, never evidence excerpts or raw
candidates, and the model cannot approve its own action.
AUTO_REFUND_PERMITTED is always FALSE by policy: this system never
auto-authorises a refund, only ALLOW/DENY/REQUIRE_HUMAN for the *proposed*
investigative/escalation action.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.models import AuthorityDecision, AuthorityRecord, Claim, ClaimStatus
from app.services.trace import TraceRecorder

POLICY_VERSION = "authority-policy-v1"


def authorise_case(case: dict[str, Any], claims: list[Claim], trace: TraceRecorder) -> AuthorityRecord:
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
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        policy_version=POLICY_VERSION,
    )
    trace.record("AUTHORISE", "AUTHORITY_DECIDED")
    return record
