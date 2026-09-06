"""Enterprise guardrails engine: input scanning, PII redaction, and a
groundedness ("hallucination") check on a generated, non-authoritative case
summary.

Every check here is read-only with respect to the control chain: it can
annotate, redact, or replace text, but it never receives — and therefore
structurally cannot influence — a `Claim` or `AuthorityDecision`
(`app/services/authorise.py::authorise_case` reads only `claims`, never this
module's output). See docs/adrs/0006-rag-guardrails-are-non-authoritative.md.

`app/services/validate.py::validate_evidence` (formerly `workflow.py::_validate`, before that module
was split up) already had a flat `INJECTION_MARKERS`
substring scan producing a single `PROMPT_INJECTION_CONTENT` reason code;
`scan_for_injection` below is a drop-in replacement that additionally
categorizes *which* pattern matched, without changing which excerpts get
flagged (`INJECTION_CATEGORY_MARKERS` is the same seven markers, just grouped).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Protocol

from app.models import CaseSummarySentence, Claim, Evidence, GuardrailFinding, GuardrailReport

INJECTION_CATEGORY_MARKERS: dict[str, tuple[str, ...]] = {
    "INSTRUCTION_OVERRIDE": ("ignore previous instructions", "ignore all previous", "disregard the above"),
    "ROLE_MANIPULATION": ("you are now", "system:"),
    "AUTHORITY_MANIPULATION": ("set decision", "set authority"),
}


def scan_for_injection(text: str) -> list[str]:
    """Return every injection category whose marker(s) appear in `text`.
    Non-blocking by itself — the caller decides what, if anything, a match
    means (in `validate_evidence`, it sets one PROMPT_INJECTION_CONTENT
    reason code regardless of how many categories matched)."""
    lowered = text.lower()
    return [category for category, markers in INJECTION_CATEGORY_MARKERS.items() if any(m in lowered for m in markers)]


# Regex-based pattern matching, not a trained PII/DLP classifier — see
# docs/production_gap_register.md. The AU-mobile pattern matches this
# repository's Australian-retail theme (ACCC/Kogan fixtures).
PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "AU_PHONE": re.compile(r"\b(?:\+61\s?4|04)\d{2}[\s-]?\d{3}[\s-]?\d{3}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
}


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Replace any detected PII with a `[REDACTED_<CATEGORY>]` marker.
    Returns the redacted text and the list of categories found (empty if
    none)."""
    redacted = text
    found: list[str] = []
    for category, pattern in PII_PATTERNS.items():
        if pattern.search(redacted):
            found.append(category)
            redacted = pattern.sub(f"[REDACTED_{category}]", redacted)
    return redacted, found


_STATUS_WORDS = {"TRUE": "confirmed", "FALSE": "not established", "UNKNOWN": "undetermined"}


def generate_case_summary(claims: list[Claim]) -> list[CaseSummarySentence]:
    """Deterministic, template-based case summary: one sentence per typed
    Claim, built only from Claim fields — never from raw evidence excerpt
    text. Each sentence's `evidence_ids`/`claim_ids` are the citations it
    carries by construction, which `check_groundedness` then independently
    re-verifies rather than trusting.

    This stands in for "the model's answer" in a RAG pipeline. It is
    template-based today (not a live LLM call — see
    docs/production_gap_register.md), which is precisely why the groundedness
    guardrail below is proven with a hand-crafted violation rather than a
    naturally occurring one."""
    sentences: list[CaseSummarySentence] = []
    for claim in claims:
        status_word = _STATUS_WORDS[claim.status.value]
        reason = ", ".join(claim.reason_codes) if claim.reason_codes else "no recorded reason"
        citation = f", citing evidence {', '.join(claim.evidence_ids)}" if claim.evidence_ids else ""
        text = f"Claim {claim.claim_type} is {status_word} ({reason}){citation}."
        sentences.append(
            CaseSummarySentence(text=text, evidence_ids=list(claim.evidence_ids), claim_ids=[claim.claim_id])
        )
    return sentences


UNGROUNDED_FALLBACK_TEXT = "[REDACTED: unsupported statement removed by groundedness guardrail]"


