from normalizers.text import normalize_text
import pytest


class TestHtmlEntityDecoding:

    def test_ampersand(self):
        assert normalize_text("Medtronic &amp; Abbott") == "Medtronic & Abbott"

    def test_trademark(self):
        # &trade; decodes to ™ (U+2122), NFKC then expands it to "TM"
        assert normalize_text("IN.PACT&trade; Admiral") == "IN.PACTTM Admiral"

    def test_less_than_greater_than(self):
        assert normalize_text("&lt;3mm&gt;") == "<3mm>"

    def test_numeric_entity_decimal(self):
        assert normalize_text("&#174;") == "®"

    def test_numeric_entity_hex(self):
        assert normalize_text("&#x00AE;") == "®"

    def test_multiple_entities(self):
        assert normalize_text("&amp;amp; &lt;test&gt;") == "&amp; <test>"

    def test_nbsp_entity_removed(self):
        # &nbsp; decodes to \u00a0 which is then stripped as invisible char
        assert normalize_text("hello&nbsp;world") == "hello world"


class TestNfkcNormalization:

    def test_fi_ligature(self):
        assert normalize_text("ﬁlter") == "filter"

    def test_fl_ligature(self):
        assert normalize_text("ﬂow") == "flow"

    def test_fancy_left_double_quote(self):
        # NFKC does not convert curly quotes to straight quotes; they pass through
        assert normalize_text("\u201cSMART\u201d") == "\u201cSMART\u201d"

    def test_fancy_single_quote(self):
        # NFKC does not convert curly apostrophe to straight; it passes through
        assert normalize_text("it\u2019s") == "it\u2019s"

    def test_fullwidth_digits(self):
        # Fullwidth digit '１' → '1'
        assert normalize_text("１２３") == "123"

    def test_superscript_two(self):
        # ² NFKC → 2
        assert normalize_text("10\u00b2") == "102"


class TestInvisibleCharRemoval:

    def test_zero_width_space(self):
        assert normalize_text("hello\u200bworld") == "helloworld"

    def test_zero_width_non_joiner(self):
        assert normalize_text("hello\u200cworld") == "helloworld"

    def test_zero_width_joiner(self):
        assert normalize_text("hello\u200dworld") == "helloworld"

    def test_soft_hyphen(self):
        assert normalize_text("medi\u00adcal") == "medical"

    def test_bom(self):
        assert normalize_text("\ufeffDevice Name") == "Device Name"

    def test_non_breaking_space_becomes_empty(self):
        # A string of only non-breaking spaces should return None
        assert normalize_text("\u00a0\u00a0\u00a0") is None

    def test_word_joiner(self):
        assert normalize_text("A\u2060B") == "AB"

    def test_multiple_invisible_chars(self):
        result = normalize_text("\u200b\ufeff\u00adtest\u200c")
        assert result == "test"


class TestWhitespaceCollapsing:

    def test_multiple_spaces(self):
        assert normalize_text("hello   world") == "hello world"

    def test_tabs(self):
        assert normalize_text("hello\t\tworld") == "hello world"

    def test_newlines(self):
        assert normalize_text("hello\nworld") == "hello world"

    def test_mixed_whitespace(self):
        assert normalize_text("  hello \t\n world  ") == "hello world"

    def test_leading_trailing_stripped(self):
        assert normalize_text("   trimmed   ") == "trimmed"

    def test_internal_newline_tab_combo(self):
        assert normalize_text("line1\n\t line2") == "line1 line2"


class TestEdgeCases:

    def test_none_returns_none(self):
        assert normalize_text(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_text("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_text("   \t\n  ") is None

    def test_non_string_int_returns_none(self):
        assert normalize_text(42) is None

    def test_non_string_list_returns_none(self):
        assert normalize_text(["text"]) is None

    def test_normal_string_unchanged(self):
        assert normalize_text("Medtronic IN.PACT Admiral") == "Medtronic IN.PACT Admiral"

    def test_already_clean(self):
        result = normalize_text("ZILVER PTX Stent")
        assert result == "ZILVER PTX Stent"

    def test_combined_html_invisible_whitespace(self):
        raw = "  &amp;\u200b\ufeff  multiple   spaces  "
        assert normalize_text(raw) == "& multiple spaces"
