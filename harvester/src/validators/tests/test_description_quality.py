import pytest
from validators.comparison_validator import _gudid_description_is_sku_label


class TestSkuLabelClassifier:
    @pytest.mark.parametrize("desc", [
        "A peripheral vascular stent designed for the treatment of occluded arteries in the lower extremities.",
        "Drug-eluting coronary stent system for the treatment of patients with coronary artery disease.",
        "Self-expanding nitinol endoprosthesis intended for the treatment of peripheral arterial disease.",
    ])
    def test_prose_returns_false(self, desc):
        assert _gudid_description_is_sku_label(desc, "MODEL1", "CAT1") is False

    @pytest.mark.parametrize("desc", [
        "STENT",
        "Drug-eluting balloon",
        "Coronary stent kit",
    ])
    def test_short_returns_true(self, desc):
        assert _gudid_description_is_sku_label(desc, "MODEL1", "CAT1") is True

    def test_contains_model_number_returns_true(self):
        assert _gudid_description_is_sku_label(
            "PXB35-09-17-080 peripheral stent system for vascular treatment",
            "PXB35-09-17-080", None,
        ) is True

    def test_contains_catalog_number_returns_true(self):
        assert _gudid_description_is_sku_label(
            "Catalog ABC-123 drug-eluting stent for peripheral arteries",
            None, "ABC-123",
        ) is True

    @pytest.mark.parametrize("desc", [
        "PERIPHERAL VASCULAR STENT SYSTEM DRUG-ELUTING BALLOON EXP",
        "NITINOL ENDOPROSTHESIS CORONARY STENT BALLOON CATHETER",
        "DRUG-ELUTING STENT SYSTEM BALLOON EXPANDABLE VASCULAR",
    ])
    def test_all_caps_returns_true(self, desc):
        assert _gudid_description_is_sku_label(desc, "M", "C") is True

    def test_sku_pattern_returns_true(self):
        assert _gudid_description_is_sku_label(
            "PXB35-09-17-080 STENT NITINOL SYSTEM",
            "NONMATCHING", "OTHER",
        ) is True

    def test_none_returns_false(self):
        assert _gudid_description_is_sku_label(None, "M", "C") is False

    def test_empty_returns_false(self):
        assert _gudid_description_is_sku_label("", "M", "C") is False