def check_groundedness(
    sentences: list[CaseSummarySentence],
    known_evidence_ids: set[str],
    known_claim_ids: set[str],
) -> tuple[list[CaseSummarySentence], int]:
    """Independently re-verify every sentence's citations against the case's
    real, VALIDATE-produced Evidence set and real Claims. A sentence whose
    citation doesn't check out — the hallucination case, a reference to
    something that was never retrieved or validated at all — is never
    trusted: its rendered text is replaced with a safe fallback and it is
    marked `grounded=False`, rather than shown as-is.

    Deliberately checked against every validated `Evidence`, not only the
    *admitted* subset: `resolve_claims`'s `MAJOR_FAILURE_ESTABLISHED` claim
    (see app/services/resolve.py) legitimately cites evidence excluded from
    `admitted` by a `CONTRADICTION_PRESENT` reason code, precisely so the
    summary can name which sources disagree — that is correct audit
    behaviour, not a hallucination, and an earlier version of this guardrail
    flagged it as one (a real false positive caught by running the full
    evaluation dataset, not assumed away). A citation only fails this check
    if the evidence_id/claim_id does not exist in the case at all.

    `generate_case_summary` above cannot currently produce a citation that
    fails this check (it only ever cites the Claim it was built from), so
    this guardrail is proven with a hand-constructed violation in
    `tests/test_guardrails.py::test_groundedness_guardrail_blocks_a_fabricated_citation`,
    not by a naturally occurring failure — see the module docstring."""
    checked: list[CaseSummarySentence] = []
    ungrounded_count = 0
    for sentence in sentences:
        claims_ok = all(cid in known_claim_ids for cid in sentence.claim_ids)
        evidence_ok = all(eid in known_evidence_ids for eid in sentence.evidence_ids)
        if claims_ok and evidence_ok:
            checked.append(sentence)
        else:
            ungrounded_count += 1
            checked.append(
                CaseSummarySentence(
                    text=UNGROUNDED_FALLBACK_TEXT,
                    evidence_ids=sentence.evidence_ids,
                    claim_ids=sentence.claim_ids,
                    grounded=False,
                )
            )
    return checked, ungrounded_count


class GuardrailTraceRecorder(Protocol):
    """Structural match for `app.services.trace.TraceRecorder.record` —
    identical shape to `app.agents.TraceRecorder`, redeclared here so this
    module has no import dependency on either app.services or app.agents."""

    def record(
        self,
        stage: str,
        event_type: str,
        *,
        tool_name: str | None = None,
        evidence_ids: list[str] | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> None: ...


def run_guardrails(
    case: dict[str, Any],
    evidence: list[Evidence],
    claims: list[Claim],
    trace: GuardrailTraceRecorder,
) -> GuardrailReport:
    """Orchestrates the three guardrail checkpoints and returns one
    GuardrailReport for the case run:

    - input: PII scan over the case's own free-text fields and every
      evidence excerpt (redaction only — never blocks admission, that
      remains `validate_evidence`/`admitted_evidence`'s job per ADR-0001,
      app/services/validate.py).
    - retrieval: surfaces the relevance score `validate_evidence` already
      attached to each Evidence (app.retrieval.score_candidates) — nothing
      new to compute here.
    - output: generates the non-authoritative case summary and independently
      groundedness-checks it before it is fit to expose via the API/UI.
    """
    input_findings: list[GuardrailFinding] = []

    event = case.get("event", {})
    for field_name, value in event.items():
        if not isinstance(value, str):
            continue
        _, pii_categories = redact_pii(value)
        for category in pii_categories:
            input_findings.append(
                GuardrailFinding(
                    category=f"PII_{category}",
                    target=f"case.event.{field_name}",
                    detail="Redacted before display",
                )
            )

    for e in evidence:
        for category in scan_for_injection(e.excerpt):
            input_findings.append(
                GuardrailFinding(
                    category=f"INJECTION_{category}",
                    target=e.evidence_id,
                    detail="Flagged; non-blocking and cannot alter authority (see validate.py::NON_BLOCKING_REASONS)",
                )
            )
        _, pii_categories = redact_pii(e.excerpt)
        for category in pii_categories:
            input_findings.append(
                GuardrailFinding(category=f"PII_{category}", target=e.evidence_id, detail="Redacted before display")
            )

    relevance_scores = {e.evidence_id: e.relevance_score for e in evidence if e.relevance_score is not None}

    known_evidence_ids = {e.evidence_id for e in evidence}
    known_claim_ids = {c.claim_id for c in claims}
    raw_sentences = generate_case_summary(claims)
    checked_sentences, ungrounded_count = check_groundedness(raw_sentences, known_evidence_ids, known_claim_ids)

    evidence_finding_ids = [f.target for f in input_findings if f.target in {e.evidence_id for e in evidence}]
    trace.record("GUARDRAILS", "INPUT_SCAN_COMPLETED", evidence_ids=evidence_finding_ids)
    trace.record("GUARDRAILS", "CASE_SUMMARY_GENERATED", evidence_ids=sorted(relevance_scores.keys()))
    trace.record(
        "GUARDRAILS",
        "GROUNDEDNESS_VIOLATION_BLOCKED" if ungrounded_count else "GROUNDEDNESS_CHECK_PASSED",
    )

    return GuardrailReport(
        report_id=f"GUARDRAIL-{case['case_id']}",
        case_id=case["case_id"],
        input_findings=input_findings,
        relevance_scores=relevance_scores,
        summary_sentences=checked_sentences,
        ungrounded_count=ungrounded_count,
        generated_at=datetime.now(timezone.utc),
    )
