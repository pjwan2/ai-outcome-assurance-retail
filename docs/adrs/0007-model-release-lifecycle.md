# ADR 0007: Model-checkpoint release lifecycle is a real state machine, not a database field

## Status
Accepted

## Context
`app/orm_models.py::ReleaseRecordORM` (the case-assurance evaluation gate's result record) has had a
`rollback_of` column since early in this repository's history. It has never had any code behind it —
setting it does nothing, nothing reads it to change behaviour, and `docs/production_gap_register.md`
already said so explicitly. Separately, `backend/app/serving/` (ADR unrelated — see the model-serving
slice in `docs/architecture.md`) needed a way to say "this checkpoint is the one currently serving
traffic" and "revert to the checkpoint that was serving traffic before this one" for real, not as an
aspiration.

## Decision
`app/model_release.py` adds a `ModelReleaseORM` lifecycle, deliberately separate from
`ReleaseRecordORM` (different concern: a serving checkpoint, not an evaluation-dataset run):

```text
CANDIDATE -> (gate) -> (human approval) -> ACTIVE -> SUPERSEDED (normal forward progress)
                                                    -> ROLLED_BACK (explicit revert, a problem was found)
```

- `run_release_gate` exercises a caller-supplied `DeterministicFakeModel` instance against a fixed
  synthetic prompt set — a deterministic smoke check (nothing raises, every prompt yields at least one
  token), not a real quality/regression benchmark. `activate_release` fails closed
  (`ReleaseGateNotPassedError`, `ReleaseNotApprovedError`) if the gate hasn't passed or a human hasn't
  called `approve_release` first.
- **`SUPERSEDED` vs `ROLLED_BACK` is a deliberate, meaningful distinction**, not just the two obvious
  states. A release replaced by ordinary forward progress (a newer candidate activates normally) is
  `SUPERSEDED`; a release explicitly reverted away from because it turned out to be bad is
  `ROLLED_BACK`. Collapsing these into one status would make an audit trail unable to distinguish "we
  shipped v2" from "we shipped v2 and it was bad" — a real difference for anyone reading the history
  later.
- **Activation updates both rows in one DB transaction**, and — a real gap found and fixed after this
  ADR's first version — **"at most one ACTIVE release" is now a database constraint, not just an
  ordering promise**: a partial unique index (`uq_model_release_single_active`, `ModelReleaseORM.status`
  where `status = 'ACTIVE'`) means two racing activations (each reading "no active release" before
  either commits) cannot both succeed — the loser's commit raises an `IntegrityError`, which
  `activate_release` turns into a typed `ConcurrentActivationError` rather than letting a raw DB
  exception escape or, worse, silently leaving two ACTIVE rows. This is a genuine conflict with no
  single correct automatic resolution (unlike the rollback race below), so it fails closed. Note this
  required an implementation detail: within one transaction, the demotion to `SUPERSEDED` must be
  flushed *before* the new release is set `ACTIVE`, or SQLAlchemy's flush ordering can transiently
  present two ACTIVE rows to the same partial index mid-flush and reject a legitimate,
  non-concurrent activation against itself.
- **The process-local cache survives a restart.** A second real gap: `_ACTIVE_CACHE` previously only
  ever started from the hard-coded bootstrap value, updated only by `activate_release`/
  `rollback_active_release` — so a process restart after activating a real checkpoint would silently
  revert served traffic to bootstrap even though the database still recorded a different release as
  ACTIVE. `hydrate_active_cache_from_db`, called once from `app.api`'s `lifespan` on startup, reads
  whichever release is actually ACTIVE in the database and initialises the cache from it.
- **Rollback is idempotent via the same `idempotency_key` pattern `app/reviews.py::decide_review`
  already uses** in this codebase: replaying the same `(idempotency_key)` after a successful rollback
  returns the prior result without a second audit event or a second state flip — safe against a client
  retrying after a network failure. A *different* idempotency_key always attempts a fresh rollback of
  whatever is currently active; rolling back is a normal, repeatable operation across the service's
  lifetime, not a one-time action. This idempotency is now also database-enforced: a unique constraint
  on `ModelReleaseAuditEventORM.idempotency_key` means two concurrent retries of the *same* rollback
  request that both pass the application-level pre-check (a real possibility — that check and the
  eventual commit are two separate steps) cannot both write an audit row; the loser's `IntegrityError`
  is caught and reconciled into the same result the winner produced, instead of a raw DB error reaching
  a caller that is supposed to be able to retry safely.
- **Activation and rollback are queryable audits, not log lines**: `ModelReleaseAuditEventORM` records
  every `REGISTERED`/`GATE_RUN`/`APPROVED`/`ACTIVATED`/`ROLLED_BACK` transition with an actor and
  detail payload.
- **The activation actually changes what traffic is served.** `app.model_release.get_active_model_info()`
  is a process-local cache (mirroring the DB row, updated inside the same call that commits the
  transaction) that `app/serving/router.py::get_model_backend` reads on every request to build the
  `DeterministicFakeModel`'s `ModelInfo` (`model_name`/`checkpoint_id`). This is what makes "activating a
  release changes what a real HTTP request sees" a proven claim
  (`tests/test_model_release.py::test_real_requests_observe_activation_and_rollback_end_to_end`) instead
  of an assertion about a database row nothing else reads — precisely the gap this ADR exists to close.

## Consequences
- This is real rollback *for the serving slice specifically* — `ReleaseRecordORM.rollback_of` (the
  case-assurance evaluation gate) is untouched by this ADR and still has nothing behind it; the two
  are not the same system. `docs/production_gap_register.md` keeps both facts visible side by side:
  a resolved row for this ADR's real mechanism, and a gap row stating plainly that the older field
  remains unenforced.
- No automatic regression-triggered rollback exists — `rollback_active_release` is always called
  explicitly (by a human or an external process), never by continuous health monitoring detecting a
  problem on its own. That would be a real, larger feature (synthetic traffic sampling, alerting
  thresholds) and is listed as a gap, not implied by this ADR.
- The release gate is a smoke check against a deterministic fake model, not a quality/regression
  benchmark against a real model's behaviour — see `docs/production_gap_register.md`.
- The read path (`get_active_model_info()`) is still a single process's in-memory cache, consistent
  with the rest of `app/serving/`'s honesty about not being distributed infrastructure: the database is
  now safe to share across instances (at most one ACTIVE row is enforced there directly), but one
  instance activating or rolling back a release does not push that change to another instance's
  cache — it would only pick it up on its own next restart (via `hydrate_active_cache_from_db`). A
  multi-instance deployment would need every instance to either share the cache or re-read the DB per
  request, neither of which is implemented here.
