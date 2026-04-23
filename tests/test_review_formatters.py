from app.services.review_formatters import format_code_list, format_device_sizes


class TestFormatDeviceSizes:
    def test_none_returns_na(self):
        assert format_device_sizes(None) == "N/A"

    def test_empty_list_returns_na(self):
        assert format_device_sizes([]) == "N/A"

    def test_non_list_returns_na(self):
        assert format_device_sizes("not a list") == "N/A"
        assert format_device_sizes({"sizeType": "Diameter"}) == "N/A"

    def test_happy_path_millimeter(self):
        sizes = [
            {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "25.0"}, "sizeText": None},
            {"sizeType": "Length", "size": {"unit": "Millimeter", "value": "1200"}, "sizeText": None},
            {"sizeType": "Lumen/Inner Diameter", "size": {"unit": "Millimeter", "value": "7"}, "sizeText": None},
        ]
        assert format_device_sizes(sizes) == (
            "Diameter: 25 mm\n"
            "Length: 1200 mm\n"
            "Lumen/Inner Diameter: 7 mm"
        )

    def test_centimeter_passthrough_uses_short_unit(self):
        # Source unit respected as-is; no cm->mm conversion here.
        sizes = [{"sizeType": "Diameter", "size": {"unit": "Centimeter", "value": "25"}, "sizeText": None}]
        assert format_device_sizes(sizes) == "Diameter: 25 cm"

    def test_inch_shortened(self):
        sizes = [{"sizeType": "Length", "size": {"unit": "Inch", "value": "4"}, "sizeText": None}]
        assert format_device_sizes(sizes) == "Length: 4 in"

    def test_size_text_fallback_when_size_null(self):
        sizes = [{"sizeType": "Length", "size": None, "sizeText": "1-5 cm"}]
        assert format_device_sizes(sizes) == "Length: 1-5 cm"

    def test_size_text_fallback_when_size_empty_value(self):
        sizes = [{"sizeType": "Width", "size": {"unit": "Millimeter", "value": ""}, "sizeText": "varies"}]
        assert format_device_sizes(sizes) == "Width: varies"

    def test_malformed_entry_skipped(self):
        sizes = [
            {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "10"}, "sizeText": None},
            {"not_a_size_entry": True},
            {"sizeType": None, "size": {"unit": "Millimeter", "value": "99"}},
            "garbage",
            {"sizeType": "Length", "size": {"unit": "Millimeter", "value": "50"}, "sizeText": None},
        ]
        assert format_device_sizes(sizes) == "Diameter: 10 mm\nLength: 50 mm"

    def test_all_entries_malformed_returns_na(self):
        sizes = [{"sizeType": "Diameter", "size": None, "sizeText": None}]
        assert format_device_sizes(sizes) == "N/A"

    def test_float_value_trimmed(self):
        sizes = [{"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "25.50"}, "sizeText": None}]
        assert format_device_sizes(sizes) == "Diameter: 25.5 mm"

    def test_unknown_unit_kept_as_is(self):
        sizes = [{"sizeType": "Custom", "size": {"unit": "Parsec", "value": "1"}, "sizeText": None}]
        assert format_device_sizes(sizes) == "Custom: 1 Parsec"


class TestFormatCodeList:
    def test_none_returns_na(self):
        assert format_code_list(None) == "N/A"

    def test_empty_list_returns_na(self):
        assert format_code_list([]) == "N/A"

    def test_non_list_returns_na(self):
        assert format_code_list("NIP,PFV") == "N/A"

    def test_happy_path(self):
        assert format_code_list(["NIP", "PFV"]) == "NIP, PFV"

    def test_single_code(self):
        assert format_code_list(["K123456"]) == "K123456"

    def test_drops_none_and_empty_entries(self):
        assert format_code_list(["NIP", None, "", "PFV"]) == "NIP, PFV"

    def test_all_empty_returns_na(self):
        assert format_code_list([None, ""]) == "N/A"

    def test_strips_whitespace(self):
        assert format_code_list(["  NIP ", "PFV"]) == "NIP, PFV"
