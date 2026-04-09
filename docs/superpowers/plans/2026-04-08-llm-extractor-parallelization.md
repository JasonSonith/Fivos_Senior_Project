# LLM Extractor Parallelization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut batch extraction wall-clock time ~6× by running multiple HTML files through the LLM fallback chain in parallel, with per-provider concurrency caps and non-blocking semaphore acquire so workers fall through to the next model instead of queueing.

**Architecture:** `ThreadPoolExecutor(max_workers=4)` processes files in parallel. Each worker runs the full per-page pipeline (`_process_single_ollama`). Inside `_llm_request`, each model in the chain does `sem.acquire(blocking=False)` against per-provider semaphores (`ollama=1`, `groq=3`, `nvidia=4`). If the slot is taken, the worker falls through to the next model instead of blocking. Thread-safety fixes convert `_last_model_used` to `threading.local()` and wrap `_disabled_models` writes with a `Lock`.

**Tech Stack:** Python 3.13, `concurrent.futures.ThreadPoolExecutor`, `threading.Semaphore`, `threading.Lock`, `threading.local`, `unittest.mock` for tests, `pytest`.

---

## Prerequisites

All tests run from the project root with the package path set:

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/pipeline/tests/ -q
```

Before starting, verify the baseline passes:

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -q
```

Expected: all existing tests pass.

---

## File Structure

| File | Role | Action |
|---|---|---|
| `harvester/src/pipeline/llm_extractor.py` | Fallback chain + LLM helpers | **Modify** — add concurrency primitives, convert `_last_model_used` to thread-local, lock `_disabled_models` writes, non-blocking semaphore acquire in `_llm_request` |
| `harvester/src/pipeline/parallel_batch.py` | Shared parallel batch executor | **Create** — `FileExtractionResult` dataclass + `process_html_files_parallel()` function |
| `harvester/src/pipeline/runner.py` | CLI runner | **Modify** — add `_scrape_urls_with_meta()`, refactor `scrape_urls()` to wrap it, refactor `process_batch()` to use parallel helper, update logging format |
| `harvester/src/orchestrator.py` | UI orchestration | **Modify** — refactor `run_harvest_batch()` into three phases (scrape meta → parallel extract → sequential DB/JSON), preserve frontend result shape |
| `harvester/src/pipeline/tests/test_llm_extractor_concurrency.py` | Concurrency unit tests | **Create** — 3 tests: non-blocking fall-through, thread-local last-model, disabled-models cross-thread |
| `harvester/src/pipeline/tests/test_parallel_batch.py` | Parallel batch unit tests | **Create** — 7 tests from the design spec |

---

## Task 1: Convert `_last_model_used` to `threading.local()`

Fixes a real data race: under the current module-level global, worker A's model name could be clobbered by worker B before A calls `get_last_model()`. With `threading.local()`, each worker thread has its own value.

**Files:**
- Modify: `harvester/src/pipeline/llm_extractor.py:254-259, 274, 304`
- Create: `harvester/src/pipeline/tests/test_llm_extractor_concurrency.py`

- [ ] **Step 1: Write the failing test**

Create `harvester/src/pipeline/tests/test_llm_extractor_concurrency.py`:

```python
"""Concurrency and thread-safety tests for llm_extractor."""
import threading
from unittest.mock import patch

from pipeline import llm_extractor
from pipeline.llm_extractor import _set_last_model, get_last_model


def test_thread_local_last_model():
    """Each thread's get_last_model() returns its own thread's value, not another's."""
    results = {}
    barrier = threading.Barrier(2)

    def worker(name: str, model: str):
        _set_last_model(model)
        barrier.wait()  # ensure both threads have set before either reads
        results[name] = get_last_model()

    t1 = threading.Thread(target=worker, args=("A", "gemma4"))
    t2 = threading.Thread(target=worker, args=("B", "llama-3.3-70b-versatile"))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert results["A"] == "gemma4"
    assert results["B"] == "llama-3.3-70b-versatile"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/pipeline/tests/test_llm_extractor_concurrency.py::test_thread_local_last_model -v
```

Expected: **FAIL** with `ImportError: cannot import name '_set_last_model' from 'pipeline.llm_extractor'`.

- [ ] **Step 3: Add `threading.local()` primitive and helper in `llm_extractor.py`**

In `harvester/src/pipeline/llm_extractor.py`, find the existing block at lines 254-259:

```python
# Track which model answered the last request
_last_model_used: str | None = None


def get_last_model() -> str | None:
    return _last_model_used
```

