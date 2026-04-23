# GUDID Validation Resilience & Parallelization — Design

**Date:** 2026-04-23
**Owner:** Jason
**Status:** Draft (pending review)

## Problem

The GUDID validation loop in `harvester/src/orchestrator.py` has two related failure modes that just surfaced on a 551-device run:

1. **Fragility.** The `for device in devices:` loop at `orchestrator.py:373` calls `fetch_gudid_record()` with no `try/except`. `gudid_client.py` uses `timeout=15` and `raise_for_status()`, so any transient timeout or network hiccup on a single device propagates up, is caught by the outermost handler in `cli.py:288`, and kills validation for **every** device — including the ~550 that would have succeeded. The recent run failed after scraping + extracting + DB-writing all 551 records cleanly, because one FDA call timed out.

2. **Serial throughput.** Every device does 1–2 HTTP round-trips to `accessgudid.nlm.nih.gov`. At ~1.5 s median per call, 551 devices is ~15–17 minutes wall-clock. No retry on transient errors; no caching between runs. The 15 s timeout is aggressive for a government service that occasionally runs slow.

## Goal

Two stacked PRs:

- **PR #1 — Resilience.** One slow or flaky FDA call cannot kill a batch run. Every 4xx-other-than-429 is fast-failed. Every Timeout / ConnectionError / 429 is retried up to 3× with exponential backoff + jitter. Timeout bumped to 60 s.

- **PR #2 — Throughput.** 8-way `ThreadPoolExecutor` parallelizes per-device work. Local disk cache keyed on `(catalog_number, version_model_number)` with a 24 h TTL short-circuits repeat runs entirely. Target wall-clock on 551 devices: ~3 min on first run, <10 s on a fully-cached re-run.

## Non-goals

- **No `asyncio` / `aiohttp`.** Codebase is synchronous; threads are the right tool.
- **No raising `max_workers` above 8.** NLM's published ToS caps all its APIs at 20 rps/IP; 8 workers × median 1.5 s/call ≈ 5 rps steady-state, well under the ceiling. Raising the cap requires a separate spec amendment.
- **No API keys / auth changes.** The public `/api/v3/` endpoints work unauthenticated; UMLS keys are optional and out of scope.
- **No `validationResults` / `verified_devices` schema migration.** One new `status` enum value (`"fetch_error"`) and two optional top-level fields (`error_type`, `error_message`) are additive. The review dashboard reads what it already reads.
- **No refactor of `llm_extractor` concurrency.** Different subsystem, different constraints (quality-first fallback chain vs. uniform bounded pool).
- **No drive-by cleanups.** The pre-existing `result["not_found"]` counter that's declared but never incremented — left alone.
- **`result["errors"]` is a new top-level counter only; not persisted in a separate collection.** One aggregate number per run, returned to the CLI / dashboard.

## PR split

```
main
 └── Jason (current, base for both PRs)
      └── Jason-gudid-resilience     PR #1: phases 1-3  (bug fix + timeout + retry)
           └── Jason-gudid-parallel  PR #2: phases 4-5  (parallel + disk cache, stacked)
```

PR #2 is opened only after PR #1 merges into `Jason` and is rebased onto the post-merge tip. Each PR is independently reviewable and revertible.

## Architecture

Two layers of change, nested:

```
┌──────────────────────────────────────────────────────────────┐
│ orchestrator.run_validation                                  │
│                                                              │
│   for device in devices:                                     │  Phase 1
│     try: fetch → compare → result record                     │
│     except RequestException: errors += 1, write fetch_error  │
│                                                              │
│   → becomes →                                                │
│                                                              │
│   ThreadPoolExecutor(max_workers=8, prefix="gudid")          │  Phase 4
│     worker: _validate_one_device(device) → result record     │
│   main thread:                                               │
│     as_completed → aggregate counters + write DB serially    │
└───────────────────────┬──────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│ validators/gudid_client.fetch_gudid_record                   │
│                                                              │
│   cache.get(sha1(catalog|model))  → hit short-circuits       │  Phase 5
│   search_gudid_di    @retry  @timeout=60                     │  Phases 2, 3
│   GET lookup.json    @retry  @timeout=60                     │  Phases 2, 3
│   cache.set(...)                                             │  Phase 5
└───────────────────────┬──────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│ validators/gudid_cache  (new module, diskcache-backed)       │  Phase 5
│   .cache/gudid/  SQLite store, 24 h TTL                      │
└──────────────────────────────────────────────────────────────┘
```

