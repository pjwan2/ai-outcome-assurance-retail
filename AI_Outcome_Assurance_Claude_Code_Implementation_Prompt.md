# AI Outcome Assurance
## Claude Code Implementation Prompt — Runnable Public-Retail Vertical Slice



---

# BEGIN PROMPT

You are the lead Senior AI Engineer responsible for implementing a credible interview-grade prototype called **AI Outcome Assurance**.

Work directly in the current repository. First inspect what already exists; then implement the smallest coherent vertical slice that satisfies this specification. Do not rebuild working components without evidence that they are unsuitable.

## 1. Product outcome

Build a runnable system that answers this operational question:

> Before relying on an AI-supported retail outcome, can an operator reconstruct the case, exact evidence, claim logic, authority decision, review route and observed result?

The prototype must demonstrate the following principle:

> Investigation may be probabilistic. Evidence status, canonical state, decision authority and side effects remain controlled by typed application code and versioned rules.

This is an independent public-retail prototype. It is not legal advice, not a production deployment and not proof of enterprise safety.

## 2. Hard scope and privacy boundary

Use only:

- public retailer policy or guarantee pages;
- public ACCC consumer guidance;
- entirely synthetic orders, products, customers, sellers, conversations, faults, reviewer decisions and evaluation cases;
- public model APIs and official public developer documentation.

Never add:

- company-internal policy, architecture, source code, customer data, incident data, prompts, outputs or proprietary terminology;
- real personal information;
- banking policy or banking customer cases;
- automatic legal-entitlement decisions;
- claims of production safety, accreditation or live deployment;
- invented test results or implementation claims.

If the repository contains potentially confidential material, report only its path and classification. Do not copy the content into generated documents or fixtures.

Do not include internal job grades or self-assessed seniority claims in the product or documentation. Let runnable engineering evidence speak for itself.

## 3. Canonical synthetic retail case

Use one consistent hero case across fixtures, API examples, UI, tests and the demo script:

- Product: premium laptop purchased through a marketplace retailer.
- Event: intermittent shutdown begins 45 days after delivery.
- Seller response: the seller tells the customer to contact the manufacturer.
- Customer request: refund.
- Sources: public retailer guarantee/customer-charter pages and public ACCC guidance.
- Identity: synthetic case, order, seller, customer, timestamps and product identifiers.
- Legal boundary: the system must not determine statutory entitlement.

Expected controlled outcome:

1. Verify the order, seller, event dates, policy source/version, exact cited span and entity binding.
2. Represent the marketplace-escalation pathway as a versioned operational rule based on public wording.
3. Keep the claim that the defect is a “major failure” as `UNKNOWN` when reliable fault assessment is absent.
4. Return `REQUIRE_HUMAN` for the refund action.
5. Request the missing fault evidence.
6. Route the case to a review queue with a reason code and owner.
7. Persist trace events so the case can be replayed and inspected.
8. Record the actual reviewer/outcome result separately from the proposed action.

Core message:

> Operationalise uncertainty; do not automate legal entitlement.

Public source manifest:

- <https://www.kogan.com/au/guarantee/>
- <https://www.kogan.com/au/customer-charter/>
- <https://www.accc.gov.au/consumers/buying-products-and-services/consumer-rights-and-guarantees>
- <https://www.accc.gov.au/consumers/buying-products-and-services/warranties>

Do not depend on live web access during the demo. Store a source manifest and small, legally safe local fixtures containing source metadata and short necessary excerpts or paraphrased operational rules. Preserve URL, retrieval time, content hash, source class, effective/as-of date when known and exact locator information. Clearly label paraphrase versus quote.

## 4. Delivery strategy

Implement the following as the **core vertical slice**:

