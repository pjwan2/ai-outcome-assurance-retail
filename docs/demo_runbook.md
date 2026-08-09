# Demo runbook

## Prerequisites

- Python 3.12+, Node 18+
- No API keys required — the default provider is `DeterministicInvestigationPlanner`-equivalent
  fixture logic. No live OpenAI/Anthropic calls happen anywhere in this repository today.

## Setup

```bash
make setup      # pip install backend deps, npm install frontend deps
make migrate    # alembic upgrade head — creates backend/ai_outcome_assurance.db
make test       # pytest -q — 39 tests
make lint       # ruff check
make typecheck  # mypy app
make eval       # prints R1 (PASS) and R2 (BLOCK) release-gate JSON
```

## Run the backend

```bash
cd backend
python run_server.py
# or: python -m uvicorn app.api:app --port 8000
```

## Run the frontend

```bash
cd frontend
npm run dev
```

Open the printed Vite URL (default `http://localhost:5173`). The UI calls `http://127.0.0.1:8000` using
a built-in demo bearer token (see `backend/app/auth.py`) — no manual login step for the local demo.

## Run with Docker instead

```bash
docker compose up --build   # backend :8000 (auto-migrates on boot), frontend :5173 (nginx)
```

Build- and run-verified: both images build, the backend runs its Alembic migration on container start,
and the API responds correctly behind the container network.

## Smoke test (no browser needed)

```bash
make demo-smoke
```

Resets the DB, creates the hero case, and asserts: case created, evidence validated, all 8 claims
resolved, `MAJOR_FAILURE_ESTABLISHED = UNKNOWN`, `AuthorityDecision.REQUIRE_HUMAN`, a review task
exists, ≥6 trace events, termination status `NEEDS_REVIEW`. Exits non-zero on any failure.

## 10-minute live demo script

See `docs/demo_script.md` for the talk track. In short:

1. `make demo-reset && make demo-smoke` — show the deterministic outcome in the terminal.
2. Start backend + frontend, open the UI. Pick a case from the sidebar dropdown (`CASE-RET-001`
   through `-004`) to show more than one outcome — e.g. `CASE-RET-003` resolves to `DENY` with no
   review needed, in contrast to the hero case's `REQUIRE_HUMAN`.
3. **Case Overview** tab — point out `REQUIRE_HUMAN` badge, deterministic-mode badge.
4. **Evidence & Claims** tab — point out the tri-state claim table, especially
   `MAJOR_FAILURE_ESTABLISHED = UNKNOWN` and `AUTO_REFUND_PERMITTED = FALSE`.
5. **Review Queue** tab — make a reviewer decision, show it persists.
6. **Trace & Release** tab — show the trace log, then click "Run release gate" and show R1 PASS /
   R2 BLOCK side by side.
7. Run `pytest -q tests/test_adversarial.py -v` live to show wrong-seller / prompt-injection /
   budget-exhaustion tests passing.
