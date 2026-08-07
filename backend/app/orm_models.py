"""SQLAlchemy 2 persistence models for the AI Outcome Assurance control chain.

These mirror the typed dataclasses in `app.models` but add relational
constraints (foreign keys, indexes, enum validation) required to make case
state durable and queryable. `Case.state_version` is used for optimistic
concurrency: every material transition must increment it, and a write with a
stale version is rejected rather than silently overwritten.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models import AuthorityDecision, ClaimStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CaseORM(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    order_ref: Mapped[str] = mapped_column(String, nullable=False, index=True)
    seller_ref: Mapped[str] = mapped_column(String, nullable=False, index=True)
    product_ref: Mapped[str] = mapped_column(String, nullable=False, index=True)
    risk_band: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="CREATED")
    source_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    evidence: Mapped[list[EvidenceORM]] = relationship(back_populates="case", cascade="all, delete-orphan")
    claims: Mapped[list[ClaimORM]] = relationship(back_populates="case", cascade="all, delete-orphan")
    authority_records: Mapped[list[AuthorityRecordORM]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    review_tasks: Mapped[list[ReviewTaskORM]] = relationship(back_populates="case", cascade="all, delete-orphan")
    outcomes: Mapped[list[OutcomeORM]] = relationship(back_populates="case", cascade="all, delete-orphan")
    trace_events: Mapped[list[TraceEventORM]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="TraceEventORM.sequence"
    )


class SourceSnapshotORM(Base):
    __tablename__ = "source_snapshots"

    source_id: Mapped[str] = mapped_column(String, primary_key=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source_class: Mapped[str] = mapped_column(String, nullable=False, index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    allowed_for_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint("source_id", "version", name="uq_source_version"),)


class EvidenceORM(Base):
    __tablename__ = "evidence"

    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_snapshots.source_id"), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String, nullable=True)
    locator: Mapped[str] = mapped_column(String, nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt_kind: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    authority_status: Mapped[str] = mapped_column(String, nullable=False)
    entity_binding_status: Mapped[str] = mapped_column(String, nullable=False)
    support_status: Mapped[str] = mapped_column(String, nullable=False)
    validation_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)

    case: Mapped[CaseORM] = relationship(back_populates="evidence")

    __table_args__ = (Index("ix_evidence_case_source", "case_id", "source_id"),)


class ClaimORM(Base):
    __tablename__ = "claims"

    claim_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False, index=True)
    claim_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[ClaimStatus] = mapped_column(Enum(ClaimStatus), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    counter_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    rule_version: Mapped[str] = mapped_column(String, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    case: Mapped[CaseORM] = relationship(back_populates="claims")

    __table_args__ = (UniqueConstraint("case_id", "claim_type", name="uq_case_claim_type"),)


class AuthorityRecordORM(Base):
    __tablename__ = "authority_records"

    authority_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False, index=True)
    proposed_action: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[AuthorityDecision] = mapped_column(Enum(AuthorityDecision), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_role: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    policy_version: Mapped[str] = mapped_column(String, nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    case: Mapped[CaseORM] = relationship(back_populates="authority_records")


class ReviewTaskORM(Base):
    __tablename__ = "review_tasks"

    review_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    assigned_role: Mapped[str] = mapped_column(String, nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewer_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    case: Mapped[CaseORM] = relationship(back_populates="review_tasks")


class OutcomeORM(Base):
    __tablename__ = "outcomes"

    outcome_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String, nullable=False)
    intended_action: Mapped[str] = mapped_column(String, nullable=False)
    observed_result: Mapped[str] = mapped_column(String, nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(String, nullable=False)
    mismatch_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    case: Mapped[CaseORM] = relationship(back_populates="outcomes")

    __table_args__ = (UniqueConstraint("case_id", "attempt_id", name="uq_case_attempt"),)


class TraceEventORM(Base):
    __tablename__ = "trace_events"

    trace_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String, nullable=True)
    argument_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    state_before_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    state_after_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    case: Mapped[CaseORM] = relationship(back_populates="trace_events")

    __table_args__ = (UniqueConstraint("case_id", "sequence", name="uq_case_sequence"),)


class EvaluationRunORM(Base):
    __tablename__ = "evaluation_runs"

    evaluation_id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String, nullable=False)
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_positive_total: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_positive_recovered: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_recall: Mapped[float] = mapped_column(Float, nullable=False)
    critical_recall_wilson_lower_bound_95: Mapped[float] = mapped_column(Float, nullable=False)
    false_authorisation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    wrong_entity_evidence_admitted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_injection_altered_decision_count: Mapped[int] = mapped_column(Integer, nullable=False)
    per_slice: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ReleaseRecordORM(Base):
    __tablename__ = "release_records"

    release_id: Mapped[str] = mapped_column(String, primary_key=True)
    config_name: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    thresholds_version: Mapped[str] = mapped_column(String, nullable=False)
    dataset_version: Mapped[str] = mapped_column(String, nullable=False)
    evaluation_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_runs.evaluation_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