1. Typed domain contracts and canonical state.
2. Public-source manifest and synthetic retail fixtures.
3. Candidate retrieval and evidence validation.
4. Tri-state claim resolution: `TRUE | FALSE | UNKNOWN`.
5. Separate authority decision: `ALLOW | DENY | REQUIRE_HUMAN`.
6. Human review queue.
7. Trace, audit and deterministic replay.
8. Evaluation dataset and release gate.
9. Minimal operator UI.
10. Offline deterministic demo plus one optional public OpenAI adapter.

Leave these explicitly **proposed**, not falsely implemented:

- enterprise IAM and access-control integration;
- production data classification and retention;
- distributed queues and distributed tracing;
- real retailer/order/CRM integration;
- automatic refunds or other irreversible external actions;
- enterprise legal/compliance accreditation;
- autonomous multi-agent swarms;
- cross-case long-term memory;
- production-scale vector infrastructure;
- live Anthropic and Google adapters unless there is time after all core acceptance criteria pass.

## 5. Preferred stack

Preserve the existing stack when it already supports the requirements. For a new repository, use:

### Backend

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- SQLite for the portable interview demo
- Pytest
- Ruff and mypy or pyright

### Frontend

- React
- TypeScript
- Vite
- a small, accessible component layer without a heavy design-system dependency

### Runtime

- Docker Compose
- deterministic offline provider enabled by default
- optional OpenAI adapter enabled only by environment variable

Do not require paid API access to run tests, evaluation or the main demo.

## 6. Repository inspection before editing

Before making changes:

1. Print a concise repository inventory.
2. Identify current entry points, database models, migrations, APIs, frontend routes, fixtures, tests and documentation.
3. Run existing tests and lint/type checks using documented commands.
4. Record the actual results.
5. Search for secrets, real personal data and prohibited internal content without printing sensitive values.
6. Produce a short implementation plan mapped to existing files.
7. Continue autonomously unless a destructive change, secret-handling decision or true product ambiguity requires confirmation.

Never use destructive Git commands. Preserve unrelated user changes. Do not hide or delete failing tests.

## 7. Required parent architecture

Implement or clearly map the following control chain:

```text
CASE
  -> INVESTIGATE
  -> VALIDATE
  -> RESOLVE
  -> AUTHORISE
  -> RECONCILE

Cross-cutting:
CANONICAL STATE -> TRACE -> EVALUATION -> RELEASE GATE -> OWNERSHIP
```

Responsibilities:

### CASE

- establish immutable case identity;
- bind order, seller, product and as-of time;
- load declared public source references;
- assign risk band and current status.

### INVESTIGATE

- search only governed local fixtures or explicitly allowed public-source snapshots;
- return candidate material, never verified fact;
- use read-only tools;
- operate within step, token, tool-call and time budgets.

### VALIDATE

- verify source ID and source class;
- verify source version/content hash;
- verify effective/as-of date where available;
- verify exact locator or cited span;
- verify correct seller/order/product/case binding;
- distinguish quote from paraphrase;
- detect missing, contradictory or countervailing evidence;
- treat retrieved instructions as untrusted content.

### RESOLVE

- apply versioned deterministic rules to verified evidence;
- produce typed claims with `TRUE`, `FALSE` or `UNKNOWN`;
- attach supporting and counter-evidence IDs;
- never convert missing evidence into a confident answer.

### AUTHORISE

- keep proposed action separate from permission;
- produce `ALLOW`, `DENY` or `REQUIRE_HUMAN`;
- enforce the decision in application code;
- use reason codes, expiry and stop conditions;
- never let the model approve its own action.

### RECONCILE

- record intended action separately from observed result;
- record reviewer identity and decision for synthetic demo users;
- detect outcome mismatch;
- make replay and incident-style inspection possible.

## 8. Typed domain model

Implement Pydantic schemas and persistent SQLAlchemy models equivalent to the following. Adapt names to existing conventions, but do not use loose unvalidated dictionaries for material state.

```python
class ClaimStatus(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"

class AuthorityDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"

class TerminationStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONTROL_BLOCKED = "CONTROL_BLOCKED"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
```