Replace it with:

```python
# Per-thread last-model tracking (thread-safe under concurrent workers)
_thread_state = threading.local()


def _set_last_model(model: str) -> None:
    _thread_state.last_model = model


def get_last_model() -> str | None:
    return getattr(_thread_state, "last_model", None)
```

- [ ] **Step 4: Add `threading` import**

At the top of `harvester/src/pipeline/llm_extractor.py`, add `import threading` after the existing `import time` line (around line 5).

- [ ] **Step 5: Update the one writer in `_llm_request`**

In `harvester/src/pipeline/llm_extractor.py`, find the existing block inside `_llm_request` (around line 274 and 304):

```python
def _llm_request(system_msg: str, user_msg: str, schema: dict, timeout: int = 60) -> dict | None:
    """Try each model in MODEL_CHAIN until one succeeds."""
    global _last_model_used
```

Remove the `global _last_model_used` line entirely.

Then find (around line 304):

```python
        if result is not None:
            _last_model_used = model
            logger.info("Extraction succeeded with %s (%s)", model, provider)
            return result
```

Change `_last_model_used = model` to `_set_last_model(model)`:

```python
        if result is not None:
            _set_last_model(model)
            logger.info("Extraction succeeded with %s (%s)", model, provider)
            return result
```

- [ ] **Step 6: Run test to verify it passes**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/pipeline/tests/test_llm_extractor_concurrency.py::test_thread_local_last_model -v
```

Expected: **PASS**.

- [ ] **Step 7: Run the full existing test suite to verify no regressions**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -q
```

Expected: all existing tests pass.

- [ ] **Step 8: Commit**

```bash
git add harvester/src/pipeline/llm_extractor.py harvester/src/pipeline/tests/test_llm_extractor_concurrency.py
git commit -m "$(cat <<'EOF'
fix: convert _last_model_used to threading.local for worker safety

Replaces module-level global with threading.local() so each worker
thread reads its own last-model value. Fixes a latent data race where
one worker's model name could be clobbered by another before
get_last_model() is called to record it on the extracted record.
EOF
)"
```

---

## Task 2: Lock `_disabled_models` writes

Wraps the mutable set writes in a `threading.Lock`. Reads stay lockless (tolerated staleness).

**Files:**
- Modify: `harvester/src/pipeline/llm_extractor.py:30, 202, 237`

- [ ] **Step 1: Add the lock and a helper**

In `harvester/src/pipeline/llm_extractor.py`, find the existing line (around line 30):

```python
# Track which models have been confirmed unavailable this session
_disabled_models: set[str] = set()
```

Replace with:

```python
# Track which models have been confirmed unavailable this session.
# Writes go through _disable_model() which holds _disabled_lock;
# reads are lockless and tolerate brief staleness.
_disabled_models: set[str] = set()
_disabled_lock = threading.Lock()


def _disable_model(model: str) -> None:
    with _disabled_lock:
        _disabled_models.add(model)
```

- [ ] **Step 2: Replace the two direct writes inside `_openai_request` and `_ollama_request`**

In `harvester/src/pipeline/llm_extractor.py`, find the existing line inside `_openai_request` (around line 202):

```python
            _disabled_models.add(model)
            return None
```

Replace with:

```python
            _disable_model(model)
            return None
```

Then find the line inside `_ollama_request` (around line 237):

```python
        _disabled_models.add("ollama")
        return None
```

Replace with:

```python
        _disable_model("ollama")
        return None
```

- [ ] **Step 3: Verify the module still imports and existing tests pass**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -q
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add harvester/src/pipeline/llm_extractor.py
git commit -m "$(cat <<'EOF'
fix: serialize _disabled_models writes with a lock

