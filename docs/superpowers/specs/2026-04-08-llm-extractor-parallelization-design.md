# LLM Extractor Parallelization — Design

**Date:** 2026-04-08
**Owner:** Jason
**Status:** Design — pending implementation plan

## Problem

The harvesting pipeline processes HTML files sequentially. Each page requires two LLM calls (page-level fields + product rows). On a 28-URL run with gemma4 as the primary model (~20 seconds per call), the extraction phase takes ~30 minutes of wall-clock time. The actual bottleneck is network/GPU latency per LLM call, not CPU. The system is idle waiting for responses most of the time.

The cloud fallback models (Groq, NVIDIA NIM) are I/O-bound and can handle concurrent requests comfortably within their rate limits, but the current code issues them one at a time.

## Goals

- Cut batch extraction wall-clock time by 4-6× on 28-URL runs.
- Work for both the CLI batch (`python runner.py --urls …`) and the web UI batch upload path.
- Preserve fallback chain quality ordering — gemma4 still gets used maximally.
- Preserve the existing frontend contract for batch job results.
- Fix shared-state bugs that would break under concurrency (`_last_model_used` race, `_disabled_models` mutation).
- Keep the diff small enough to be reviewed and understood.

## Non-Goals

- Rewriting the HTTP client from `requests` to `httpx` / `aiohttp`.
- Asyncio or multiprocessing — threads are sufficient for HTTP I/O-bound work at this scale.
- Parallelizing Playwright scraping (already batched internally by `BrowserEngine`).
- Parallelizing DB writes (MongoDB is not the bottleneck).
- Parallelizing GUDID validation (out of scope; flagged as separate follow-up).
- Adding env-var configuration for concurrency knobs — hardcoded constants for now.

## Architecture

### Concurrency model

`concurrent.futures.ThreadPoolExecutor(max_workers=4)` processes multiple HTML files in parallel. Each worker fully handles one page start-to-finish: read HTML → sanitize → extract (2-pass) → normalize → validate → package. Workers share the LLM fallback chain through three per-provider semaphores.

### Per-provider concurrency caps

Hardcoded constants at the top of `llm_extractor.py`:

```python
EXTRACT_WORKERS = 4
OLLAMA_CONCURRENCY = 1   # single GPU, gemma4 is 9.6 GB on 12 GB VRAM
GROQ_CONCURRENCY = 3     # free tier ~30 RPM; 3 concurrent × 5s ≈ 36 RPM
NVIDIA_CONCURRENCY = 4   # 40 RPM; 4 concurrent × 10s ≈ 24 RPM
```

Rationale: Ollama is local (GPU-limited, single slot). Groq and NVIDIA are cloud and handle concurrency fine within their rate budgets.

### Non-blocking semaphore acquire — key design insight

Inside `_llm_request`, each model in the chain attempts `sem.acquire(blocking=False)`. If the provider's slot pool is saturated, the worker **immediately falls through to the next model** instead of blocking. This preserves quality-first fallback: gemma4 stays maximally utilized (1 worker at a time), overflow cascades to Groq then NVIDIA. No worker wastes time queueing on a busy model.

### Thread-safety fixes to existing shared state

1. **`_disabled_models: set[str]`** — writes wrapped in `threading.Lock`. Reads remain lockless; we tolerate brief staleness (a worker might try a model that was just disabled; the call will fail gracefully and the next iteration will skip it).

2. **`_last_model_used: str | None`** — converted from a module-level global to `threading.local()`. Each worker thread reads its own last-model value. This fixes a real data race: under the current design, worker A's model name could be clobbered by worker B before A calls `get_last_model()` to record it in the extracted record.

### New shared batch executor

New module `harvester/src/pipeline/parallel_batch.py` exposes one function used by both CLI and UI batch paths:

```python
@dataclass
class FileExtractionResult:
    path: str
    source_url: str | None
    records: list[dict]
    error: str | None

def process_html_files_parallel(
    html_paths: list[str],
    harvest_run_id: str,
    source_urls: dict[str, str] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[FileExtractionResult]:
    ...
```

## Components

### Files touched

