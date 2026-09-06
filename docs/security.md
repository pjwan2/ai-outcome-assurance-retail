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
  and those hashes are now real, chained SHA-256 values (`app/services/trace.py::TraceRecorder`),
  tamper-evident via `GET /api/cases/{case_id}/trace/verify` (`tests/test_trace_chain.py`).
- **Static checks.** `make lint` (ruff) and `make typecheck` (mypy) are both clean
  (`ruff check app tests` → 0 issues; `mypy app` → 0 issues).
- **CI on every push/PR.** `.github/workflows/ci.yml` runs backend tests/lint/typecheck/demo-smoke and
  frontend typecheck/build, confirmed green on GitHub Actions:
  https://github.com/pjwan2/ai-outcome-assurance-retail/actions/runs/31313642354
- **Bearer-token authn/authz on mutating endpoints.** `app/auth.py::require_auth` gates
  `POST /api/cases`, `POST /api/cases/{id}/run`, `POST /api/cases/{id}/replay`,
  `POST /api/reviews/{id}/decision`, and `POST /api/generate/stream` — missing/invalid tokens get
  `401`. Review decisions derive `reviewer_id` from the authenticated token (never a client-supplied
  field) and check the token's role against `ReviewTask.assigned_role`, returning
  `403 ROLE_NOT_PERMITTED` on mismatch (`tests/test_api.py::test_create_case_requires_auth`,
  `::test_wrong_role_cannot_decide_review`). This is a static token map, not enterprise IAM — see
  `docs/production_gap_register.md`.
- **Rate-limit key is the authenticated principal, not a client-supplied value.**
  `app/serving/router.py::generate_stream` keys its `TokenBucketRateLimiter` on
  `principal.reviewer_id`, derived from the same bearer token as the auth check above — a request body
  `session_id` is accepted for log correlation only and has no effect on the rate limit. An earlier
  version keyed the limiter on the client-supplied `session_id` directly, which a client could rotate
  on every request to bypass its own limit entirely; found and fixed, proven by
  `tests/test_serving.py::test_rate_limit_is_keyed_by_principal_not_client_supplied_session_id`.
- **No client-controllable failure-injection surface.** An earlier version of `POST
  /api/generate/stream` accepted a `fail_mode` field on the public request body — a real client could
  have forced the server into its own error paths. `fail_mode` is now a construction-time property of a
  `DeterministicFakeModel` instance, reachable only through FastAPI's dependency-override mechanism in
  tests (`app/serving/router.py::get_model_backend`); `GenerateRequest` has no such field. `prompt`
  (1-4000 chars), `session_id` (≤128 chars), and `timeout_seconds` (0 < t ≤ 60) are all bounded by
  Pydantic `Field` constraints, rejecting malformed input with `422` before any handler code runs.
- **Bounded rate-limiter memory.** `app/serving/rate_limit.py::TokenBucketRateLimiter` caps the number
  of tracked buckets (`max_tracked_keys`, default 10,000) with LRU eviction — an unbounded number of
  distinct callers cannot grow its memory footprint without limit.
- **Deadline covers the whole request, not just the first token.** `POST /api/generate/stream`'s
  `timeout_seconds` used to bound only the pre-stream "prime" step; a model that answered quickly but
  then stalled mid-stream could run well past the timeout a client was told to expect. A single
  deadline (`app/serving/streaming.py::stream_generation`) now covers the concurrency-slot wait, the
  first token, and every subsequent token — found and fixed, regression-tested by
  `tests/test_serving.py::test_deadline_covers_the_full_stream_not_just_the_first_token`.
