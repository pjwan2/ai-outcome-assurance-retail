"""Tests for app.model_release: the gate-then-approve-then-activate-then-
rollback lifecycle for backend/app/serving/'s model checkpoints.

Each test gets a fresh in-memory database (matching tests/test_persistence.py's
pattern) so DB state never leaks between tests. `app.model_release._ACTIVE_CACHE`
is a process-local module global, not database state, so it's reset by an
autouse fixture instead.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.model_release as model_release
from app.api import app
from app.auth import DEFAULT_DEV_TOKEN
from app.db import Base
from app.model_release import (
    ActiveModelInfo,
    ConcurrentActivationError,
    ModelReleaseStatus,
    NoActiveReleaseError,
    NoPreviousReleaseError,
    ReleaseGateNotPassedError,
    ReleaseNotApprovedError,
    activate_release,
    approve_release,
    get_active_model_info,
    hydrate_active_cache_from_db,
    register_candidate,
    rollback_active_release,
    run_release_gate,
)
from app.orm_models import ModelReleaseAuditEventORM
from app.serving.model_backend import DeterministicFakeModel

AUTH_HEADERS = {"Authorization": f"Bearer {DEFAULT_DEV_TOKEN}"}


def _done_event_data(sse_text: str) -> dict:
    for line in sse_text.splitlines():
        if line.startswith("data:"):
            payload = json.loads(line.removeprefix("data:").strip())
            if "checkpoint_id" in payload:
                return payload
    raise AssertionError(f"no done event found in SSE response: {sse_text!r}")


@pytest.fixture
def session():
    """A couple of these tests exercise `TestClient(app)` in the same test as
    a raw session (`test_real_requests_observe_activation_and_rollback_end_to_end`);
    TestClient runs the ASGI app on a worker thread, and Python's GC can run
    a Session/Connection's finalizer on whatever thread happens to trigger
    it — not necessarily the thread that created it. Without
    `check_same_thread=False` and a deterministic `close()`/`dispose()` here,
    that finalizer running on the wrong thread intermittently raised
    `sqlite3.ProgrammingError: SQLite objects created in a thread can only
    be used in that same thread` (a real flake found while hardening this
    suite, not a business-logic bug)."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db_session = sessionmaker(bind=engine)()
    try:
        yield db_session
    finally:
        db_session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _reset_active_cache():
    original = model_release._ACTIVE_CACHE
    yield
    model_release._ACTIVE_CACHE = original


async def _gated_and_approved_candidate(session, *, checkpoint_id: str, approved_by: str = "alice"):
    release = register_candidate(
        session, model_name="deterministic-fake-model", checkpoint_id=checkpoint_id, config_hash=f"hash-{checkpoint_id}"
    )
    await run_release_gate(session, release, DeterministicFakeModel(token_delay_seconds=0))
    approve_release(session, release, approved_by=approved_by)
    return release


# --- Cannot activate without passing the gate / without approval ----------


async def test_cannot_activate_without_passing_release_gate(session):
    release = register_candidate(session, model_name="m", checkpoint_id="ckpt-1", config_hash="h1")
    # Gate never run: gate_passed is still None.
    with pytest.raises(ReleaseGateNotPassedError):
        activate_release(session, release, activated_by="alice")


async def test_cannot_activate_a_release_that_failed_its_gate(session):
    release = register_candidate(session, model_name="m", checkpoint_id="ckpt-1", config_hash="h1")
    await run_release_gate(session, release, DeterministicFakeModel(token_delay_seconds=0, fail_mode="permanent"))
    assert release.gate_passed is False
    assert "GENERATION_FAILED" in release.gate_reason_codes
    with pytest.raises(ReleaseGateNotPassedError):
        activate_release(session, release, activated_by="alice")


async def test_cannot_activate_without_approval(session):
    release = register_candidate(session, model_name="m", checkpoint_id="ckpt-1", config_hash="h1")
    await run_release_gate(session, release, DeterministicFakeModel(token_delay_seconds=0))
    assert release.gate_passed is True
    with pytest.raises(ReleaseNotApprovedError):
        activate_release(session, release, activated_by="alice")


# --- Activation makes traffic read the new checkpoint ----------------------


async def test_activating_a_release_makes_get_active_model_info_reflect_it(session):
    release = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-v2")
    activate_release(session, release, activated_by="alice")

    active = get_active_model_info()
    assert active.checkpoint_id == "ckpt-v2"
    assert active.release_id == release.release_id


async def test_second_activation_supersedes_not_rolls_back_the_first(session):
    first = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-v1")
    activate_release(session, first, activated_by="alice")

    second = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-v2")
    activate_release(session, second, activated_by="alice")

    session.refresh(first)
    session.refresh(second)
    assert first.status == ModelReleaseStatus.SUPERSEDED.value
    assert second.status == ModelReleaseStatus.ACTIVE.value
    assert second.previous_release_id == first.release_id
    assert get_active_model_info().checkpoint_id == "ckpt-v2"


# --- Rollback ---------------------------------------------------------