| File | Change |
|---|---|
| `harvester/src/pipeline/llm_extractor.py` | Add per-provider semaphores + `_disabled_lock`. Refactor `_llm_request` for non-blocking acquire. Convert `_last_model_used` to `threading.local()`. |
| `harvester/src/pipeline/parallel_batch.py` | **New.** Contains `FileExtractionResult` dataclass and `process_html_files_parallel()` helper. |
| `harvester/src/pipeline/runner.py` | `process_batch()` becomes a thin wrapper around `process_html_files_parallel()`. Add internal `_scrape_urls_with_meta()` helper; keep `scrape_urls()` as a thin wrapper so existing callers are unchanged. Update log format to include `%(threadName)s`. |
| `harvester/src/orchestrator.py` | `run_harvest_batch()` restructured into three phases: scrape (meta), extract (parallel), write/DB (sequential). Preserves existing return shape for the frontend. |
| `harvester/src/pipeline/tests/test_parallel_batch.py` | **New.** Unit tests with mocked `_process_single_ollama`. |
| `harvester/src/pipeline/tests/test_llm_extractor_concurrency.py` | **New.** Unit tests for `_llm_request` semaphore behavior and `threading.local()` correctness. |

### `llm_extractor.py` changes (additive)

```python
import threading

EXTRACT_WORKERS = 4
OLLAMA_CONCURRENCY = 1
GROQ_CONCURRENCY = 3
NVIDIA_CONCURRENCY = 4

_provider_sems = {
    "ollama": threading.Semaphore(OLLAMA_CONCURRENCY),
    "groq":   threading.Semaphore(GROQ_CONCURRENCY),
    "nvidia": threading.Semaphore(NVIDIA_CONCURRENCY),
}

_disabled_lock = threading.Lock()
_thread_state = threading.local()

def _set_last_model(model: str) -> None:
    _thread_state.last_model = model

def get_last_model() -> str | None:
    return getattr(_thread_state, "last_model", None)
```

All existing `_last_model_used = model` statements become `_set_last_model(model)`. All `_disabled_models.add(...)` calls become:

```python
with _disabled_lock:
    _disabled_models.add(model)
```

Inside the `_llm_request` loop, each model iteration becomes:

```python
sem = _provider_sems[provider]
if not sem.acquire(blocking=False):
    logger.debug("%s provider saturated, falling through", provider)
    continue
try:
    if provider in ("groq", "nvidia"):
        result = _openai_request(provider_urls[provider], api_key, model, messages, timeout)
    else:
        result = _ollama_request(model, messages, schema, timeout)
finally:
    sem.release()
```

### `parallel_batch.py` (new, ~70 lines)

```python
"""Parallel HTML file extraction for harvester batch runs.

Shared by CLI batch (runner.process_batch) and UI batch (orchestrator.run_harvest_batch).
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class FileExtractionResult:
    path: str
    source_url: str | None
    records: list[dict] = field(default_factory=list)
    error: str | None = None


def process_html_files_parallel(
    html_paths: list[str],
    harvest_run_id: str,
    source_urls: dict[str, str] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[FileExtractionResult]:
    """Extract records from HTML files in parallel.

    - Each worker runs _process_single_ollama on one file.
    - Per-provider concurrency caps live inside llm_extractor (semaphores).
    - progress_callback(completed, total) fires whenever any worker finishes.
    - Exceptions in workers are caught, logged, and returned as error results.
    """
    from pipeline.llm_extractor import EXTRACT_WORKERS
    from pipeline.runner import _process_single_ollama

    total = len(html_paths)
    if total == 0:
        return []

    source_urls = source_urls or {}
    completed = 0
    progress_lock = threading.Lock()

    def _work(path: str) -> FileExtractionResult:
        try:
            records = _process_single_ollama(
                path,
                source_url=source_urls.get(path),
                harvest_run_id=harvest_run_id,
            )
            return FileExtractionResult(
                path=path, source_url=source_urls.get(path),
                records=records, error=None,
            )
        except Exception as exc:
            logger.error("parallel_batch: worker crashed on %s: %s", path, exc, exc_info=True)
            return FileExtractionResult(
                path=path, source_url=source_urls.get(path),
                records=[], error=str(exc),
            )

    results: list[FileExtractionResult] = []
    with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS, thread_name_prefix="extract") as pool:
        futures = {pool.submit(_work, p): p for p in html_paths}
        for future in as_completed(futures):
            results.append(future.result())
            with progress_lock:
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

    return results
```

