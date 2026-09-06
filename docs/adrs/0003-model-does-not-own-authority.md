# ADR 0003: The model does not own the authority decision

## Status
Accepted

## Context
If an investigation planner (deterministic today, potentially model-backed later per PRD §13) can
directly cause an irreversible action, then a bad or manipulated planner output becomes a bad or
manipulated real-world outcome — including via prompt injection in retrieved content.

## Decision
`authorise_case` (`app/services/authorise.py`) is plain Python, not a prompt: it pattern-matches on typed
`Claim.status` values and returns a typed `AuthorityRecord`. It never sees raw evidence excerpts.
`enforce_action` (`app/authority_enforcement.py`) additionally blocks `AUTO_REFUND`/`ISSUE_REFUND`
outside `AuthorityDecision.ALLOW`, and `AUTO_REFUND_PERMITTED` is unconditionally `FALSE` in this
prototype's rule set — there is no code path in this repository that can auto-issue a refund.

## Consequences
Proven, not just claimed: `tests/test_adversarial.py::test_auto_refund_blocked_when_authority_requires_human`
and `test_prompt_injection_content_is_flagged_but_never_changes_authority` both fail if this boundary
is ever removed. If a future OpenAI/Anthropic-backed planner is added (PRD §6/§13), it plugs in at
`INVESTIGATE` only — this ADR's boundary is why that is safe to do incrementally.
