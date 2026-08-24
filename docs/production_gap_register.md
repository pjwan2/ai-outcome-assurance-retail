# Production gap register

Explicitly proposed, not implemented (PRD §4). Listed here so nothing in this repository can be
mistaken for a production claim.

| Gap | Why it matters | What exists today |
|---|---|---|
| Enterprise IAM / access control | `app/auth.py` is a static bearer-token-to-role map (`API_TOKENS` env var), not OAuth/OIDC/SSO, no token expiry or revocation, no audit log of auth events | Real authn/authz boundary exists and is enforced (401/403 tested), but it is demo-grade, not enterprise IAM |
| Production data classification & retention | No PII/retention policy engine | Only synthetic fixtures exist |
| Distributed queues / distributed tracing | Single-process, synchronous pipeline | In-process `_TraceRecorder`, SQLite |
| Real retailer/order/CRM integration | No external system calls anywhere | Local JSON fixtures only |
| Automatic refunds or other irreversible actions | `AUTO_REFUND_PERMITTED` is hard-coded FALSE, `enforce_action` blocks `AUTO_REFUND`/`ISSUE_REFUND` outside `ALLOW` | Enforced in code and tested (`tests/test_adversarial.py` #16) |
| Enterprise legal/compliance accreditation | No accreditation process exists | N/A — explicitly out of scope (PRD §2) |
| Cross-case long-term memory | Each run is independent | No memory store |
| Production-scale vector infrastructure | Only fixture-backed lexical matching | No embeddings, no vector DB |
| Live Anthropic/Google adapters | Not started | `app.tools`/pipeline interfaces are provider-neutral but no live adapter exists |
| Live OpenAI adapter | Optional per PRD §13/§6, not implemented in this session | Offline deterministic path only |
## Resolved since the previous version of this document

These were listed as gaps before and are now implemented and tested — kept here so the history of
what changed is visible, not silently dropped:

- **CaseStatus state machine enforcement** — `run_case_pipeline` now steps through
  `CREATED → INVESTIGATING → EVIDENCE_VALIDATED → CLAIMS_RESOLVED → AUTHORITY_EVALUATED → NEEDS_REVIEW`
  or `→ READY_TO_RECONCILE → COMPLETED`, calling `app/state_machine.py::validate_transition` at each
  step and recording a `STATE_TRANSITION` trace event. An illegal transition raises
  `InvalidTransitionError` and is never recorded (`tests/test_trace_chain.py`).
- **TraceEvent hash chaining** — every `TraceEvent` now carries real `argument_hash`, `result_hash`,
  `state_before_hash`, `state_after_hash` values folded into a running SHA-256 chain
  (`app/services/workflow.py::_TraceRecorder`). `verify_trace_chain()` recomputes and checks it;
  tampering, reordering, or replaying the same fixture are all covered by
  `tests/test_trace_chain.py`. Exposed via `GET /api/cases/{case_id}/trace/verify`.
- **Containerisation** — `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` added and
  **build-verified end-to-end**: `docker compose build` succeeded for both images, `docker compose up`
  started both containers, the backend ran its Alembic migration on boot, and
  `POST /api/cases` / `GET /api/cases/{id}/trace/verify` were exercised against the running backend
  container. The frontend container (nginx) served the built SPA.
- **CI/CD** — this is now a git repository with `.github/workflows/ci.yml`, confirmed green on GitHub
  Actions: https://github.com/pjwan2/ai-outcome-assurance-retail/actions/runs/31313642354 (backend and
  frontend jobs both passed).
- **Multi-case intake** — four runnable fixture cases now exist (`CASE-RET-001` through `-004`),
  covering the hero case, a confirmed-major-failure escalation, a resolved-minor-fault negative
  control, and a wrong-seller-binding case. `GET /api/case-fixtures` lists them;
  `POST /api/cases {"case_id": "..."}` runs any of them — the `case_id` is no longer ignored.
  Still not free-text intake: every case is one of these versioned fixtures
  (`backend/scripts/generate_eval_dataset.py`-style reproducibility, not a live intake form).
- **Basic authn/authz** — `app/auth.py` requires a bearer token on every mutating endpoint (create
  case, run/replay case, decide review). Review decisions derive `reviewer_id` from the authenticated
  token, not a client-supplied field, and check the token's role against the review's
  `assigned_role` (403 on mismatch). See the IAM row above for what this is *not* — it is not
  enterprise IAM.
- **Bounded, loop-controlled multi-agent investigation** — `app/agents.py::SupervisorPlanner`
  delegates to an independent `RetrievalAgent` and `CriticAgent`, each a durable, budget-bounded
  `AgentRun` with persisted `AgentStep`s (previously `RunBudget` was in-memory only and vanished after
  each call). This is still what it was before, made real and auditable, not a step toward an
  open-ended swarm: a database `CheckConstraint` confines every `AgentRun` to `INVESTIGATE`, `AUTHORISE`
  remains untouched plain Python (ADR-0003), and both agents are deterministic/offline — no live
  OpenAI/Anthropic adapter exists (see the row below). See
  `docs/adrs/0005-loop-controlled-multi-agent-investigation.md` and
  `backend/tests/test_agent_orchestration.py`.