Wraps set mutations behind a _disable_model() helper that holds a
threading.Lock. Reads remain lockless — a worker might briefly try a
model that was just disabled, but the next call will fail gracefully
and the loop will skip it on the next iteration.
EOF
)"
```

---

## Task 3: Non-blocking semaphore acquire in `_llm_request`

Adds per-provider semaphores and refactors the model-chain loop so workers fall through when a provider is saturated instead of blocking.

**Files:**
- Modify: `harvester/src/pipeline/llm_extractor.py` (add constants, semaphores, refactor `_llm_request`)
- Modify: `harvester/src/pipeline/tests/test_llm_extractor_concurrency.py` (add 2 tests)

- [ ] **Step 1: Write the failing tests**

Append to `harvester/src/pipeline/tests/test_llm_extractor_concurrency.py`:

```python
def test_non_blocking_sem_falls_through_when_saturated():
    """When Ollama semaphore is saturated, _llm_request skips to the next model."""
    # Pre-acquire the Ollama slot so the first model in the chain can't be used
    llm_extractor._provider_sems["ollama"].acquire()
    try:
        # Mock Groq env key so the chain will try it
        with patch.dict("os.environ", {"GROQ_API_KEY": "fake-key"}):
            # Mock _openai_request to return a canned response for Groq
            with patch.object(llm_extractor, "_openai_request") as mock_openai:
                mock_openai.return_value = {"device_name": "FALLBACK"}
                result = llm_extractor._llm_request(
                    system_msg="sys",
                    user_msg="user",
                    schema={},
                    timeout=5,
                )
        assert result == {"device_name": "FALLBACK"}
        # The last-model should be a Groq model (not gemma4)
        assert "groq" not in (get_last_model() or "").lower() or get_last_model() != "gemma4"
        assert get_last_model() != "gemma4"
    finally:
        llm_extractor._provider_sems["ollama"].release()


def test_disabled_models_respected_across_threads():
    """A model disabled by one thread stays disabled for another."""
    # Reset state
    with llm_extractor._disabled_lock:
        llm_extractor._disabled_models.clear()
    llm_extractor._disable_model("gemma4")

    seen_models = []
    lock = threading.Lock()

    def fake_openai_request(url, api_key, model, messages, timeout, _retry=False):
        with lock:
            seen_models.append(model)
        return {"device_name": "OK"}

    with patch.dict("os.environ", {"GROQ_API_KEY": "k", "NVIDIA_API_KEY": "k"}):
        with patch.object(llm_extractor, "_openai_request", side_effect=fake_openai_request):
            threads = [
                threading.Thread(
                    target=llm_extractor._llm_request,
                    args=("sys", "user", {}, 5),
                )
                for _ in range(4)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

    # None of the threads should have tried gemma4 (it's disabled)
    assert "gemma4" not in seen_models

    # Cleanup
    with llm_extractor._disabled_lock:
        llm_extractor._disabled_models.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/pipeline/tests/test_llm_extractor_concurrency.py -v
```

Expected: both new tests **FAIL** with `AttributeError: module 'pipeline.llm_extractor' has no attribute '_provider_sems'`.

- [ ] **Step 3: Add concurrency constants and semaphores**

In `harvester/src/pipeline/llm_extractor.py`, after the `MODEL_CHAIN` list (around line 27) and before the `_disabled_models` line, add:

```python
# Concurrency knobs — tuned for RTX 4070 (gemma4 fits in 12GB VRAM)
# and Groq/NVIDIA free-tier rate limits. See design doc
# docs/superpowers/specs/2026-04-08-llm-extractor-parallelization-design.md
EXTRACT_WORKERS = 4
OLLAMA_CONCURRENCY = 1   # single GPU slot
GROQ_CONCURRENCY = 3     # ~30 RPM free tier
NVIDIA_CONCURRENCY = 4   # 40 RPM free tier

_provider_sems: dict[str, threading.Semaphore] = {
    "ollama": threading.Semaphore(OLLAMA_CONCURRENCY),
    "groq":   threading.Semaphore(GROQ_CONCURRENCY),
    "nvidia": threading.Semaphore(NVIDIA_CONCURRENCY),
}
```

- [ ] **Step 4: Refactor the `_llm_request` model loop for non-blocking acquire**

In `harvester/src/pipeline/llm_extractor.py`, find the existing `_llm_request` model loop (around lines 283-311):

```python
    for entry in MODEL_CHAIN:
        model = entry["model"]
        provider = entry["provider"]

        if model in _disabled_models:
            continue
        if provider == "ollama" and "ollama" in _disabled_models:
            continue

        env_key = entry.get("env_key")
        if env_key:
            api_key = os.environ.get(env_key)
            if not api_key:
                continue

        if provider in ("groq", "nvidia"):
            result = _openai_request(provider_urls[provider], api_key, model, messages, timeout)
        else:
            result = _ollama_request(model, messages, schema, timeout)

        if result is not None:
            _set_last_model(model)
            logger.info("Extraction succeeded with %s (%s)", model, provider)
            return result

        logger.info("Model %s failed, trying next in chain", model)

    logger.error("All models in chain exhausted, extraction failed")
    return None
```

Replace with:

```python
    for entry in MODEL_CHAIN:
        model = entry["model"]
        provider = entry["provider"]

        if model in _disabled_models:
            continue
        if provider == "ollama" and "ollama" in _disabled_models:
            continue

        env_key = entry.get("env_key")
        api_key = None
        if env_key:
            api_key = os.environ.get(env_key)
            if not api_key:
                continue

        # Non-blocking acquire: if the provider pool is saturated, fall
        # through to the next model instead of queueing. Preserves
        # quality-first fallback ordering.
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

        if result is not None:
            _set_last_model(model)
            logger.info("Extraction succeeded with %s (%s)", model, provider)
            return result

        logger.info("Model %s failed, trying next in chain", model)

    logger.error("All models in chain exhausted, extraction failed")
    return None
```

- [ ] **Step 5: Run the concurrency tests to verify they pass**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/pipeline/tests/test_llm_extractor_concurrency.py -v
```

Expected: all 3 tests **PASS**.

- [ ] **Step 6: Run the full existing test suite to verify no regressions**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -q
```

Expected: all existing tests pass.

- [ ] **Step 7: Commit**

```bash
git add harvester/src/pipeline/llm_extractor.py harvester/src/pipeline/tests/test_llm_extractor_concurrency.py
git commit -m "$(cat <<'EOF'
feat: per-provider semaphores with non-blocking acquire in _llm_request

Adds EXTRACT_WORKERS and per-provider concurrency constants at the top
of llm_extractor.py. Each model in the fallback chain now acquires its
provider's semaphore with blocking=False — if the slot is taken the
worker falls through to the next model instead of queueing. Preserves
quality-first fallback: gemma4 stays saturated at 1x, Groq absorbs
overflow, NVIDIA rarely engaged.
EOF
)"
```

---

## Task 4: Create `parallel_batch.py` with `FileExtractionResult` + `process_html_files_parallel`

The shared parallel executor used by both CLI and UI batch paths. Workers wrap `_process_single_ollama` with `try/except` so one bad file cannot crash the batch.

**Files:**
- Create: `harvester/src/pipeline/parallel_batch.py`
- Create: `harvester/src/pipeline/tests/test_parallel_batch.py`

- [ ] **Step 1: Write the 7 failing tests**

Create `harvester/src/pipeline/tests/test_parallel_batch.py`:

```python
"""Unit tests for the parallel batch executor.

All tests mock _process_single_ollama to avoid real HTTP and disk I/O.
"""
import threading
import time
from unittest.mock import patch