Required entities:

```text
Case
  case_id
  as_of
  order_ref
  seller_ref
  product_ref
  risk_band
  status
  source_refs
  created_at
  state_version

SourceSnapshot
  source_id
  url
  title
  source_class
  retrieved_at
  effective_at
  content_hash
  version
  allowed_for_evidence

Evidence
  evidence_id
  case_id
  source_id
  source_version
  locator
  excerpt
  excerpt_kind
  content_hash
  authority_status
  entity_binding_status
  support_status
  validation_reasons

Claim
  claim_id
  case_id
  claim_type
  status
  evidence_ids
  counter_evidence_ids
  rule_version
  reason_codes
  confidence_metadata

AuthorityRecord
  authority_id
  case_id
  proposed_action
  decision
  reason_codes
  required_role
  expires_at
  policy_version
  input_hash

ReviewTask
  review_id
  case_id
  status
  reason_codes
  assigned_role
  reviewer_id
  reviewer_decision
  reviewer_notes
  created_at
  decided_at

Outcome
  outcome_id
  case_id
  attempt_id
  intended_action
  observed_result
  reconciliation_status
  mismatch_reason

TraceEvent
  trace_id
  case_id
  sequence
  stage
  event_type
  tool_name
  argument_hash
  result_hash
  state_before_hash
  state_after_hash
  evidence_ids
  timestamp
```

Add database constraints, foreign keys, indexes, enum validation and Alembic migration coverage. Use optimistic state versioning or an equivalent mechanism to prevent silent concurrent overwrite.

## 9. State machine and runtime invariants

Implement explicit allowed transitions. A valid example is:

```text
CREATED
  -> INVESTIGATING
  -> EVIDENCE_VALIDATED
  -> CLAIMS_RESOLVED
  -> AUTHORITY_EVALUATED
  -> NEEDS_REVIEW | READY_TO_RECONCILE
  -> COMPLETED
```

Required invariants:

- the model may propose, but application code validates and commits transitions;
- every material transition creates a trace event;
- invalid transitions fail closed;
- material state is persisted before any side effect;
- retries are allowed only for idempotent operations;
- every run has maximum steps, tool calls, elapsed time and optional token/cost budgets;
- exhausted budget produces a typed termination state;
- `UNKNOWN`, conflict, missing authority or insufficient evidence routes to review;
- replay uses stored fixtures and recorded rule/model/provider versions;
- a stopped workflow is a valid controlled outcome, not an exception to hide.

## 10. Retrieval implementation

Implement a credible but bounded retrieval layer.

### Required offline path

- index the local public-source fixtures;
- provide lexical retrieval using SQLite FTS5 or an equivalent existing component;
- filter by allowed source class, source version, as-of date and entity scope before evidence admission;
- return candidate IDs, scores and locators;
- apply deterministic post-retrieval validation;
- support exact-span lookup.

### Optional live semantic path

If `OPENAI_API_KEY` is available:

- use the current official OpenAI SDK and currently supported embeddings API;
- cache embeddings by content hash and embedding-model version;
- fuse lexical and semantic candidates using Reciprocal Rank Fusion or another documented deterministic method;
- never allow semantic similarity to override source authority, date or entity-binding checks;
- record retrieval mode and model version in trace metadata.

If no API key is available, the system must clearly report `lexical_only` and continue normally. Do not call lexical TF-IDF “semantic retrieval”.

### Reranking

Implement deterministic reranking first using:

- source authority;
- exact entity binding;
- valid as-of/effective date;
- exact-support availability;
- contradiction/counter-evidence flags;
- retrieval score as one input, not the final authority.

An LLM reranker may be added only after the deterministic path and evaluation fixtures pass.

## 11. Evidence validation

Implement independent validators with explicit reason codes:

