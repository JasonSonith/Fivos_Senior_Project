from normalizers.model_numbers import clean_model_number


class TestModelNumberCleaning:
    def test_model_prefix(self):
        assert clean_model_number("Model: CS-2000X") == "CS-2000X"

    def test_ref_prefix(self):
        assert clean_model_number("REF 12345-AB") == "12345-AB"

    def test_catalog_number(self):
        assert clean_model_number("Cat. No. 9876") == "9876"

    def test_sku_prefix(self):
        assert clean_model_number("SKU: WX-100") == "WX-100"

    def test_part_number(self):
        assert clean_model_number("Part Number 555-A") == "555-A"

    def test_uppercase(self):
        assert clean_model_number("abc-123x") == "ABC-123X"

    def test_whitespace_collapse(self):
        assert clean_model_number("  CS   2000  X  ") == "CS 2000 X"

    def test_no_prefix(self):
        assert clean_model_number("ZWP-100") == "ZWP-100"

    def test_empty(self):
        assert clean_model_number("") is None
        assert clean_model_number(None) is None

    def test_prefix_only(self):
        assert clean_model_number("Model:") is None
