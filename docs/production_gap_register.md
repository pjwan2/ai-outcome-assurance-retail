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
| CaseStatus state machine enforcement | Defined but not wired into persistence | `app/state_machine.py` (unit tested, not integrated) |
| TraceEvent hash chaining | Schema fields exist, unpopulated | `argument_hash`/`result_hash`/etc. are `None` |
| Containerisation | No Dockerfile/compose file | Local `python`/`npm` commands only |
| CI/CD | Not a git repository yet | `make test`/`lint`/`typecheck` run locally |
| Multi-case intake | Only the hero fixture is runnable via the API | `case_id` path params are accepted but ignored |