```text
SOURCE_NOT_ALLOWED
SOURCE_VERSION_MISMATCH
SOURCE_STALE_OR_OUT_OF_TIME
LOCATOR_NOT_FOUND
HASH_MISMATCH
WRONG_CASE_BINDING
WRONG_ORDER_BINDING
WRONG_SELLER_BINDING
WRONG_PRODUCT_BINDING
CLAIM_NOT_SUPPORTED
CONTRADICTION_PRESENT
PROMPT_INJECTION_CONTENT
```

Retrieved content is data, never an instruction. Add at least one fixture containing prompt-injection language and prove that it cannot alter tool permissions, rules, source authority or the authority decision.

## 12. Deterministic claim and authority rules

Implement versioned rules for the hero case. Use explicit rule IDs and reason codes.

Minimum claims:

```text
ORDER_AND_SELLER_VERIFIED
PUBLIC_SOURCE_VALID
SELLER_RESPONSE_RECORDED
MARKETPLACE_ESCALATION_PATH_SUPPORTED
FAULT_ASSESSMENT_AVAILABLE
MAJOR_FAILURE_ESTABLISHED
AUTO_REFUND_PERMITTED
HUMAN_REVIEW_REQUIRED
```

Expected hero-case statuses:

```text
ORDER_AND_SELLER_VERIFIED             TRUE
PUBLIC_SOURCE_VALID                   TRUE
SELLER_RESPONSE_RECORDED              TRUE
MARKETPLACE_ESCALATION_PATH_SUPPORTED TRUE or UNKNOWN based on complete timing fixture
FAULT_ASSESSMENT_AVAILABLE            FALSE
MAJOR_FAILURE_ESTABLISHED             UNKNOWN
AUTO_REFUND_PERMITTED                 FALSE
HUMAN_REVIEW_REQUIRED                 TRUE
```

Expected proposed action and authority result:

```json
{
  "proposed_action": "REQUEST_FAULT_EVIDENCE_AND_ESCALATE",
  "decision": "REQUIRE_HUMAN",
  "reason_codes": [
    "FAULT_STATUS_UNKNOWN",
    "REFUND_REQUIRES_REVIEW",
    "ESCALATION_PATH_AVAILABLE"
  ]
}
```

The authority engine must not be an LLM prompt. It must be deterministic application logic with tests.

## 13. Bounded AI investigation

Create an `InvestigationPlanner` interface.

### Required provider

Implement `DeterministicInvestigationPlanner` for offline tests and demo. It should choose from a fixed allow-list of read-only tools and produce the same typed proposal for the same fixture.

### Optional OpenAI provider

Implement `OpenAIInvestigationPlanner` behind an environment flag.

Requirements:

- verify current API and SDK usage against official OpenAI documentation at implementation time;
- use the current public Responses-style API or its official successor;
- use strict structured outputs or tool schemas;
- expose only read-only investigation tools;
- validate every model-produced object with Pydantic;
- reject unknown tools and extra arguments;
- bound steps, calls, time, tokens and cost;
- store provider, model, request/response IDs and token usage without storing secrets;
- never send the model real personal or internal data;
- never let provider conversation state become canonical business state;
- fall back safely to the deterministic planner when the provider is unavailable.

Define a provider-neutral contract so Anthropic or Google adapters could be added later. Do not implement empty adapters merely to list provider names.

## 14. API contract

Implement these endpoints or equivalent REST routes consistent with the existing project:

```text
POST /api/cases
GET  /api/cases/{case_id}
POST /api/cases/{case_id}/run
GET  /api/cases/{case_id}/evidence
GET  /api/cases/{case_id}/claims
GET  /api/cases/{case_id}/authority
GET  /api/cases/{case_id}/trace
POST /api/cases/{case_id}/replay

GET  /api/reviews
GET  /api/reviews/{review_id}
POST /api/reviews/{review_id}/decision

POST /api/evaluations/run
GET  /api/evaluations/{evaluation_id}
GET  /api/releases/latest

GET  /health/live
GET  /health/ready
```

