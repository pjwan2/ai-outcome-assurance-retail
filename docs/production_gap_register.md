# Production gap register

Explicitly proposed, not implemented (PRD §4). Listed here so nothing in this repository can be
mistaken for a production claim.

| Gap | Why it matters | What exists today |
|---|---|---|
| Enterprise IAM / access control | API has no authn/authz | `reviewer_id` is a free-text field |
| Production data classification & retention | No PII/retention policy engine | Only synthetic fixtures exist |
| Distributed queues / distributed tracing | Single-process, synchronous pipeline | In-process `_TraceRecorder`, SQLite |
| Real retailer/order/CRM integration | No external system calls anywhere | Local JSON fixtures only |
| Automatic refunds or other irreversible actions | `AUTO_REFUND_PERMITTED` is hard-coded FALSE, `enforce_action` blocks `AUTO_REFUND`/`ISSUE_REFUND` outside `ALLOW` | Enforced in code and tested (`tests/test_adversarial.py` #16) |
| Enterprise legal/compliance accreditation | No accreditation process exists | N/A — explicitly out of scope (PRD §2) |
| Autonomous multi-agent swarms | Single deterministic pipeline, no agent loop | `DeterministicInvestigationPlanner`-equivalent fixed logic only |
| Cross-case long-term memory | Each run is independent | No memory store |
| Production-scale vector infrastructure | Only fixture-backed lexical matching | No embeddings, no vector DB |
| Live Anthropic/Google adapters | Not started | `app.tools`/pipeline interfaces are provider-neutral but no live adapter exists |
| Live OpenAI adapter | Optional per PRD §13/§6, not implemented in this session | Offline deterministic path only |
| Multi-case intake | Only the hero fixture is runnable via the API | `case_id` path params are accepted but ignored — see `docs/limitations.md` |
| Docker build verification | Dockerfiles/compose exist and were reviewed, but `docker compose up --build` has not been run end-to-end (no Docker daemon in the dev sandbox that wrote them) | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` — please confirm with a real build on your machine before relying on it |

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
- **Containerisation** — `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` added (see
  the row above for the one remaining caveat: not yet build-verified end-to-end).
- **CI/CD** — this is now a git repository with `.github/workflows/ci.yml`, confirmed green on GitHub
  Actions: https://github.com/pjwan2/ai-outcome-assurance-retail/actions/runs/31313642354 (backend and
  frontend jobs both passed).