**Worker / main-thread split.** The Phase 4 worker function does only network + CPU: `fetch_gudid_record` → `compare_records` → return a `DeviceValidationResult` dataclass. Counter aggregation and all MongoDB writes happen on the main thread from a `list[DeviceValidationResult]` populated as futures complete. Rationale:

- Counters (`result["full_matches"] += 1` etc.) are not thread-safe; lock-free aggregation in the main thread is cleaner than adding locks.
- MongoDB writes at ~10 ms each × 551 devices = ~5 s serial — negligible versus ~100 s of parallel fetch time.
- Unit-testing a pure worker with a mocked `fetch_gudid_record` is simpler than testing a worker that also writes to the DB.
- Preserves the current one-`validationResults`-doc-per-device contract — the review dashboard's per-device page cannot show a row that would silently disappear because two harvested catalog numbers happened to resolve to the same DI.

**Thread naming.** `thread_name_prefix="gudid"` → `[gudid_0]` … `[gudid_7]` in the `[%(threadName)s]` log format, mirroring the existing `[extract_0]` convention from `pipeline/parallel_batch.py`.

## Phase 1 — Per-device error isolation (PR #1)

**File:** `harvester/src/orchestrator.py`, inside `run_validation()` around line 374.

Wrap the `fetch_gudid_record(...)` call in `try/except requests.RequestException`. On exception:

```python
from datetime import datetime, timezone
import logging, requests

logger = logging.getLogger(__name__)

try:
    di, gudid_record = fetch_gudid_record(
        catalog_number=device.get("catalogNumber"),
        version_model_number=device.get("versionModelNumber"),
    )
except requests.RequestException as exc:
    logger.warning(
        "GUDID fetch failed for catalog=%s model=%s: %s: %s",
        device.get("catalogNumber"),
        device.get("versionModelNumber"),
        type(exc).__name__,
        exc,
    )
    result["errors"] += 1
    now = datetime.now(timezone.utc)
    validation_col.insert_one({
        "device_id": device.get("_id"),
        "brandName": device.get("brandName"),
        "status": "fetch_error",
        "error_type": type(exc).__name__,
        "error_message": str(exc)[:500],
        "matched_fields": None, "total_fields": None,
        "match_percent": None, "weighted_percent": None,
        "description_similarity": None,
        "comparison_result": None,
        "gudid_record": None,
        "gudid_di": None,
        "created_at": now, "updated_at": now,
    })
    continue
```

**Result dict change.** Add one new key:

```python
result = {
    "success": False,
    "total": 0,
    "full_matches": 0,
    "partial_matches": 0,
    "mismatches": 0,
    "not_found": 0,
    "gudid_deactivated": 0,
    "harvest_gap_product_codes": 0,
    "harvest_gap_premarket": 0,
    "errors": 0,                      # NEW
    "error": None,
}
```

Existing keys untouched. Downstream callers (`runner.py:689–699`, `cli.py:311–326`) read specific keys by name and do not iterate the dict, so the added key is backward-compatible.

**CLI display.** One added line in both `runner.py` and `cli.py` validation blocks: `Errors: N` (yellow when `N > 0`, plain otherwise). Printed directly after `Not found:` in the existing validation summary.

**New `validationResults` status value.** `"fetch_error"`. Joins the existing enum {`match`, `partial_match`, `mismatch`, `gudid_deactivated`}. Two additional top-level fields on these docs only: `error_type` (exception class name) and `error_message` (first 500 chars).