Use idempotency keys for case execution, replay and review decisions where appropriate. Return typed errors with stable error codes. Generate and retain OpenAPI documentation.

## 15. Operator UI

Build a minimal professional UI with four views:

### 1. Case Overview

- synthetic order/seller/product timeline;
- current state and termination status;
- proposed action versus authority decision;
- clear badge showing deterministic or OpenAI investigation mode.

### 2. Evidence & Claims

- candidate material separated from verified evidence;
- source URL, version, hash and exact locator;
- authority/entity/support validation results;
- claim status: TRUE, FALSE or UNKNOWN;
- counter-evidence and reason codes.

### 3. Review Queue

- pending review reason;
- evidence/claim/authority summary;
- reviewer can approve escalation, request more evidence or reject the proposed route;
- no “approve refund” control in the hero demo;
- decision is persisted and traced.

### 4. Trace & Release

- ordered state transitions and tool calls;
- hashes and evidence IDs;
- evaluation results and failed risk slices;
- release decision: PASS or BLOCK with reasons.

Use a clean enterprise UI. Do not spend time on animation or decorative dashboards before the control flow and tests pass.

## 16. Evaluation dataset

Create a synthetic, versioned evaluation dataset.

Preferred shape:

- 28 total cases;
- 24 critical-positive cases where a required escalation or review pathway must be found;
- 4 negative/control cases;
- risk slices covering missing evidence, wrong seller, stale source, wrong product, contradiction, prompt injection, fabricated locator and unsafe authority request.

If an existing dataset already supports the project, preserve it and report its actual composition instead of replacing it.

Required evaluation levels:

### Retrieval

- critical recall;
- Recall@k by source class;
- exact-locator accuracy;
- wrong-authority admission rate;
- wrong-entity admission rate;
- counter-evidence recall.

### Evidence

- support precision;
- unsupported-claim rate;
- contradiction detection;
- fabricated-locator rejection.

### Decision and authority

- tri-state claim correctness;
- false-authorisation rate;
- required-human recall;
- reason-code correctness.

### Trajectory

- valid tool selection;
- permitted arguments;
- valid handoff/transition;
- cited evidence;
- safe authority path;
- typed termination;
- reconciliation recorded.

### Outcome

- correct review route;
- reviewer outcome persisted;
- intended versus observed result reconciled.

## 17. R1/R2 release-gate demonstration

Only implement this section if the repository already uses the R1/R2 concept or the evaluation dataset in section 16 is completed.

Create two explicitly labelled evaluation configurations:

- `R1_REFERENCE`: the current candidate configuration.
- `R2_REGRESSION_FIXTURE`: a deliberately degraded regression-test configuration used only to prove that the release gate blocks material recall loss.

Target demonstration, only if produced by actual runnable evaluation:

```text
R1 critical positives recovered: 24 / 24
R2 critical positives recovered: 12 / 24
R2 release decision: BLOCK
```

Do not hard-code metric output. The values must be calculated from fixtures and predictions. Tests should prove the gate blocks R2.

Clearly state in documentation and UI that R2 is a deliberately degraded regression fixture, not a production model or real deployment result.

If actual results differ, report the actual results and update all documentation. Never modify fixtures merely to recover the desired slide number.

For 24/24 observed successes, calculate and display the 95% Wilson lower bound and explain that observed success is not a guarantee.

## 18. Release gate

Implement a deterministic release decision using versioned thresholds.

At minimum, block release when any of the following occurs:

- false authorisation > 0;
- unauthorised side-effect attempt > 0;
- fabricated evidence admitted > 0;
- wrong seller/order/product evidence admitted > 0;
- prompt injection changes a permission or rule > 0;
- critical recall falls below the configured threshold;
- required-human cases are auto-authorised;
- required evaluation slice is absent;
- evaluation artefacts cannot be reproduced.