- **Containers run unprivileged.** `backend/Dockerfile` creates and switches to a
  non-root `app` user before `CMD` runs — the process never runs as root, and
  `/data` is chowned to that user so the SQLite volume stays writable. The
  frontend's `nginx:alpine` image runs its worker processes (the ones that
  actually parse requests) as the unprivileged `nginx` user by default — confirmed
  via `docker run --rm nginx:alpine head -5 /etc/nginx/nginx.conf` (`user nginx;`);
  only the master process, which just binds port 80 and supervises workers, stays
  root, the standard nginx security model. Not switched to a fully-unprivileged
  base image (e.g. `nginxinc/nginx-unprivileged`) since that would also move the
  listen port away from 80 and ripple into `docker-compose.yml` for marginal
  additional benefit over the existing worker-level separation.
  **A real gap found while verifying this**: a pre-existing `backend-data` named
  volume created by an older, root-running image is root-owned, and the new
  non-root `app` user cannot write to it — `POST /api/cases` fails with
  `sqlite3.OperationalError: attempt to write a readonly database`. Confirmed
  this is specific to upgrading an existing deployment in place, not a defect
  for new ones: `docker compose down -v` (dropping the stale volume) followed
  by `docker compose up --build` recreates it with the correct ownership and
  every endpoint — case creation, trace verify, guardrails, evaluation, the
  serving slice, the frontend — was re-verified working end to end. Anyone
  upgrading an existing local deployment past this change needs to drop and
  recreate the volume (fine for this synthetic-data demo; would need an actual
  migration step for anything with real data worth keeping).
- **Dependency pinning + scanning.** `backend/requirements.txt` (runtime) and
  `backend/requirements-dev.txt` (test/lint/load-test tooling, never installed in
  the runtime image) pin exact versions. CI runs `pip-audit -r requirements.txt`
  and `npm audit --audit-level=high` on every push/PR. `pip-audit` currently
  reports no known vulnerabilities (starlette was bumped to `1.6.0` — paired with
  `fastapi==0.141.1`, the first fastapi release with no `starlette<0.51` upper
  bound — after `pip-audit` found 7 CVEs against the previously-resolved
  `starlette==0.50.0`; the full test suite was re-run and stayed green after the
  bump). `npm audit` reports no known vulnerabilities. It previously had a
  moderate `esbuild`/`vite` finding accepted with a comment saying its only
  fix was a breaking `vite` v8 upgrade "not taken in this pass" — that
  comment went stale: removing the CI step's `continue-on-error: true`
  (below) surfaced a second, separate **high**-severity finding
  (`GHSA-fx2h-pf6j-xcff`, a dev-server `fs.deny` path-traversal bypass on
  Windows) that the old moderate-only framing didn't cover and that
  `continue-on-error` had been silently passing either way. Actually did the
  vite v8 upgrade this time: `npx tsc --noEmit`, `npm run build`, and
  `npm run dev` were all re-verified working after the bump, and `npm audit
  --audit-level=high` now finds nothing. CI runs the same command with no
  `continue-on-error`, so a real future finding fails the build instead of
  being silently passed.
- **Docker build verified end-to-end.** `docker compose up --build` built both images; the backend ran
  `alembic upgrade head` on boot (succeeded), `GET /health`, `POST /api/cases`, `GET
  /api/cases/{id}/trace/verify` (`chain_verified: true`), and `GET /api/cases/{id}/guardrails` were all
  exercised against the running containers, and the frontend container served the built SPA (HTTP 200).
  Re-verified after the RAG guardrails work landed, not a stale claim from before it existed.

## Explicitly not implemented (proposed only)

- **No read-side authorization.** `require_auth` (above) gates only the four mutating endpoints. Every
  `GET` endpoint — evidence, claims, trace, guardrails, agent-runs, reviews — is unauthenticated and
  returns the same data to any caller; there is no document-level, case-level, or scope-based read
  permission anywhere in this repository. See `docs/production_gap_register.md`.
- No live network ingestion exists in this repository, so a URL allow-list, timeouts, size limits and
  content-type checks for "any optional ingestion command" (PRD §20) have no code to attach to yet.
  Fixtures are local, versioned JSON files only.
- **CORS is wide open** (`allow_origins=["*"]` in `app/api.py`) to let the Vite dev server (different
  port) call the API during local demos — a same-machine, no-real-data convenience, unrelated to (and
  not a substitute for) the bearer-token authz above. Must be scoped to a specific origin before any
  shared or hosted deployment.

See `docs/production_gap_register.md` for the full list.
