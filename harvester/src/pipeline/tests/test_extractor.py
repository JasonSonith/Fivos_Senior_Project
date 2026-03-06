import xml.etree.ElementTree as ElementTree

from bs4 import BeautifulSoup

from pipeline.extractor import extract_fields


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _xml(raw: str) -> ElementTree.Element:
    return ElementTree.fromstring(raw)


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------

class TestExtractFieldsHtml:
    def test_field_found(self):
        soup = _soup('<html><body><h1 class="product-title">Stent X</h1></body></html>')
        adapter = {"extraction": {"device_name": "h1.product-title"}}
        result = extract_fields(soup, adapter, "html")
        assert result["device_name"] == "Stent X"

    def test_field_missing_returns_none(self):
        soup = _soup('<html><body><p>No title here</p></body></html>')
        adapter = {"extraction": {"device_name": "h1.product-title"}}
        result = extract_fields(soup, adapter, "html")
        assert result["device_name"] is None

    def test_multiple_fields(self):
        soup = _soup(
            '<html><body>'
            '<h1 class="product-title">Stent X</h1>'
            '<span class="manufacturer">Acme Corp</span>'
            '</body></html>'
        )
        adapter = {
            "extraction": {
                "device_name": "h1.product-title",
                "manufacturer": "span.manufacturer",
            }
        }
        result = extract_fields(soup, adapter, "html")
        assert result["device_name"] == "Stent X"
        assert result["manufacturer"] == "Acme Corp"

    def test_empty_adapter_returns_empty_dict(self):
        soup = _soup("<html><body><h1>Test</h1></body></html>")
        result = extract_fields(soup, {}, "html")
        assert result == {}


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

class TestExtractFieldsJson:
    def test_top_level_key(self):
        data = {"device_name": "Stent X", "length_mm": 40}
        adapter = {"extraction": {"device_name": "device_name"}}
        result = extract_fields(data, adapter, "json")
        assert result["device_name"] == "Stent X"

    def test_nested_dot_path(self):
        data = {"product": {"specs": {"length_mm": 40}}}
        adapter = {"extraction": {"length": "product.specs.length_mm"}}
        result = extract_fields(data, adapter, "json")
        assert result["length"] == "40"

    def test_missing_key_returns_none(self):
        data = {"product": {"name": "Stent X"}}
        adapter = {"extraction": {"length": "product.specs.length_mm"}}
        result = extract_fields(data, adapter, "json")
        assert result["length"] is None

    def test_shallow_missing_key_returns_none(self):
        data = {"device_name": "Stent X"}
        adapter = {"extraction": {"model_number": "model_number"}}
        result = extract_fields(data, adapter, "json")
        assert result["model_number"] is None


# ---------------------------------------------------------------------------
# XML extraction
# ---------------------------------------------------------------------------

class TestExtractFieldsXml:
    def test_xpath_hit(self):
        root = _xml("<device><name>Stent X</name><length>40</length></device>")
        adapter = {"extraction": {"device_name": "./name"}}
        result = extract_fields(root, adapter, "xml")
        assert result["device_name"] == "Stent X"

    def test_xpath_miss_returns_none(self):
        root = _xml("<device><name>Stent X</name></device>")
        adapter = {"extraction": {"length": "./length"}}
        result = extract_fields(root, adapter, "xml")
        assert result["length"] is None

    def test_nested_xpath(self):
        root = _xml(
            "<device>"
            "  <specs><length>40</length><width>5</width></specs>"
            "</device>"
        )
        adapter = {
            "extraction": {
                "length": "./specs/length",
                "width": "./specs/width",
            }
        }
        result = extract_fields(root, adapter, "xml")
        assert result["length"] == "40"
        assert result["width"] == "5"