Store:

- dataset version;
- code/rule version;
- retrieval configuration;
- provider/model version when used;
- thresholds;
- per-slice metrics;
- release decision and reason codes;
- creation time and command used.

## 19. Required adversarial tests

Add tests for at least:

1. Wrong seller with otherwise similar policy text.
2. Wrong order binding.
3. Stale or mismatched source version.
4. Missing exact locator.
5. Fabricated evidence ID.
6. Prompt injection inside retrieved content.
7. Contradictory evidence.
8. Missing fault assessment.
9. Model proposes an unknown tool.
10. Model proposes extra tool arguments.
11. Invalid state transition.
12. Retry of a non-idempotent action.
13. Budget exhaustion.
14. Review decision replay/idempotency.
15. Intended outcome differs from observed result.
16. Attempted auto-refund when authority is `REQUIRE_HUMAN`.

Do not mock the validators or authority engine in their own tests. Provider API calls must be mocked in the normal test suite.

## 20. Security controls

Implement and test:

- secrets loaded only from environment variables;
- `.env.example` without real values;
- no secrets in trace or logs;
- URL allow-list for any optional ingestion command;
- timeouts, size limits and content-type checks;
- untrusted-content handling for retrieved documents;
- strict tool registry and argument schemas;
- escaped UI rendering of model/retrieval content;
- case-scoped queries to prevent cross-case leakage;
- log minimisation;
- dependency and static-security scan commands where practical.

## 21. Required documentation

Create or update:

```text
README.md
docs/architecture.md
docs/demo_runbook.md
docs/demo_script.md
docs/evaluation.md
docs/release_gate.md
docs/security.md
docs/limitations.md
docs/production_gap_register.md
docs/interview_evidence.md
docs/adrs/0001-control-boundaries.md
docs/adrs/0002-tri-state-claims.md
docs/adrs/0003-model-does-not-own-authority.md
docs/adrs/0004-public-retail-and-synthetic-data.md
```

`docs/interview_evidence.md` must separate:

- `IMPLEMENTED AND VERIFIED`;
- `DEMONSTRATED WITH SYNTHETIC FIXTURES`;
- `PROPOSED FOR ENTERPRISE PRODUCTION`.

For every implemented claim, include file/symbol evidence and the reproduction command. Do not include self-assessed job-level fit.

## 22. Demo commands

Provide simple commands equivalent to:

```bash
make setup
make migrate
make seed
make test
make lint
make typecheck
make eval
make demo-reset
make demo-smoke
docker compose up --build
```

If the project uses another task runner, provide equally simple documented commands.

`make demo-smoke` must:

1. reset/seed the synthetic database;
2. create the hero case;
3. run the offline investigation;
4. validate evidence;
5. resolve tri-state claims;
6. produce `REQUIRE_HUMAN`;
7. create a review task;
8. record trace events;
9. print the case ID and URLs needed for the UI demo;
10. exit non-zero if any expected control outcome is missing.

## 23. Phased implementation order

Implement in this order. Keep the repository runnable after each phase.

### Phase 0 — Audit and plan

- inspect repository;
- run current checks;
- identify prohibited data or secrets;
- map requirements to files;
- create a baseline evidence report.

### Phase 1 — Contracts, persistence and fixtures

- typed enums and schemas;
- SQLAlchemy models and migration;
- public-source manifest;
- hero case and synthetic fixtures;
- unit tests.

### Phase 2 — Controlled outcome pipeline

- state machine;
- candidate retrieval;
- evidence validators;
- deterministic claim rules;
- authority gate;
- review queue;
- reconciliation;
- trace events.

### Phase 3 — Offline AI-shaped runtime

- governed tool registry;
- deterministic planner;
- budgets and typed termination;
- replay;
- prompt-injection and invalid-tool tests.

### Phase 4 — Evaluation and release gate

