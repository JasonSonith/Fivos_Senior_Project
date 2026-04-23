import pytest

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


def test_deviceDescription_sku_label_skip_status():
    per_field, _ = compare_records(
        {"deviceDescription": "A peripheral stent for treating arterial disease.",
         "versionModelNumber": "PXB35"},
        {"deviceDescription": "PXB35 STENT",
         "versionModelNumber": "PXB35"},
    )
    assert per_field["deviceDescription"]["status"] == "sku_label_skip"
    assert per_field["deviceDescription"]["similarity"] is None


def test_deviceDescription_prose_both_sides_scores_match():
    per_field, _ = compare_records(
        {"deviceDescription": "A peripheral stent for arterial disease treatment.",
         "versionModelNumber": "X"},
        {"deviceDescription": "Peripheral vascular stent for treating arterial disease.",
         "versionModelNumber": "X"},
    )
    assert per_field["deviceDescription"]["status"] == "match"
    assert per_field["deviceDescription"]["similarity"] > 0


def test_norm_brand_strips_descriptive_suffix():
    per_field, _ = compare_records(
        {"brandName": "Zilver PTX drug-eluting stent", "versionModelNumber": "X"},
        {"brandName": "Zilver PTX",                    "versionModelNumber": "X"},
    )
    assert per_field["brandName"]["status"] == "match"


class TestCanonicalizeSizeEntry:
    def test_millimeter_passes_through(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "3.5"}, "sizeText": None}
        assert _canonicalize_size_entry(entry) == {
            "sizeType": "Diameter", "value": 3.5, "canonical_unit": "mm"
        }

    def test_inch_converts_to_mm(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Length", "size": {"unit": "Inch", "value": "1"}, "sizeText": None}
        result = _canonicalize_size_entry(entry)
        assert result["canonical_unit"] == "mm"
        assert result["value"] == 25.4

    def test_french_converts_to_mm(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "size": {"unit": "French", "value": "6"}, "sizeText": None}
        result = _canonicalize_size_entry(entry)
        assert result["canonical_unit"] == "mm"
        assert result["value"] == pytest.approx(2.0, abs=1e-3)

    def test_centimeter_converts_to_mm(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Length", "size": {"unit": "Centimeter", "value": "3"}, "sizeText": None}
        result = _canonicalize_size_entry(entry)
        assert result["canonical_unit"] == "mm"
        assert result["value"] == 30.0

    def test_gram_passes_through(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Weight", "size": {"unit": "Gram", "value": "5"}, "sizeText": None}
        result = _canonicalize_size_entry(entry)
        assert result["canonical_unit"] == "g"
        assert result["value"] == 5.0

    def test_sizeText_only_returns_none(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "size": None, "sizeText": "N/A"}
        assert _canonicalize_size_entry(entry) is None

    def test_missing_size_returns_none(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "sizeText": None}
        assert _canonicalize_size_entry(entry) is None

    def test_unknown_unit_returns_none(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "size": {"unit": "SomeMadeUpUnit", "value": "1"}, "sizeText": None}
        assert _canonicalize_size_entry(entry) is None

    def test_non_numeric_value_returns_none(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "abc"}, "sizeText": None}
        assert _canonicalize_size_entry(entry) is None


class TestCompareDeviceSizes:

    def _mm(self, t, v):
        return {"sizeType": t, "size": {"unit": "Millimeter", "value": str(v)}, "sizeText": None}

    def test_both_null(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes(None, None)
        assert result["status"] == "both_null"
        assert result["per_type"] == []

    def test_harvested_null(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes(None, [self._mm("Diameter", 3.5)])
        assert result["status"] == "not_compared"

    def test_harvested_empty_list(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes([], [self._mm("Diameter", 3.5)])
        assert result["status"] == "not_compared"

    def test_gudid_null_harvested_has(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes([self._mm("Diameter", 3.5)], None)
        assert result["status"] == "mismatch"

    def test_exact_match(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5)],
            [self._mm("Diameter", 3.5)],
        )
        assert result["status"] == "match"
        assert len(result["per_type"]) == 1
        assert result["per_type"][0]["sizeType"] == "Diameter"
        assert result["per_type"][0]["status"] == "match"

    def test_within_tolerance(self):
        from validators.comparison_validator import _compare_device_sizes
        # 3.5 vs 3.52 → diff 0.02, tolerance 0.05 → match
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5)],
            [self._mm("Diameter", 3.52)],
        )
        assert result["status"] == "match"

    def test_outside_tolerance(self):
        from validators.comparison_validator import _compare_device_sizes
        # 3.5 vs 3.6 → diff 0.1, tolerance 0.05 → mismatch
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5)],
            [self._mm("Diameter", 3.6)],
        )
        assert result["status"] == "mismatch"
        assert result["per_type"][0]["status"] == "mismatch"

    def test_unit_conversion_match(self):
        from validators.comparison_validator import _compare_device_sizes
        # Harvester has 30 Millimeter; GUDID has 3 Centimeter
        gudid_cm = {"sizeType": "Length", "size": {"unit": "Centimeter", "value": "3"}, "sizeText": None}
        result = _compare_device_sizes(
            [self._mm("Length", 30)],
            [gudid_cm],
        )
        assert result["status"] == "match"

    def test_french_unit_match(self):
        from validators.comparison_validator import _compare_device_sizes
        # Harvester has 2 Millimeter (after normalize_measurement on "6 Fr");
        # GUDID has 6 French → also 2 mm canonical
        gudid_fr = {"sizeType": "Diameter", "size": {"unit": "French", "value": "6"}, "sizeText": None}
        result = _compare_device_sizes(
            [self._mm("Diameter", 2.0)],
            [gudid_fr],
        )
        assert result["status"] == "match"

    def test_harvester_subset_of_gudid(self):
        from validators.comparison_validator import _compare_device_sizes
        # Harvester: only Diameter. GUDID: Diameter, Length, Weight. All match.
        gudid = [
            self._mm("Diameter", 3.5),
            self._mm("Length", 20),
            {"sizeType": "Weight", "size": {"unit": "Gram", "value": "5"}, "sizeText": None},
        ]
        result = _compare_device_sizes([self._mm("Diameter", 3.5)], gudid)
        assert result["status"] == "match"
        assert len(result["per_type"]) == 1

    def test_harvester_has_extra_type(self):
        from validators.comparison_validator import _compare_device_sizes
        # Harvester: Diameter + Length. GUDID: only Diameter. Length is harvester-only.
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5), self._mm("Length", 20)],
            [self._mm("Diameter", 3.5)],
        )
        assert result["status"] == "mismatch"
        # Length should appear in per_type as mismatch
        length_entry = next(p for p in result["per_type"] if p["sizeType"] == "Length")
        assert length_entry["status"] == "mismatch"

    def test_one_type_mismatches(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5), self._mm("Length", 20)],
            [self._mm("Diameter", 3.5), self._mm("Length", 18)],
        )
        assert result["status"] == "mismatch"
        per_type_by_name = {p["sizeType"]: p["status"] for p in result["per_type"]}
        assert per_type_by_name["Diameter"] == "match"
        assert per_type_by_name["Length"] == "mismatch"

    def test_sizeText_only_harvested_skipped(self):
        from validators.comparison_validator import _compare_device_sizes
        h = [
            self._mm("Diameter", 3.5),
            {"sizeType": "Length", "size": None, "sizeText": "Variable"},
        ]
        g = [self._mm("Diameter", 3.5)]
        result = _compare_device_sizes(h, g)
        assert result["status"] == "match"
        assert len(result["per_type"]) == 1
        assert result["per_type"][0]["sizeType"] == "Diameter"

    def test_sizeText_only_gudid_not_compared(self):
        from validators.comparison_validator import _compare_device_sizes
        h = [self._mm("Diameter", 3.5)]
        g = [{"sizeType": "Diameter", "size": None, "sizeText": "Variable"}]
        result = _compare_device_sizes(h, g)
        # No comparable entries → not_compared
        assert result["status"] == "not_compared"
        assert result["per_type"][0]["status"] == "not_compared"

    def test_unknown_gudid_unit_not_compared(self):
        from validators.comparison_validator import _compare_device_sizes
        h = [self._mm("Diameter", 3.5)]
        g = [{"sizeType": "Diameter", "size": {"unit": "NotAUnit", "value": "3.5"}, "sizeText": None}]
        result = _compare_device_sizes(h, g)
        assert result["status"] == "not_compared"

    def test_per_type_formatted_strings(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5)],
            [self._mm("Diameter", 3.5)],
        )
        pt = result["per_type"][0]
        assert pt["harvested"] == "3.5 mm"
        assert pt["gudid"] == "3.5 mm"


