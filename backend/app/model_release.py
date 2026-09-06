"""Model-checkpoint release lifecycle for backend/app/serving/: register a
candidate, gate it, get it approved, activate it atomically, and roll it back
to the previous known-good checkpoint if it turns out to be bad — with a real
audit trail, not just a database field.

This is deliberately a separate concern from `app.release_gate`
(`ReleaseRecordORM`), which gates the *case-assurance evaluation dataset*,
not a serving checkpoint. `ReleaseRecordORM.rollback_of` is still just a
field with nothing behind it (see docs/production_gap_register.md) — this
module is where "rollback" is actually implemented, for the serving slice
specifically.

Lifecycle: CANDIDATE -> (gate) -> (human approval) -> ACTIVE -> either
SUPERSEDED (a later release activates normally) or ROLLED_BACK (this release
is explicitly reverted away from because it was bad). Exactly one release is
ACTIVE at a time; `app.serving.router.get_model_backend` reads the active
one's `model_name`/`checkpoint_id` through `get_active_model_info` below, so
activating or rolling back a release actually changes what traffic is
served — not just a row in a table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.orm import Session

from app.orm_models import ModelReleaseAuditEventORM, ModelReleaseORM
from app.serving.model_backend import (
    DEFAULT_MODEL_INFO,
    DeterministicFakeModel,
    PermanentBackendError,
    TransientBackendError,
)

# A handful of fixed synthetic prompts a candidate must handle cleanly before
# it can be approved — a deterministic smoke check, not a real quality/eval
# benchmark (the model behind it is a hash-seeded fake — see
# docs/production_gap_register.md for what this is not a substitute for).
GATE_SYNTHETIC_PROMPTS = ("hello", "please summarise the refund policy", "what is the order status")


class ModelReleaseStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ROLLED_BACK = "ROLLED_BACK"


class ModelReleaseError(Exception):
    """Base class for every model_release error — all fail closed: none of
    these are caught anywhere that would silently let an unsafe activation
    through."""


class ReleaseNotFoundError(ModelReleaseError):
    def __init__(self, release_id: str) -> None:
        self.release_id = release_id
        super().__init__(f"No ModelRelease with id '{release_id}'")


class ReleaseNotCandidateError(ModelReleaseError):
    def __init__(self, release_id: str, status: str) -> None:
        self.release_id = release_id
        self.status = status
        super().__init__(f"ModelRelease '{release_id}' is '{status}', not CANDIDATE — cannot activate")


class ReleaseGateNotPassedError(ModelReleaseError):
    def __init__(self, release_id: str) -> None:
        self.release_id = release_id
        super().__init__(f"ModelRelease '{release_id}' has not passed its release gate")


class ReleaseNotApprovedError(ModelReleaseError):
    def __init__(self, release_id: str) -> None:
        self.release_id = release_id
        super().__init__(f"ModelRelease '{release_id}' has not been approved")


class NoActiveReleaseError(ModelReleaseError):
    def __init__(self) -> None:
        super().__init__("There is no active ModelRelease to roll back")


class NoPreviousReleaseError(ModelReleaseError):
    def __init__(self, release_id: str) -> None:
        self.release_id = release_id
        super().__init__(f"Active ModelRelease '{release_id}' has no previous_release_id to roll back to")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record_audit(
    session: Session,
    release_id: str,
    event_type: str,
    *,
    actor: str | None = None,
    idempotency_key: str | None = None,
    detail: dict | None = None,
) -> ModelReleaseAuditEventORM:
    event = ModelReleaseAuditEventORM(
        event_id=f"MRAUDIT-{uuid.uuid4().hex[:12]}",
        release_id=release_id,
        event_type=event_type,
        actor=actor,
        idempotency_key=idempotency_key,
        detail=detail or {},
    )
    session.add(event)
    return event


@dataclass(frozen=True)
class ActiveModelInfo:
    release_id: str
    model_name: str
    checkpoint_id: str


# Process-local cache of the active release, mirroring the DB row so
# app.serving.router.get_model_backend doesn't need a DB session on every
# single request. Bootstrapped to a default so the serving slice behaves
# exactly as it did before ModelRelease existed until something explicitly
# activates a real release. Updated only by activate_release/
# rollback_active_release below, inside the same transaction that commits
# the DB change — see _sync_cache.
_ACTIVE_CACHE = ActiveModelInfo(
    release_id="RELEASE-BOOTSTRAP",
    model_name=DEFAULT_MODEL_INFO.model_name,
    checkpoint_id=DEFAULT_MODEL_INFO.checkpoint_id,
)


def get_active_model_info() -> ActiveModelInfo:
    return _ACTIVE_CACHE


def _sync_cache(release: ModelReleaseORM) -> None:
    global _ACTIVE_CACHE
    _ACTIVE_CACHE = ActiveModelInfo(
        release_id=release.release_id, model_name=release.model_name, checkpoint_id=release.checkpoint_id
    )


def _get_active_row(session: Session) -> ModelReleaseORM | None:
    return session.query(ModelReleaseORM).filter_by(status=ModelReleaseStatus.ACTIVE.value).one_or_none()


def get_release(session: Session, release_id: str) -> ModelReleaseORM:
    release = session.get(ModelReleaseORM, release_id)
    if release is None:
        raise ReleaseNotFoundError(release_id)
    return release


def register_candidate(session: Session, *, model_name: str, checkpoint_id: str, config_hash: str) -> ModelReleaseORM:
    release = ModelReleaseORM(
        release_id=f"RELEASE-{uuid.uuid4().hex[:12]}",
        model_name=model_name,
        checkpoint_id=checkpoint_id,
        config_hash=config_hash,
        status=ModelReleaseStatus.CANDIDATE.value,
    )
    session.add(release)
    _record_audit(session, release.release_id, "REGISTERED")
    session.commit()
    return release


async def run_release_gate(
    session: Session, release: ModelReleaseORM, model_backend: DeterministicFakeModel
) -> ModelReleaseORM:
    """Exercise `model_backend` — the caller's choice, e.g. a
    `DeterministicFakeModel` deliberately constructed with `fail_mode` set,
    for tests — against a fixed synthetic prompt set. This is a deterministic
    smoke check (nothing raises, every prompt produces at least one token),
    not a real quality/regression benchmark."""
    reason_codes: list[str] = []
    for prompt in GATE_SYNTHETIC_PROMPTS:
        try:
            tokens = [token async for token in model_backend.generate(prompt)]
        except (TransientBackendError, PermanentBackendError):
            reason_codes.append("GENERATION_FAILED")
            continue
        if not tokens:
            reason_codes.append("EMPTY_OUTPUT")

    release.gate_passed = not reason_codes
    release.gate_reason_codes = reason_codes
    _record_audit(
        session, release.release_id, "GATE_RUN", detail={"passed": release.gate_passed, "reason_codes": reason_codes}
    )
    session.commit()
    return release


def approve_release(session: Session, release: ModelReleaseORM, *, approved_by: str) -> ModelReleaseORM:
    if not release.gate_passed:
        raise ReleaseGateNotPassedError(release.release_id)
    release.approved_by = approved_by
    release.approved_at = _now()
    _record_audit(session, release.release_id, "APPROVED", actor=approved_by)
    session.commit()
    return release


def activate_release(session: Session, release: ModelReleaseORM, *, activated_by: str) -> ModelReleaseORM:
    """Atomically (within one DB transaction) make `release` the active one:
    fails closed if the gate hasn't passed or it hasn't been approved, and
    demotes whatever was previously ACTIVE to SUPERSEDED — a release only
    becomes ROLLED_BACK through an explicit rollback, never through being
    superseded by normal forward progress."""
    if release.status != ModelReleaseStatus.CANDIDATE.value:
        raise ReleaseNotCandidateError(release.release_id, release.status)
    if not release.gate_passed:
        raise ReleaseGateNotPassedError(release.release_id)
    if release.approved_by is None:
        raise ReleaseNotApprovedError(release.release_id)

    current_active = _get_active_row(session)
    if current_active is not None:
        current_active.status = ModelReleaseStatus.SUPERSEDED.value

    release.status = ModelReleaseStatus.ACTIVE.value
    release.activated_by = activated_by
    release.activated_at = _now()
    release.previous_release_id = current_active.release_id if current_active else None
    _record_audit(session, release.release_id, "ACTIVATED", actor=activated_by)
    session.commit()
    _sync_cache(release)
    return release


def rollback_active_release(session: Session, *, activated_by: str, idempotency_key: str) -> ModelReleaseORM:
    """Roll the currently active release back to its `previous_release_id`.
    Idempotent: replaying the same `idempotency_key` (a client retry after a
    network failure, say) returns the previously-computed result without
    re-mutating state or writing a second audit event. A *different*
    idempotency_key always attempts a fresh rollback of whatever is
    currently active — rolling back twice for two different real incidents
    is a normal, supported operation, not a repeat of the same one."""
    existing_event = (
        session.query(ModelReleaseAuditEventORM)
        .filter_by(event_type="ROLLED_BACK", idempotency_key=idempotency_key)
        .one_or_none()
    )
    if existing_event is not None:
        return get_release(session, existing_event.release_id)

    current_active = _get_active_row(session)
    if current_active is None:
        raise NoActiveReleaseError()
    if current_active.previous_release_id is None:
        raise NoPreviousReleaseError(current_active.release_id)

    previous = get_release(session, current_active.previous_release_id)
    current_active.status = ModelReleaseStatus.ROLLED_BACK.value
    current_active.rolled_back_at = _now()
    previous.status = ModelReleaseStatus.ACTIVE.value
    previous.activated_by = activated_by
    previous.activated_at = _now()
    _record_audit(
        session,
        previous.release_id,
        "ROLLED_BACK",
        actor=activated_by,
        idempotency_key=idempotency_key,
        detail={"rolled_back_from": current_active.release_id},
    )
    session.commit()
    _sync_cache(previous)
    return previous