- versioned dataset;
- stage metrics;
- risk slices;
- release artefact;
- Wilson lower bound;
- optional R1/R2 regression demonstration.

### Phase 5 — API and UI

- REST endpoints;
- four operator views;
- error states;
- review action;
- trace/release inspection.

### Phase 6 — Optional public OpenAI integration

- provider-neutral interface;
- strict structured output/tool schemas;
- optional live planner and optional embeddings;
- offline fallback;
- mocked adapter tests;
- token/cost tracing.

### Phase 7 — Documentation and interview hardening

- runbook and demo script;
- limitations and gap register;
- architecture diagram using Mermaid;
- evidence matrix;
- clean install verification;
- final screenshots only after functionality is stable.

Do not begin Phase 6 while Phases 1–4 are failing.

## 24. Definition of done

The project is done for this interview slice only when:

- a clean setup can run locally from documented commands;
- the hero case completes to `NEEDS_REVIEW` or equivalent controlled state;
- the refund is never auto-authorised;
- the major-failure claim remains `UNKNOWN` without fault evidence;
- every material claim links to admitted evidence or an explicit missing-evidence reason;
- every material state transition is traced;
- a reviewer decision is persisted and replayable;
- adversarial fixtures fail safely;
- evaluation produces a machine-readable artefact;
- the release gate blocks unsafe regression;
- tests, lint and type checks pass or remaining failures are explicitly documented;
- all data is public or synthetic;
- implemented, demonstrated and proposed capabilities are separated;
- no document claims production safety;
- the demo works without a model API key.

## 25. Working protocol

During implementation:

1. Start with the audit summary and phase plan.
2. Make small, coherent edits.
3. Run focused tests after each edit.
4. Run the full suite at the end of every phase.
5. Show actual command results; do not summarise a command that was not run.
6. Preserve failing evidence until the root cause is fixed.
7. Do not reduce test coverage or weaken a gate to obtain a pass.
8. Do not silently change the hero outcome.
9. Ask before destructive operations or material scope changes.
10. Otherwise continue autonomously through the phases.

At the end of each phase, report:

```text
PHASE:
FILES CHANGED:
IMPLEMENTED:
TESTS ADDED:
COMMANDS RUN:
ACTUAL RESULTS:
KNOWN LIMITATIONS:
NEXT PHASE:
```

## 26. Final response required from Claude Code

When implementation is complete, return:

1. A concise architecture summary.
2. The exact end-to-end hero-case result.
3. Files added and changed.
4. Database migrations added.
5. Test, lint and type-check results.
6. Evaluation and release-gate results.
7. Security and adversarial-test results.
8. Commands for the 10-minute live demo.
9. Implemented versus proposed capability table.
10. Remaining production gaps.
11. Exact claims that are safe to use in an interview.
12. Any existing presentation claim that must be removed or revised.

The final engineering standard is:

> Runnable. Checkable. Reviewable. Explicitly bounded.

# END PROMPT

---

## 建议使用方式

1. 把本文件复制到代码项目根目录。
2. 先让 Claude Code 完成 Phase 0，并确认它识别到了现有代码和测试。
3. 不要要求它一口气接三家模型；先完成离线可运行链路和 Release Gate。
4. Phase 1–4 全部稳定以后，再执行 OpenAI 可选适配器。
5. 最终只把 `docs/interview_evidence.md` 中可复现的内容写进 PPT。

面试前最值得真正完成的五项是：

- Typed state 与数据库迁移；
- Evidence Validation 与三值 Claims；
- 独立 Authority Gate 与 Human Review；
- Trace/Replay；
- Evaluation Dataset 与 Release Gate。

这些完成以后，即使没有复杂多 Agent，也已经能够体现高级 AI Engineering 判断。相反，如果这些基础控制没有完成，同时展示大量 Agent、Memory、MCP 或多模型，只会增加被追问时的风险。