async def test_rollback_restores_the_previous_known_good_version(session):
    first = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-good")
    activate_release(session, first, activated_by="alice")
    second = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-bad")
    activate_release(session, second, activated_by="alice")

    restored = rollback_active_release(session, activated_by="oncall-bob", idempotency_key="rb-1")

    assert restored.release_id == first.release_id
    assert restored.status == ModelReleaseStatus.ACTIVE.value
    session.refresh(second)
    assert second.status == ModelReleaseStatus.ROLLED_BACK.value
    assert get_active_model_info().checkpoint_id == "ckpt-good"


async def test_repeated_rollback_with_the_same_idempotency_key_is_a_no_op(session):
    first = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-good")
    activate_release(session, first, activated_by="alice")
    second = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-bad")
    activate_release(session, second, activated_by="alice")

    first_result = rollback_active_release(session, activated_by="oncall-bob", idempotency_key="rb-1")
    second_result = rollback_active_release(session, activated_by="oncall-bob", idempotency_key="rb-1")

    assert first_result.release_id == second_result.release_id == first.release_id
    audit_events = (
        session.query(ModelReleaseAuditEventORM)
        .filter_by(event_type="ROLLED_BACK", idempotency_key="rb-1")
        .all()
    )
    assert len(audit_events) == 1, "a repeated rollback must not write a second audit event"


async def test_rollback_without_an_active_release_raises(session):
    with pytest.raises(NoActiveReleaseError):
        rollback_active_release(session, activated_by="bob", idempotency_key="rb-x")


async def test_rollback_of_the_first_ever_release_raises_no_previous(session):
    only_release = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-only")
    activate_release(session, only_release, activated_by="alice")

    with pytest.raises(NoPreviousReleaseError):
        rollback_active_release(session, activated_by="bob", idempotency_key="rb-x")


async def test_rollback_writes_a_real_audit_record(session):
    first = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-good")
    activate_release(session, first, activated_by="alice")
    second = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-bad")
    activate_release(session, second, activated_by="alice")

    rollback_active_release(session, activated_by="oncall-bob", idempotency_key="rb-audit")

    event = (
        session.query(ModelReleaseAuditEventORM)
        .filter_by(event_type="ROLLED_BACK", idempotency_key="rb-audit")
        .one()
    )
    assert event.actor == "oncall-bob"
    assert event.release_id == first.release_id  # the release that became active again
    assert event.detail["rolled_back_from"] == second.release_id


# --- Sanity: the cache really is process-local, not a DB read --------------


def test_active_model_info_defaults_before_anything_is_ever_activated():
    model_release._ACTIVE_CACHE = ActiveModelInfo(
        release_id="RELEASE-BOOTSTRAP", model_name="deterministic-fake-model", checkpoint_id="bootstrap"
    )
    assert get_active_model_info().release_id == "RELEASE-BOOTSTRAP"


# --- A restart must not silently fall back to the bootstrap checkpoint -----


async def test_hydrate_active_cache_from_db_restores_the_active_release_after_a_simulated_restart(session):
    """A real gap found while reviewing this module: activate_release only
    ever updated the in-memory _ACTIVE_CACHE, so a process restart after
    activating a real checkpoint would silently go back to serving the
    bootstrap checkpoint even though the database still says otherwise.
    hydrate_active_cache_from_db (called from app.api's lifespan on real
    startup) is the fix — this test simulates the restart directly by
    resetting the cache to bootstrap and re-hydrating from the same session's
    database state, without going through the app's actual lifespan."""
    release = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-survives-restart")
    activate_release(session, release, activated_by="alice")
    assert get_active_model_info().checkpoint_id == "ckpt-survives-restart"

    model_release._ACTIVE_CACHE = ActiveModelInfo(
        release_id="RELEASE-BOOTSTRAP", model_name="deterministic-fake-model", checkpoint_id="bootstrap"
    )
    assert get_active_model_info().checkpoint_id == "bootstrap"  # sanity: the "restart" really reset it

    restored = hydrate_active_cache_from_db(session)

    assert restored.checkpoint_id == "ckpt-survives-restart"
    assert get_active_model_info().checkpoint_id == "ckpt-survives-restart"


async def test_hydrate_active_cache_from_db_keeps_bootstrap_when_nothing_was_ever_activated(session):
    model_release._ACTIVE_CACHE = ActiveModelInfo(
        release_id="RELEASE-BOOTSTRAP", model_name="deterministic-fake-model", checkpoint_id="bootstrap"
    )
    restored = hydrate_active_cache_from_db(session)
    assert restored.checkpoint_id == "bootstrap"


# --- End-to-end: activation/rollback actually change what HTTP traffic sees


