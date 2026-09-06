"""Unit tests for app.retrieval: deterministic TF-IDF cosine scoring used by
app.services.workflow._validate to attach Evidence.relevance_score."""

from app.retrieval import build_query, is_low_relevance, score_candidates, tokenize


def test_scoring_is_deterministic():
    candidates = [
        {"source_id": "SRC-A", "excerpt": "The seller offers a refund for major failures."},
        {"source_id": "SRC-B", "excerpt": "Unrelated weather forecast for tomorrow."},
    ]
    first = score_candidates("refund major failure", candidates)
    second = score_candidates("refund major failure", candidates)
    assert first == second


def test_relevant_candidate_scores_higher_than_unrelated_one():
    candidates = [
        {"source_id": "SRC-RELEVANT", "excerpt": "Marketplace sellers may offer a refund for a major failure."},
        {"source_id": "SRC-UNRELATED", "excerpt": "Weather forecasts predict rain across the region tomorrow."},
    ]
    scores = score_candidates("refund major failure laptop", candidates)
    assert scores["SRC-RELEVANT"] > scores["SRC-UNRELATED"]
    assert is_low_relevance(scores["SRC-UNRELATED"])
    assert not is_low_relevance(scores["SRC-RELEVANT"])


def test_empty_query_yields_zero_scores_not_an_error():
    scores = score_candidates("", [{"source_id": "SRC-A", "excerpt": "Some excerpt text."}])
    assert scores == {"SRC-A": 0.0}


def test_build_query_pulls_from_case_fields_only():
    case = {
        "customer_request": "refund",
        "product_ref": "PROD-LAPTOP-01",
        "event": {"seller_response": "Please contact the manufacturer."},
    }
    query = build_query(case)
    tokens = tokenize(query)
    assert "refund" in tokens
    assert "manufacturer" in tokens
