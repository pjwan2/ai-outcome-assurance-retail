# ADR 0006: RAG retrieval scoring and guardrails stay non-authoritative

## Status
Accepted

## Context
Two gaps sat in this repository even after ADR-0005's multi-agent investigation loop:

- `app/agents.py::RetrievalAgent` returned candidates with no ranking signal at all — a source was a
  "match" purely because its `source_id` appeared in `case["source_refs"]`. That is fixture lookup,
  not retrieval.
- Nothing played the role of "the model's answer." `validate_evidence` (`workflow.py::_validate` at the
  time this ADR was written, before a later refactor split `workflow.py` into `app/services/*.py`)
  already had guardrail-shaped checks
  (source authority, hash integrity, contradiction detection, a flat `INJECTION_MARKERS` substring
  scan), but there was no generation step, so there was nothing for a groundedness/hallucination
  guardrail to check.

This ADR adds both, under the same fail-closed posture ADR-0001/0003 already established for
INVESTIGATE: whatever is added must be able to annotate, score, or redact, but must never become a
second path into `authorise_case`.

## Decision
`app/retrieval.py` adds deterministic TF-IDF + cosine-similarity scoring (pure standard library — no
embedding model, no vector database, no network call; see the "What is not claimed here" additions
in `docs/verification_matrix.md`). `validate_evidence` (`app/services/validate.py`) attaches a
`relevance_score` to every `Evidence` and records a new `LOW_RELEVANCE_RETRIEVAL` reason code for
low-scoring candidates. That reason code is added to the existing `NON_BLOCKING_REASONS` set
alongside `PROMPT_INJECTION_CONTENT` — it changes nothing about admission, resolution, or authority.

`app/guardrails.py` adds a three-checkpoint engine:

- **Input**: `scan_for_injection` replaces the old flat `INJECTION_MARKERS` tuple with a categorized
  `INJECTION_CATEGORY_MARKERS` dict (same seven markers, grouped into `INSTRUCTION_OVERRIDE` /
  `ROLE_MANIPULATION` / `AUTHORITY_MANIPULATION`) — `validate_evidence` still sets exactly one
  `PROMPT_INJECTION_CONTENT` reason code, so no existing behaviour changes. `redact_pii` finds and
  masks email/AU-mobile/credit-card-shaped text (regex-based, not a trained DLP classifier) in the
  case's own free-text fields and in evidence excerpts.
- **Retrieval**: surfaces the `relevance_score` `validate_evidence` already computed — nothing new here.
- **Output**: `generate_case_summary` builds a deterministic, template-based, non-authoritative case
  summary from typed `Claim` objects only — never from raw excerpt text. Each sentence carries the
  evidence/claim IDs it cites *by construction*. `check_groundedness` independently re-verifies every
  citation against the case's real, VALIDATE-produced evidence and claims; a citation that doesn't
  exist is the hallucination case, and its sentence is replaced with a safe fallback string rather
  than shown as-is.

`run_guardrails` is called from `run_case_pipeline` right after `resolve_claims`, before
`authorise_case`. `authorise_case`'s signature is untouched — it still reads only `claims` — so this
step structurally cannot influence the authority decision, the same boundary ADR-0001/0003 enforce for
INVESTIGATE. Guardrail findings are recorded via the same `TraceRecorder.record(...)`
(`app/services/trace.py`) INVESTIGATE already uses (`app.agents.TraceRecorder` /
`app.guardrails.GuardrailTraceRecorder` are the same structural Protocol), so guardrail activity is
folded into the existing SHA-256 trace chain for free.

### A false positive worth recording
`check_groundedness` was first written to verify citations against the *admitted* evidence set. Running it
across the full 28-case evaluation dataset (not just the hero case) surfaced two failures:
`EVAL-CP-CONTRADICTION` and `EVAL-CP-CONTRADICTION-B`. The cause: `resolve_claims`'s
`MAJOR_FAILURE_ESTABLISHED` claim deliberately cites evidence excluded from `admitted` by a
`CONTRADICTION_PRESENT` reason code, specifically so the claim can name which sources disagree — that
is correct, pre-existing audit behaviour, not a hallucination. The fix was to verify citations against
every validated `Evidence` the case produced, not only the admitted subset — grounded means "this
reference is real," not "this reference was admitted," which is a separate, already-encoded dimension
(`authority_status`/`entity_binding_status`/`support_status`). See
`tests/test_guardrails.py::test_contradiction_case_counter_evidence_citation_is_grounded_not_hallucinated`.

## Consequences
- `groundedness_pass_rate` is 1.0 on the current dataset by construction: the generator only ever
  cites the `Claim` it was built from, so it cannot currently produce a citation that fails the check.
  The guardrail itself is proven independently, with a hand-constructed violation
  (`tests/test_guardrails.py::test_groundedness_guardrail_blocks_a_fabricated_citation`) — the same
  honest framing ADR-0005 already uses for the `AgentRun` `CheckConstraint` test. Neither this ADR nor
  `docs/verification_matrix.md` claims the 1.0 is evidence the guardrail would catch a real live-LLM
  hallucination; that would require an actual live generation adapter, which does not exist here (see
  `docs/production_gap_register.md`).
- `mean_retrieval_relevance`/`groundedness_pass_rate`/`pii_redaction_count` are computed the same
  no-hard-coded-numbers way as every other evaluation metric and are wired into
  `EvaluationRunORM`/the `/api/evaluations/{id}` response. No new release-gate hard block is added on
  them — see `docs/release_gate.md` for why.
- The "Production-scale vector infrastructure" row in `docs/production_gap_register.md` is now
  partially addressed (real relevance scoring exists) but not resolved (still no ANN index or vector
  database) — the register spells out the difference explicitly rather than marking it done.
