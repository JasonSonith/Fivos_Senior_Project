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
        result = compare_records(BASE_HARVESTED, BASE_GUDID)
        assert result["versionModelNumber"]["match"] is True
        assert result["catalogNumber"]["match"] is True
        assert result["brandName"]["match"] is True
        assert result["companyName"]["match"] is True

    def test_model_number_mismatch(self):
        harvested = {**BASE_HARVESTED, "versionModelNumber": "XYZ"}
        result = compare_records(harvested, BASE_GUDID)
        assert result["versionModelNumber"]["match"] is False

    def test_description_similarity_present(self):
        result = compare_records(BASE_HARVESTED, BASE_GUDID)
        assert "description_similarity" in result["deviceDescription"]
        assert result["deviceDescription"]["description_similarity"] == 1.0

    def test_harvested_model_none_skips(self):
        harvested = {**BASE_HARVESTED, "versionModelNumber": None}
        result = compare_records(harvested, BASE_GUDID)
        assert result["versionModelNumber"]["match"] is None


class TestMRISafetyStatus:

    def test_match_exact(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "MR Safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Safe"}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is True

    def test_match_variant_normalization(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "mri safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Safe"}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is True

    def test_mismatch(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "MR Safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Conditional"}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is False

    def test_harvested_null_skips(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": None}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Safe"}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is None

    def test_gudid_null_skips(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "MR Safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": None}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is None

    def test_both_null_skips(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": None}
        gudid = {**BASE_GUDID, "MRISafetyStatus": None}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is None


class TestSingleUse:

    def test_match_true(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": True}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is True

    def test_match_false(self):
        harvested = {**BASE_HARVESTED, "singleUse": False}
        gudid = {**BASE_GUDID, "singleUse": False}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is True

    def test_mismatch(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": False}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is False

    def test_gudid_string_true_normalizes(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": "true"}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is True

    def test_harvested_null_skips(self):
        harvested = {**BASE_HARVESTED, "singleUse": None}
        gudid = {**BASE_GUDID, "singleUse": True}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is None

    def test_gudid_null_skips(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": None}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is None


class TestRx:

    def test_match_true(self):
        harvested = {**BASE_HARVESTED, "rx": True}
        gudid = {**BASE_GUDID, "rx": True}
        result = compare_records(harvested, gudid)
        assert result["rx"]["match"] is True

    def test_match_false(self):
        harvested = {**BASE_HARVESTED, "rx": False}
        gudid = {**BASE_GUDID, "rx": False}
        result = compare_records(harvested, gudid)
        assert result["rx"]["match"] is True

    def test_mismatch(self):
        harvested = {**BASE_HARVESTED, "rx": True}
        gudid = {**BASE_GUDID, "rx": False}
        result = compare_records(harvested, gudid)
        assert result["rx"]["match"] is False

    def test_gudid_string_false_normalizes(self):
        harvested = {**BASE_HARVESTED, "rx": False}
        gudid = {**BASE_GUDID, "rx": "false"}
        result = compare_records(harvested, gudid)
        assert result["rx"]["match"] is True

    def test_both_null_skips(self):
        harvested = {**BASE_HARVESTED, "rx": None}
        gudid = {**BASE_GUDID, "rx": None}
        result = compare_records(harvested, gudid)
        assert result["rx"]["match"] is None
