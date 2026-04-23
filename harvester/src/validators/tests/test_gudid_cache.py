"""Unit tests for gudid_cache module."""
import os
import sys

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    """Point gudid_cache at a temp directory and reset enabled state per test."""
    from validators import gudid_cache
    monkeypatch.setattr(gudid_cache, "_CACHE_ROOT", tmp_path / "gudid")
    monkeypatch.setattr(gudid_cache, "_cache", None)
    gudid_cache.set_enabled(True)
    yield gudid_cache
    if gudid_cache._cache is not None:
        gudid_cache._cache.close()
        monkeypatch.setattr(gudid_cache, "_cache", None)


class TestGudidCache:

    def test_miss_returns_none(self, tmp_cache):
        assert tmp_cache.get("CAT-X", "MOD-X") is None

    def test_roundtrip_positive(self, tmp_cache):
        tmp_cache.set("CAT-X", "MOD-X", "DI-123", {"brandName": "X"})
        result = tmp_cache.get("CAT-X", "MOD-X")
        assert result == ("DI-123", {"brandName": "X"})

    def test_roundtrip_negative(self, tmp_cache):
        tmp_cache.set("CAT-X", "MOD-X", None, None)
        assert tmp_cache.get("CAT-X", "MOD-X") == (None, None)

    def test_set_enabled_false_bypasses(self, tmp_cache):
        tmp_cache.set("CAT-X", "MOD-X", "DI-123", {"brandName": "X"})
        tmp_cache.set_enabled(False)
        assert tmp_cache.get("CAT-X", "MOD-X") is None
        tmp_cache.set("CAT-Y", "MOD-Y", "DI-Y", {"brandName": "Y"})
        tmp_cache.set_enabled(True)
        assert tmp_cache.get("CAT-Y", "MOD-Y") is None

    def test_cache_directory_created_on_first_use(self, tmp_cache, tmp_path):
        assert not (tmp_path / "gudid").exists()
        tmp_cache.set("CAT-X", "MOD-X", "DI-123", {"brandName": "X"})
        assert (tmp_path / "gudid").exists()

    def test_keys_differ_by_inputs(self, tmp_cache):
        tmp_cache.set("CAT-A", "MOD-X", "DI-A", {"brandName": "A"})
        tmp_cache.set("CAT-B", "MOD-X", "DI-B", {"brandName": "B"})
        assert tmp_cache.get("CAT-A", "MOD-X") == ("DI-A", {"brandName": "A"})
        assert tmp_cache.get("CAT-B", "MOD-X") == ("DI-B", {"brandName": "B"})


class TestFetchGudidRecordShortCircuitsHttp:
    """End-to-end: second fetch_gudid_record call with same inputs does no HTTP."""

    def test_second_call_does_zero_http(self, tmp_cache, monkeypatch):
        from unittest.mock import MagicMock, patch
        from validators import gudid_client
        import requests

        monkeypatch.setattr("time.sleep", lambda *a, **kw: None)

        # Return a stable DI from search, and a stable record from the JSON GET.
        monkeypatch.setattr(gudid_client, "search_gudid_di", MagicMock(return_value="DI-123"))

        lookup_resp = MagicMock(spec=requests.Response)
        lookup_resp.status_code = 200
        lookup_resp.json.return_value = {"gudid": {"device": {"brandName": "X"}}}
        lookup_resp.raise_for_status.return_value = None

        with patch.object(gudid_client.requests, "get", return_value=lookup_resp) as mock_get:
            di1, rec1 = gudid_client.fetch_gudid_record(catalog_number="CAT", version_model_number="MOD")
            first_pass_calls = mock_get.call_count
            assert first_pass_calls > 0

            # Second call with same inputs — should short-circuit via cache.
            di2, rec2 = gudid_client.fetch_gudid_record(catalog_number="CAT", version_model_number="MOD")
            assert mock_get.call_count == first_pass_calls, (
                f"Expected 0 new HTTP calls on cached run, got "
                f"{mock_get.call_count - first_pass_calls}"
            )

        assert di1 == di2 == "DI-123"
        # fetch_gudid_record shapes the record with all MERGE_FIELDS, many of
        # which will be None since our mock only populated brandName.
        assert rec1 == rec2
        assert rec1["brandName"] == "X"

    def test_negative_result_also_cached(self, tmp_cache, monkeypatch):
        from unittest.mock import MagicMock
        from validators import gudid_client

        monkeypatch.setattr("time.sleep", lambda *a, **kw: None)

        search_mock = MagicMock(return_value=None)
        monkeypatch.setattr(gudid_client, "search_gudid_di", search_mock)

        # First call: search runs and returns None; second call should skip search.
        assert gudid_client.fetch_gudid_record(catalog_number="CAT", version_model_number="MOD") == (None, None)
        assert search_mock.call_count == 1

        assert gudid_client.fetch_gudid_record(catalog_number="CAT", version_model_number="MOD") == (None, None)
        assert search_mock.call_count == 1, "Second call should have been served from cache"
