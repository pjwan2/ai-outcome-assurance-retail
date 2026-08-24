"""Deterministic, offline multi-agent investigation (INVESTIGATE stage only).

Formalizes the `InvestigationPlanner` interface proposed in the PRD (section
13): a `SupervisorPlanner` delegates to a `RetrievalAgent` (candidate lookup)
and a `CriticAgent` (independent second opinion on case binding), producing
durable `AgentRun`/`AgentStep`/`AgentHandoff` records instead of the
transient, in-memory-only bookkeeping `app.budget.RunBudget` had on its own.

Every agent here only ever returns *candidates* or advisory annotations —
`app.services.workflow._validate`/`_admitted` remains the sole stage that can
promote a candidate to admitted Evidence (ADR-0001), and nothing in this
module can reach AUTHORISE (ADR-0003). See
docs/adrs/0005-loop-controlled-multi-agent-investigation.md.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from app.budget import BudgetExceededError, RunBudget
from app.models import (
    AgentDefinition,
    AgentHandoff,
    AgentProvider,
    AgentRole,
    AgentRun,
    AgentStep,
    TerminationStatus,
)
from app.tools import validate_tool_call


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TraceRecorder(Protocol):
    """Structural match for `app.services.workflow._TraceRecorder.record` —
    kept as a Protocol (not an import) so this module has no dependency on
    workflow.py, avoiding a circular import."""

    def record(
        self,
        stage: str,
        event_type: str,
        *,
        tool_name: str | None = None,
        evidence_ids: list[str] | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> None: ...


class InvestigationBudgetExceeded(BudgetExceededError):
    """Raised instead of a plain BudgetExceededError so the caller can still
    persist an auditable (partial) agent-run record for a CONTROL_BLOCKED
    termination. Subclasses BudgetExceededError so existing
    `except BudgetExceededError` call sites keep working unchanged."""

    def __init__(self, original: BudgetExceededError, agent_runs: list[AgentRun]) -> None:
        self.resource = original.resource
        self.limit = original.limit
        self.agent_runs = agent_runs
        Exception.__init__(self, str(original))


SUPERVISOR_AGENT = AgentDefinition(
    agent_id="AGENT-SUPERVISOR-V1",
    name="Investigation Supervisor",
    role=AgentRole.SUPERVISOR,
    provider=AgentProvider.DETERMINISTIC,
    config_hash=_sha256("supervisor-v1"),
)
RETRIEVAL_AGENT = AgentDefinition(
    agent_id="AGENT-RETRIEVAL-V1",
    name="Fixture Retrieval Agent",
    role=AgentRole.RETRIEVAL,
    provider=AgentProvider.DETERMINISTIC,
    config_hash=_sha256("retrieval-v1"),
)
CRITIC_AGENT = AgentDefinition(
    agent_id="AGENT-CRITIC-V1",
    name="Binding Critic Agent",
    role=AgentRole.CRITIC,
    provider=AgentProvider.DETERMINISTIC,
    config_hash=_sha256("critic-v1"),
)
REGISTERED_AGENTS: list[AgentDefinition] = [SUPERVISOR_AGENT, RETRIEVAL_AGENT, CRITIC_AGENT]


@dataclass
class InvestigationResult:
    candidates: list[dict[str, Any]]
    agent_runs: list[AgentRun] = field(default_factory=list)
    agent_steps: list[AgentStep] = field(default_factory=list)
    agent_handoffs: list[AgentHandoff] = field(default_factory=list)


class RetrievalAgent:
    """Wraps the fixture-lexical-search candidate lookup (unchanged logic
    from the pre-multi-agent `_investigate`). Consumes exactly one unit of
    the run's tool-call budget."""

    definition = RETRIEVAL_AGENT

    def run(
        self,
        case: dict[str, Any],
        sources: list[dict[str, Any]],
        trace: TraceRecorder,
        budget: RunBudget,
        agent_run_id: str,
    ) -> tuple[list[dict[str, Any]], list[AgentStep]]:
        budget.consume_tool_call()
        tool_args = {"case_id": case["case_id"], "query": None}
        validate_tool_call("fixture_lexical_search", tool_args)
        trace.record(
            "INVESTIGATE", "CANDIDATE_SEARCH_STARTED", tool_name="fixture_lexical_search", arguments=tool_args
        )
        candidates = [s for s in sources if s["source_id"] in case["source_refs"]]
        trace.record(
            "INVESTIGATE",
            "CANDIDATES_RETURNED",
            tool_name="fixture_lexical_search",
            evidence_ids=[c["source_id"] for c in candidates],
        )
        step = AgentStep(
            step_id=f"STEP-{agent_run_id}-001",
            agent_run_id=agent_run_id,
            sequence=1,
            step_type="TOOL_CALL",
            timestamp=_now(),
            tool_name="fixture_lexical_search",
            tool_input_hash=_sha256(repr(sorted(tool_args.items()))),
            tool_output_hash=_sha256(repr(sorted(c["source_id"] for c in candidates))),
            candidate_evidence_ids=[c["source_id"] for c in candidates],
        )
        return candidates, [step]


