# Demo script (talk track)

**Premise (10 seconds):** "Before relying on an AI-supported retail outcome, can an operator
reconstruct the case, the exact evidence, the claim logic, the authority decision, the review route,
and the observed result? This prototype answers yes, for one synthetic retail refund case, end to end,
offline."

**The case:** A customer buys a premium laptop through a marketplace retailer. It starts shutting down
intermittently 45 days after delivery. The seller tells them to contact the manufacturer. The customer
wants a refund. All entities (`CASE-RET-001`, `ORD-1001`, `SELLER-900`, `PROD-LAPTOP-01`) are synthetic.

**What the system must never do:** auto-approve the refund, or silently assume the fault is "major"
without evidence.

**Walkthrough:**

1. Run `make demo-smoke` — narrate each check as it prints: case created, evidence validated, 8 claims
   resolved, `MAJOR_FAILURE_ESTABLISHED = UNKNOWN`, `REQUIRE_HUMAN`, review task created, trace
   recorded, terminal status `NEEDS_REVIEW`.
2. Open the UI. **Case Overview**: show the badge is `NEEDS_REVIEW`, decision `REQUIRE_HUMAN`, mode
   `DETERMINISTIC (offline)`.
3. **Evidence & Claims**: two admitted sources (Kogan Guarantee, ACCC guidance), both with
   `authority_status=VALID`. Point at `FAULT_ASSESSMENT_AVAILABLE = FALSE` — there is no fault report
   fixture attached to this case, so the system correctly refuses to guess. Note the new relevance
   score column — deterministic TF-IDF cosine similarity against the case, not a raw membership check.
4. **Guardrails**: the generated case summary — built from typed Claims only, never raw text — with
   every sentence shown as `GROUNDED`. Explain the guardrail behind it: `check_groundedness`
   independently re-verifies every citation, and a fabricated one gets replaced, not shown — proven
   with a hand-constructed violation in `tests/test_guardrails.py`, not just the happy path.
5. **Review Queue**: show the pending task with reason `MISSING_FAULT_EVIDENCE`. Note there is no
   "approve refund" button anywhere in this demo — only escalation/evidence-request/reject actions.
6. **Trace & Release**: scroll the trace log — every stage left a row, including the new `GUARDRAILS`
   entries. Click "run release gate": R1 (current fixtures) passes; R2 (a fixture with retrieval scope
   deliberately broken) is blocked with `WRONG_ENTITY_EVIDENCE_ADMITTED`. This is the release gate
   actually running, not a slide.
7. Close with the adversarial suite: `pytest -q tests/test_adversarial.py tests/test_guardrails.py -v`
   — wrong seller, prompt injection, budget exhaustion, attempted auto-refund while `REQUIRE_HUMAN`,
   and a fabricated citation blocked by the groundedness guardrail, all failing safe.

**One-line close:** "Investigation was allowed to be probabilistic. Evidence status, the claim, the
authority decision, and the refund action were not — those stayed in typed, tested, versioned
application code the whole time."
