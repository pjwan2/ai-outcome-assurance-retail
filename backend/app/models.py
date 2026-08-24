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


class AgentRole(str, Enum):
    SUPERVISOR = "SUPERVISOR"
    RETRIEVAL = "RETRIEVAL"
    CRITIC = "CRITIC"
    INVESTIGATION_PLANNER = "INVESTIGATION_PLANNER"


class AgentProvider(str, Enum):
    """Only DETERMINISTIC is ever instantiated today. OPENAI/ANTHROPIC are
    schema-ready values for a future live adapter (PRD section 13) — adding
    one plugs in at INVESTIGATE only, per ADR-0003."""

    DETERMINISTIC = "DETERMINISTIC"
    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"


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


@dataclass
class AgentDefinition:
    """A versioned registry entry for one participant allowed to run at
    INVESTIGATE. `config_hash` binds a specific prompt/config revision so an
    AgentRun's provenance is reproducible."""

    agent_id: str
    name: str
    role: AgentRole
    provider: AgentProvider
    config_hash: str
    model_name: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    is_active: bool = True


@dataclass
class AgentRun:
    """A durable, budget-bounded loop. Persists what `app.budget.RunBudget`
    otherwise discards once the call returns. `stage` is always INVESTIGATE
    (ADR-0003) — enforced again at the ORM layer with a DB CheckConstraint,
    not just here."""

    agent_run_id: str
    case_id: str
    agent_id: str
    max_tool_calls: int
    max_steps: int
    started_at: datetime
    stage: str = "INVESTIGATE"
    parent_run_id: str | None = None
    max_wall_clock_seconds: float | None = None
    tool_calls_used: int = 0
    steps_used: int = 0
    termination_status: TerminationStatus | None = None
    termination_reason_codes: list[str] = field(default_factory=list)
    token_usage_prompt: int | None = None
    token_usage_completion: int | None = None
    cost_usd: float | None = None
    ended_at: datetime | None = None


@dataclass
class AgentStep:
    """One loop iteration/turn within an AgentRun. `candidate_evidence_ids`
    are proposals only — VALIDATE is still the sole gate that can promote a
    candidate to admitted Evidence (ADR-0001)."""

    step_id: str
    agent_run_id: str
    sequence: int
    step_type: str
    timestamp: datetime
    tool_name: str | None = None
    tool_input_hash: str | None = None
    tool_output_hash: str | None = None
    candidate_evidence_ids: list[str] = field(default_factory=list)
    latency_ms: float | None = None


@dataclass
class AgentHandoff:
    """A bounded delegation edge from a supervising AgentRun to a specialist
    AgentRun it spawned. Multiple agents on one case show up as multiple
    AgentRun rows linked by these edges — not a free-form swarm."""

    handoff_id: str
    parent_run_id: str
    child_run_id: str
    from_agent_id: str
    to_agent_id: str
    delegated_task: str
    created_at: datetime
    reason_codes: list[str] = field(default_factory=list)