class TestDeviceSizesIntegration:
    def _mm(self, t, v):
        return {"sizeType": t, "size": {"unit": "Millimeter", "value": str(v)}, "sizeText": None}

    def test_deviceSizes_appears_in_per_field_on_match(self):
        h = {**BASE_HARVESTED, "deviceSizes": [self._mm("Diameter", 3.5)]}
        g = {**BASE_GUDID, "deviceSizes": [self._mm("Diameter", 3.5)]}
        per_field, _ = compare_records(h, g)
        assert "deviceSizes" in per_field
        assert per_field["deviceSizes"]["status"] == "match"
        assert per_field["deviceSizes"]["per_type"][0]["sizeType"] == "Diameter"

    def test_deviceSizes_mismatch_contributes_weight_2(self):
        from validators.comparison_validator import FIELD_WEIGHTS
        assert FIELD_WEIGHTS["deviceSizes"] == 2

        h = {**BASE_HARVESTED, "deviceSizes": [self._mm("Diameter", 3.5)]}
        g = {**BASE_GUDID, "deviceSizes": [self._mm("Diameter", 3.6)]}
        _, summary = compare_records(h, g)
        h_no_sizes = {**BASE_HARVESTED}
        g_no_sizes = {**BASE_GUDID}
        _, summary_baseline = compare_records(h_no_sizes, g_no_sizes)
        assert summary["denominator"] == summary_baseline["denominator"] + 2
        assert summary["numerator"] == summary_baseline["numerator"]

    def test_deviceSizes_match_contributes_to_numerator(self):
        h = {**BASE_HARVESTED, "deviceSizes": [self._mm("Diameter", 3.5)]}
        g = {**BASE_GUDID, "deviceSizes": [self._mm("Diameter", 3.5)]}
        _, summary = compare_records(h, g)

        h_no = {**BASE_HARVESTED}
        g_no = {**BASE_GUDID}
        _, summary_baseline = compare_records(h_no, g_no)
        assert summary["numerator"] == summary_baseline["numerator"] + 2
        assert summary["denominator"] == summary_baseline["denominator"] + 2

    def test_deviceSizes_not_compared_when_harvested_null(self):
        h = {**BASE_HARVESTED}  # no deviceSizes key
        g = {**BASE_GUDID, "deviceSizes": [self._mm("Diameter", 3.5)]}
        per_field, summary = compare_records(h, g)
        assert per_field["deviceSizes"]["status"] == "not_compared"
        h_no = {**BASE_HARVESTED}
        g_no = {**BASE_GUDID}
        _, summary_baseline = compare_records(h_no, g_no)
        assert summary["denominator"] == summary_baseline["denominator"]
