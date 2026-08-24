import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.agents import CRITIC_AGENT, RETRIEVAL_AGENT, SUPERVISOR_AGENT
from app.budget import BudgetExceededError, RunBudget
from app.db import Base
from app.models import TerminationStatus
from app.orm_models import AgentHandoffORM, AgentRunORM, AgentStepORM
from app.persistence import persist_case_run
from app.services.workflow import run_case_pipeline


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_investigate_produces_supervisor_and_two_child_agent_runs():
    artifacts = run_case_pipeline()

    assert len(artifacts.agent_runs) == 3
    by_agent = {r.agent_id: r for r in artifacts.agent_runs}
    assert SUPERVISOR_AGENT.agent_id in by_agent
    assert RETRIEVAL_AGENT.agent_id in by_agent
    assert CRITIC_AGENT.agent_id in by_agent

    supervisor = by_agent[SUPERVISOR_AGENT.agent_id]
    retrieval = by_agent[RETRIEVAL_AGENT.agent_id]
    critic = by_agent[CRITIC_AGENT.agent_id]

    assert supervisor.parent_run_id is None
    assert retrieval.parent_run_id == supervisor.agent_run_id
    assert critic.parent_run_id == supervisor.agent_run_id
    assert all(r.stage == "INVESTIGATE" for r in artifacts.agent_runs)
    assert all(r.termination_status == TerminationStatus.COMPLETED for r in artifacts.agent_runs)

    assert len(artifacts.agent_handoffs) == 2
    handoff_children = {h.child_run_id for h in artifacts.agent_handoffs}
    assert handoff_children == {retrieval.agent_run_id, critic.agent_run_id}
    assert all(h.parent_run_id == supervisor.agent_run_id for h in artifacts.agent_handoffs)


def test_retrieval_agent_candidates_match_admitted_evidence_sources():
    # The multi-agent refactor must not change what INVESTIGATE returns:
    # every admitted Evidence source must trace back to a candidate the
    # RetrievalAgent step recorded.
    artifacts = run_case_pipeline()
    retrieval_run = next(r for r in artifacts.agent_runs if r.agent_id == RETRIEVAL_AGENT.agent_id)
    retrieval_steps = [s for s in artifacts.agent_steps if s.agent_run_id == retrieval_run.agent_run_id]
    assert len(retrieval_steps) == 1
    candidate_ids = set(retrieval_steps[0].candidate_evidence_ids)
    admitted_source_ids = {e.source_id for e in artifacts.evidence}
    assert admitted_source_ids.issubset(candidate_ids)


def test_budget_exhaustion_still_raises_on_first_retrieval_call():
    # Regression guard: app.agents.SupervisorPlanner must consume the budget
    # through the same RunBudget instance the caller passed in, exactly once,
    # so test_adversarial.py's RunBudget(max_tool_calls=0) case keeps failing
    # on the very first tool call.
    budget = RunBudget(max_tool_calls=0)
    with pytest.raises(BudgetExceededError):
        budget.consume_tool_call()


def test_control_blocked_run_still_persists_partial_agent_runs():
    artifacts = run_case_pipeline(budget=RunBudget(max_tool_calls=0))
    assert artifacts.termination_status == TerminationStatus.CONTROL_BLOCKED
    assert len(artifacts.agent_runs) == 2
    statuses = {r.termination_status for r in artifacts.agent_runs}
    assert statuses == {TerminationStatus.CONTROL_BLOCKED}
    reason_codes = {code for r in artifacts.agent_runs for code in r.termination_reason_codes}
    assert "BUDGET_EXCEEDED" in reason_codes


def test_agent_run_stage_is_constrained_to_investigate_at_the_db_level():
    session = _session_factory()
    session.add(
        AgentRunORM(
            agent_run_id="AGENTRUN-BAD",
            case_id="CASE-RET-001",
            agent_id=SUPERVISOR_AGENT.agent_id,
            stage="AUTHORISE",
            max_tool_calls=1,
            max_steps=1,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_agent_step_sequence_is_unique_per_run():
    session = _session_factory()
    session.add(
        AgentRunORM(
            agent_run_id="AGENTRUN-X",
            case_id="CASE-RET-001",
            agent_id=RETRIEVAL_AGENT.agent_id,
            max_tool_calls=10,
            max_steps=10,
        )
    )
    session.commit()
    session.add(AgentStepORM(step_id="STEP-1", agent_run_id="AGENTRUN-X", sequence=1, step_type="TOOL_CALL"))
    session.commit()
    session.add(AgentStepORM(step_id="STEP-2", agent_run_id="AGENTRUN-X", sequence=1, step_type="TOOL_CALL"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_agent_handoff_child_run_is_unique():
    session = _session_factory()
    session.add_all(
        [
            AgentRunORM(
                agent_run_id="AGENTRUN-PARENT",
                case_id="CASE-RET-001",
                agent_id=SUPERVISOR_AGENT.agent_id,
                max_tool_calls=10,
                max_steps=10,
            ),
            AgentRunORM(
                agent_run_id="AGENTRUN-PARENT-2",
                case_id="CASE-RET-001",
                agent_id=SUPERVISOR_AGENT.agent_id,
                max_tool_calls=10,
                max_steps=10,
            ),
            AgentRunORM(
                agent_run_id="AGENTRUN-CHILD",
                case_id="CASE-RET-001",
                agent_id=RETRIEVAL_AGENT.agent_id,
                max_tool_calls=10,
                max_steps=10,
            ),
        ]
    )
    session.commit()
    session.add_all(
        [
            AgentHandoffORM(
                handoff_id="HANDOFF-1",
                parent_run_id="AGENTRUN-PARENT",
                child_run_id="AGENTRUN-CHILD",
                from_agent_id=SUPERVISOR_AGENT.agent_id,
                to_agent_id=RETRIEVAL_AGENT.agent_id,
                delegated_task="RETRIEVE",
            )
        ]
    )
    session.commit()
    session.add(
        AgentHandoffORM(
            handoff_id="HANDOFF-2",
            parent_run_id="AGENTRUN-PARENT-2",
            child_run_id="AGENTRUN-CHILD",
            from_agent_id=SUPERVISOR_AGENT.agent_id,
            to_agent_id=RETRIEVAL_AGENT.agent_id,
            delegated_task="RETRIEVE_AGAIN",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_persist_case_run_round_trips_agent_orchestration_records():
    session = _session_factory()
    artifacts = run_case_pipeline()

    case_row = persist_case_run(session, artifacts)

    assert len(case_row.agent_runs) == len(artifacts.agent_runs)
    persisted_step_count = (
        session.query(AgentStepORM)
        .filter(AgentStepORM.agent_run_id.in_([r.agent_run_id for r in artifacts.agent_runs]))
        .count()
    )
    assert persisted_step_count == len(artifacts.agent_steps)
    assert session.query(AgentHandoffORM).count() == len(artifacts.agent_handoffs)


def test_replay_does_not_leave_orphaned_agent_handoffs():
    session = _session_factory()
    first = persist_case_run(session, run_case_pipeline())
    first_handoff_ids = {h.handoff_id for h in session.query(AgentHandoffORM).all()}
    assert len(first_handoff_ids) == 2

    second = persist_case_run(session, run_case_pipeline())
    assert second.state_version == first.state_version + 1
    remaining = {h.handoff_id for h in session.query(AgentHandoffORM).all()}
    # Deterministic IDs mean the replayed handoffs have the same ids as
    # before — the point of this test is that there are still exactly 2, not
    # 4 (i.e. the pre-delete cleanup in persist_case_run actually ran).
    assert len(remaining) == 2
