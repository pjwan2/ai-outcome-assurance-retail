"""RESOLVE: applies versioned deterministic rules to admitted evidence only
(never raw candidates — ADR-0001) and produces the case's typed, tri-state
Claims. This is the only stage that reads app.services.validate.admitted_evidence.
"""

from __future__ import annotations

from typing import Any

from app.models import Claim, ClaimStatus, Evidence
from app.services.fixtures import valid_bindings
from app.services.trace import TraceRecorder
from app.services.validate import admitted_evidence

RULE_VERSION = "rules-v2"


def resolve_claims(case: dict[str, Any], evidence: list[Evidence], trace: TraceRecorder) -> list[Claim]:
    admitted = admitted_evidence(evidence)
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
        trace.record("RESOLVE", "CLAIM_RESOLVED", evidence_ids=evidence_ids + (counter_evidence_ids or []))

    bindings = valid_bindings()
    binding_match = any(
        b["order_ref"] == case["order_ref"]
        and b["seller_ref"] == case["seller_ref"]
        and b["product_ref"] == case["product_ref"]
        for b in bindings
    )
    binding_reasons: list[str] = []
    if not binding_match:
        if not any(b["order_ref"] == case["order_ref"] for b in bindings):
            binding_reasons.append("WRONG_ORDER_BINDING")
        if not any(b["seller_ref"] == case["seller_ref"] for b in bindings):
            binding_reasons.append("WRONG_SELLER_BINDING")
        if not any(b["product_ref"] == case["product_ref"] for b in bindings):
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
