.PHONY: setup migrate seed test lint typecheck eval demo-reset demo-smoke

setup:
	cd backend && python -m pip install -r requirements-dev.txt
	cd frontend && npm install

migrate:
	cd backend && python -m alembic upgrade head

seed:
	cd backend && python scripts/generate_eval_dataset.py

test:
	cd backend && python -m pytest -q

lint:
	cd backend && python -m ruff check app tests loadtest

typecheck:
	cd backend && python -m mypy app

eval:
	cd backend && python -c "from app.release_gate import run_release_gate, run_regression_release_gate; import json; print('R1', json.dumps(run_release_gate(), indent=2)); print('R2', json.dumps(run_regression_release_gate(), indent=2))"

demo-reset:
	cd backend && rm -f ai_outcome_assurance.db && python -m alembic upgrade head

demo-smoke:
	cd backend && python scripts/demo_smoke.py
