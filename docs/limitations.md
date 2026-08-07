# Limitations

This is an interview-grade vertical slice, not a production system. Specifically:

- **One case shape.** The pipeline always loads `app/fixtures/synthetic_case.json` by default;
  `POST /api/cases/{case_id}/run` and `.../replay` ignore the `case_id` path parameter and always
  re-run the hero fixture. There is no free-text case intake.
- **`TraceEvent` hash fields are unpopulated.** `argument_hash`, `result_hash`, `state_before_hash`,
  `state_after_hash` exist in the schema (PRD §8) but are not computed by
  `app/services/workflow.py::_TraceRecorder`.
- **`CaseStatus` state machine is defined but not enforced.** `app/state_machine.py` exists and is unit
  tested, but `persist_case_run` writes `Case.status` directly to the pipeline's terminal
  `TerminationStatus` rather than stepping through `validate_transition` at each stage.
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
- **No authentication.** The API has no authn/authz layer; `reviewer_id` is caller-supplied.
- **No containerisation verified.** `docker compose up --build` is referenced in the PRD but no
  `Dockerfile`/`docker-compose.yml` exists in this repository yet.
- **Not a git repository as of this session.** No CI, no commit history, no branch protection.

See `docs/production_gap_register.md` for what would need to change for production use.