from pipeline.parallel_batch import (
    FileExtractionResult,
    process_html_files_parallel,
)


def test_empty_input_returns_empty():
    result = process_html_files_parallel([], harvest_run_id="hr-test")
    assert result == []


def test_all_files_succeed():
    def fake_worker(path, source_url=None, harvest_run_id=None):
        return [{"device_name": f"D-{path}"}]

    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        results = process_html_files_parallel(
            ["a.html", "b.html", "c.html", "d.html", "e.html"],
            harvest_run_id="hr-test",
        )

    assert len(results) == 5
    for r in results:
        assert isinstance(r, FileExtractionResult)
        assert r.error is None
        assert len(r.records) == 1


def test_one_file_raises_others_succeed():
    """A worker exception must not kill the batch — 'never crash the run'."""
    def fake_worker(path, source_url=None, harvest_run_id=None):
        if path == "bad.html":
            raise ValueError("simulated worker crash")
        return [{"device_name": f"D-{path}"}]

    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        results = process_html_files_parallel(
            ["good1.html", "bad.html", "good2.html"],
            harvest_run_id="hr-test",
        )

    assert len(results) == 3
    by_path = {r.path: r for r in results}
    assert by_path["bad.html"].records == []
    assert "simulated worker crash" in by_path["bad.html"].error
    assert by_path["good1.html"].error is None
    assert len(by_path["good1.html"].records) == 1
    assert by_path["good2.html"].error is None
    assert len(by_path["good2.html"].records) == 1


def test_progress_callback_fires_per_completion():
    def fake_worker(path, source_url=None, harvest_run_id=None):
        return [{"device_name": "X"}]

    progress_events = []
    lock = threading.Lock()

    def on_progress(completed, total):
        with lock:
            progress_events.append((completed, total))

    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        process_html_files_parallel(
            ["a.html", "b.html", "c.html", "d.html"],
            harvest_run_id="hr-test",
            progress_callback=on_progress,
        )

    assert len(progress_events) == 4
    # Totals are always 4
    assert all(total == 4 for _, total in progress_events)
    # Completed counts cover 1..4
    assert sorted(completed for completed, _ in progress_events) == [1, 2, 3, 4]