### `runner.py` — `process_batch` becomes a thin wrapper

```python
def process_batch(input_dir, output_dir="harvester/output", harvest_run_id=None):
    html_files = sorted(
        glob.glob(os.path.join(input_dir, "*.html"))
        + glob.glob(os.path.join(input_dir, "*.htm"))
    )
    summary = {
        "processed": len(html_files), "succeeded": 0, "failed": 0,
        "ollama_extracted": 0, "output_dir": output_dir, "files": [],
    }
    if not html_files:
        return summary

    from pipeline.parallel_batch import process_html_files_parallel
    results = process_html_files_parallel(html_files, harvest_run_id=harvest_run_id)

    for r in results:
        if r.records:
            for record in r.records:
                summary["files"].append(write_record_json(record, output_dir))
            summary["succeeded"] += len(r.records)
            summary["ollama_extracted"] += len(r.records)
        else:
            summary["failed"] += 1

    return summary
```

### `runner.py` — new `_scrape_urls_with_meta` helper

```python
def _scrape_urls_with_meta(urls, output_dir):
    """Scrape URLs, return per-URL metadata list (preserves input order and failures).

    Each entry: {"url": str, "final_url": str|None, "path": str|None, "error": str|None}
    """
    from web_scraper.scraper import (
        BrowserEngine, safe_filename_from_url, is_pdf_url, dedupe_keep_order,
    )

    urls = dedupe_keep_order(urls)
    urls = [u for u in urls if not is_pdf_url(u)]
    os.makedirs(output_dir, exist_ok=True)

    async def _run():
        async with BrowserEngine(...) as engine:
            return await asyncio.gather(*(engine.fetch(u) for u in urls))

    results = asyncio.run(_run())
    meta = []
    for url, r in zip(urls, results):
        if r.ok and r.html:
            fname = safe_filename_from_url(r.final_url or r.url)
            path = os.path.join(output_dir, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(r.html)
            meta.append({"url": url, "final_url": r.final_url or r.url, "path": path, "error": None})
        else:
            meta.append({"url": url, "final_url": None, "path": None, "error": r.error})
    return meta


def scrape_urls(urls, output_dir):
    """Legacy wrapper — returns list of successfully-saved paths. Unchanged signature."""
    meta = _scrape_urls_with_meta(urls, output_dir)
    return [m["path"] for m in meta if m["path"]]
```

### `orchestrator.py` — `run_harvest_batch` restructured

```python
def run_harvest_batch(urls, job_store=None, job_id=None):
    from pipeline.runner import _scrape_urls_with_meta, write_record_json
    from pipeline.parallel_batch import process_html_files_parallel
    from database.db_connection import get_db

    run_id = _get_run_id()
    output_dir = os.path.abspath(_DEFAULT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    # Phase 1: scrape (with per-URL metadata, preserves failed URLs)
    meta = _scrape_urls_with_meta(urls, _DEFAULT_HTML_DIR)
    scraped = [m for m in meta if m["path"]]
    source_urls = {m["path"]: m["url"] for m in scraped}

    # Phase 2: extract in parallel
    def _progress(completed, total):
        if job_store and job_id:
            job_store[job_id] = {
                "status": "running",
                "result": {"progress": completed, "total": total},
            }

    file_results = process_html_files_parallel(
        [m["path"] for m in scraped],
        harvest_run_id=run_id,
        source_urls=source_urls,
        progress_callback=_progress,
    )
    file_results_by_path = {r.path: r for r in file_results}

    # Phase 3: write JSON + DB insert sequentially
    try:
        db = get_db()
    except Exception as e:
        logger.warning("run_harvest_batch: MongoDB unavailable: %s", e)
        db = None

    results = []
    for m in meta:
        entry = {
            "url": m["url"],
            "scraped": m["path"] is not None,
            "devices_extracted": 0,
            "db_inserted": 0,
            "error": m["error"],
        }
        fr = file_results_by_path.get(m["path"]) if m["path"] else None
        if fr:
            entry["devices_extracted"] = len(fr.records)
            if fr.error:
                entry["error"] = fr.error
            for record in fr.records:
                write_record_json(record, output_dir)
                if db is not None:
                    try:
                        db["devices"].insert_one(record)
                        entry["db_inserted"] += 1
                    except Exception as e:
                        entry["error"] = f"DB error: {e}"
        results.append(entry)

    return {
        "total": len(urls),
        "succeeded": sum(1 for r in results if r["devices_extracted"] > 0 and not r["error"]),
        "failed": sum(1 for r in results if r["devices_extracted"] == 0 or r["error"]),
        "results": results,
        "run_id": run_id,
    }
```

