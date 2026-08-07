# ADR 0002: Tri-state claims (TRUE / FALSE / UNKNOWN)

## Status
Accepted

## Context
A binary TRUE/FALSE claim model forces a guess when evidence is absent or contradictory. For a claim
like "is this a major failure," guessing FALSE when there is no fault assessment would silently deny a
possibly-valid refund; guessing TRUE would silently approve escalation without evidence.

## Decision
`ClaimStatus` (`app/models.py`) is `TRUE | FALSE | UNKNOWN`. `_resolve`
(`app/services/workflow.py`) only returns TRUE/FALSE when admitted evidence actually supports that
conclusion; absence of evidence or contradictory admitted evidence (`CONTRADICTION_PRESENT`) both
resolve to UNKNOWN, never to a default.

## Consequences
`MAJOR_FAILURE_ESTABLISHED = UNKNOWN` in the hero case is the intended, tested outcome
(`tests/test_workflow.py`), not a bug. UNKNOWN claims route to human review
(`_authorise`: `major_failure == ClaimStatus.UNKNOWN` → `REQUIRE_HUMAN`), so uncertainty is
operationalised rather than hidden.