**Review dashboard.** `app/routes/review.py` currently renders the existing statuses. `fetch_error` records get a neutral gray "Could not verify" badge and a short explanation panel showing `error_type` / `error_message`. No side-by-side comparison table (no GUDID record to compare). Scoped to PR #1 so the dashboard never shows an unknown status.

**Test.** `harvester/src/tests/test_orchestrator.py`: mock `fetch_gudid_record` to raise `requests.Timeout` on the 2nd of 3 devices. Assert:
- `result["errors"] == 1`
- devices 1 and 3 have their normal `validationResults` docs
- device 2 has a `fetch_error` doc with non-empty `error_type`
- `result["success"] is True`
- No exception propagates out of `run_validation`

## Phase 2 — Timeout constant (PR #1)

**File:** `harvester/src/validators/gudid_client.py`

At module top:
```python
REQUEST_TIMEOUT = 60  # seconds
```

Replace `timeout=15` at lines 19, 134, and 178 (all three — `lookup_by_di` at 178 shares the same HTTP contract and should bump consistently).

No test needed; constant swap.

## Phase 3 — Retry with backoff (PR #1)

**File:** `harvester/src/validators/gudid_client.py`

**Dependency.** Add `tenacity>=8.0` to `requirements.txt`.

**Typed exception for 429.** Tenacity's retry predicate is cleanest with a dedicated exception class rather than inspecting status codes inside the predicate:

```python
class GudidRateLimitError(requests.HTTPError):
    """Raised when GUDID returns HTTP 429. Retried."""
    pass

def _raise_for_status_with_rate_limit(response: requests.Response) -> None:
    if response.status_code == 429:
        raise GudidRateLimitError(response=response)
    response.raise_for_status()
```

Replace both existing `response.raise_for_status()` calls with `_raise_for_status_with_rate_limit(response)`.

**Retry decorator.** Applied to `search_gudid_di` and `fetch_gudid_record`:

```python
from tenacity import (
    retry, stop_after_attempt, wait_exponential, wait_random,
    retry_if_exception_type, before_sleep_log,
)

_RETRY_POLICY = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4) + wait_random(0, 1),
    retry=retry_if_exception_type((
        requests.Timeout,
        requests.ConnectionError,
        GudidRateLimitError,
    )),
    before_sleep=before_sleep_log(logger, logging.INFO),
    reraise=True,
)

@retry(**_RETRY_POLICY)
def search_gudid_di(...): ...

@retry(**_RETRY_POLICY)
def fetch_gudid_record(...): ...
```

**Key points.**
- `reraise=True` so callers see the original `Timeout` / `ConnectionError` / `GudidRateLimitError`, not `tenacity.RetryError`. Phase 1's `except requests.RequestException` depends on this — `RetryError` is not a `RequestException`.
- 4xx other than 429 (e.g., 404 for a bad DI) passes through on the first attempt because those exceptions are not in the `retry_if_exception_type` tuple.
- `fetch_gudid_record` calls `search_gudid_di` internally. Retries are sequential, not nested: worst case is 3 (search attempts) + 3 (lookup attempts) = 6 HTTP calls per device. Median is 1 + 1 = 2.
- `before_sleep_log` emits structured lines like `Retrying search_gudid_di in 2.12s (attempt 2/3) after Timeout` at INFO.

**Tests.** New file `harvester/src/validators/tests/test_gudid_client_retry.py`:
1. Mock `requests.get` → `Timeout, Timeout, Response(200, json=...)`. Assert `call_count == 3`, result matches the 200 body.
2. Mock `requests.get` → `Timeout × 3`. Assert `requests.Timeout` is raised (not `RetryError`).
3. Mock `requests.get` → `Response(429), Response(200, json=...)`. Assert retry triggered, call count == 2.
4. Mock `requests.get` → `Response(404)`. Assert `requests.HTTPError` raised on first call, `call_count == 1` (no retry on real errors).

