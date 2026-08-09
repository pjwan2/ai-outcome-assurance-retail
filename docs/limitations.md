# Limitations

This is an interview-grade vertical slice, not a production system. Specifically:

- **Four fixture cases, not free-text intake.** `GET /api/case-fixtures` lists the runnable cases
  (`CASE-RET-001..004`); `POST /api/cases` can run any of them, but there is still no way to submit an
  arbitrary new case — every case is a versioned JSON fixture
  (`backend/app/fixtures/synthetic_case.json` and `backend/app/fixtures/cases/*.json`).
- **No live retrieval or embeddings.** Only the offline lexical/fixture path (PRD §10 "required offline
  path") is implemented. No OpenAI/Anthropic adapter exists in this repository.
- **Evaluation dataset is generated, not hand-authored per case.** The 24 critical-positive cases are
  parametrised variations across a small binding registry and risk-slice list
  (`backend/scripts/generate_eval_dataset.py`), not 24 independently written narratives. This keeps the
  dataset reproducible but means slice diversity is mechanical, not organic.
- **R2 regression fixture does not reproduce a dramatic recall drop.** In this implementation, R2 still
  resolves most claims correctly even with a widened retrieval scope, so the gate blocks specifically on
  `WRONG_ENTITY_EVIDENCE_ADMITTED`, not on a large critical-recall collapse. The PRD's illustrative
  "12/24" example was not reproduced and is not claimed anywhere in this repository.
- **Auth is demo-grade, not enterprise IAM.** `app/auth.py` is a static `API_TOKENS` env-var map of
  bearer tokens to (reviewer_id, role) — no OAuth/OIDC, no token expiry/rotation/revocation, no
  password or MFA, and the zero-config default dev token
  (`dev-local-demo-token`) is baked into the frontend for a frictionless local demo. Fine for this
  prototype; must not be reused as-is anywhere with real users or data.
- **CORS is wide open (`allow_origins=["*"]`).** Fine for a same-machine offline demo with no real user
  data; would need to be scoped to a specific origin before any shared/hosted deployment.

See `docs/production_gap_register.md` for what would need to change for production use.
