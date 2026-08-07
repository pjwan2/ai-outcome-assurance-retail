"""Review decision handling with idempotency (PRD section 14/19).

A review can only be decided once. Re-submitting the same idempotency key
returns the original recorded decision unchanged (safe retry). Submitting a
*different* decision for an already-decided review is rejected — decisions
are not a non-idempotent action that can be silently repeated.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.orm_models import ReviewTaskORM


class ReviewAlreadyDecidedError(Exception):
    def __init__(self, review_id: str) -> None:
        self.review_id = review_id
        super().__init__(f"Review '{review_id}' has already been decided and cannot be re-decided")


def decide_review(
    review: ReviewTaskORM,
    reviewer_id: str,
    decision: str,
    notes: str | None,
    idempotency_key: str,
) -> ReviewTaskORM:
    """Apply a reviewer decision to a pending review task.

    Idempotent: replaying the exact same (review_id, idempotency_key) after
    it already succeeded returns the stored result without re-mutating
    state. A conflicting second decision on an already-decided review is
    rejected.
    """
    if review.status == "DECIDED":
        if review.reviewer_notes and f"idempotency_key={idempotency_key}" in review.reviewer_notes:
            return review
        raise ReviewAlreadyDecidedError(review.review_id)

    review.status = "DECIDED"
    review.reviewer_id = reviewer_id
    review.reviewer_decision = decision
    review.reviewer_notes = f"{notes or ''} [idempotency_key={idempotency_key}]".strip()
    review.decided_at = datetime.now(timezone.utc)
    return review
