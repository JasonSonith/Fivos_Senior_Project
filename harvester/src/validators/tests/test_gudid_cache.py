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
