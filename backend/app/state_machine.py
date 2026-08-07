"""Explicit case state machine (PRD section 9). Application code validates
and commits every transition; the model may only propose one. Invalid
transitions fail closed by raising InvalidTransitionError rather than
silently mutating status."""

from __future__ import annotations

from enum import Enum


class CaseStatus(str, Enum):
    CREATED = "CREATED"
    INVESTIGATING = "INVESTIGATING"
    EVIDENCE_VALIDATED = "EVIDENCE_VALIDATED"
    CLAIMS_RESOLVED = "CLAIMS_RESOLVED"
    AUTHORITY_EVALUATED = "AUTHORITY_EVALUATED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY_TO_RECONCILE = "READY_TO_RECONCILE"
    COMPLETED = "COMPLETED"


ALLOWED_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.CREATED: {CaseStatus.INVESTIGATING},
    CaseStatus.INVESTIGATING: {CaseStatus.EVIDENCE_VALIDATED},
    CaseStatus.EVIDENCE_VALIDATED: {CaseStatus.CLAIMS_RESOLVED},
    CaseStatus.CLAIMS_RESOLVED: {CaseStatus.AUTHORITY_EVALUATED},
    CaseStatus.AUTHORITY_EVALUATED: {CaseStatus.NEEDS_REVIEW, CaseStatus.READY_TO_RECONCILE},
    CaseStatus.NEEDS_REVIEW: {CaseStatus.READY_TO_RECONCILE},
    CaseStatus.READY_TO_RECONCILE: {CaseStatus.COMPLETED},
    CaseStatus.COMPLETED: set(),
}


class InvalidTransitionError(Exception):
    def __init__(self, current: CaseStatus, target: CaseStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition case from {current.value} to {target.value}")


def validate_transition(current: CaseStatus, target: CaseStatus) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(current, target)
