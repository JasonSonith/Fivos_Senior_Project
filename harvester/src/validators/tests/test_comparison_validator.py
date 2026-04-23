from validators.comparison_validator import compare_records


BASE_HARVESTED = {
    "versionModelNumber": "ADM-35-40-130",
    "catalogNumber": "CAT-001",
    "brandName": "Admiral",
    "companyName": "Medtronic, Inc.",
    "deviceDescription": "Drug-coated balloon for peripheral arterial disease",
}

BASE_GUDID = {
    "versionModelNumber": "ADM-35-40-130",
    "catalogNumber": "CAT-001",
    "brandName": "Admiral",
    "companyName": "MEDTRONIC INC",
    "deviceDescription": "Drug-coated balloon for peripheral arterial disease",
}


class TestIdentifierFieldsRegression:
    """Existing four identifier fields + description similarity must keep working."""

    def test_all_four_identifiers_match(self):
        per_field, _ = compare_records(BASE_HARVESTED, BASE_GUDID)
        assert per_field["versionModelNumber"]["status"] == "match"
        assert per_field["catalogNumber"]["status"] == "match"
        assert per_field["brandName"]["status"] == "match"
        assert per_field["companyName"]["status"] == "match"

    def test_model_number_mismatch(self):
        harvested = {**BASE_HARVESTED, "versionModelNumber": "XYZ"}
        per_field, _ = compare_records(harvested, BASE_GUDID)
        assert per_field["versionModelNumber"]["status"] == "mismatch"

    def test_description_similarity_present(self):
        per_field, _ = compare_records(BASE_HARVESTED, BASE_GUDID)
        assert "similarity" in per_field["deviceDescription"]
        assert per_field["deviceDescription"]["similarity"] == 1.0

    def test_harvested_model_none_skips(self):
        harvested = {**BASE_HARVESTED, "versionModelNumber": None}
        per_field, _ = compare_records(harvested, BASE_GUDID)
        assert per_field["versionModelNumber"]["status"] == "not_compared"


