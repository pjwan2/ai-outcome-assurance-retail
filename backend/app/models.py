from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ClaimStatus(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class AuthorityDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"


class TerminationStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONTROL_BLOCKED = "CONTROL_BLOCKED"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


@dataclass
class SourceSnapshot:
    source_id: str
    url: str
    title: str
    source_class: str
    retrieved_at: datetime
    effective_at: datetime | None
    content_hash: str
    version: str
    allowed_for_evidence: bool


@dataclass
class Evidence:
    evidence_id: str
    case_id: str
    source_id: str
    locator: str
    excerpt: str
    excerpt_kind: str
    content_hash: str
    authority_status: str
    entity_binding_status: str
    support_status: str
    validation_reasons: list[str] = field(default_factory=list)


@dataclass
class Claim:
    claim_id: str
    case_id: str
    claim_type: str
    status: ClaimStatus
    evidence_ids: list[str]
    counter_evidence_ids: list[str]
    rule_version: str
    reason_codes: list[str]


@dataclass
class AuthorityRecord:
    authority_id: str
    case_id: str
    proposed_action: str
    decision: AuthorityDecision
    reason_codes: list[str]
    required_role: str
    expires_at: datetime
    policy_version: str


@dataclass
class ReviewTask:
    review_id: str
    case_id: str
    status: str
    reason_codes: list[str]
    assigned_role: str
    reviewer_id: str | None
    reviewer_decision: str | None
    reviewer_notes: str | None


@dataclass
class Outcome:
    outcome_id: str
    case_id: str
    attempt_id: str
    intended_action: str
    observed_result: str
    reconciliation_status: str
    mismatch_reason: str | None


@dataclass
class TraceEvent:
    trace_id: str
    case_id: str
    sequence: int
    stage: str
    event_type: str
    tool_name: str | None
    argument_hash: str | None
    result_hash: str | None
    state_before_hash: str | None
    state_after_hash: str | None
    evidence_ids: list[str] = field(default_factory=list)
    timestamp: datetime | None = None
