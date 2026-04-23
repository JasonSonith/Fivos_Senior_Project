from validators.comparison_validator import compare_records


def test_summary_weighted_differs_from_unweighted():
    """Weighted score should differ from unweighted when weights are not all equal."""
    harvested = {
        "versionModelNumber": "X", "catalogNumber": "Y",
        "brandName": "Z",           "companyName": "Q",
        "MRISafetyStatus": "MR Safe", "singleUse": True, "rx": True,
    }
    gudid = {
        "versionModelNumber": "X", "catalogNumber": "Y",
        "brandName": "Z",           "companyName": "Q",
        "MRISafetyStatus": "MR Unsafe", "singleUse": True, "rx": True,
    }
    _per_field, summary = compare_records(harvested, gudid)
    # 4 high (weight 3) all match → 12 numerator, 12 denominator
    # 2 medium (weight 2) match → +4 numerator, +4 denominator → 16/16
    # 1 medium (weight 2) mismatch → +0 numerator, +2 denominator → 16/18
    assert summary["numerator"] == 16
    assert summary["denominator"] == 18
    # Unweighted: 6/7
    assert summary["unweighted_numerator"] == 6
    assert summary["unweighted_denominator"] == 7