class TestMRISafetyStatus:

    def test_match_exact(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "MR Safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Safe"}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["MRISafetyStatus"]["status"] == "match"

    def test_match_variant_normalization(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "mri safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Safe"}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["MRISafetyStatus"]["status"] == "match"

    def test_mismatch(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "MR Safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Conditional"}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["MRISafetyStatus"]["status"] == "mismatch"

    def test_harvested_null_skips(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": None}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Safe"}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["MRISafetyStatus"]["status"] == "not_compared"

    def test_gudid_null_skips(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "MR Safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": None}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["MRISafetyStatus"]["status"] == "not_compared"

    def test_both_null_yields_both_null(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": None}
        gudid = {**BASE_GUDID, "MRISafetyStatus": None}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["MRISafetyStatus"]["status"] == "both_null"


class TestSingleUse:

    def test_match_true(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": True}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["singleUse"]["status"] == "match"

    def test_match_false(self):
        harvested = {**BASE_HARVESTED, "singleUse": False}
        gudid = {**BASE_GUDID, "singleUse": False}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["singleUse"]["status"] == "match"

    def test_mismatch(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": False}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["singleUse"]["status"] == "mismatch"

    def test_gudid_string_true_normalizes(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": "true"}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["singleUse"]["status"] == "match"

    def test_harvested_null_skips(self):
        harvested = {**BASE_HARVESTED, "singleUse": None}
        gudid = {**BASE_GUDID, "singleUse": True}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["singleUse"]["status"] == "not_compared"

    def test_gudid_null_skips(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": None}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["singleUse"]["status"] == "not_compared"


class TestRx:

    def test_match_true(self):
        harvested = {**BASE_HARVESTED, "rx": True}
        gudid = {**BASE_GUDID, "rx": True}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["rx"]["status"] == "match"

    def test_match_false(self):
        harvested = {**BASE_HARVESTED, "rx": False}
        gudid = {**BASE_GUDID, "rx": False}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["rx"]["status"] == "match"

    def test_mismatch(self):
        harvested = {**BASE_HARVESTED, "rx": True}
        gudid = {**BASE_GUDID, "rx": False}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["rx"]["status"] == "mismatch"

    def test_gudid_string_false_normalizes(self):
        harvested = {**BASE_HARVESTED, "rx": False}
        gudid = {**BASE_GUDID, "rx": "false"}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["rx"]["status"] == "match"

    def test_both_null_yields_both_null(self):
        harvested = {**BASE_HARVESTED, "rx": None}
        gudid = {**BASE_GUDID, "rx": None}
        per_field, _ = compare_records(harvested, gudid)
        assert per_field["rx"]["status"] == "both_null"


def test_both_null_brand_name_yields_both_null_status():
    per_field, _ = compare_records(
        {"brandName": None, "versionModelNumber": "X"},
        {"brandName": None, "versionModelNumber": "X"},
    )
    assert per_field["brandName"]["status"] == "both_null"


def test_both_empty_string_company_yields_both_null():
    per_field, _ = compare_records(
        {"companyName": "", "versionModelNumber": "X"},
        {"companyName": "", "versionModelNumber": "X"},
    )
    assert per_field["companyName"]["status"] == "both_null"


def test_both_null_excluded_from_denominator():
    per_field, summary = compare_records(
        {"brandName": None, "versionModelNumber": "X"},
        {"brandName": None, "versionModelNumber": "X"},
    )
    # versionModelNumber matches (counts), brandName both-null (excluded)
    assert summary["unweighted_denominator"] == 1


def test_both_null_device_description_yields_both_null_status():
    per_field, _ = compare_records(
        {"versionModelNumber": "X"},
        {"versionModelNumber": "X"},
    )
    assert per_field["deviceDescription"]["status"] == "both_null"


def test_both_null_mri_safety_status():
    per_field, _ = compare_records(
        {"MRISafetyStatus": None, "versionModelNumber": "X"},
        {"MRISafetyStatus": None, "versionModelNumber": "X"},
    )
    assert per_field["MRISafetyStatus"]["status"] == "both_null"


def test_compare_records_returns_tuple_with_summary():
    harvested = {"versionModelNumber": "ABC-123", "brandName": "X"}
    gudid = {"versionModelNumber": "ABC123", "brandName": "X"}
    per_field, summary = compare_records(harvested, gudid)
    assert per_field["versionModelNumber"]["status"] == "match"
    assert per_field["brandName"]["status"] == "match"
    assert summary["unweighted_numerator"] >= 2
    assert summary["unweighted_denominator"] >= 2
    assert summary["numerator"] >= summary["unweighted_numerator"]
    assert summary["denominator"] >= summary["unweighted_denominator"]


def test_medtronic_vs_covidien_scores_as_corporate_alias():
    per_field, _ = compare_records(
        {"companyName": "Medtronic Inc.", "versionModelNumber": "X"},
        {"companyName": "Covidien LP",    "versionModelNumber": "X"},
    )
    assert per_field["companyName"]["status"] == "corporate_alias"
    assert per_field["companyName"]["alias_group"] == "Medtronic"


def test_alias_match_counts_toward_numerator():
    per_field, summary = compare_records(
        {"companyName": "Medtronic Inc.", "versionModelNumber": "X"},
        {"companyName": "Covidien LP",    "versionModelNumber": "X"},
    )
    assert summary["unweighted_numerator"] == 2
    assert summary["unweighted_denominator"] == 2


def test_cross_family_mismatch_not_alias():
    per_field, _ = compare_records(
        {"companyName": "Medtronic", "versionModelNumber": "X"},
        {"companyName": "Stryker",   "versionModelNumber": "X"},
    )
    assert per_field["companyName"]["status"] == "mismatch"


def test_exact_company_match_does_not_set_alias_group():
    per_field, _ = compare_records(
        {"companyName": "Medtronic", "versionModelNumber": "X"},
        {"companyName": "Medtronic", "versionModelNumber": "X"},
    )
    assert per_field["companyName"]["status"] == "match"
    assert "alias_group" not in per_field["companyName"]