async def test_real_requests_observe_activation_and_rollback_end_to_end(session):
    """The claim this whole module exists to prove: activating or rolling
    back a ModelRelease is not just a database row — a real request to
    POST /api/generate/stream observes the change, because
    app.serving.router.get_model_backend reads the same process-local cache
    activate_release/rollback_active_release update."""
    first = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-e2e-good")
    activate_release(session, first, activated_by="alice")

    with TestClient(app) as client:
        before = _done_event_data(
            client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x"}).text
        )
        assert before["checkpoint_id"] == "ckpt-e2e-good"

        second = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-e2e-bad")
        activate_release(session, second, activated_by="alice")

        after_activation = _done_event_data(
            client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x"}).text
        )
        assert after_activation["checkpoint_id"] == "ckpt-e2e-bad"

        rollback_active_release(session, activated_by="oncall-bob", idempotency_key="e2e-rb-1")

        after_rollback = _done_event_data(
            client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x"}).text
        )
        assert after_rollback["checkpoint_id"] == "ckpt-e2e-good"


# --- Concurrency invariants are enforced by the database, not just by
# application code checking before it writes -------------------------------


async def test_database_rejects_a_second_active_release_independent_of_application_code(session):
    """`activate_release` itself always demotes whatever it finds ACTIVE
    first, so it can never be caught writing a second ACTIVE row through its
    own logic — that only proves the application checks correctly, not that
    the database would catch a bypass (a bug in this module, a hand-written
    script, a future code path). This writes a second ACTIVE row directly,
    skipping activate_release entirely, to prove uq_model_release_single_active
    (the partial unique index on ModelReleaseORM) is a real, independent
    backstop."""
    first = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-a")
    activate_release(session, first, activated_by="alice")

    second = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-b")
    second.status = ModelReleaseStatus.ACTIVE.value
    session.add(second)
    with pytest.raises(IntegrityError):
        session.commit()


def test_database_rejects_a_second_rollback_audit_event_with_the_same_idempotency_key(session):
    """Same principle as above, for the other new constraint: writes two
    ModelReleaseAuditEventORM rows with the same idempotency_key directly,
    bypassing rollback_active_release's own pre-check, to prove the unique
    constraint on idempotency_key is enforced by the database itself."""
    session.add(
        ModelReleaseAuditEventORM(
            event_id="MRAUDIT-dup-1", release_id="RELEASE-x", event_type="ROLLED_BACK", idempotency_key="dup-key"
        )
    )
    session.commit()
    session.add(
        ModelReleaseAuditEventORM(
            event_id="MRAUDIT-dup-2", release_id="RELEASE-x", event_type="ROLLED_BACK", idempotency_key="dup-key"
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


async def test_activate_release_raises_a_typed_error_on_a_genuine_concurrent_activation_race(session, monkeypatch):
    """`activate_release`'s own current_active lookup can only protect
    against a race it can see mid-transaction — not one already committed by
    another process in the window between its read and its write. Real
    thread interleaving would make this a flaky test to assert on, so the
    race window is reproduced deterministically: `_get_active_row` is forced
    to (wrongly) report "nothing is active yet", the same stale read a
    concurrent transaction would have made, so this call proceeds to commit
    a second ACTIVE row that the database's unique index then rejects. Must
    surface as a typed ConcurrentActivationError, not a raw, leaked
    IntegrityError."""
    first = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-a")
    activate_release(session, first, activated_by="alice")

    second = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-b")
    monkeypatch.setattr(model_release, "_get_active_row", lambda _session: None)

    with pytest.raises(ConcurrentActivationError):
        activate_release(session, second, activated_by="bob")

    # The database still only ever had `first` as ACTIVE — the rejected
    # write never stuck.
    still_active = session.query(model_release.ModelReleaseORM).filter_by(status="ACTIVE").one()
    assert still_active.release_id == first.release_id


async def test_rollback_active_release_reconciles_a_lost_race_on_the_same_idempotency_key(session, monkeypatch):
    """Simulates two callers retrying the identical rollback request (same
    idempotency_key) racing each other: both can pass the "does this event
    already exist?" pre-check before either commits, since that check and
    the eventual commit are not one atomic step. Reproduced deterministically
    (real threads would be flaky) by making the *first* call to
    _find_rollback_event report "nothing yet" — simulating this call's own
    stale read — while a later call (the except-handler's retry, after the
    database's unique constraint rejects the second write) sees the real,
    already-committed winner."""
    first = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-good")
    activate_release(session, first, activated_by="alice")
    second = await _gated_and_approved_candidate(session, checkpoint_id="ckpt-bad")
    activate_release(session, second, activated_by="alice")

    winner_result = rollback_active_release(session, activated_by="alice-oncall", idempotency_key="race-key")
    assert winner_result.release_id == first.release_id

    real_find_rollback_event = model_release._find_rollback_event
    call_count = {"n": 0}

    def _stale_on_first_call(session_, key_):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        return real_find_rollback_event(session_, key_)

    monkeypatch.setattr(model_release, "_find_rollback_event", _stale_on_first_call)
    monkeypatch.setattr(model_release, "_get_active_row", lambda _session: second)

    loser_result = rollback_active_release(session, activated_by="bob-oncall", idempotency_key="race-key")

    assert loser_result.release_id == first.release_id
    events = (
        session.query(ModelReleaseAuditEventORM)
        .filter_by(event_type="ROLLED_BACK", idempotency_key="race-key")
        .all()
    )
    assert len(events) == 1, "the reconciled race must not leave a second audit row"
