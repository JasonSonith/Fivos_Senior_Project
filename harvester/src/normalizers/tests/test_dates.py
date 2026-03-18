import pytest
from normalizers.dates import normalize_date


class TestISOPassthrough:
    def test_iso(self):
        assert normalize_date("2026-03-06") == "2026-03-06"

    def test_iso_slash(self):
        assert normalize_date("2026/03/06") == "2026-03-06"

    def test_compact(self):
        assert normalize_date("20260306") == "2026-03-06"


class TestUSFormats:
    def test_us_slash(self):
        assert normalize_date("03/06/2026") == "2026-03-06"

    def test_us_dash(self):
        assert normalize_date("03-06-2026") == "2026-03-06"


class TestEuropeanFormats:
    def test_european_slash_day_over_12(self):
        assert normalize_date("31/01/2026") == "2026-01-31"

    def test_european_dash_day_over_12(self):
        assert normalize_date("31-01-2026") == "2026-01-31"

    def test_european_dot(self):
        assert normalize_date("06.03.2026") == "2026-03-06"


class TestMonthNameFormats:
    def test_long_month_us(self):
        assert normalize_date("March 6, 2026") == "2026-03-06"

    def test_long_month_european(self):
        assert normalize_date("6 March 2026") == "2026-03-06"

    def test_short_month_us(self):
        assert normalize_date("Mar 6, 2026") == "2026-03-06"

    def test_short_month_european(self):
        assert normalize_date("6 Mar 2026") == "2026-03-06"

    def test_short_month_dashed(self):
        assert normalize_date("06-Mar-2026") == "2026-03-06"


class TestEdgeCases:
    def test_whitespace_padded(self):
        assert normalize_date("  2026-03-06  ") == "2026-03-06"

    def test_unparseable(self):
        assert normalize_date("not-a-date") is None

    def test_empty_string(self):
        assert normalize_date("") is None

    def test_non_string_int(self):
        assert normalize_date(20260306) is None

    def test_non_string_none(self):
        assert normalize_date(None) is None
