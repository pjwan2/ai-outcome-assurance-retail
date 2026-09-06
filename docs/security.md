# Security

## Implemented

- **Secrets from environment only.** `backend/.env.example` has no real values. `DATABASE_URL` is read
  from `os.environ` in `app/db.py`; no secrets are logged or placed in `TraceEvent` fields.
- **Untrusted-content handling.** Retrieved excerpt text is scanned for categorized injection markers
  (`app/guardrails.py::scan_for_injection`, `INJECTION_CATEGORY_MARKERS`) but the result is only a
  reason code (`PROMPT_INJECTION_CONTENT`) appended to `Evidence.validation_reasons` — it never
  changes `authority_status`, `entity_binding_status`, rule outcomes, or the authority decision.
  Proven by
  `tests/test_adversarial.py::test_prompt_injection_content_is_flagged_but_never_changes_authority`
  and by the `EVAL-CP-PROMPT_INJECTION` dataset case.
- **PII redaction and groundedness-checked generated text.** `app/guardrails.py::redact_pii` masks
  email/AU-mobile/credit-card-shaped text before it's exposed via the guardrail report; the generated
  case summary is independently groundedness-checked (`check_groundedness`) and any sentence citing
  evidence or a claim that doesn't actually exist in the case is replaced with a safe fallback string
  rather than shown as-is. Neither of these can change a `Claim` or `AuthorityDecision` — see
  [ADR 0006](adrs/0006-rag-guardrails-are-non-authoritative.md).
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
  frontend typecheck/build, confirmed green on GitHub Actions:
  https://github.com/pjwan2/ai-outcome-assurance-retail/actions/runs/31313642354
- **Bearer-token authn/authz on mutating endpoints.** `app/auth.py::require_auth` gates
  `POST /api/cases`, `POST /api/cases/{id}/run`, `POST /api/cases/{id}/replay`, and
  `POST /api/reviews/{id}/decision` — missing/invalid tokens get `401`. Review decisions derive
  `reviewer_id` from the authenticated token (never a client-supplied field) and check the token's role
  against `ReviewTask.assigned_role`, returning `403 ROLE_NOT_PERMITTED` on mismatch
  (`tests/test_api.py::test_create_case_requires_auth`,
  `::test_wrong_role_cannot_decide_review`). This is a static token map, not enterprise IAM — see
  `docs/production_gap_register.md`.
- **Docker build verified end-to-end.** `docker compose build` succeeded for both images;
  `docker compose up` started both containers, the backend ran its Alembic migration on boot, and
  `POST /api/cases` / `GET /api/cases/{id}/trace/verify` were exercised against the running container.

## Explicitly not implemented (proposed only)

- No live network ingestion exists in this repository, so a URL allow-list, timeouts, size limits and
  content-type checks for "any optional ingestion command" (PRD §20) have no code to attach to yet.
  Fixtures are local, versioned JSON files only.
- No dependency/SCA scanner is wired into CI yet.
- **CORS is wide open** (`allow_origins=["*"]` in `app/api.py`) to let the Vite dev server (different
  port) call the API during local demos. Acceptable for an offline, same-machine, no-real-data demo;
  must be scoped to a specific origin before any shared or hosted deployment.

See `docs/production_gap_register.md` for the full list.