### Logging format change

Update the logging setup in `runner.py` main() and in the log-file handler:

```python
format="%(asctime)s [%(threadName)s] %(levelname)s %(name)s: %(message)s"
```

Main thread shows as `[MainThread]`, workers show as `[extract_0]`, `[extract_1]`, etc. Makes interleaved parallel logs readable.

## Data Flow

```
[run_harvest_batch (UI)]          [process_batch (CLI)]
         |                                 |
         v                                 v
 _scrape_urls_with_meta              glob(*.html)
  (Playwright, batched)
         |                                 |
         +----------------+----------------+
                          |
                          v
         process_html_files_parallel(paths, …)
                          |
                          v
             ThreadPoolExecutor(max_workers=4)
             ┌────────┬────────┬────────┬────────┐
             ▼        ▼        ▼        ▼
          worker1  worker2  worker3  worker4
             │        │        │        │
             │  each calls _process_single_ollama:
             │     ├─ sanitize_html / parse_html
             │     ├─ extract_all_fields
             │     │     ├─ extract_page_fields → _llm_request(PAGE)
             │     │     └─ extract_product_rows → _llm_request(ROWS)
             │     ├─ normalize_record
             │     ├─ parse_regulatory_from_text
             │     ├─ validate_record
             │     └─ package_gudid_record
             └──→ returns FileExtractionResult
                          |
                          v
                 future.result() in main thread
                          |
                          v
                completed += 1 (under lock)
                progress_callback(completed, total)
```

### Inside `_llm_request` (critical path)

Each worker's `_llm_request` iterates `MODEL_CHAIN` top-to-bottom. For each model:

1. Check if model is in `_disabled_models` (lockless read) — skip if disabled.
2. `sem = _provider_sems[provider]`
3. `if not sem.acquire(blocking=False): continue` — **fall through, do not queue**.
4. Call `_openai_request` / `_ollama_request` inside a `try/finally` that releases the sem.
5. On success: `_set_last_model(model)` (thread-local), return result.
6. On failure (`None`): log and continue to next model.

### 4-worker, 4-page cold start timeline

| t (s) | worker1 | worker2 | worker3 | worker4 | Ollama | Groq | NVIDIA |
|---|---|---|---|---|---|---|---|
| 0 | gemma4 ✓ | groq-70b ✓ | groq-70b ✓ | groq-70b ✓ | 1/1 | 3/3 | 0/4 |
| 5 | gemma4 (in flight) | done → page 5 → groq-70b ✓ | done → page 6 → groq-70b ✓ | done → page 7 → groq-70b ✓ | 1/1 | 3/3 | 0/4 |
| 20 | done → page 8 → gemma4 ✓ | … | … | … | 1/1 | 3/3 | 0/4 |

Groq carries the bulk, gemma4 stays saturated at 1×, NVIDIA rarely engaged. 28 pages × 2 passes = 56 calls; realistic wall-clock target **~5 min vs current ~30 min** (theoretical steady-state is lower, but JSON parse failures and fallback retries add real overhead).

### Invariants

- No worker blocks on a semaphore — workers are only blocked on HTTP I/O.
- `_set_last_model` writes and `get_last_model` reads happen on the same worker thread; `threading.local()` guarantees correctness.
- `_disabled_models` writes are serialized; reads are lockless and tolerate staleness.
- DB writes stay on the main thread after parallel extraction completes.

