# ADR 0001: Control boundaries between investigation and authority

## Status
Accepted

## Context
The system needs to use AI-shaped, probabilistic investigation (candidate retrieval) while keeping
material state changes and irreversible actions under deterministic, testable control.

## Decision
Split the pipeline into stages with different trust levels:

- `INVESTIGATE` returns *candidates*, never verified fact (`app/services/workflow.py::_investigate`).
- `VALIDATE` is the only stage allowed to promote a candidate to admitted `Evidence`
  (`_validate`, `_admitted`).
- `RESOLVE` may only read admitted evidence, never raw candidates (`_resolve`).
- `AUTHORISE` may only read typed `Claim` objects, never evidence excerpts or raw candidates
  (`_authorise`).
- `enforce_action` (`app/authority_enforcement.py`) is the single choke point for irreversible actions.

## Consequences
A compromised or hallucinating investigation stage can at worst produce bad *candidates* — it cannot
reach the authority decision without passing through validation and resolution, both of which are
plain application code with their own tests.