def test_source_urls_passed_through():
    received = {}

    def fake_worker(path, source_url=None, harvest_run_id=None):
        received[path] = source_url
        return [{"device_name": "X"}]

    source_urls = {
        "a.html": "https://example.com/a",
        "b.html": "https://example.com/b",
    }

    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        results = process_html_files_parallel(
            ["a.html", "b.html"],
            harvest_run_id="hr-test",
            source_urls=source_urls,
        )

    assert received == source_urls
    for r in results:
        assert r.source_url == source_urls[r.path]


def test_progress_callback_thread_safe():
    """20 files × 4 workers — the callback must see exactly 20 events."""
    def fake_worker(path, source_url=None, harvest_run_id=None):
        time.sleep(0.01)  # force interleaving
        return [{"device_name": "X"}]

    events = []
    lock = threading.Lock()

    def on_progress(completed, total):
        with lock:
            events.append((completed, total))

    paths = [f"f{i}.html" for i in range(20)]
    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        process_html_files_parallel(
            paths,
            harvest_run_id="hr-test",
            progress_callback=on_progress,
        )

    assert len(events) == 20
    completed_values = sorted(c for c, _ in events)
    assert completed_values == list(range(1, 21))


def test_worker_receives_harvest_run_id():
    received_ids = []
    lock = threading.Lock()

    def fake_worker(path, source_url=None, harvest_run_id=None):
        with lock:
            received_ids.append(harvest_run_id)
        return [{"device_name": "X"}]

    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        process_html_files_parallel(
            ["a.html", "b.html", "c.html"],
            harvest_run_id="HR-EXPECTED",
        )

    assert received_ids == ["HR-EXPECTED"] * 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/pipeline/tests/test_parallel_batch.py -v
```

Expected: all 7 tests **FAIL** with `ModuleNotFoundError: No module named 'pipeline.parallel_batch'`.

- [ ] **Step 3: Create the `parallel_batch.py` module**

Create `harvester/src/pipeline/parallel_batch.py`:

```python
"""Parallel HTML file extraction for harvester batch runs.

Shared by CLI batch (runner.process_batch) and UI batch
(orchestrator.run_harvest_batch). Each worker runs _process_single_ollama
on one file; per-provider concurrency caps live inside llm_extractor
(semaphores). Exceptions in workers are caught and returned as error
results so one bad file cannot crash the batch.
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

    Args:
        html_paths: Paths to HTML files to process.
        harvest_run_id: ID threaded through to each record for traceability.
        source_urls: Optional path -> source URL map (propagated to _process_single_ollama).
        progress_callback: Called as (completed, total) whenever any worker finishes.

    Returns:
        One FileExtractionResult per input path, regardless of success.
    """
    # Imported inside the function to avoid a circular import with runner.py,
    # which imports parallel_batch from inside process_batch().
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
                path=path,
                source_url=source_urls.get(path),
                records=records,
                error=None,
            )
        except Exception as exc:
            logger.error(
                "parallel_batch: worker crashed on %s: %s",
                path, exc, exc_info=True,
            )
            return FileExtractionResult(
                path=path,
                source_url=source_urls.get(path),
                records=[],
                error=str(exc),
            )

    results: list[FileExtractionResult] = []
    with ThreadPoolExecutor(
        max_workers=EXTRACT_WORKERS,
        thread_name_prefix="extract",
    ) as pool:
        futures = {pool.submit(_work, p): p for p in html_paths}
        for future in as_completed(futures):
            results.append(future.result())
            with progress_lock:
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/pipeline/tests/test_parallel_batch.py -v
```

Expected: all 7 tests **PASS**.

- [ ] **Step 5: Run the full test suite to verify no regressions**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -q
```

Expected: all existing tests + new tests pass.

- [ ] **Step 6: Commit**

```bash
git add harvester/src/pipeline/parallel_batch.py harvester/src/pipeline/tests/test_parallel_batch.py
git commit -m "$(cat <<'EOF'
feat: add parallel_batch module with FileExtractionResult + executor

Shared ThreadPoolExecutor-based batch extractor used by both CLI and
UI paths. Workers wrap _process_single_ollama in try/except so one bad
file cannot crash the batch (matches the 'never crash the run'
principle). Progress callback fires per completion under a lock.
EOF
)"
```

---

## Task 5: Add `_scrape_urls_with_meta` helper; refactor `scrape_urls` as a thin wrapper