## Error Handling

### Layer 1 — Single model call fails
Unchanged. `_openai_request` / `_ollama_request` return `None` on exception. `_llm_request` logs `"Model X failed, trying next in chain"` and continues.

### Layer 2 — Semaphore saturation
New. `sem.acquire(blocking=False)` returns False → log at DEBUG level, continue the chain. Not an error.

### Layer 3 — All models exhausted for one page
Unchanged. `_llm_request` returns `None`; `extract_all_fields` returns `[]`; `_process_single_ollama` logs a warning; file counts as failed.

### Layer 4 — Unexpected exception inside a worker
**New. Critical upgrade.** `parallel_batch._work` wraps `_process_single_ollama` in `try/except Exception`. Without this catch, `future.result()` in the main thread would re-raise and abort the batch. With it, **one bad page cannot kill the other 27** — matches the "never crash the run" principle already documented in `CLAUDE.md`.

### Layer 5 — Scraping failures
Handled by `_scrape_urls_with_meta`: failed URLs have `path=None`, `error="..."`. Flow through to the frontend results array with `scraped: false`.

### Layer 6 — DB insert failures (UI path)
Handled in the sequential post-extraction loop, per-URL. Sets `entry["error"] = "DB error: ..."`. Unchanged semantics.

### Not in scope

- Wrapping `run_validation` loop in try/except (separate follow-up, flagged in `2026-04-08` changelog).
- Shared state mutation can't fail in CPython — no try/except needed for `_disabled_models.add()` or `_set_last_model()`.

## Testing

### `test_parallel_batch.py` (new) — 7 unit tests, all mocked

1. `test_empty_input_returns_empty` — no paths → no workers spawned.
2. `test_all_files_succeed` — 5 paths → 5 results with records.
3. `test_one_file_raises_others_succeed` — exception in one worker doesn't crash the batch. **Validates the "never crash the run" invariant.**
4. `test_progress_callback_fires_per_completion` — N callbacks total, final is `(N, N)`, monotonic.
5. `test_source_urls_passed_through` — path→url mapping preserved.
6. `test_progress_callback_thread_safe` — 20 files × 4 workers, no corruption.
7. `test_worker_receives_harvest_run_id` — `harvest_run_id` propagates to each worker call.

All use `unittest.mock.patch` on `_process_single_ollama`. Zero real HTTP, zero disk I/O. Runtime < 1 second.

### `test_llm_extractor_concurrency.py` (new) — 3 unit tests

1. `test_non_blocking_sem_falls_through_when_saturated` — pre-acquire Ollama semaphore, verify request falls through to Groq mock.
2. `test_disabled_models_respected_across_threads` — add model to `_disabled_models`, spawn 4 threads calling `_llm_request`, verify none retry the disabled model.
3. `test_thread_local_last_model` — two threads with different mocked models, each thread's `get_last_model()` returns its own model. **Validates `threading.local()` correctness.**

### Smoke test (manual)

```bash
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --overwrite
```

Success criteria:
1. Wall-clock drops from ~30 min to ~5 min or less.
2. Device count ≈ previous run (323 ± normal LLM variance).
3. Log file shows `[extract_N]` thread names interleaved correctly.
4. No unhandled tracebacks in the log.
5. `validationResults` collection populated (validator fix from earlier; unrelated to this change but good end-to-end check).

### Regression protection

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -q
```

All existing tests must still pass.

## Out of scope / Follow-ups

- **Wrap `run_validation` per-device loop in try/except** — flagged in earlier session, separate fix.
- **INFO-level logging inside the validator** — separate fix.
- **Env-var-driven concurrency knobs** — easy to promote later if needed.
- **Parallelizing DB writes** — not a bottleneck; would complicate progress reporting for negligible gain.
- **Parallelizing GUDID validation** — separate scope; GUDID API has its own rate limits to reason about.

## Rollout

1. Implement behind no flag — parallelization is on by default. Sequential is recoverable by setting `EXTRACT_WORKERS = 1` if we need to debug.
2. Ship fix + smoke-test locally on the 28-URL list before merging to main.
3. Document the new log format in `CLAUDE.md` (format string change).
