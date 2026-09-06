"""VALIDATE: the only stage allowed to promote a candidate to admitted
Evidence (ADR-0001). Verifies source authority, version/date, case binding,
locator and hash integrity for each candidate; scans excerpt text for
injection markers (app.guardrails) and scores it against the case's derived
query with app.retrieval's TF-IDF cosine similarity. Both the injection scan
and the relevance score only ever add a reason code — never authority/
entity/support status — so untrusted or low-relevance content is data, not
something that can change what gets admitted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.guardrails import scan_for_injection
from app.models import Evidence, SourceSnapshot
from app.retrieval import build_query, is_low_relevance, score_candidates
from app.services.trace import TraceRecorder

STALE_SOURCE_MAX_AGE_DAYS = 365

# PROMPT_INJECTION_CONTENT and LOW_RELEVANCE_RETRIEVAL are recorded but never
# block admission or change downstream rule/authority behaviour — untrusted
# content is data, not an instruction, and a low TF-IDF score is a guardrail
# signal for the operator, not a reason to override the checks below.
NON_BLOCKING_REASONS = {"PROMPT_INJECTION_CONTENT", "LOW_RELEVANCE_RETRIEVAL"}


def validate_evidence(
    case: dict[str, Any], candidates: list[dict[str, Any]], trace: TraceRecorder
) -> tuple[list[SourceSnapshot], list[Evidence]]:
    snapshots: list[SourceSnapshot] = []
    evidence: list[Evidence] = []
    expected_versions: dict[str, str] = case.get("expected_source_versions", {})
    as_of = datetime.fromisoformat(case["as_of"].replace("Z", "+00:00"))
    relevance_scores = score_candidates(build_query(case), candidates)

    for cand in candidates:
        snapshot = SourceSnapshot(
            source_id=cand["source_id"],
            url=cand["url"],
            title=cand["title"],
            source_class=cand["source_class"],
            retrieved_at=datetime.fromisoformat(cand["retrieved_at"].replace("Z", "+00:00")),
            effective_at=(
                datetime.fromisoformat(cand["effective_at"]).replace(tzinfo=timezone.utc)
                if cand.get("effective_at")
                else None
            ),
            content_hash=cand["content_hash"],
            version=cand["version"],
            allowed_for_evidence=cand["allowed_for_evidence"],
        )
        snapshots.append(snapshot)

        reasons: list[str] = []

        authority_status = "VALID" if snapshot.allowed_for_evidence else "INVALID"
        if not snapshot.allowed_for_evidence:
            reasons.append("SOURCE_NOT_ALLOWED")

        entity_binding_status = "VALID" if cand["source_id"] in case["source_refs"] else "INVALID"
        if entity_binding_status == "INVALID":
            reasons.append("WRONG_CASE_BINDING")

        expected_version = expected_versions.get(cand["source_id"])
        if expected_version and expected_version != snapshot.version:
            reasons.append("SOURCE_VERSION_MISMATCH")

        if snapshot.effective_at and (as_of - snapshot.effective_at).days > STALE_SOURCE_MAX_AGE_DAYS:
            reasons.append("SOURCE_STALE_OR_OUT_OF_TIME")

        if cand.get("tampered_hash"):
            reasons.append("HASH_MISMATCH")

        locator = cand.get("locator") or cand.get("excerpt_kind")
        if not cand.get("excerpt") or not locator:
            reasons.append("LOCATOR_NOT_FOUND")

        support_status = "SUPPORTED" if cand.get("excerpt") and "LOCATOR_NOT_FOUND" not in reasons else "UNSUPPORTED"
        if support_status == "UNSUPPORTED" and "LOCATOR_NOT_FOUND" not in reasons:
            reasons.append("CLAIM_NOT_SUPPORTED")

        if scan_for_injection(cand.get("excerpt", "")):
            reasons.append("PROMPT_INJECTION_CONTENT")

        relevance_score = relevance_scores.get(cand["source_id"], 0.0)
        if is_low_relevance(relevance_score):
            reasons.append("LOW_RELEVANCE_RETRIEVAL")

        ev = Evidence(
            evidence_id=f"EVID-{cand['source_id']}",
            case_id=case["case_id"],
            source_id=cand["source_id"],
            locator=f"{cand.get('excerpt_kind', 'unknown')}:{cand['source_id']}",
            excerpt=cand.get("excerpt", ""),
            excerpt_kind=cand.get("excerpt_kind", "paraphrase"),
            content_hash=cand["content_hash"],
            authority_status=authority_status,
            entity_binding_status=entity_binding_status,
            support_status=support_status,
            validation_reasons=reasons,
            relevance_score=relevance_score,
        )
        evidence.append(ev)
        trace.record(
            "VALIDATE",
            "EVIDENCE_VALIDATED" if not reasons else "EVIDENCE_REJECTED",
            evidence_ids=[ev.evidence_id],
        )

    fault_sources = {c["source_id"]: c for c in candidates if c["source_class"] == "fault_assessment"}
    conclusions = {c.get("fault_conclusion") for c in fault_sources.values() if c.get("fault_conclusion")}
    if len(conclusions) > 1:
        for e in evidence:
            if e.source_id in fault_sources:
                e.validation_reasons.append("CONTRADICTION_PRESENT")

    return snapshots, evidence


def admitted_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """Evidence is admissible only if it has no blocking validation reason —
    see NON_BLOCKING_REASONS above for what doesn't count."""
    return [
        e
        for e in evidence
        if e.authority_status == "VALID"
        and e.entity_binding_status == "VALID"
        and e.support_status == "SUPPORTED"
        and not (set(e.validation_reasons) - NON_BLOCKING_REASONS)
    ]