Preserves per-URL scrape information (success or failure) so `run_harvest_batch` can account for failed URLs in its return shape. Existing callers of `scrape_urls` are unchanged.

**Files:**
- Modify: `harvester/src/pipeline/runner.py:494-535`

- [ ] **Step 1: Replace the existing `scrape_urls` with the meta helper + wrapper**

In `harvester/src/pipeline/runner.py`, find the existing `scrape_urls` (lines 494-535) and replace it with:

```python
def _scrape_urls_with_meta(urls: list[str], output_dir: str) -> list[dict]:
    """Scrape URLs, return per-URL metadata (preserves input order and failures).

    Each entry is a dict: {url, final_url, path, error}. For successful
    URLs, final_url and path are set and error is None. For failed URLs,
    final_url and path are None and error contains the failure reason.
    """
    from web_scraper.scraper import (
        BrowserEngine, safe_filename_from_url, is_pdf_url, dedupe_keep_order,
    )

    urls = dedupe_keep_order(urls)
    urls = [u for u in urls if not is_pdf_url(u)]
    os.makedirs(output_dir, exist_ok=True)

    logger.info("Scraping %d URL(s)...", len(urls))

    async def _run():
        async with BrowserEngine(
            max_concurrency=3,
            page_timeout_ms=30_000,
            retries=3,
            retry_delay_s=5.0,
            rate_limit_delay_s=2.0,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            headless=True,
        ) as engine:
            return await asyncio.gather(*(engine.fetch(u) for u in urls))

    results = asyncio.run(_run())
    meta: list[dict] = []
    saved_count = 0
    for url, r in zip(urls, results):
        if r.ok and r.html:
            fname = safe_filename_from_url(r.final_url or r.url)
            path = os.path.join(output_dir, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(r.html)
            saved_count += 1
            logger.info("Scraped: %s", r.final_url or r.url)
            meta.append({
                "url": url,
                "final_url": r.final_url or r.url,
                "path": path,
                "error": None,
            })
        else:
            logger.warning("Scrape failed: %s — %s", r.url, r.error)
            meta.append({
                "url": url,
                "final_url": None,
                "path": None,
                "error": r.error,
            })
    logger.info("Scraped %d/%d pages.", saved_count, len(urls))
    return meta


def scrape_urls(urls: list[str], output_dir: str) -> list[str]:
    """Scrape URLs via Playwright and save HTML files. Returns list of saved paths.

    Backward-compatible wrapper around _scrape_urls_with_meta() for callers
    that only need successful paths.
    """
    meta = _scrape_urls_with_meta(urls, output_dir)
    return [m["path"] for m in meta if m["path"]]
```

- [ ] **Step 2: Run the full test suite to verify no regressions**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -q
```

Expected: all existing tests pass. (The refactor is behavior-preserving for `scrape_urls`; no new tests needed because the pure function underneath is exercised by existing integration paths.)

- [ ] **Step 3: Commit**

```bash
git add harvester/src/pipeline/runner.py
git commit -m "$(cat <<'EOF'
refactor: extract _scrape_urls_with_meta; scrape_urls is now a wrapper

_scrape_urls_with_meta returns per-URL metadata (url, final_url, path,
error) so run_harvest_batch can account for failed scrapes in its
results list. scrape_urls() keeps its existing list[str] signature for
backward compatibility.
EOF
)"
```

---

## Task 6: Refactor `runner.process_batch` to use `process_html_files_parallel`

Thin wrapper around the shared parallel executor. Preserves the existing summary dict shape.

**Files:**
- Modify: `harvester/src/pipeline/runner.py:431-477`

- [ ] **Step 1: Replace `process_batch`**

In `harvester/src/pipeline/runner.py`, find the existing `process_batch` function (lines 431-477) and replace it with:

```python
def process_batch(
    input_dir: str,
    output_dir: str = "harvester/output",
    harvest_run_id: str | None = None,
) -> dict:
    """Process all HTML files in a directory using parallel LLM extraction.

    Returns a summary dict with keys: processed, succeeded, failed,
    ollama_extracted, output_dir, files.
    """
    from pipeline.parallel_batch import process_html_files_parallel

    html_files = sorted(
        glob.glob(os.path.join(input_dir, "*.html"))
        + glob.glob(os.path.join(input_dir, "*.htm"))
    )

    summary = {
        "processed": len(html_files),
        "succeeded": 0,
        "failed": 0,
        "ollama_extracted": 0,
        "output_dir": output_dir,
        "files": [],
    }

    if not html_files:
        return summary

    results = process_html_files_parallel(
        html_files,
        harvest_run_id=harvest_run_id or "",
    )

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

