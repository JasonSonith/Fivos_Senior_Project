"""Disk-backed cache for fetch_gudid_record results.

Key:   sha1(catalog_number | version_model_number)
Value: (di, record_dict_or_sentinel) tuple
TTL:   24 hours (NLM's caching recommendation ceiling)
"""
import hashlib
import logging
from pathlib import Path

from diskcache import Cache

logger = logging.getLogger(__name__)

_CACHE_ROOT = Path(__file__).resolve().parents[3] / ".cache" / "gudid"
_TTL_SECONDS = 24 * 60 * 60
_NOT_FOUND = "__GUDID_NOT_FOUND__"

_cache: Cache | None = None
_enabled: bool = True


def _get_cache() -> Cache:
    global _cache
    if _cache is None:
        _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        _cache = Cache(str(_CACHE_ROOT))
    return _cache


def set_enabled(flag: bool) -> None:
    global _enabled
    _enabled = flag
    logger.info("GUDID disk cache %s", "enabled" if flag else "disabled (--no-cache)")


def _key(catalog_number, version_model_number) -> str:
    raw = f"{catalog_number or ''}|{version_model_number or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def get(catalog_number, version_model_number):
    """Return (di, record) tuple on hit, or None on miss.

    A cached negative lookup returns (di_or_None, None).
    """
    if not _enabled:
        return None
    hit = _get_cache().get(_key(catalog_number, version_model_number))
    if hit is None:
        return None
    di, record = hit
    if record == _NOT_FOUND:
        return (di, None)
    return (di, record)


def set(catalog_number, version_model_number, di, record) -> None:
    if not _enabled:
        return
    value = (di, record if record is not None else _NOT_FOUND)
    _get_cache().set(
        _key(catalog_number, version_model_number),
        value,
        expire=_TTL_SECONDS,
    )
