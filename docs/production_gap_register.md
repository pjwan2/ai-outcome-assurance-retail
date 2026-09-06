# Production gap register

Explicitly proposed, not implemented (PRD §4). Listed here so nothing in this repository can be
mistaken for a production claim.

| Gap | Why it matters | What exists today |
|---|---|---|
| Enterprise IAM / access control | `app/auth.py` is a static bearer-token-to-role map (`API_TOKENS` env var), not OAuth/OIDC/SSO, no token expiry or revocation, no audit log of auth events | Real authn/authz boundary exists and is enforced (401/403 tested), but it is demo-grade, not enterprise IAM |
| Production data classification & retention | No PII/retention policy engine | Only synthetic fixtures exist |
| Distributed queues / distributed tracing | Single-process, synchronous pipeline | In-process `TraceRecorder`, SQLite |
| Real retailer/order/CRM integration | No external system calls anywhere | Local JSON fixtures only |
| Automatic refunds or other irreversible actions | `AUTO_REFUND_PERMITTED` is hard-coded FALSE, `enforce_action` blocks `AUTO_REFUND`/`ISSUE_REFUND` outside `ALLOW` | Enforced in code and tested (`tests/test_adversarial.py` #16) |
| Enterprise legal/compliance accreditation | No accreditation process exists | N/A — explicitly out of scope (PRD §2) |
| Cross-case long-term memory | Each run is independent | No memory store |
| Production-scale vector infrastructure | Deterministic TF-IDF/cosine relevance scoring exists (`app/retrieval.py`) and is wired into VALIDATE and evaluation, but it is not an ANN index or vector database, and has no embedding model | Real relevance scoring exists; embeddings/vector DB/ANN search do not |
| Live Anthropic/Google adapters | Not started | `app.tools`/pipeline interfaces are provider-neutral but no live adapter exists |
| Live OpenAI adapter | Optional per PRD §13/§6, not implemented in this session | Offline deterministic path only |
| Live LLM-generated explanations | `app/guardrails.py::generate_case_summary` is deterministic, template-based text built from typed Claims — no model call | Groundedness checking is unit-tested against a hand-crafted violation, not against a real model's output |
| Enterprise PII/DLP classifier | `app/guardrails.py::redact_pii` is three fixed regexes (email, AU mobile, credit-card-shaped digit runs), not a trained classifier | Catches the patterns it's given; no ML-based detection, no locale coverage beyond AU mobile |
| Maintained red-team/jailbreak corpus | `INJECTION_CATEGORY_MARKERS` is seven substring markers grouped into three categories — the same detection surface the prototype always had | No adversarial corpus, no fuzzing, no coverage measurement against known jailbreak techniques |
| Document-level read-permission enforcement | `app/auth.py::require_auth` gates only the four mutating endpoints (create/run/replay a case, decide a review); every `GET` endpoint (`/api/cases/{id}/evidence`, `/claims`, `/trace`, `/guardrails`, `/agent-runs`, etc.) is unauthenticated and returns identical data to any caller | No read-side authorization exists anywhere in this repository — see `docs/security.md` |
| Structure-aware document ingestion | No parsing pipeline for real documents (PDF/HTML/Word) with heading/section-aware chunking | Evidence excerpts are small, pre-authored strings in JSON fixtures (`app/fixtures/*.json`), never ingested from an actual source document |
| A reranking stage on retrieved candidates | No second-stage reranker (cross-encoder, LLM-based, or heuristic) runs after retrieval | `app/retrieval.py::score_candidates` computes one TF-IDF cosine score per candidate; ranking and admission both stop there |
| Document-owner / scope metadata | No schema field records who owns a document or what scope (team/tenant/department) it belongs to | `SourceSnapshot`/`Evidence` carry `source_class` and `allowed_for_evidence` — authority/class flags, not ownership or scope |
| Live model behind `app/serving/` | No real inference call anywhere — `DeterministicFakeModel` is hash-seeded and offline by design | The async-serving mechanics (streaming, timeout, cancellation, retry, backpressure, rate limiting) are real; the model behind them is not |
| Distributed rate limiting / concurrency control | `ConcurrencyLimiter` and `TokenBucketRateLimiter` (`app/serving/`) are in-process, single-instance, in-memory | A multi-replica deployment would need a shared store (e.g. Redis) — not implemented |
| `ReleaseRecordORM.rollback_of` is still just a field | It has existed since the enterprise-provenance migration with no code that reads or enforces it — setting it changes nothing | Not the same system as `app.model_release` (ADR-0007) below, which *does* implement real rollback — for `backend/app/serving/`'s checkpoints specifically, not the case-assurance evaluation gate this field belongs to |
| Automatic regression-triggered rollback | `app.model_release.rollback_active_release` is always called explicitly (by a human or an external process) | No continuous health/quality monitoring exists that would detect a regression and call it on its own — see [ADR 0007](adrs/0007-model-release-lifecycle.md) |
| Model-release gate is a smoke check, not a quality benchmark | `run_release_gate` exercises a candidate against a handful of fixed prompts and checks nothing raises | No real evaluation methodology exists (there is no real model to evaluate — see the `DeterministicFakeModel` row above) |
| Multi-instance model-release coordination | `get_active_model_info()` is a single process's in-memory cache | A multi-replica deployment would need every instance to share it (or re-read the DB per request) — not implemented |

These rows exist specifically because a public capability claim must never outrun what this repository
can independently prove — see `docs/verification_matrix.md`'s "Scope".

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
  (`app/services/trace.py::TraceRecorder`). `verify_trace_chain()` recomputes and checks it;
  tampering, reordering, or replaying the same fixture are all covered by
  `tests/test_trace_chain.py`. Exposed via `GET /api/cases/{case_id}/trace/verify`.
- **Containerisation** — `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` added and
  **build-verified end-to-end**, re-run and re-confirmed after the RAG guardrails work landed:
  `docker compose up --build` built both images, the backend ran its Alembic migration on boot (log
  shows all 5 revisions applying, including the guardrail-report migration), `GET /health` returned
  `{"status":"ok"}`, `POST /api/cases` created the hero case, `GET
  /api/cases/CASE-RET-001/trace/verify` returned `chain_verified: true`, `GET
  /api/cases/CASE-RET-001/guardrails` returned a populated report, and the frontend container served
  the built SPA (HTTP 200). Run on a machine with an unrelated container already bound to host port
  8000, so this specific run used a temporary host-port override — the committed `docker-compose.yml`
  itself is unchanged (still `8000`/`5173`).
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
- **RAG retrieval scoring and a guardrails engine** — `app/retrieval.py` adds deterministic TF-IDF
  cosine relevance scoring (previously VALIDATE had no ranking signal, only fixture-membership
  lookup); `app/guardrails.py` adds categorized injection detection, PII redaction, and a
  groundedness-checked generated case summary. Still bounded the same way as everything else here:
  `authorise_case` is untouched and reads only `claims`, so none of this can influence the authority
  decision. See `docs/adrs/0006-rag-guardrails-are-non-authoritative.md` and
  `backend/tests/test_guardrails.py`. This is a partial resolution of the vector-infrastructure row
  above, not a full one — see that row for what's still missing.
- **Real model-release activation and rollback** — `app.model_release` implements
  CANDIDATE → (gate) → (approval) → ACTIVE, with `SUPERSEDED` (replaced by normal forward progress)
  kept distinct from `ROLLED_BACK` (explicitly reverted because it was bad), an idempotent rollback
  operation (same `idempotency_key` pattern as `app/reviews.py::decide_review`), and a real, queryable
  audit trail (`ModelReleaseAuditEventORM`) for every transition. Activating or rolling back a release
  changes what `app/serving/router.py::get_model_backend` actually serves, proven end to end by
  `tests/test_model_release.py::test_real_requests_observe_activation_and_rollback_end_to_end` — not
  just a database row, which is exactly what the new gap rows above are careful to say this is *not*
  a claim of (no automatic regression detection, gate is a smoke check, single-process only). See
  [ADR 0007](adrs/0007-model-release-lifecycle.md).
