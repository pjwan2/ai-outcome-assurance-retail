# AI Outcome Assurance

Runnable, checkable, reviewable, explicitly-bounded prototype: before relying on an AI-supported retail
outcome, can an operator reconstruct the case, the exact evidence, the claim logic, the authority
decision, the review route, and the observed result?

Independent public-retail prototype. Not legal advice, not a production deployment, no proof of
enterprise safety. All orders/sellers/customers/products/reviewers are synthetic. See
[`docs/limitations.md`](docs/limitations.md) and [`docs/production_gap_register.md`](docs/production_gap_register.md).

## Quickstart

```bash
make setup
make migrate
make test        # 30 tests
make lint        # ruff, clean
make typecheck    # mypy, clean
make eval         # R1 PASS / R2 BLOCK release-gate JSON
make demo-smoke   # end-to-end hero case check, exits non-zero on failure
```

Then, in two terminals:

```bash
cd backend && python run_server.py     # http://127.0.0.1:8000
cd frontend && npm run dev             # http://localhost:5173
```

No API key is required anywhere in this repository — the only investigation planner implemented is
deterministic and offline.

## What's here

- **Deterministic control chain**: `backend/app/services/workflow.py` — CASE → INVESTIGATE → VALIDATE →
  RESOLVE → AUTHORISE → RECONCILE, with a `TraceEvent` per material step.
- **Typed persistence**: SQLAlchemy 2 + Alembic (`backend/app/orm_models.py`, `backend/alembic/`).
- **Tri-state claims, independent authority gate, human review queue** — never an LLM prompt
  (`app/services/workflow.py::_authorise`, `app/authority_enforcement.py`).
- **28-case versioned evaluation dataset + deterministic release gate**, R1 reference vs R2 regression
  fixture (`app/evaluation.py`, `app/release_gate.py`, `backend/scripts/generate_eval_dataset.py`).
- **16 adversarial tests** (wrong seller/order, stale source, hash mismatch, missing locator, prompt
  injection, contradiction, budget exhaustion, invalid state transition, idempotent review decisions,
  outcome mismatch, blocked auto-refund — `backend/tests/test_adversarial.py`).
- **REST API** (`backend/app/api.py`) and a **4-view operator UI** (`frontend/src/App.tsx`): Case
  Overview, Evidence & Claims, Review Queue, Trace & Release.

Full docs: [`docs/architecture.md`](docs/architecture.md) ·
[`docs/demo_runbook.md`](docs/demo_runbook.md) ·
[`docs/demo_script.md`](docs/demo_script.md) ·
[`docs/evaluation.md`](docs/evaluation.md) ·
[`docs/release_gate.md`](docs/release_gate.md) ·
[`docs/security.md`](docs/security.md) ·
[`docs/interview_evidence.md`](docs/interview_evidence.md).
