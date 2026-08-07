"""Evaluation runner for the versioned synthetic dataset (app/fixtures/eval_dataset.json).

Runs the same deterministic pipeline used by the API/demo against every
dataset case and computes machine-readable metrics. Nothing here is
hard-coded: every number is derived from running app.services.workflow
against the fixtures in this repository.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from app.services.workflow import CaseArtifacts, run_case_pipeline

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_json(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def wilson_lower_bound(successes: int, total: int, z: float = 1.96) -> float:
    """95% Wilson score interval lower bound for a binomial proportion.
    Used to express that N/N observed success is not a guarantee of future
    performance, especially for small N."""
    if total == 0:
        return 0.0
    p = successes / total
    denom = 1 + z ** 2 / total
    centre = p + z ** 2 / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z ** 2 / (4 * total)) / total)
    return max(0.0, (centre - margin) / denom)


def _case_result(
    entry: dict[str, Any], sources_pool: dict[str, dict], pipeline_source_refs: list[str] | None = None
) -> dict[str, Any]:
    case = entry["case"]
    original_source_refs = case["source_refs"]
    effective_refs = pipeline_source_refs if pipeline_source_refs is not None else original_source_refs
    pipeline_case = {**case, "source_refs": effective_refs}
    sources = [sources_pool[sid] for sid in effective_refs]
    artifacts: CaseArtifacts = run_case_pipeline(pipeline_case, sources)

    expected = entry["expected"]
    actual_decision = artifacts.authority.decision.value
    requires_review = artifacts.review is not None
    auto_refund = next(c for c in artifacts.claims if c.claim_type == "AUTO_REFUND_PERMITTED").status.value

    decision_correct = actual_decision == expected["authority_decision"]
    review_correct = requires_review == expected["requires_review"]
    no_false_authorisation = auto_refund == "FALSE"
    false_authorised = actual_decision == "ALLOW" and expected["authority_decision"] != "ALLOW"

    # Evidence admitted from a source the *dataset author* did not declare for
    # this case is wrong-entity admission — regardless of whether the widened
    # R2 fixture also stuffed it into source_refs.
    wrong_binding_admitted = any(
        e.entity_binding_status == "VALID"
        for e in artifacts.evidence
        if e.source_id not in original_source_refs
    )
    injection_flagged = any("PROMPT_INJECTION_CONTENT" in e.validation_reasons for e in artifacts.evidence)
    injection_altered_decision = expected.get("injection_reason_present") and actual_decision == "ALLOW"

    passed = decision_correct and review_correct and no_false_authorisation and not injection_altered_decision

    return {
        "case_id": entry["case_id"],
        "category": entry["category"],
        "risk_slice": entry["risk_slice"],
        "passed": passed,
        "actual_authority_decision": actual_decision,
        "expected_authority_decision": expected["authority_decision"],
        "requires_review": requires_review,
        "false_authorised": false_authorised,
        "wrong_binding_admitted": wrong_binding_admitted,
        "injection_flagged": injection_flagged,
        "injection_altered_decision": bool(injection_altered_decision),
    }


def run_evaluation(
    dataset_name: str = "eval_dataset.json",
    sources_name: str = "eval_sources.json",
    disable_entity_binding_check: bool = False,
) -> dict[str, Any]:
    """Run every case in the dataset and compute stage/slice metrics.

    `disable_entity_binding_check` powers the R2 regression fixture: it
    monkeypatches nothing in production code, it only widens which sources
    are visible to a case so entity-binding validation is effectively
    defeated for regression-testing purposes (see app.release_gate).
    """
    dataset = _load_json(dataset_name)
    sources_pool = {s["source_id"]: s for s in _load_json(sources_name)["sources"]}

    # R2 regression fixture: widen retrieval scope so every case's pipeline
    # run can see every source in the pool, simulating a broken retrieval
    # scope filter. Evaluation still compares against each case's originally
    # declared source_refs, so any wrongly-admitted evidence is detected.
    all_source_ids = list(sources_pool.keys()) if disable_entity_binding_check else None

    results = [
        _case_result(entry, sources_pool, pipeline_source_refs=all_source_ids) for entry in dataset["cases"]
    ]

    critical_positive = [r for r in results if r["category"] == "critical_positive"]
    negative_control = [r for r in results if r["category"] == "negative_control"]

    critical_recovered = sum(1 for r in critical_positive if r["passed"])
    critical_total = len(critical_positive)
    negative_correct = sum(1 for r in negative_control if r["passed"])

    false_authorisation_count = sum(1 for r in results if r["false_authorised"])
    wrong_binding_admitted_count = sum(1 for r in results if r["wrong_binding_admitted"])
    injection_altered_count = sum(1 for r in results if r["injection_altered_decision"])

    per_slice: dict[str, dict[str, int]] = {}
    for r in results:
        slice_stats = per_slice.setdefault(r["risk_slice"], {"total": 0, "passed": 0})
        slice_stats["total"] += 1
        slice_stats["passed"] += int(r["passed"])

    return {
        "dataset_version": dataset["dataset_version"],
        "total_cases": len(results),
        "critical_positive_total": critical_total,
        "critical_positive_recovered": critical_recovered,
        "critical_recall": critical_recovered / critical_total if critical_total else 0.0,
        "critical_recall_wilson_lower_bound_95": wilson_lower_bound(critical_recovered, critical_total),
        "negative_control_total": len(negative_control),
        "negative_control_correct": negative_correct,
        "false_authorisation_count": false_authorisation_count,
        "wrong_entity_evidence_admitted_count": wrong_binding_admitted_count,
        "prompt_injection_altered_decision_count": injection_altered_count,
        "per_slice": per_slice,
        "results": results,
    }
