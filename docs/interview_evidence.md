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
| Prompt injection cannot alter authority | `app/guardrails.py::scan_for_injection` (categorized, called from `_validate`); injection only adds a reason code | `pytest tests/test_adversarial.py::test_prompt_injection_content_is_flagged_but_never_changes_authority` |
| Governed tool registry, unknown-tool/extra-arg rejection | `app/tools.py` | `pytest tests/test_adversarial.py -k tool` |
| Budgeted runs, typed CONTROL_BLOCKED termination | `app/budget.py`, `run_case_pipeline` | `pytest tests/test_adversarial.py::test_budget_exhaustion_produces_control_blocked_termination` |
| Idempotent review decisions | `app/reviews.py::decide_review` | `pytest tests/test_adversarial.py -k review` |
| Outcome reconciliation with mismatch detection | `app/reconcile.py::reconcile_observed_result` | `pytest tests/test_adversarial.py::test_outcome_mismatch_is_recorded_not_silently_overwritten` |
| Versioned synthetic evaluation dataset (28 cases, 24 critical + 4 negative) | `app/fixtures/eval_dataset.json`, generator `backend/scripts/generate_eval_dataset.py` | `pytest tests/test_evaluation_and_release_gate.py` |
| Deterministic release gate, R1 PASS / R2 BLOCK | `app/release_gate.py` | `make eval` |
| Wilson 95% lower bound on critical recall | `app/evaluation.py::wilson_lower_bound` | `pytest tests/test_evaluation_and_release_gate.py::test_wilson_lower_bound_is_below_observed_rate_for_small_n` |
| REST API covering PRD §14 endpoints | `backend/app/api.py` | `pytest tests/test_api.py` |
| Operator UI — 6 tabs (Case Overview, Agent Runs, Evidence & Claims, Guardrails, Review Queue, Trace & Release) | `frontend/src/App.tsx` | `npm run dev`, verified: `tsc --noEmit` clean, `npm run build` succeeds, dev server serves the app against a live backend |
| `CaseStatus` state machine actually enforced, not just defined | `app/state_machine.py::validate_transition`, called from `run_case_pipeline` via `_TraceRecorder.transition` | `pytest tests/test_trace_chain.py::test_state_transitions_are_recorded_and_valid` |
| `TraceEvent` SHA-256 hash chain (tamper/reorder detection) | `app/services/workflow.py::_TraceRecorder`, `verify_trace_chain()` | `pytest tests/test_trace_chain.py`, `GET /api/cases/{case_id}/trace/verify` |
| Counter-evidence linked on contradictory claims | `app/services/workflow.py::_resolve` populates `Claim.counter_evidence_ids` | `pytest tests/test_adversarial.py::test_contradiction_populates_counter_evidence_ids` |
| Ruff + mypy clean | — | `make lint`, `make typecheck` |
| 68 passing automated tests, 0 mocked validators/authority logic | `backend/tests/` | `make test` |
| Loop-controlled agent runs: persisted budget consumption and step-by-step audit trail, not just an in-memory counter | `app/budget.py::RunBudget.tool_calls_used/steps_used`, `app/agents.py`, `app/orm_models.py::AgentRunORM/AgentStepORM` | `pytest tests/test_agent_orchestration.py::test_investigate_produces_supervisor_and_two_child_agent_runs` |
| Bounded multi-agent delegation (Supervisor → Retrieval + Critic agents), INVESTIGATE-only boundary enforced by a database CheckConstraint, not just application code | `app/agents.py::SupervisorPlanner`, `AgentRunORM` (`ck_agent_run_stage_investigate_only`) | `pytest tests/test_agent_orchestration.py::test_agent_run_stage_is_constrained_to_investigate_at_the_db_level` |
| A CONTROL_BLOCKED (budget-exhausted) run still leaves an auditable partial agent-run record, not a silent failure | `app/agents.py::InvestigationBudgetExceeded` | `pytest tests/test_agent_orchestration.py::test_control_blocked_run_still_persists_partial_agent_runs` |
| Agent-run/agent-definition REST endpoints, exercised over real HTTP (not just direct ORM/session calls) | `app/api.py::get_case_agent_runs`, `::list_agent_definitions` | `pytest tests/test_api.py::test_agent_definitions_and_agent_runs_endpoints` |
| Enterprise evaluation provenance: code version (git SHA), environment tag, per-agent metric slice, human release-approval fields | `app/evaluation.py::run_evaluation`, `app/orm_models.py::EvaluationRunORM/ReleaseRecordORM` | `pytest tests/test_api.py::test_evaluation_and_release_endpoints`, `GET /api/evaluations/{id}` returns `code_version`/`environment`/`per_agent_slice` |
| Agent-runs UI: supervisor→retrieval/critic delegation tree, budget/step audit, rendered in the operator UI (not backend-only) | `frontend/src/App.tsx::AgentRuns` | `npm run dev`, browser-verified with Playwright (0 console errors, populated with real data) — see the "Add Agent Runs panel" commit |
| CI passing on GitHub Actions (backend + frontend) | `.github/workflows/ci.yml` | https://github.com/pjwan2/ai-outcome-assurance-retail/actions/runs/31313642354 — both jobs green |
| Four runnable fixture cases, `case_id` actually respected | `app/fixtures/cases/CASE-RET-00{2,3,4}.json`, `app/services/workflow.py::load_case_fixture` | `pytest tests/test_api.py::test_list_case_fixtures_and_run_a_non_hero_case` |
| Bearer-token auth + role-checked review decisions | `app/auth.py::require_auth`, `app/api.py::post_review_decision` | `pytest tests/test_api.py::test_create_case_requires_auth`, `::test_wrong_role_cannot_decide_review` |
| Docker build + run verified end-to-end (not just written) | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` | `docker compose up --build`, then `curl localhost:8000/health` |
| Deterministic TF-IDF + cosine relevance scoring on every retrieved candidate (no embedding model/vector DB) | `app/retrieval.py::score_candidates`, wired into `app/services/workflow.py::_validate` | `pytest tests/test_retrieval.py` |
| Low-relevance retrieval flagged but non-blocking, same treatment as prompt injection | `app/services/workflow.py::_NON_BLOCKING_REASONS` | `pytest tests/test_guardrails.py::test_low_relevance_is_flagged_but_never_blocks_admission` |
| Categorized prompt-injection detection (was a flat marker list) | `app/guardrails.py::scan_for_injection`, `INJECTION_CATEGORY_MARKERS` | `pytest tests/test_guardrails.py::test_scan_for_injection_categorizes_instruction_override` |
| Regex-based PII detection and redaction (email/AU-mobile/credit-card) applied to case text and evidence excerpts | `app/guardrails.py::redact_pii` | `pytest tests/test_guardrails.py -k redact_pii` |
| Generated, non-authoritative case summary with independent groundedness ("hallucination") check — a fabricated citation is blocked and replaced, proven with a hand-constructed violation | `app/guardrails.py::generate_case_summary`, `check_groundedness` | `pytest tests/test_guardrails.py::test_groundedness_guardrail_blocks_a_fabricated_citation` |
| Groundedness checked against the case's real evidence, not only the *admitted* subset — a real false positive on contradiction cases found and fixed by running the full eval dataset | `app/guardrails.py::check_groundedness` docstring, [ADR 0006](adrs/0006-rag-guardrails-are-non-authoritative.md) | `pytest tests/test_guardrails.py::test_contradiction_case_counter_evidence_citation_is_grounded_not_hallucinated` |
| Guardrail engine cannot reach the authority decision — `_authorise`'s signature is unchanged | `app/services/workflow.py::run_case_pipeline` calls `run_guardrails` before `_authorise`, which still reads only `claims` | `pytest tests/test_guardrails.py::test_guardrail_report_never_changes_authority_decision` |
| RAG guardrail metrics (mean retrieval relevance, groundedness pass rate, PII redaction count) computed across the full 28-case dataset, no hard-coded numbers | `app/evaluation.py::run_evaluation` | `pytest tests/test_evaluation_and_release_gate.py::test_rag_guardrail_metrics_are_wired_into_evaluation` |
| Guardrail report and per-evidence relevance score exposed over real HTTP | `app/api.py::get_case_guardrail_report`, `get_case_evidence` | `pytest tests/test_api.py::test_guardrails_endpoint_returns_report_after_case_run`, `::test_evidence_endpoint_includes_relevance_score` |

## DEMONSTRATED WITH SYNTHETIC FIXTURES

- The full hero-case narrative (marketplace laptop refund, seller redirect to manufacturer, missing
  fault evidence) — all identifiers synthetic.
- 16 adversarial scenarios from PRD §19, run against fixtures, not real retailer data.
- Negative-control cases where a minor/cosmetic fault assessment correctly resolves to `DENY` without
  triggering human review.

## PROPOSED FOR ENTERPRISE PRODUCTION

See `docs/production_gap_register.md` in full for the current, maintained list — as of this writing:
enterprise IAM/SSO, PII/data-retention policy, distributed queues/tracing, real retailer/CRM
integration, live OpenAI/Anthropic model adapters, legal/compliance accreditation, cross-case
long-term memory, production-scale vector infrastructure. (Containerisation, CI/CD, multi-case intake,
`CaseStatus` enforcement, trace hash chaining, and bounded multi-agent investigation are now resolved
— see that file's "Resolved since the previous version" section, not this stale list.)

## What is safe to say in an interview

- "I implemented a deterministic authority gate that a model cannot influence, and I have a test that
  proves an attempted auto-refund is blocked when the decision is REQUIRE_HUMAN."
- "I built a release gate that actually blocks a degraded configuration — it's not a slide, it's a
  passing test (`test_r2_regression_fixture_is_blocked`)."
- "Prompt injection in retrieved content is flagged but structurally cannot change the authority
  decision, because the decision only ever reads typed Claim objects, never raw text."
- "24/24 observed critical recall on this dataset has a Wilson 95% lower bound of ~0.86 — I did not
  present the raw 100% as if it were a guarantee."
- "I built a bounded, budget-controlled multi-agent investigation loop — a supervisor delegates to
  independent retrieval and critic agents — and the constraint that keeps any agent from reaching the
  authority decision is enforced by a database CheckConstraint, not just trusted application code."
- "I added real retrieval scoring — deterministic TF-IDF cosine similarity, not a fixture-membership
  lookup — and a three-checkpoint guardrail engine: categorized injection detection, PII redaction,
  and a groundedness check on a generated case summary that blocks and replaces any sentence whose
  citation doesn't actually exist in the case."
- "The generator is template-based today, so it can't currently produce a real hallucination — I
  proved the groundedness guardrail actually works with a unit test that hand-constructs a fabricated
  citation, rather than only testing the happy path."
- "While building that guardrail I found a real false positive: it initially flagged a legitimate
  contradiction-case citation as ungrounded because it checked against *admitted* evidence instead of
  all validated evidence. I found that by running the full 28-case evaluation dataset, not just the
  hero case, and fixed the check's definition — that's documented in ADR-0006, not swept under the
  rug."

## What must NOT be claimed

- No claim of production safety, accreditation, or live deployment (PRD §2).
- No claim that R2 reproduces a specific "12/24" degraded-recall number — it does not, and the honest
  number is documented in `docs/evaluation.md`.
- No claim of live OpenAI/Anthropic integration — none exists in this repository.
  `AgentProvider.OPENAI`/`ANTHROPIC` are schema-ready enum values only; every agent that actually runs
  (`RetrievalAgent`, `CriticAgent`, `SupervisorPlanner`) is deterministic and offline.
- No claim that `docker compose up --build` has been run successfully — the Dockerfiles/compose file
  exist and were reviewed, but the build was not executed (no Docker daemon in the dev sandbox).
- No claim that the Guardrails tab was visually/browser-verified — no screenshot/browser automation
  tool was available in the session that built it. What was actually verified: `tsc --noEmit` clean,
  `npm run build` succeeds, the dev server serves the app shell, and `GET
  /api/cases/{case_id}/guardrails` returns exactly the JSON shape the component consumes (checked
  over real HTTP, not assumed). Open the app yourself to confirm rendering before an interview.
- No claim of a vector database, ANN index, or embedding model — `app/retrieval.py` is pure-Python
  TF-IDF/cosine similarity over the fixture corpus, a deliberate choice for determinism and offline
  testability, not a placeholder for something more sophisticated already built.
- No claim that the case summary is generated by a live LLM — `generate_case_summary`
  (`app/guardrails.py`) is deterministic and template-based. The groundedness guardrail is
  independently unit-tested against a hand-crafted violation; that is not the same as evidence it
  would catch a real model's hallucination in production.
- No claim that PII detection is a trained DLP classifier — `redact_pii` is three fixed regexes
  (email, AU mobile, credit-card-shaped digit runs). No claim that injection categorization is backed
  by a maintained red-team corpus — `INJECTION_CATEGORY_MARKERS` is the same seven substring markers
  the prototype always had, just grouped into categories.
- No claim that `groundedness_pass_rate: 1.0` on the current dataset means the guardrail is proven
  against real hallucinations — it is 1.0 by construction (the generator only ever cites the Claim it
  was built from) and the register above documents exactly what would need to change (a live
  generation adapter) for that number to mean something harder.