class CriticAgent:
    """Independent second opinion: re-checks each candidate's case binding
    before VALIDATE runs. Never admits, rejects, or mutates evidence — its
    output is advisory metadata on its own AgentStep only, so it cannot
    become a second path into authority (ADR-0001/0003). Consumes no tool
    calls: it only re-examines candidates the RetrievalAgent already fetched."""

    definition = CRITIC_AGENT

    def run(
        self,
        case: dict[str, Any],
        candidates: list[dict[str, Any]],
        trace: TraceRecorder,
        agent_run_id: str,
    ) -> list[AgentStep]:
        flagged = [c["source_id"] for c in candidates if c["source_id"] not in case["source_refs"]]
        trace.record("INVESTIGATE", "CANDIDATE_BINDING_REVIEWED", evidence_ids=flagged)
        step = AgentStep(
            step_id=f"STEP-{agent_run_id}-001",
            agent_run_id=agent_run_id,
            sequence=1,
            step_type="CRITIQUE",
            timestamp=_now(),
            candidate_evidence_ids=[c["source_id"] for c in candidates],
        )
        return [step]


class SupervisorPlanner:
    """Orchestrates RetrievalAgent then CriticAgent under one case's
    INVESTIGATE stage, producing a full agent-run/handoff record. This is
    the `InvestigationPlanner` entry point `run_case_pipeline` calls."""

    definition = SUPERVISOR_AGENT
    retrieval_agent = RetrievalAgent()
    critic_agent = CriticAgent()

    def run(
        self,
        case: dict[str, Any],
        sources: list[dict[str, Any]],
        trace: TraceRecorder,
        budget: RunBudget,
    ) -> InvestigationResult:
        case_id = case["case_id"]
        started_at = _now()
        supervisor_run_id = f"AGENTRUN-{case_id}-SUPERVISOR"
        retrieval_run_id = f"AGENTRUN-{case_id}-RETRIEVAL"
        critic_run_id = f"AGENTRUN-{case_id}-CRITIC"

        supervisor_run = AgentRun(
            agent_run_id=supervisor_run_id,
            case_id=case_id,
            agent_id=self.definition.agent_id,
            max_tool_calls=budget.max_tool_calls,
            max_steps=budget.max_steps,
            started_at=started_at,
        )

        try:
            candidates, retrieval_steps = self.retrieval_agent.run(case, sources, trace, budget, retrieval_run_id)
        except BudgetExceededError as exc:
            ended_at = _now()
            reason_codes = ["BUDGET_EXCEEDED", str(exc.resource).upper()]
            retrieval_run = AgentRun(
                agent_run_id=retrieval_run_id,
                case_id=case_id,
                agent_id=self.retrieval_agent.definition.agent_id,
                parent_run_id=supervisor_run_id,
                max_tool_calls=budget.max_tool_calls,
                max_steps=budget.max_steps,
                started_at=started_at,
                tool_calls_used=budget.tool_calls_used,
                steps_used=budget.steps_used,
                termination_status=TerminationStatus.CONTROL_BLOCKED,
                termination_reason_codes=reason_codes,
                ended_at=ended_at,
            )
            supervisor_run.termination_status = TerminationStatus.CONTROL_BLOCKED
            supervisor_run.termination_reason_codes = reason_codes
            supervisor_run.ended_at = ended_at
            raise InvestigationBudgetExceeded(exc, agent_runs=[supervisor_run, retrieval_run]) from exc

        retrieval_run = AgentRun(
            agent_run_id=retrieval_run_id,
            case_id=case_id,
            agent_id=self.retrieval_agent.definition.agent_id,
            parent_run_id=supervisor_run_id,
            max_tool_calls=budget.max_tool_calls,
            max_steps=budget.max_steps,
            started_at=started_at,
            tool_calls_used=budget.tool_calls_used,
            steps_used=len(retrieval_steps),
            termination_status=TerminationStatus.COMPLETED,
            ended_at=_now(),
        )

        critic_steps = self.critic_agent.run(case, candidates, trace, critic_run_id)
        critic_run = AgentRun(
            agent_run_id=critic_run_id,
            case_id=case_id,
            agent_id=self.critic_agent.definition.agent_id,
            parent_run_id=supervisor_run_id,
            max_tool_calls=budget.max_tool_calls,
            max_steps=budget.max_steps,
            started_at=started_at,
            tool_calls_used=0,
            steps_used=len(critic_steps),
            termination_status=TerminationStatus.COMPLETED,
            ended_at=_now(),
        )

        supervisor_run.tool_calls_used = budget.tool_calls_used
        supervisor_run.steps_used = len(retrieval_steps) + len(critic_steps)
        supervisor_run.termination_status = TerminationStatus.COMPLETED
        supervisor_run.ended_at = _now()

        handoffs = [
            AgentHandoff(
                handoff_id=f"HANDOFF-{case_id}-RETRIEVAL",
                parent_run_id=supervisor_run_id,
                child_run_id=retrieval_run_id,
                from_agent_id=self.definition.agent_id,
                to_agent_id=self.retrieval_agent.definition.agent_id,
                delegated_task="RETRIEVE_CANDIDATES",
                created_at=started_at,
            ),
            AgentHandoff(
                handoff_id=f"HANDOFF-{case_id}-CRITIC",
                parent_run_id=supervisor_run_id,
                child_run_id=critic_run_id,
                from_agent_id=self.definition.agent_id,
                to_agent_id=self.critic_agent.definition.agent_id,
                delegated_task="REVIEW_CANDIDATE_BINDING",
                created_at=started_at,
            ),
        ]
        trace.record("INVESTIGATE", "AGENT_HANDOFF_RETRIEVAL")
        trace.record("INVESTIGATE", "AGENT_HANDOFF_CRITIC")

        return InvestigationResult(
            candidates=candidates,
            agent_runs=[supervisor_run, retrieval_run, critic_run],
            agent_steps=[*retrieval_steps, *critic_steps],
            agent_handoffs=handoffs,
        )