- [ ] **Step 2: Run the full test suite**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add harvester/src/pipeline/runner.py
git commit -m "$(cat <<'EOF'
refactor: process_batch now delegates to parallel batch executor

process_batch becomes a thin wrapper around
parallel_batch.process_html_files_parallel. Summary dict shape
unchanged: {processed, succeeded, failed, ollama_extracted, output_dir,
files}.
EOF
)"
```

---

## Task 7: Refactor `orchestrator.run_harvest_batch` into three phases

Phase 1 scrapes with metadata, Phase 2 extracts in parallel, Phase 3 writes JSON + inserts to DB sequentially. Preserves the existing frontend contract (`total`, `succeeded`, `failed`, `results` array with `{url, scraped, devices_extracted, db_inserted, error}`).

**Files:**
- Modify: `harvester/src/orchestrator.py:144-175`

- [ ] **Step 1: Replace `run_harvest_batch`**

In `harvester/src/orchestrator.py`, find the existing `run_harvest_batch` function (lines 144-175) and replace it with:

```python
def run_harvest_batch(urls: list[str], job_store: dict | None = None, job_id: str | None = None) -> dict:
    """Scrape + parallel-extract + DB insert, in three phases.

    Phase 1: sequential scrape (Playwright is already internally batched).
    Phase 2: parallel LLM extraction via ThreadPoolExecutor.
    Phase 3: sequential JSON writes + MongoDB inserts on the main thread.

    Returns the shape expected by app/templates/harvester.html:
        {total, succeeded, failed, results: [...], run_id}
    Each results entry: {url, scraped, devices_extracted, db_inserted, error}
    """
    from pipeline.runner import _scrape_urls_with_meta, write_record_json
    from pipeline.parallel_batch import process_html_files_parallel
    from database.db_connection import get_db

    run_id = _get_run_id()
    output_dir = os.path.abspath(_DEFAULT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    # Phase 1: scrape (per-URL metadata preserves failures)
    meta = _scrape_urls_with_meta(urls, _DEFAULT_HTML_DIR)
    scraped = [m for m in meta if m["path"]]
    source_urls = {m["path"]: m["url"] for m in scraped}

    # Phase 2: parallel extraction
    def _progress(completed: int, total: int) -> None:
        if job_store is not None and job_id is not None:
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

    # Phase 3: JSON write + DB insert sequentially
    try:
        db = get_db()
    except Exception as e:
        logger.warning("run_harvest_batch: MongoDB unavailable: %s", e)
        db = None

    results: list[dict] = []
    for m in meta:
        entry = {
            "url": m["url"],
            "scraped": m["path"] is not None,
            "devices_extracted": 0,
            "db_inserted": 0,
            "error": m["error"],
        }
        fr = file_results_by_path.get(m["path"]) if m["path"] else None
        if fr is not None:
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
        "succeeded": sum(
            1 for r in results
            if r["devices_extracted"] > 0 and not r["error"]
        ),
        "failed": sum(
            1 for r in results
            if r["devices_extracted"] == 0 or r["error"]
        ),
        "results": results,
        "run_id": run_id,
    }
```

- [ ] **Step 2: Run the full test suite**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add harvester/src/orchestrator.py
git commit -m "$(cat <<'EOF'
refactor: run_harvest_batch is now three-phase (scrape, parallel extract, DB)

Phase 1 calls _scrape_urls_with_meta to preserve per-URL scrape status.
Phase 2 delegates to parallel_batch.process_html_files_parallel. Phase
3 writes JSON and inserts to MongoDB sequentially on the main thread.
Preserves the frontend result shape {total, succeeded, failed, results,
run_id} with per-URL entries including scraped/devices_extracted/
db_inserted/error. Progress updates now report completed-count instead
of a per-URL current_url (which the frontend already handles via
null-check).
EOF
)"
```

---

## Task 8: Update log format to include thread name

Adds `[%(threadName)s]` to the log format so parallel worker logs are readable when interleaved.

**Files:**
- Modify: `harvester/src/pipeline/runner.py` (find the `logging.basicConfig` call in `main()`)

- [ ] **Step 1: Locate the current logging setup**

```bash
grep -n "basicConfig\|FileHandler\|setFormatter" harvester/src/pipeline/runner.py
```

The match in `main()` (around line 599) will be:

```python
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
```

If there are also `FileHandler` / `setFormatter` calls for the `harvester/log-files/` log, include them too.

