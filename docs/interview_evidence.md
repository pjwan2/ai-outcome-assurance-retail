# Interview evidence

No self-assessed seniority claims below — only what is runnable and where.

## IMPLEMENTED AND VERIFIED

| Claim | Evidence | Reproduce |
|---|---|---|
| Typed tri-state claims (TRUE/FALSE/UNKNOWN) | `backend/app/models.py::ClaimStatus`, `app/services/workflow.py::_resolve` | `pytest tests/test_workflow.py` |
| Independent, deterministic authority gate (no LLM) | `app/services/workflow.py::_authorise`, `app/authority_enforcement.py::enforce_action` | `pytest tests/test_adversarial.py::test_auto_refund_blocked_when_authority_requires_human` |
| SQLAlchemy 2 schema + Alembic migrations | `app/orm_models.py`, `backend/alembic/versions/*.py` | `python -m alembic upgrade head` |
| Optimistic state versioning | `app/persistence.py::persist_case_run` increments `Case.state_version` | `pytest tests/test_persistence.py::test_persist_case_run_is_replayable_and_bumps_state_version` |
| Evidence validators with reason codes | `app/services/workflow.py::_validate` (SOURCE_NOT_ALLOWED, WRONG_*_BINDING, SOURCE_VERSION_MISMATCH, SOURCE_STALE_OR_OUT_OF_TIME, HASH_MISMATCH, LOCATOR_NOT_FOUND, CLAIM_NOT_SUPPORTED, CONTRADICTION_PRESENT, PROMPT_INJECTION_CONTENT) | `pytest tests/test_adversarial.py` |
| Prompt injection cannot alter authority | `INJECTION_MARKERS` scan in `_validate`; injection only adds a reason code | `pytest tests/test_adversarial.py::test_prompt_injection_content_is_flagged_but_never_changes_authority` |
| Governed tool registry, unknown-tool/extra-arg rejection | `app/tools.py` | `pytest tests/test_adversarial.py -k tool` |
| Budgeted runs, typed CONTROL_BLOCKED termination | `app/budget.py`, `run_case_pipeline` | `pytest tests/test_adversarial.py::test_budget_exhaustion_produces_control_blocked_termination` |
| Idempotent review decisions | `app/reviews.py::decide_review` | `pytest tests/test_adversarial.py -k review` |
| Outcome reconciliation with mismatch detection | `app/reconcile.py::reconcile_observed_result` | `pytest tests/test_adversarial.py::test_outcome_mismatch_is_recorded_not_silently_overwritten` |
| Versioned synthetic evaluation dataset (28 cases, 24 critical + 4 negative) | `app/fixtures/eval_dataset.json`, generator `backend/scripts/generate_eval_dataset.py` | `pytest tests/test_evaluation_and_release_gate.py` |
| Deterministic release gate, R1 PASS / R2 BLOCK | `app/release_gate.py` | `make eval` |
| Wilson 95% lower bound on critical recall | `app/evaluation.py::wilson_lower_bound` | `pytest tests/test_evaluation_and_release_gate.py::test_wilson_lower_bound_is_below_observed_rate_for_small_n` |
| REST API covering PRD §14 endpoints | `backend/app/api.py` | `pytest tests/test_api.py` |
| Operator UI — 4 views | `frontend/src/App.tsx` | `npm run dev`, verified: `tsc --noEmit` clean, `npm run build` succeeds, dev server serves the app against a live backend |
| `CaseStatus` state machine actually enforced, not just defined | `app/state_machine.py::validate_transition`, called from `run_case_pipeline` via `_TraceRecorder.transition` | `pytest tests/test_trace_chain.py::test_state_transitions_are_recorded_and_valid` |
| `TraceEvent` SHA-256 hash chain (tamper/reorder detection) | `app/services/workflow.py::_TraceRecorder`, `verify_trace_chain()` | `pytest tests/test_trace_chain.py`, `GET /api/cases/{case_id}/trace/verify` |
| Counter-evidence linked on contradictory claims | `app/services/workflow.py::_resolve` populates `Claim.counter_evidence_ids` | `pytest tests/test_adversarial.py::test_contradiction_populates_counter_evidence_ids` |
| Ruff + mypy clean | — | `make lint`, `make typecheck` |
| 39 passing automated tests, 0 mocked validators/authority logic | `backend/tests/` | `make test` |
| CI passing on GitHub Actions (backend + frontend) | `.github/workflows/ci.yml` | https://github.com/pjwan2/ai-outcome-assurance-retail/actions/runs/31313642354 — both jobs green |
| Four runnable fixture cases, `case_id` actually respected | `app/fixtures/cases/CASE-RET-00{2,3,4}.json`, `app/services/workflow.py::load_case_fixture` | `pytest tests/test_api.py::test_list_case_fixtures_and_run_a_non_hero_case` |
| Bearer-token auth + role-checked review decisions | `app/auth.py::require_auth`, `app/api.py::post_review_decision` | `pytest tests/test_api.py::test_create_case_requires_auth`, `::test_wrong_role_cannot_decide_review` |
| Docker build + run verified end-to-end (not just written) | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` | `docker compose up --build`, then `curl localhost:8000/health` |

## DEMONSTRATED WITH SYNTHETIC FIXTURES

- The full hero-case narrative (marketplace laptop refund, seller redirect to manufacturer, missing
  fault evidence) — all identifiers synthetic.
- 16 adversarial scenarios from PRD §19, run against fixtures, not real retailer data.
- Negative-control cases where a minor/cosmetic fault assessment correctly resolves to `DENY` without
  triggering human review.

## PROPOSED FOR ENTERPRISE PRODUCTION

See `docs/production_gap_register.md` in full — IAM, retention policy, distributed tracing, real CRM
integration, live model adapters, containerisation, CI/CD, multi-case intake, CaseStatus enforcement,
trace hash chaining.

## What is safe to say in an interview

- "I implemented a deterministic authority gate that a model cannot influence, and I have a test that
  proves an attempted auto-refund is blocked when the decision is REQUIRE_HUMAN."
- "I built a release gate that actually blocks a degraded configuration — it's not a slide, it's a
  passing test (`test_r2_regression_fixture_is_blocked`)."
- "Prompt injection in retrieved content is flagged but structurally cannot change the authority
  decision, because the decision only ever reads typed Claim objects, never raw text."
- "24/24 observed critical recall on this dataset has a Wilson 95% lower bound of ~0.86 — I did not
  present the raw 100% as if it were a guarantee."

## What must NOT be claimed

- No claim of production safety, accreditation, or live deployment (PRD §2).
- No claim that R2 reproduces a specific "12/24" degraded-recall number — it does not, and the honest
  number is documented in `docs/evaluation.md`.
- No claim of live OpenAI/Anthropic integration — none exists in this repository.
- No claim that `docker compose up --build` has been run successfully — the Dockerfiles/compose file
  exist and were reviewed, but the build was not executed (no Docker daemon in the dev sandbox).
