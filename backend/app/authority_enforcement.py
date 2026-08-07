"""Application-code enforcement of the authority decision (PRD sections 7,
12, 19). This is the boundary that makes AuthorityDecision.REQUIRE_HUMAN
actually stop an irreversible action — the model or caller can *propose*
AUTO_REFUND, but only this function decides whether it is allowed to run,
and it never consults a model to do so.
"""

from __future__ import annotations

from app.models import AuthorityDecision, AuthorityRecord

IRREVERSIBLE_ACTIONS = {"AUTO_REFUND", "ISSUE_REFUND"}


class UnauthorisedActionError(Exception):
    def __init__(self, action: str, decision: AuthorityDecision) -> None:
        self.action = action
        self.decision = decision
        super().__init__(f"Action '{action}' is blocked: authority decision is {decision.value}, not ALLOW")


def enforce_action(authority: AuthorityRecord, action: str) -> None:
    """Raise UnauthorisedActionError unless the action is explicitly ALLOWed.
    Irreversible actions are always blocked outside of ALLOW, regardless of
    what any upstream component proposed."""
    if action in IRREVERSIBLE_ACTIONS and authority.decision != AuthorityDecision.ALLOW:
        raise UnauthorisedActionError(action, authority.decision)
