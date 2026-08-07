from app.evaluation import run_evaluation, wilson_lower_bound
from app.release_gate import run_regression_release_gate, run_release_gate


def test_dataset_has_28_cases_24_critical_4_negative():
    evaluation = run_evaluation()
    assert evaluation["total_cases"] == 28
    assert evaluation["critical_positive_total"] == 24
    assert evaluation["negative_control_total"] == 4


def test_required_risk_slices_are_covered():
    evaluation = run_evaluation()
    required = {
        "missing_evidence",
        "wrong_seller",
        "wrong_order",
        "wrong_product",
        "stale_source",
        "hash_mismatch",
        "fabricated_locator",
        "source_version_mismatch",
        "contradiction",
        "prompt_injection",
    }
    assert required.issubset(evaluation["per_slice"].keys())


def test_r1_reference_passes_release_gate():
    r1 = run_release_gate()
    assert r1["decision"] == "PASS"
    assert r1["reason_codes"] == []
    assert r1["critical_positive_recovered"] == r1["critical_positive_total"]


def test_r2_regression_fixture_is_blocked():
    r2 = run_regression_release_gate()
    assert r2["decision"] == "BLOCK"
    assert len(r2["reason_codes"]) > 0


def test_wilson_lower_bound_is_below_observed_rate_for_small_n():
    # 24/24 observed is not a guarantee: the lower bound must be strictly
    # below the naive 100% observed rate.
    lb = wilson_lower_bound(24, 24)
    assert 0.0 < lb < 1.0


def test_wilson_lower_bound_zero_total_is_zero():
    assert wilson_lower_bound(0, 0) == 0.0