- [ ] **Step 2: Update the format string(s)**

In every location where the log format is set (`basicConfig` in `main()` and any `Formatter(...)` used on the file handler), change:

```python
format="%(levelname)s %(name)s: %(message)s"
```

to:

```python
format="%(asctime)s [%(threadName)s] %(levelname)s %(name)s: %(message)s"
```

(If a format already has `%(asctime)s`, just insert `[%(threadName)s] ` after the levelname.)

- [ ] **Step 3: Smoke-test the format by running the existing CLI with no URLs**

```bash
python3 harvester/src/pipeline/runner.py --no-validate 2>&1 | head -5
```

Expected: log lines include `[MainThread]` (or similar). No crashes.

- [ ] **Step 4: Run the full test suite**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add harvester/src/pipeline/runner.py
git commit -m "$(cat <<'EOF'
chore: include thread name in pipeline log format

Adds [%(threadName)s] to the log format used by runner.main() and the
file log handler so parallel worker logs remain readable when
interleaved. Main thread shows as [MainThread]; parallel workers show
as [extract_0], [extract_1], etc.
EOF
)"
```

---

## Task 9: Final verification — full test suite and smoke test

- [ ] **Step 1: Run the full automated test suite**

```bash
PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -v
```

Expected: every test passes. Count the new tests:
- `test_llm_extractor_concurrency.py`: 3 tests
- `test_parallel_batch.py`: 7 tests

That's **10 new tests** added by this plan.

- [ ] **Step 2: Smoke-test the CLI end-to-end**

```bash
python3 harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --overwrite 2>&1 | tee /tmp/parallel-smoke.log
```

Expected wall-clock: **~5 minutes or less** (vs ~30 min baseline from `harvest_20260408_155652.log`).

- [ ] **Step 3: Verify parallel execution in the log**

```bash
grep -oE '\[extract_[0-9]+\]' /tmp/parallel-smoke.log | sort -u
```

Expected output: `[extract_0]`, `[extract_1]`, `[extract_2]`, `[extract_3]` (all 4 worker thread names should appear).

- [ ] **Step 4: Verify the device count is comparable to the baseline**

The baseline 2026-04-08 run produced 323 devices. The new run should produce a similar count (within ±10% tolerance for LLM variance). Check the `"Inserted N/M records"` log line.

- [ ] **Step 5: Verify no unhandled exceptions in the log**

```bash
grep -E 'Traceback|Exception|CRASHED' /tmp/parallel-smoke.log
```

Expected: no output (the only acceptable matches are logger warnings from the existing "Model X failed, trying next in chain" path, which are handled).

- [ ] **Step 6: Verify validationResults was populated**

From the MongoDB shell or a script:

```bash
python3 -c "
import sys
sys.path.insert(0, 'harvester/src')
from database.db_connection import get_db
db = get_db()
print('devices:', db['devices'].count_documents({}))
print('validationResults:', db['validationResults'].count_documents({}))
"
```

Expected: `devices > 0` and `validationResults > 0` (the latter depends on the earlier `gudid_client.py` null-field fix being applied).

- [ ] **Step 7: If everything passes, push the branch**

```bash
git status
git log --oneline -10
git push origin Jason
```

---

## Self-Review Checklist

Before handing off, the plan author ran these checks:

**Spec coverage:**
- Concurrency caps (EXTRACT_WORKERS, OLLAMA/GROQ/NVIDIA) — Task 3 Step 3.
- Non-blocking semaphore acquire — Task 3 Step 4.
- `_last_model_used` → `threading.local()` — Task 1.
- `_disabled_models` lock — Task 2.
- `parallel_batch.py` module — Task 4.
- `_scrape_urls_with_meta` helper — Task 5.
- `process_batch` refactor — Task 6.
- `run_harvest_batch` refactor — Task 7.
- Log format change — Task 8.
- Test plan (7 parallel_batch + 3 llm_extractor_concurrency) — Tasks 3 and 4.

**Placeholder scan:** No TBD, TODO, FIXME, "similar to", or "add error handling". Every code block is complete.

**Type consistency:** `FileExtractionResult` signature identical in Task 4 (definition), Task 6 (uses `r.records`/`r.error`), and Task 7 (uses `r.records`/`r.error`). `process_html_files_parallel` signature identical across Tasks 4, 6, 7. `_scrape_urls_with_meta` returns `list[dict]` with keys `{url, final_url, path, error}` — consistent between Tasks 5 and 7.
