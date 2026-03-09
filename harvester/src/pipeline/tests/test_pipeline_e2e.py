from pathlib import Path

from bs4 import BeautifulSoup

from pipeline.extractor import extract_fields
from pipeline.parser import parse_html
from security.sanitizer import sanitize_html
from normalizers.model_numbers import clean_model_number
from normalizers.text import normalize_text
from validators.record_validator import validate_record
from pipeline.tests.fixtures.mock_adapters import MEDTRONIC_INPACT_ADAPTER

FIXTURE = Path(__file__).parent / "fixtures" / "medtronic_sample.html"


class TestMedtronicInpactPipeline:
    def setup_method(self):
        self.raw_html = FIXTURE.read_text(encoding="utf-8")

    def test_sanitize_removes_scripts(self):
        result = sanitize_html(self.raw_html)
        assert "<script>" not in result

    def test_parse_returns_soup(self):
        sanitized = sanitize_html(self.raw_html)
        soup = parse_html(sanitized)
        assert soup is not None
        assert isinstance(soup, BeautifulSoup)

    def test_extract_device_name(self):
        sanitized = sanitize_html(self.raw_html)
        soup = parse_html(sanitized)
        fields = extract_fields(soup, MEDTRONIC_INPACT_ADAPTER, "html")
        assert fields.get("device_name") is not None
        assert "IN.PACT" in fields["device_name"]

    def test_extract_model_number(self):
        sanitized = sanitize_html(self.raw_html)
        soup = parse_html(sanitized)
        fields = extract_fields(soup, MEDTRONIC_INPACT_ADAPTER, "html")
        assert fields.get("model_number") is not None
        assert len(fields["model_number"]) > 0

    def test_normalize_device_name(self):
        sanitized = sanitize_html(self.raw_html)
        soup = parse_html(sanitized)
        fields = extract_fields(soup, MEDTRONIC_INPACT_ADAPTER, "html")
        normalized = normalize_text(fields["device_name"])
        assert "IN.PACT" in normalized
        assert "\u00ad" not in normalized  # no soft hyphens

    def test_normalize_model_number(self):
        sanitized = sanitize_html(self.raw_html)
        soup = parse_html(sanitized)
        fields = extract_fields(soup, MEDTRONIC_INPACT_ADAPTER, "html")
        cleaned = clean_model_number(fields["model_number"])
        assert cleaned is not None
        assert cleaned == cleaned.upper()

    def test_validate_record_passes_with_required_fields(self):
        sanitized = sanitize_html(self.raw_html)
        soup = parse_html(sanitized)
        fields = extract_fields(soup, MEDTRONIC_INPACT_ADAPTER, "html")
        record = {
            "device_name": normalize_text(fields["device_name"]),
            "manufacturer": "Medtronic",
            "model_number": clean_model_number(fields["model_number"]),
            "source_url": "https://www.medtronic.com/en-us/products/product.IPU04004013P.html",
        }
        is_valid, issues = validate_record(record)
        assert is_valid, f"Record invalid: {issues}"

    def test_full_pipeline_result_dict(self):
        """Full pipeline from raw HTML to validated record dict."""
        sanitized = sanitize_html(self.raw_html)
        soup = parse_html(sanitized)
        fields = extract_fields(soup, MEDTRONIC_INPACT_ADAPTER, "html")
        record = {
            "device_name": normalize_text(fields.get("device_name", "")),
            "manufacturer": "Medtronic",
            "model_number": clean_model_number(fields.get("model_number", "")),
            "source_url": "https://www.medtronic.com/en-us/products/",
        }
        is_valid, issues = validate_record(record)
        assert record["device_name"]
        assert record["model_number"]
        assert is_valid
