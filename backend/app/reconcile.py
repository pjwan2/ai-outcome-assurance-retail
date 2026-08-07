"""Reconciliation: compare the intended action against what actually
happened, and record any mismatch explicitly (PRD section 7/19) rather than
overwriting the intended action in place.
"""

from __future__ import annotations

from app.models import Outcome


def reconcile_observed_result(outcome: Outcome, observed_result: str) -> Outcome:
    """Return a new Outcome recording the observed result against the
    original intended action, flagging any mismatch."""
    mismatch = observed_result != outcome.intended_action
    return Outcome(
        outcome_id=outcome.outcome_id,
        case_id=outcome.case_id,
        attempt_id=outcome.attempt_id,
        intended_action=outcome.intended_action,
        observed_result=observed_result,
        reconciliation_status="MISMATCH" if mismatch else "MATCHED",
        mismatch_reason="OBSERVED_RESULT_DIFFERS_FROM_INTENDED_ACTION" if mismatch else None,
    )