No live network in any test.

## Phase 4 — ThreadPoolExecutor parallelization (PR #2)

**File:** `harvester/src/orchestrator.py`

Extract the per-device work into a worker function returning a dataclass. Main thread drives the pool, aggregates results, writes DB serially.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class DeviceValidationResult:
    device: dict
    di: Optional[str]
    gudid_record: Optional[dict]
    outcome: Literal["matched", "partial_match", "mismatch", "not_found",
                     "gudid_deactivated", "fetch_error"]
    comparison: Optional[dict]     # compare_records() per-field output
    summary: Optional[dict]        # compare_records() scoring summary
    error_type: Optional[str]
    error_message: Optional[str]

def _validate_one_device(device: dict) -> DeviceValidationResult:
    try:
        di, gudid_record = fetch_gudid_record(
            catalog_number=device.get("catalogNumber"),
            version_model_number=device.get("versionModelNumber"),
        )
    except requests.RequestException as exc:
        logger.warning(
            "GUDID fetch failed for catalog=%s model=%s: %s: %s",
            device.get("catalogNumber"),
            device.get("versionModelNumber"),
            type(exc).__name__, exc,
        )
        return DeviceValidationResult(
            device=device, di=None, gudid_record=None,
            outcome="fetch_error", comparison=None, summary=None,
            error_type=type(exc).__name__,
            error_message=str(exc)[:500],
        )

    if not gudid_record:
        return DeviceValidationResult(
            device=device, di=di, gudid_record=None,
            outcome="not_found",
            comparison=None, summary=None,
            error_type=None, error_message=None,
        )

    if gudid_record.get("deviceRecordStatus") == "Deactivated":
        return DeviceValidationResult(
            device=device, di=di, gudid_record=gudid_record,
            outcome="gudid_deactivated",
            comparison=None, summary=None,
            error_type=None, error_message=None,
        )

    comparison, summary = compare_records(device, gudid_record)
    outcome = _derive_outcome(summary)
    return DeviceValidationResult(
        device=device, di=di, gudid_record=gudid_record,
        outcome=outcome, comparison=comparison, summary=summary,
        error_type=None, error_message=None,
    )

def _derive_outcome(summary: dict) -> str:
    mp = summary.get("match_percent", 0.0)
    if mp >= 1.0:
        return "matched"
    if mp > 0:
        return "partial_match"
    return "mismatch"
```

`_derive_outcome` is the existing matched/partial/mismatch logic hoisted from the loop into a named helper. No behavior change.

**Driver loop:**

```python
results: list[DeviceValidationResult] = []
completed = 0

with ThreadPoolExecutor(max_workers=8, thread_name_prefix="gudid") as pool:
    futures = [pool.submit(_validate_one_device, d) for d in devices]
    for fut in as_completed(futures):
        res = fut.result()       # worker's own try/except has already run; no re-raise expected
        completed += 1
        results.append(res)
        if completed % 25 == 0 or completed == len(devices):
            logger.info("[gudid] %d/%d devices validated", completed, len(devices))

# Serial DB writes + counter aggregation. One DB write per device, preserving
# the current behavior where two harvested devices resolving to the same DI
# each get their own validationResults doc under their own device_id.
for res in results:
    _persist_result(res, result, validation_col, verified_col, devices_col)
