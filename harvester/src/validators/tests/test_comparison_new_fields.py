from validators.comparison_validator import compare_records


def _with_defaults(overrides):
    base = {"versionModelNumber": "X"}
    base.update(overrides)
    return base


class TestGmdnFields:
    def test_gmdnPTName_match_case_insensitive(self):
        h = _with_defaults({"gmdnPTName": "stent, coronary"})
        g = _with_defaults({"gmdnPTName": "Stent, Coronary"})
        per_field, _ = compare_records(h, g)
        assert per_field["gmdnPTName"]["status"] == "match"

    def test_gmdnPTName_mismatch(self):
        h = _with_defaults({"gmdnPTName": "Stent"})
        g = _with_defaults({"gmdnPTName": "Balloon"})
        per_field, _ = compare_records(h, g)
        assert per_field["gmdnPTName"]["status"] == "mismatch"

    def test_gmdnCode_exact_match(self):
        h = _with_defaults({"gmdnCode": "12345"})
        g = _with_defaults({"gmdnCode": "12345"})
        per_field, _ = compare_records(h, g)
        assert per_field["gmdnCode"]["status"] == "match"

    def test_gmdn_harvested_null_is_not_compared(self):
        h = _with_defaults({"gmdnPTName": None})
        g = _with_defaults({"gmdnPTName": "Stent"})
        per_field, _ = compare_records(h, g)
        assert per_field["gmdnPTName"]["status"] == "not_compared"

    def test_gmdn_both_null(self):
        h = _with_defaults({"gmdnPTName": None})
        g = _with_defaults({"gmdnPTName": None})
        per_field, _ = compare_records(h, g)
        assert per_field["gmdnPTName"]["status"] == "both_null"


class TestProductCodesSubsetMatch:
    def test_equal_sets_match(self):
        h = _with_defaults({"productCodes": ["DYB", "OXM"]})
        g = _with_defaults({"productCodes": ["DYB", "OXM"]})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "match"

    def test_harvested_subset_of_gudid_match(self):
        h = _with_defaults({"productCodes": ["DYB"]})
        g = _with_defaults({"productCodes": ["DYB", "OXM"]})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "match"

    def test_harvested_has_extra_mismatch(self):
        h = _with_defaults({"productCodes": ["DYB", "ZZZ"]})
        g = _with_defaults({"productCodes": ["DYB"]})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "mismatch"

    def test_disjoint_mismatch(self):
        h = _with_defaults({"productCodes": ["ZZZ"]})
        g = _with_defaults({"productCodes": ["DYB"]})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "mismatch"

    def test_harvested_null_not_compared(self):
        h = _with_defaults({"productCodes": None})
        g = _with_defaults({"productCodes": ["DYB"]})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "not_compared"

    def test_both_empty_both_null(self):
        h = _with_defaults({"productCodes": []})
        g = _with_defaults({"productCodes": []})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "both_null"


class TestDeviceCountInBase:
    def test_equal_integers_match(self):
        h = _with_defaults({"deviceCountInBase": 1})
        g = _with_defaults({"deviceCountInBase": 1})
        per_field, _ = compare_records(h, g)
        assert per_field["deviceCountInBase"]["status"] == "match"

    def test_different_integers_mismatch(self):
        h = _with_defaults({"deviceCountInBase": 1})
        g = _with_defaults({"deviceCountInBase": 5})
        per_field, _ = compare_records(h, g)
        assert per_field["deviceCountInBase"]["status"] == "mismatch"


class TestIssuingAgency:
    def test_exact_match(self):
        h = _with_defaults({"issuingAgency": "GS1"})
        g = _with_defaults({"issuingAgency": "GS1"})
        per_field, _ = compare_records(h, g)
        assert per_field["issuingAgency"]["status"] == "match"

    def test_mismatch(self):
        h = _with_defaults({"issuingAgency": "GS1"})
        g = _with_defaults({"issuingAgency": "HIBCC"})
        per_field, _ = compare_records(h, g)
        assert per_field["issuingAgency"]["status"] == "mismatch"


class TestLabeledBooleans:
    def test_lotBatch_match_string_both(self):
        h = _with_defaults({"lotBatch": "true"})
        g = _with_defaults({"lotBatch": "true"})
        per_field, _ = compare_records(h, g)
        assert per_field["lotBatch"]["status"] == "match"

    def test_lotBatch_mismatch(self):
        h = _with_defaults({"lotBatch": True})
        g = _with_defaults({"lotBatch": False})
        per_field, _ = compare_records(h, g)
        assert per_field["lotBatch"]["status"] == "mismatch"

    def test_serialNumber_null_harvested_not_compared(self):
        h = _with_defaults({"serialNumber": None})
        g = _with_defaults({"serialNumber": "false"})
        per_field, _ = compare_records(h, g)
        assert per_field["serialNumber"]["status"] == "not_compared"


class TestPremarketSubmissionsSubsetMatch:
    def test_harvested_subset_match(self):
        h = _with_defaults({"premarketSubmissions": ["K123456"]})
        g = _with_defaults({"premarketSubmissions": ["K123456", "K789012"]})
        per_field, _ = compare_records(h, g)
        assert per_field["premarketSubmissions"]["status"] == "match"

    def test_harvested_claims_unfiled_mismatch(self):
        h = _with_defaults({"premarketSubmissions": ["K999999"]})
        g = _with_defaults({"premarketSubmissions": ["K123456"]})
        per_field, _ = compare_records(h, g)
        assert per_field["premarketSubmissions"]["status"] == "mismatch"

    def test_harvested_null_not_compared(self):
        h = _with_defaults({"premarketSubmissions": None})
        g = _with_defaults({"premarketSubmissions": ["K123456"]})
        per_field, _ = compare_records(h, g)
        assert per_field["premarketSubmissions"]["status"] == "not_compared"

    def test_both_empty_both_null(self):
        h = _with_defaults({"premarketSubmissions": []})
        g = _with_defaults({"premarketSubmissions": []})
        per_field, _ = compare_records(h, g)
        assert per_field["premarketSubmissions"]["status"] == "both_null"
