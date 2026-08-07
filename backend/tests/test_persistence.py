from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import AuthorityDecision, ClaimStatus
from app.orm_models import ClaimORM
from app.persistence import persist_case_run
from app.services.workflow import run_case_pipeline


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_persist_case_run_writes_full_control_chain():
    session = _session_factory()
    artifacts = run_case_pipeline()

    case_row = persist_case_run(session, artifacts)

    assert case_row.case_id == "CASE-RET-001"
    assert case_row.state_version == 1
    assert len(case_row.evidence) == len(artifacts.evidence)
    assert len(case_row.claims) == len(artifacts.claims)
    assert len(case_row.trace_events) == len(artifacts.trace_events)
    assert case_row.authority_records[0].decision == AuthorityDecision.REQUIRE_HUMAN

    major_failure = (
        session.query(ClaimORM)
        .filter_by(case_id="CASE-RET-001", claim_type="MAJOR_FAILURE_ESTABLISHED")
        .one()
    )
    assert major_failure.status == ClaimStatus.UNKNOWN


def test_persist_case_run_is_replayable_and_bumps_state_version():
    session = _session_factory()
    artifacts = run_case_pipeline()

    first = persist_case_run(session, artifacts)
    assert first.state_version == 1

    second = persist_case_run(session, run_case_pipeline())
    assert second.state_version == 2
    assert len(second.trace_events) == len(artifacts.trace_events)
