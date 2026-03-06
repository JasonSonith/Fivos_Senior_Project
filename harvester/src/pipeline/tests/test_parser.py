import xml.etree.ElementTree as ElementTree

import pytest
from bs4 import BeautifulSoup

from pipeline.parser import parse_document, parse_html, parse_json, parse_xml


class TestParseHtml:
    def test_valid_html(self):
        soup = parse_html("<html><body><h1>Test</h1></body></html>")
        assert isinstance(soup, BeautifulSoup)
        assert soup.find("h1").get_text() == "Test"

    def test_empty_string(self):
        soup = parse_html("")
        assert isinstance(soup, BeautifulSoup)

    def test_malformed_html_does_not_crash(self):
        soup = parse_html("<html><body><h1>Unclosed")
        assert isinstance(soup, BeautifulSoup)
        # BeautifulSoup repairs malformed HTML; h1 should still be findable
        assert soup.find("h1") is not None

    def test_returns_beautifulsoup_type(self):
        result = parse_html("<p>hello</p>")
        assert isinstance(result, BeautifulSoup)


class TestParseJson:
    def test_valid_json_dict(self):
        result = parse_json('{"device_name": "Stent X", "length_mm": 40}')
        assert result == {"device_name": "Stent X", "length_mm": 40}

    def test_valid_json_list_returns_empty(self):
        result = parse_json('[1, 2, 3]')
        assert result == {}

    def test_invalid_json_returns_empty(self):
        result = parse_json("not json at all {{{")
        assert result == {}

    def test_empty_string_returns_empty(self):
        result = parse_json("")
        assert result == {}

    def test_nested_dict(self):
        result = parse_json('{"product": {"name": "Stent", "dims": {"length": 40}}}')
        assert result["product"]["dims"]["length"] == 40


class TestParseXml:
    def test_valid_xml(self):
        root = parse_xml("<device><name>Stent X</name></device>")
        assert isinstance(root, ElementTree.Element)
        assert root.tag == "device"
        assert root.find("name").text == "Stent X"

    def test_malformed_xml_returns_none(self):
        result = parse_xml("<device><unclosed>")
        assert result is None

    def test_empty_string_returns_none(self):
        result = parse_xml("")
        assert result is None


class TestParseDocument:
    def test_routes_html(self):
        result = parse_document("<h1>Hello</h1>", "html")
        assert isinstance(result, BeautifulSoup)

    def test_routes_json(self):
        result = parse_document('{"key": "val"}', "json")
        assert isinstance(result, dict)
        assert result["key"] == "val"

    def test_routes_xml(self):
        result = parse_document("<root><item>x</item></root>", "xml")
        assert isinstance(result, ElementTree.Element)

    def test_unknown_format_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown format"):
            parse_document("<data/>", "csv")
