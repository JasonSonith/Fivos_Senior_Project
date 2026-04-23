import pytest
from validators.company_aliases import canonical_company, COMPANY_ALIASES


class TestCanonicalCompany:
    def test_exact_match_returns_canonical(self):
        assert canonical_company("Medtronic") == "Medtronic"

    def test_case_insensitive(self):
        assert canonical_company("medtronic") == "Medtronic"
        assert canonical_company("MEDTRONIC") == "Medtronic"

    def test_strips_inc_suffix(self):
        assert canonical_company("Medtronic Inc.") == "Medtronic"

    def test_strips_lp_suffix(self):
        assert canonical_company("Covidien LP") == "Medtronic"

    def test_strips_llc_suffix(self):
        assert canonical_company("Bard LLC") == "BD"

    def test_strips_corporation_suffix(self):
        assert canonical_company("Stryker Corporation") == "Stryker"

    def test_strips_ltd_suffix(self):
        assert canonical_company("BTG Ltd.") == "Boston Scientific"

    def test_covidien_maps_to_medtronic(self):
        assert canonical_company("Covidien") == "Medtronic"

    def test_bard_maps_to_bd(self):
        assert canonical_company("Bard") == "BD"
        assert canonical_company("C R Bard") == "BD"

    def test_st_jude_maps_to_abbott(self):
        assert canonical_company("St Jude Medical") == "Abbott"

    def test_ethicon_maps_to_jnj(self):
        assert canonical_company("Ethicon") == "Johnson & Johnson"

    def test_wright_medical_maps_to_stryker(self):
        assert canonical_company("Wright Medical") == "Stryker"

    def test_unknown_company_returns_none(self):
        assert canonical_company("Never Heard Of This Co") is None

    def test_empty_returns_none(self):
        assert canonical_company("") is None
        assert canonical_company(None) is None

    def test_whitespace_collapsed(self):
        assert canonical_company("  Medtronic   Inc.  ") == "Medtronic"

    def test_punctuation_stripped(self):
        assert canonical_company("Johnson, & Johnson") == "Johnson & Johnson"


def test_alias_map_has_all_seed_groups():
    for parent in ("Medtronic", "Boston Scientific", "BD", "Abbott",
                   "Johnson & Johnson", "Stryker"):
        assert parent in COMPANY_ALIASES
