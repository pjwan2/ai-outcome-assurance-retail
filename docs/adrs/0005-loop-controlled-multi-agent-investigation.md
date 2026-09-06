# ADR 0005: Loop-controlled, multi-agent investigation stays confined to INVESTIGATE

## Status
Accepted

## Context
`app.budget.RunBudget` already expressed the right shape for loop control (`max_tool_calls`,
`max_steps`) but was purely in-memory: it vanished once a call returned, and `consume_step()` was
never even invoked because no loop existed to call it. Separately, `docs/production_gap_register.md`
listed "Autonomous multi-agent swarms" as an explicit, intentionally out-of-scope gap — not because
multiple agents are unsafe in principle, but because an open-ended swarm with no persisted budget or
audit trail is hard to reason about, and because ADR-0003 requires that whatever runs at
`INVESTIGATE` can never reach `AUTHORISE` directly.

This ADR makes the loop real and adds a second, independent agent, without reopening either boundary.

## Decision
`app/agents.py` introduces three deterministic, offline participants, registered in
`AgentDefinition`/`REGISTERED_AGENTS`:

- `RetrievalAgent` — the pre-existing fixture-lexical-search candidate lookup, unchanged.
- `CriticAgent` — an independent second opinion that re-checks each candidate's case binding before
  `VALIDATE` runs. It can only annotate its own `AgentStep`; it cannot admit, reject, or mutate
  `Evidence` — that remains solely `validate_evidence`/`admitted_evidence`'s job
  (`app/services/validate.py`, ADR-0001).
- `SupervisorPlanner` — orchestrates the two via `AgentHandoff` records and is the sole entry point
  `app/services/workflow.py::_investigate` calls.

Every `AgentRun` this produces persists `stage` as `'INVESTIGATE'`, enforced by a database
`CheckConstraint` (`ck_agent_run_stage_investigate_only`) on `agent_runs` — not just by convention in
application code, the same fail-closed posture `app/state_machine.py::validate_transition` uses for
`CaseStatus`. `validate_evidence`, `resolve_claims`, `authorise_case`, `_create_review_task`, and
`_reconcile` are
untouched by this change: nothing downstream of `INVESTIGATE` can see an `AgentRun`, an `AgentStep`,
or a `CriticAgent` annotation.

Multiple agents on one case therefore show up as multiple `AgentRun` rows sharing a `case_id`, linked
into a tree (not a free-form graph) by `AgentHandoff` edges — `AgentHandoff.child_run_id` is unique,
so a run has at most one delegating parent. This is bounded, supervised delegation, not a swarm.

`AgentDefinition.provider` includes `OPENAI`/`ANTHROPIC` as schema-ready enum values for a future live
adapter (PRD section 13), but only `DETERMINISTIC` is ever instantiated in this repository — adding a
live adapter still only plugs in at `INVESTIGATE`, per ADR-0003, and is unaffected by this ADR.

## Consequences
- `RunBudget` consumption is now durable and queryable (`AgentRun.tool_calls_used`/`steps_used`,
  `AgentStep` per turn) instead of vanishing when the call returns — a `CONTROL_BLOCKED` termination is
  reconstructable after the fact, including the partial run created before the budget was exhausted.
- The "Autonomous multi-agent swarms" row in `docs/production_gap_register.md` moves to resolved, with
  the bounded scope stated explicitly so it cannot be read as more than it is: no live model adapter,
  no cross-case memory, no open-ended agent count.
- `backend/tests/test_agent_orchestration.py` proves the `INVESTIGATE`-only constraint at the database
  level (inserting `stage='AUTHORISE'` raises `IntegrityError`), not just via a passing test of the
  application code path.
