# Security

## Implemented

- **Secrets from environment only.** `backend/.env.example` has no real values. `DATABASE_URL` is read
  from `os.environ` in `app/db.py`; no secrets are logged or placed in `TraceEvent` fields.
- **Untrusted-content handling.** Retrieved excerpt text is scanned for injection markers
  (`app/services/workflow.py::INJECTION_MARKERS`) but the result is only a reason code
  (`PROMPT_INJECTION_CONTENT`) appended to `Evidence.validation_reasons` — it never changes
  `authority_status`, `entity_binding_status`, rule outcomes, or the authority decision. Proven by
  `tests/test_adversarial.py::test_prompt_injection_content_is_flagged_but_never_changes_authority`
  and by the `EVAL-CP-PROMPT_INJECTION` dataset case.
- **Strict tool registry.** `app/tools.py::TOOL_REGISTRY` is a fixed allow-list; every call is validated
  by a Pydantic model with `extra="forbid"`, so unknown tools and unexpected arguments are rejected
  before anything runs (`tests/test_adversarial.py` items 9–10).
- **Case-scoped queries.** Evidence/claims/authority/trace are all foreign-keyed to `case_id`
  (`app/orm_models.py`) and every API read (`app/api.py`) filters through the case relationship, not a
  global table scan.
- **Escaped UI rendering.** The frontend is React with no `dangerouslySetInnerHTML` anywhere — all
  retrieved/model-shaped content renders as text, not HTML.
- **Log/trace minimisation.** `TraceEvent` stores hashes and IDs, not full request/response payloads —
  and those hashes are now real, chained SHA-256 values (`app/services/workflow.py::_TraceRecorder`),
  tamper-evident via `GET /api/cases/{case_id}/trace/verify` (`tests/test_trace_chain.py`).
- **Static checks.** `make lint` (ruff) and `make typecheck` (mypy) are both clean
  (`ruff check app tests` → 0 issues; `mypy app` → 0 issues).
- **CI on every push/PR.** `.github/workflows/ci.yml` runs backend tests/lint/typecheck/demo-smoke and
  frontend typecheck/build — not yet confirmed green on GitHub's own runners as of this commit, see
  `docs/production_gap_register.md`.

## Explicitly not implemented (proposed only)

- No live network ingestion exists in this repository, so a URL allow-list, timeouts, size limits and
  content-type checks for "any optional ingestion command" (PRD §20) have no code to attach to yet.
  Fixtures are local, versioned JSON files only.
- No dependency/SCA scanner is wired into CI yet.
- No authn/authz on the API — `reviewer_id` on `POST /api/reviews/{id}/decision` is a free-text field
  supplied by the caller, not verified against any identity system.
- **CORS is wide open** (`allow_origins=["*"]` in `app/api.py`) to let the Vite dev server (different
  port) call the API during local demos. Acceptable for an offline, same-machine, no-real-data demo;
  must be scoped to a specific origin before any shared or hosted deployment.

See `docs/production_gap_register.md` for the full list.