```

The user spec's "collected into a dict keyed by DI" phrasing refers to correlation (each result carries its DI for downstream review-queue writing), not literal dict storage — a list preserves per-device records faithfully, whereas a dict would silently drop duplicate-DI rows.

**`_persist_result` helper** absorbs the existing three write paths plus the new `fetch_error` path from Phase 1. Same document shapes as today; no schema change. The six document-building blocks currently inlined in the loop become six match arms in `_persist_result`.

**Concurrency safety.**
- `compare_records` is pure (no module globals mutated). Safe.
- `fetch_gudid_record` touches the disk cache (Phase 5) and `requests`. Both are thread-safe: `diskcache.Cache` is SQLite-backed with per-op locking; `requests.Session` isn't shared (each thread uses the module-level `requests.get` which creates its own session internally per call).
- MongoDB writes happen only on the main thread, so no concurrent-update concerns on `devices` / `validationResults` / `verified_devices`.
- No locks needed anywhere.

**Worst-case throughput under retries.** 8 workers × 6 attempts × 60 s = 48 min hard upper bound for a single device. In practice median is 1–2 attempts × ~1.5 s, so 551 devices ÷ 8 ≈ 69 parallel slots × 2 × 1.5 s ≈ 3 min.

**Tests.** New file `harvester/src/validators/tests/test_orchestrator_parallel.py`:
- 4-device mock batch. Mock `fetch_gudid_record` with small per-call sleep (100 ms) to confirm concurrency: wall-clock should be < `num_devices × per_call_sleep / 2`.
- All 4 results land in `validationResults`; counter totals match the expected per-outcome tallies.
- Worker exception isolation: mock raises `Timeout` on device 2, devices 1/3/4 still complete.

## Phase 5 — Disk cache (PR #2)

**New file:** `harvester/src/validators/gudid_cache.py` (~60 LOC)

**Dependency.** Add `diskcache>=5.6` to `requirements.txt`.

```python
"""Disk-backed cache for fetch_gudid_record results.

Key: sha1(catalog_number | version_model_number)
Value: (di, record_dict_or_sentinel) tuple.
TTL: 24 hours (NLM's caching recommendation ceiling).
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

def _key(catalog_number: str | None, version_model_number: str | None) -> str:
    raw = f"{catalog_number or ''}|{version_model_number or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()

def get(catalog_number, version_model_number):
    """Return (di, record) tuple on hit, or None on miss.
    A cached negative lookup returns (di_or_None, None)."""
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
```

**Wire into `fetch_gudid_record`:**

```python
from validators import gudid_cache

@retry(**_RETRY_POLICY)
def fetch_gudid_record(catalog_number=None, version_model_number=None):
    cached = gudid_cache.get(catalog_number, version_model_number)
    if cached is not None:
        return cached

    di = search_gudid_di(catalog_number=catalog_number, version_model_number=version_model_number)
    if not di:
        gudid_cache.set(catalog_number, version_model_number, None, None)
        return None, None

    response = requests.get(LOOKUP_URL, params={"di": di}, timeout=REQUEST_TIMEOUT)
    _raise_for_status_with_rate_limit(response)
    data = response.json()
    device = data.get("gudid", {}).get("device", {})
    if not device:
        gudid_cache.set(catalog_number, version_model_number, di, None)
        return di, None

    record = {...existing structured dict...}
    gudid_cache.set(catalog_number, version_model_number, di, record)
    return di, record
```

Negative results (no DI found, or DI found but empty device) are cached with the `_NOT_FOUND` sentinel, so a second run on the same dataset does zero HTTP calls.

**CLI flag.** `--no-cache` added to `runner.py`:

```python
parser.add_argument(
    "--no-cache",
    action="store_true",
    dest="no_cache",
    help="Bypass the GUDID disk cache for this run.",
)
# In main(), before run_gudid_validation(...):
from validators import gudid_cache
gudid_cache.set_enabled(not args.no_cache)
```

**Interactive `cli.py`.** In `collect_options()`, when `mode["validate"]`, add one prompt:
```python
options["use_cache"] = prompt_yes_no("Use GUDID disk cache?", default=True)
```
In `run_mode()`, set `gudid_cache.set_enabled(options["use_cache"])` before calling `run_gudid_validation`.

**Rationale for module-level flag rather than a parameter.** `fetch_gudid_record` is called from one place (`orchestrator.run_validation`) and, through the retry decorator, has a fixed signature. Threading an `enabled=True` argument through every decorator and test would be noisy; a module-level toggle set once before the run is simpler and matches how `_disabled_models` is managed in `llm_extractor`.

**`.gitignore`.** Add `.cache/` at repo root.

**Cache location.** `<repo-root>/.cache/gudid/` → SQLite store managed by `diskcache`. Portable, inspectable, deletable. Docker-compatible (writable paths exist in the app container).

**Tests.** New file `harvester/src/validators/tests/test_gudid_cache.py`:
1. Cache hit returns without HTTP. Fresh cache → `requests.get` called twice (search + lookup); second call to `fetch_gudid_record` with same inputs → `requests.get` not called at all.
2. Negative result cached. First call returns `(None, None)` because `search_gudid_di` returns None; second call doesn't hit `requests.get`.
3. TTL expiry honored (use `diskcache`'s `expire` directly with a tiny TTL for the test).
4. `set_enabled(False)` → cache neither read nor written; `requests.get` called every time.
5. Cache directory is created on first use.

Integration-ish test (still fully mocked, no live network): run `run_validation` on a 3-device fixture twice with cache enabled; assert `requests.get.call_count > 0` on first pass and `== 0` on second pass.

## Manual validation (not committed)

After PR #2 merges, run the interactive CLI against the real 551-device dataset. Capture wall-clock before (from the recent 17 min baseline) vs. after. Record the number in the changelog. Also run a second time with cache hot and confirm <10 s completion.

If the first-run wall-clock is > 5 min, investigate before declaring PR #2 done: likely culprits are (a) FDA server slowness that day — confirm with a single spot-check; (b) `diskcache` contention — unlikely at 8 workers; (c) a bug in how `as_completed` drains futures. Do not raise `max_workers` to compensate.

## Error handling, edge cases, failure modes

| Scenario | Behavior |
|---|---|
| Single device timeout | Phase 3 retries up to 3×. If all fail, Phase 1 catches `Timeout`, writes `fetch_error`, increments `errors`, continues. |
| Every device times out | `result["errors"] == total`, `result["success"] is True` (run completed; failures surfaced). CLI prints `Errors: N` in yellow. |
| FDA returns 429 | Retried with backoff. If still 429 after 3 attempts, treated as `fetch_error`. |
| FDA returns 404 for a DI | Fast-fail, no retry. Bubbles up as `HTTPError` → caught by Phase 1 as `RequestException` → `fetch_error`. |
| Two harvested devices share a DI | Both workers run their own fetch (cache short-circuits the second) and return independent `DeviceValidationResult`s. Driver appends both to the results list; both get their own `validationResults` doc under their own `device_id`. No dedup, no overwrite. |
| `diskcache` DB corruption | `diskcache` auto-heals on open; if it raises, we let it propagate (corrupted cache is rare and better surfaced than silently bypassed). |
| `.cache/gudid/` missing | Created on first `_get_cache()`. |
| `--no-cache` flag on runner | `gudid_cache.set_enabled(False)` before run; cache neither read nor written. Next run without the flag reads stale-but-fresh (< 24 h) entries if any remain. |

## Testing summary

| Phase | New test files | New tests | Network? |
|---|---|---|---|
| 1 | (extend `test_orchestrator.py`) | 1 | No |
| 2 | — | 0 | — |
| 3 | `test_gudid_client_retry.py` | 4 | No |
| 4 | `test_orchestrator_parallel.py` | 3 | No |
| 5 | `test_gudid_cache.py` | 5 | No |
| 5 integration | (extend `test_orchestrator.py`) | 1 | No |
| **Total** | 3 new files | **14 new tests** | 0 |

Gate between phases: full `pytest` must be green. Current suite: 530 tests. Target: 544 tests. No regressions.

## Files touched

### PR #1 (phases 1–3)

| File | Change |
|---|---|
| `harvester/src/orchestrator.py` | try/except around `fetch_gudid_record`, new `errors` counter, `fetch_error` insert path |
| `harvester/src/validators/gudid_client.py` | `REQUEST_TIMEOUT=60` constant, `GudidRateLimitError`, `_raise_for_status_with_rate_limit`, `@retry` on two functions |
| `harvester/src/pipeline/runner.py` | Print `Errors: N` line in validation summary |
| `harvester/src/pipeline/cli.py` | Print `Errors: N` line in validation summary |
| `app/routes/review.py` + review template | `fetch_error` badge + short error panel |
| `requirements.txt` | `tenacity>=8.0` |
| `harvester/src/validators/CLAUDE.md` | Document 60 s timeout, retry policy, `fetch_error` status |
| `harvester/src/tests/test_orchestrator.py` | +1 test |
| `harvester/src/validators/tests/test_gudid_client_retry.py` | New file, 4 tests |

### PR #2 (phases 4–5)

| File | Change |
|---|---|
| `harvester/src/orchestrator.py` | `DeviceValidationResult`, `_validate_one_device`, `_derive_outcome`, `_persist_result`, `ThreadPoolExecutor` driver |
| `harvester/src/validators/gudid_cache.py` | New module |
| `harvester/src/validators/gudid_client.py` | Cache read/write in `fetch_gudid_record` |
| `harvester/src/pipeline/runner.py` | `--no-cache` flag + `gudid_cache.set_enabled` |
| `harvester/src/pipeline/cli.py` | Interactive cache yes/no prompt |
| `requirements.txt` | `diskcache>=5.6` |
| `.gitignore` | `.cache/` |
| `harvester/src/validators/CLAUDE.md` | Document parallelization + cache |
| `CLAUDE.md` | One-line update in "Validation Scoring" / architecture section |
| `harvester/src/validators/tests/test_orchestrator_parallel.py` | New file, 3 tests |
| `harvester/src/validators/tests/test_gudid_cache.py` | New file, 5 tests |
| `harvester/src/tests/test_orchestrator.py` | +1 integration-ish test |

### Shared (PR #2 only; changelog lives in the last merged PR)

| File | Change |
|---|---|
| `Senior Project/Changelogs/Changelog - 2026-04-23.md` | New file. Summary of PR #1 + PR #2, wall-clock before/after, any spec deviations. |

## Open questions / deviations from the original ask

| Original ask | Deviation | Rationale |
|---|---|---|
| "Mark network tests with a pytest marker if there's an existing one" | No marker added, no network tests written | Repo has no `pytest.ini` / `conftest.py` / registered markers; wall-clock is a manual step; all committed tests are fully mocked. |
| `harvester/src/gudid_client.py` path | Actual path is `harvester/src/validators/gudid_client.py` | Prompt typo; validators/ is the canonical location (matches `CLAUDE.md`). |
| Cache key = "DI string" | Cache key = sha1 of `(catalog_number \| version_model_number)` at `fetch_gudid_record` level | Caching only by DI would still require 551 search calls per run. Composite key short-circuits both round-trips. Confirmed with user during brainstorming. |
| Retry on `search_gudid_di` AND `fetch_gudid_record` | Same. They are sequential network calls, not nested — worst case 3+3 = 6 attempts, median 1+1. |
| `errors` vs existing `not_found` counter | Kept both. `not_found` is pre-existing and declared-but-never-incremented; leaving it alone to avoid unrelated cleanup. `errors` is new and specifically for `RequestException` failures. |

## Success criteria

- **PR #1.** Full `pytest` green. Single-device timeout no longer fails the batch. `Errors: N` visible in CLI output when failures occur. `validationResults` has new `fetch_error` docs for failed devices.
- **PR #2.** Full `pytest` green. 551-device wall-clock ≤ 5 min (ideally ~3 min). Second run on the same dataset completes in < 10 s (cache hits). `--no-cache` flag disables the cache.
- **Combined.** The original failure mode (one Timeout killing 551-device validation) is no longer reproducible. `verified_devices` / `validationResults` / `devices` schemas are backward-compatible with the review dashboard.
