"""Retry-policy tests for gudid_client. No live network."""
import os
import sys

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest
import requests
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    """Skip tenacity's exponential backoff in tests."""
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def reset_gudid_cache(tmp_path, monkeypatch):
    """Point gudid_cache at a per-test tmp dir; reset module state."""
    from validators import gudid_cache
    monkeypatch.setattr(gudid_cache, "_CACHE_ROOT", tmp_path / "gudid")
    monkeypatch.setattr(gudid_cache, "_cache", None)
    gudid_cache.set_enabled(True)
    yield
    if gudid_cache._cache is not None:
        gudid_cache._cache.close()


def _mock_response(status_code: int, json_data: dict | None = None, text: str = ""):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


class TestRaiseForStatusWithRateLimit:

    def test_429_raises_gudid_rate_limit_error(self):
        from validators.gudid_client import (
            GudidRateLimitError,
            _raise_for_status_with_rate_limit,
        )
        resp = _mock_response(429)
        with pytest.raises(GudidRateLimitError):
            _raise_for_status_with_rate_limit(resp)

    def test_404_raises_http_error_not_rate_limit(self):
        from validators.gudid_client import (
            GudidRateLimitError,
            _raise_for_status_with_rate_limit,
        )
        resp = _mock_response(404)
        resp.raise_for_status.side_effect = requests.HTTPError("404")
        with pytest.raises(requests.HTTPError) as exc_info:
            _raise_for_status_with_rate_limit(resp)
        assert not isinstance(exc_info.value, GudidRateLimitError)

    def test_200_does_not_raise(self):
        from validators.gudid_client import _raise_for_status_with_rate_limit
        resp = _mock_response(200)
        _raise_for_status_with_rate_limit(resp)

    def test_gudid_rate_limit_error_is_http_error(self):
        from validators.gudid_client import GudidRateLimitError
        assert issubclass(GudidRateLimitError, requests.HTTPError)
        assert issubclass(GudidRateLimitError, requests.RequestException)


class TestFetchGudidRecordRetry:

    def test_timeout_then_success_succeeds_on_third_attempt(self, monkeypatch):
        from validators import gudid_client

        monkeypatch.setattr(gudid_client, "search_gudid_di", lambda **kw: "00123456789012")

        lookup_resp = _mock_response(200, json_data={"gudid": {"device": {"brandName": "X"}}})
        call_sequence = [
            requests.Timeout("t1"),
            requests.Timeout("t2"),
            lookup_resp,
        ]

        def fake_get(*args, **kwargs):
            result = call_sequence.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch("validators.gudid_client.requests.get", side_effect=fake_get) as mock_get:
            di, record = gudid_client.fetch_gudid_record(catalog_number="ABC")

        assert mock_get.call_count == 3
        assert di == "00123456789012"
        assert record["brandName"] == "X"

    def test_timeout_exhausted_reraises_original(self, monkeypatch):
        from validators import gudid_client

        monkeypatch.setattr(gudid_client, "search_gudid_di", lambda **kw: "00123456789012")

        with patch(
            "validators.gudid_client.requests.get",
            side_effect=requests.Timeout("nope"),
        ):
            with pytest.raises(requests.Timeout):
                gudid_client.fetch_gudid_record(catalog_number="ABC")

    def test_429_then_success_retries(self, monkeypatch):
        from validators import gudid_client

        monkeypatch.setattr(gudid_client, "search_gudid_di", lambda **kw: "00123456789012")

        resp_429 = _mock_response(429)
        resp_ok = _mock_response(200, json_data={"gudid": {"device": {"brandName": "X"}}})
        call_sequence = [resp_429, resp_ok]

        def fake_get(*args, **kwargs):
            return call_sequence.pop(0)

        with patch("validators.gudid_client.requests.get", side_effect=fake_get) as mock_get:
            di, record = gudid_client.fetch_gudid_record(catalog_number="ABC")

        assert mock_get.call_count == 2
        assert record["brandName"] == "X"

    def test_404_does_not_retry(self, monkeypatch):
        from validators import gudid_client

        monkeypatch.setattr(gudid_client, "search_gudid_di", lambda **kw: "00123456789012")

        resp_404 = _mock_response(404)
        resp_404.raise_for_status.side_effect = requests.HTTPError("404")

        with patch(
            "validators.gudid_client.requests.get",
            return_value=resp_404,
        ) as mock_get:
            with pytest.raises(requests.HTTPError):
                gudid_client.fetch_gudid_record(catalog_number="ABC")

        assert mock_get.call_count == 1
