# GUDID Validation Resilience & Parallelization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 551-device validation-killing HTTP bug, then parallelize and cache GUDID API calls so batch validation is resilient to per-device failures and completes in ~3 min instead of ~17 min.

**Architecture:** Two stacked PRs off `Jason`. PR #1 (`Jason-gudid-resilience`, phases 1–3) wraps the per-device `fetch_gudid_record` call in `try/except`, bumps the HTTP timeout from 15 s to 60 s, and adds a `tenacity` retry decorator that fires on `Timeout`, `ConnectionError`, and HTTP 429 only. PR #2 (`Jason-gudid-parallel`, phases 4–5, branches off the post-merge PR #1) swaps the serial loop for an 8-worker `ThreadPoolExecutor` with worker/main-thread split (workers do network + CPU, main thread writes DB serially) and adds a `diskcache`-backed local cache keyed on `(catalog_number, version_model_number)` with 24 h TTL.

**Tech Stack:** Python 3.13, pytest, tenacity (new), diskcache (new), requests, concurrent.futures, pymongo, FastAPI + Jinja2.

**Spec:** `docs/superpowers/specs/2026-04-23-gudid-validation-resilience-design.md`

---

## File Structure

### PR #1 — Resilience (phases 1–3)

**Modify:**
- `harvester/src/orchestrator.py` — `run_validation()`: add `errors` counter, wrap `fetch_gudid_record` in `try/except requests.RequestException`, insert `fetch_error` doc on failure.
- `harvester/src/validators/gudid_client.py` — add `REQUEST_TIMEOUT = 60` constant, add `GudidRateLimitError` exception and `_raise_for_status_with_rate_limit` helper, decorate `search_gudid_di` and `fetch_gudid_record` with `@retry(...)`.
- `harvester/src/pipeline/runner.py` — print `Errors: N` line in validation summary output.
- `harvester/src/pipeline/cli.py` — print `Errors: N` line in validation summary output.
- `app/routes/review.py` + `app/templates/review.html` — handle `status == "fetch_error"` with a neutral banner + error panel.
- `harvester/src/tests/test_orchestrator.py` — add `TestRunValidationErrorIsolation` class.
- `requirements.txt` — add `tenacity>=8.0`.
- `harvester/src/validators/CLAUDE.md` — document 60 s timeout, retry policy, `fetch_error` status.

**Create:**
- `harvester/src/validators/tests/test_gudid_client_retry.py` — 4 retry-behavior tests.

### PR #2 — Parallelization + cache (phases 4–5)

**Modify:**
- `harvester/src/orchestrator.py` — hoist module imports; add `DeviceValidationResult` dataclass, `_derive_outcome`, `_validate_one_device` worker, `_persist_result` helper; swap serial loop for `ThreadPoolExecutor(max_workers=8, thread_name_prefix="gudid")` with `as_completed` progress logging.
- `harvester/src/validators/gudid_client.py` — wire `gudid_cache.get/set` into `fetch_gudid_record`.
- `harvester/src/pipeline/runner.py` — add `--no-cache` flag.
- `harvester/src/pipeline/cli.py` — interactive cache yes/no prompt.
- `requirements.txt` — add `diskcache>=5.6`.
- `.gitignore` — add `.cache/`.
- `harvester/src/validators/CLAUDE.md` — document parallelization + cache.
- `CLAUDE.md` — one-line update acknowledging parallel validation.
- `harvester/src/tests/test_orchestrator.py` — add `TestCacheShortCircuitsHttp` integration-style test.

**Create:**
- `harvester/src/validators/gudid_cache.py` — new module (~60 LOC).
- `harvester/src/validators/tests/test_gudid_cache.py` — 5 cache tests.
- `harvester/src/validators/tests/test_orchestrator_parallel.py` — 3 parallelization tests.
- `Senior Project/Changelogs/Changelog - 2026-04-23.md` — new file (new dir).

---

# PR #1 — Resilience (phases 1–3)

## Task 1.0: Create PR #1 branch

**Files:** none (git operation only).

- [ ] **Step 1: Verify clean status on Jason**

Run: `git status --short`
Expected: may show unrelated modified files from prior work. **Do not commit those.** Confirm you're on branch `Jason`: `git rev-parse --abbrev-ref HEAD` → `Jason`.

- [ ] **Step 2: Create and switch to the resilience branch**

```bash
git checkout -b Jason-gudid-resilience
```

- [ ] **Step 3: Verify**

Run: `git rev-parse --abbrev-ref HEAD`
Expected: `Jason-gudid-resilience`

---

## Task 1.1: Add `errors` counter + try/except to `run_validation` (Phase 1 core)

**Files:**
- Modify: `harvester/src/orchestrator.py` (around lines 338–395)
- Test: `harvester/src/tests/test_orchestrator.py` (add new test class)

This is the real bug fix. One slow FDA call must not kill the whole batch.

- [ ] **Step 1: Write the failing test**

Append to `harvester/src/tests/test_orchestrator.py` (read the existing file first to see the patching pattern used by the other `run_validation` tests):

```python
class TestRunValidationErrorIsolation:
    """One flaky GUDID call must not kill the whole batch."""

    def test_timeout_on_one_device_does_not_kill_run(self, monkeypatch):
        import requests
        from orchestrator import run_validation

        devices = [
            {"_id": "dev1", "catalogNumber": "A1", "versionModelNumber": "M1", "brandName": "B1"},
            {"_id": "dev2", "catalogNumber": "A2", "versionModelNumber": "M2", "brandName": "B2"},
            {"_id": "dev3", "catalogNumber": "A3", "versionModelNumber": "M3", "brandName": "B3"},
        ]

        class FakeCollection:
            def __init__(self):
                self.docs = []
            def drop(self): self.docs.clear()
            def find(self, query=None): return iter(devices)
            def insert_one(self, doc): self.docs.append(doc)
            def update_one(self, *a, **kw): pass

        class FakeDb(dict):
            def __init__(self):
                self["devices"] = FakeCollection()
                self["validationResults"] = FakeCollection()
                self["verified_devices"] = FakeCollection()

        fake_db = FakeDb()
        monkeypatch.setattr("database.db_connection.get_db", lambda: fake_db)

        # Device 2 times out; devices 1 and 3 return a simple matched record.
        def fake_fetch(catalog_number=None, version_model_number=None):
            if catalog_number == "A2":
                raise requests.Timeout("simulated timeout")
            return (f"DI-{catalog_number}", {
                "brandName": f"B{catalog_number[-1]}",
                "versionModelNumber": version_model_number,
                "catalogNumber": catalog_number,
            })

        monkeypatch.setattr("validators.gudid_client.fetch_gudid_record", fake_fetch)
        monkeypatch.setattr(
            "validators.comparison_validator.compare_records",
            lambda h, g: ({}, {"match_percent": 1.0, "weighted_percent": 1.0,
                               "matched_fields": 1, "total_fields": 1,
                               "description_similarity": None}),
        )

        result = run_validation(overwrite=True)

        assert result["success"] is True
        assert result["total"] == 3
        assert result["errors"] == 1

        val_docs = fake_db["validationResults"].docs
        assert len(val_docs) == 3
        statuses = sorted(d["status"] for d in val_docs)
        assert "fetch_error" in statuses
        fetch_err_doc = next(d for d in val_docs if d["status"] == "fetch_error")
        assert fetch_err_doc["error_type"] == "Timeout"
        assert "simulated timeout" in fetch_err_doc["error_message"]
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `pytest harvester/src/tests/test_orchestrator.py::TestRunValidationErrorIsolation -v`
Expected: test fails. Either the run raises `Timeout`, or `result["errors"]` doesn't exist (`KeyError`).

- [ ] **Step 3: Add `errors` counter to the result dict**

Open `harvester/src/orchestrator.py`. Find the `result = {...}` block inside `run_validation` (around lines 338–349) and add the `errors` key **before** `"error": None`:

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
    "errors": 0,
    "error": None,
}
```

- [ ] **Step 4: Wrap `fetch_gudid_record` in try/except**

At the top of the same file, add `import requests` if not already present. Also add a module-level `logger` if one isn't there (check the top of the file — the orchestrator already uses `logging`). Reuse the existing logger.

Replace the existing call site (around lines 374–377) with:

```python
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
        "matched_fields": None,
        "total_fields": None,
        "match_percent": None,
        "weighted_percent": None,
        "description_similarity": None,
        "comparison_result": None,
        "gudid_record": None,
        "gudid_di": None,
        "created_at": now,
        "updated_at": now,
    })
    continue
```

The `datetime`/`timezone` import should already be at the top of the file from existing code. Confirm with `grep "^from datetime" harvester/src/orchestrator.py` — if missing, add it.

- [ ] **Step 5: Run the test — must pass now**

Run: `pytest harvester/src/tests/test_orchestrator.py::TestRunValidationErrorIsolation -v`
Expected: PASS.

- [ ] **Step 6: Run the full orchestrator test file — no regressions**

Run: `pytest harvester/src/tests/test_orchestrator.py -v`
Expected: all existing tests still pass, plus the new one.

- [ ] **Step 7: Commit**

```bash
git add harvester/src/orchestrator.py harvester/src/tests/test_orchestrator.py
git commit -m "fix(validator): isolate per-device GUDID fetch errors so one timeout doesn't kill batch

Adds a try/except requests.RequestException around fetch_gudid_record in
run_validation's per-device loop. On exception: log at WARNING, increment
a new result['errors'] counter, write a 'fetch_error' doc to validationResults,
and continue. Previously a single transient FDA timeout would propagate up
and fail the entire validation run.

Closes the 551-device run failure observed on 2026-04-23.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 1.2: Show `Errors: N` in CLI validation summary

**Files:**
- Modify: `harvester/src/pipeline/runner.py` (around lines 689–699)
- Modify: `harvester/src/pipeline/cli.py` (around lines 311–326)

- [ ] **Step 1: Update `runner.py` CLI output**

Find the validation summary block in `main()` (starts around line 689: `if val.get("success"):`). After the existing `print(f"  Not found:        {val['not_found']}")` line, add:

```python
        errors = val.get("errors", 0)
        if errors > 0:
            print(f"  \033[93mErrors:           {errors}\033[0m")
        else:
            print(f"  Errors:           {errors}")
```

`\033[93m` is the ANSI yellow code already used elsewhere in the file (same as the `Partial matches` line treatment).

- [ ] **Step 2: Update `cli.py` validation summary**

Find the corresponding block in `cli.py` (around lines 311–326, inside `run_mode`). After the existing `print(f"  Not found:        {val['not_found']}")` line, add:

```python
        errors = val.get("errors", 0)
        if errors > 0:
            print(f"  \033[93mErrors:           {errors}\033[0m")
        else:
            print(f"  Errors:           {errors}")
```

- [ ] **Step 3: Smoke-check imports — no new imports needed.**

Both files already use the ANSI escape sequences inline; no module change required.

- [ ] **Step 4: Run the full suite — no regressions expected**

Run: `pytest harvester/src/tests/ harvester/src/validators/tests/ -q`
Expected: all pass. (Output formatting is not unit-tested in either file.)

- [ ] **Step 5: Commit**

```bash
git add harvester/src/pipeline/runner.py harvester/src/pipeline/cli.py
git commit -m "feat(cli): surface new 'Errors' counter in validation summary output

Display errors count with yellow highlight when > 0, matching the
existing 'Partial matches' / 'Mismatches' formatting.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 1.3: Review dashboard handles `status == "fetch_error"`

**Files:**
- Modify: `app/routes/review.py`
- Modify: `app/templates/review.html` (path may differ slightly — check `app/templates/`)

This keeps the review dashboard from rendering an "unknown" badge for the new status value. Scope is minimal: a neutral banner and display of `error_type` / `error_message`.

- [ ] **Step 1: Locate the review page rendering logic**

Run: `grep -n "gudid_deactivated\|mode=\"info\"\|status ==" app/routes/review.py`

This finds the existing status-handling branches. `gudid_deactivated` is the closest precedent — it renders a warning banner and skips the side-by-side comparison.

- [ ] **Step 2: Add a `fetch_error` branch mirroring `gudid_deactivated`**

In `app/routes/review.py`, find the block that selects a render mode / template context based on `validation_result["status"]`. Add a branch for `"fetch_error"` that:

- Sets `mode = "info"` (same as `gudid_deactivated`, which disables the side-by-side table).
- Passes `error_type` and `error_message` from the validation result into the template context.
- Sets a banner message string (e.g. `"Could not verify — GUDID fetch failed"`).

Exact code will depend on the existing route shape; match whatever pattern `gudid_deactivated` already uses.

- [ ] **Step 3: Update the review template**

Open the review template (likely `app/templates/review.html`). Find the existing `{% if status == "gudid_deactivated" %}` block. Add a mirror block:

```jinja
{% elif status == "fetch_error" %}
  <div class="banner banner-neutral">
    <strong>Could not verify</strong> — GUDID lookup failed.
    {% if error_type %}<div class="muted">({{ error_type }}: {{ error_message }})</div>{% endif %}
  </div>
{% endif %}
```

Adjust CSS class names to match the existing deactivated banner's styling so the dashboard stays visually consistent.

- [ ] **Step 4: Smoke-check locally if possible**

If you can run the dashboard: `python run.py`, visit `http://localhost:8500/review/<id>` for any `fetch_error` record (manually insert one via `mongosh` if none exist yet). Confirm no crash and the banner renders.

If you can't run it, inspect the template rendering paths by reading the neighboring deactivated block — if your branch has the same structure, it will render correctly.

- [ ] **Step 5: Commit**

```bash
git add app/routes/review.py app/templates/review.html
git commit -m "feat(review): handle 'fetch_error' status with neutral banner

Mirrors the existing 'gudid_deactivated' rendering: info mode, no
side-by-side comparison, short banner showing error_type and
error_message so the reviewer knows validation couldn't run.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2.1: Lift timeout constant to 60 s (Phase 2)

**Files:**
- Modify: `harvester/src/validators/gudid_client.py` (lines 1, 19, 134, 178)

- [ ] **Step 1: Add the constant at the top of the module**

Open `harvester/src/validators/gudid_client.py`. Directly under the existing `import` lines and the `SEARCH_URL` / `LOOKUP_URL` constants (around line 6), add:

```python
REQUEST_TIMEOUT = 60  # seconds
```

- [ ] **Step 2: Replace all three timeout call sites**

Search for `timeout=15` in the file (three occurrences: lines 19, 134, 178). Replace each with `timeout=REQUEST_TIMEOUT`.

After edit, `grep -n "timeout=" harvester/src/validators/gudid_client.py` should show three `timeout=REQUEST_TIMEOUT` matches and zero `timeout=15` matches.

- [ ] **Step 3: Run the full validator test suite**

Run: `pytest harvester/src/validators/tests/ -q`
Expected: all pass (no test references `15`).

- [ ] **Step 4: Commit**

```bash
git add harvester/src/validators/gudid_client.py
git commit -m "refactor(gudid): lift HTTP timeout to REQUEST_TIMEOUT=60 constant

Bumps from 15s to 60s for resilience against transient FDA server
slowness. 15s was aggressive for a government API under load. All three
request sites (search_gudid_di, fetch_gudid_record, lookup_by_di) share
the new constant.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3.1: Add `tenacity` dependency (Phase 3 setup)

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add `tenacity` to requirements**

Open `requirements.txt`. Add `tenacity>=8.0` in alphabetical order (between `starlette` and `typing-inspection`, i.e. after `starlette==1.0.0`):

```
starlette==1.0.0
tenacity>=8.0
typing-inspection==0.4.2
```

- [ ] **Step 2: Install it locally**

Run: `pip install -r requirements.txt`
Expected: installs tenacity successfully.

- [ ] **Step 3: Confirm import works**

Run: `python -c "from tenacity import retry, stop_after_attempt, wait_exponential; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "build: add tenacity>=8.0 for GUDID retry policy

Required by the upcoming @retry decorators on search_gudid_di and
fetch_gudid_record.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3.2: Introduce `GudidRateLimitError` + typed 429 handling

**Files:**
- Modify: `harvester/src/validators/gudid_client.py`
- Create: `harvester/src/validators/tests/test_gudid_client_retry.py`

Add the typed exception **before** the retry decorators so the next task can reference it cleanly.

- [ ] **Step 1: Write the failing test**

Create `harvester/src/validators/tests/test_gudid_client_retry.py`:

```python
"""Retry-policy tests for gudid_client. No live network."""
import pytest
import requests
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    """Skip tenacity's exponential backoff in tests."""
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)


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
        _raise_for_status_with_rate_limit(resp)  # no exception

    def test_gudid_rate_limit_error_is_http_error(self):
        from validators.gudid_client import GudidRateLimitError
        assert issubclass(GudidRateLimitError, requests.HTTPError)
        assert issubclass(GudidRateLimitError, requests.RequestException)
```

- [ ] **Step 2: Run tests — should fail (class/function missing)**

Run: `pytest harvester/src/validators/tests/test_gudid_client_retry.py -v`
Expected: all 4 fail on `ImportError` (`GudidRateLimitError`, `_raise_for_status_with_rate_limit` not defined).

- [ ] **Step 3: Add `GudidRateLimitError` and `_raise_for_status_with_rate_limit` to `gudid_client.py`**

At the top of `harvester/src/validators/gudid_client.py`, immediately below the existing imports and the `REQUEST_TIMEOUT` constant:

```python
class GudidRateLimitError(requests.HTTPError):
    """Raised when GUDID returns HTTP 429 — retried by the retry policy."""
    pass


def _raise_for_status_with_rate_limit(response: requests.Response) -> None:
    """Translate HTTP 429 into GudidRateLimitError; defer other errors to requests."""
    if response.status_code == 429:
        raise GudidRateLimitError(response=response)
    response.raise_for_status()
```

- [ ] **Step 4: Replace both existing `response.raise_for_status()` calls**

In the same file, find both existing `response.raise_for_status()` calls (inside `search_gudid_di` around line 20, inside `fetch_gudid_record` around line 135). Replace each with:

```python
_raise_for_status_with_rate_limit(response)
```

Do **not** touch the `raise_for_status()` call inside `lookup_by_di` — that function has its own `try/except requests.RequestException` that returns `None` and is not in scope for the retry changes.

- [ ] **Step 5: Run the new tests — must pass**

Run: `pytest harvester/src/validators/tests/test_gudid_client_retry.py::TestRaiseForStatusWithRateLimit -v`
Expected: 4 pass.

- [ ] **Step 6: Run the rest of the validator suite — no regressions**

Run: `pytest harvester/src/validators/tests/ -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add harvester/src/validators/gudid_client.py harvester/src/validators/tests/test_gudid_client_retry.py
git commit -m "refactor(gudid): add GudidRateLimitError for typed 429 handling

Introduces a dedicated exception class so the upcoming retry policy
predicate can distinguish 429 (rate-limit, retryable) from other 4xx
(real errors, fail-fast). Replaces raise_for_status() in the two HTTP
call sites with _raise_for_status_with_rate_limit().

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3.3: Add `@retry` decorators to `search_gudid_di` and `fetch_gudid_record`

**Files:**
- Modify: `harvester/src/validators/gudid_client.py`
- Modify: `harvester/src/validators/tests/test_gudid_client_retry.py` (add more tests)

- [ ] **Step 1: Write the failing tests**

Append to `harvester/src/validators/tests/test_gudid_client_retry.py`:

```python
class TestFetchGudidRecordRetry:

    def test_timeout_then_success_succeeds_on_third_attempt(self, monkeypatch):
        from validators import gudid_client

        # Patch search_gudid_di to return a DI without HTTP (we're testing the lookup retry).
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
        resp_429.raise_for_status.side_effect = requests.HTTPError("429")
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
```

- [ ] **Step 2: Run tests — should fail**

Run: `pytest harvester/src/validators/tests/test_gudid_client_retry.py::TestFetchGudidRecordRetry -v`
Expected: tests fail — no retry yet, the first Timeout propagates immediately.

- [ ] **Step 3: Import tenacity in `gudid_client.py`**

At the top of `harvester/src/validators/gudid_client.py`, below the existing imports:

```python
import logging

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    wait_random,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Define `_RETRY_POLICY` and apply to both functions**

Below the `_raise_for_status_with_rate_limit` helper, add:

```python
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
```

Then decorate `search_gudid_di` (around line 9) and `fetch_gudid_record` (around line 120):

```python
@retry(**_RETRY_POLICY)
def search_gudid_di(catalog_number=None, version_model_number=None):
    ...

@retry(**_RETRY_POLICY)
def fetch_gudid_record(catalog_number=None, version_model_number=None):
    ...
```

Do not decorate `lookup_by_di` — it already swallows `RequestException`.

- [ ] **Step 5: Run the retry tests — must pass**

Run: `pytest harvester/src/validators/tests/test_gudid_client_retry.py -v`
Expected: all 8 tests pass (4 from Task 3.2 + 4 new).

- [ ] **Step 6: Run the full suite — no regressions**

Run: `pytest -q`
Expected: 530 pre-existing + 1 (Task 1.1) + 4 (Task 3.2) + 4 (this task) = 539 pass, 0 fail.

- [ ] **Step 7: Commit**

```bash
git add harvester/src/validators/gudid_client.py harvester/src/validators/tests/test_gudid_client_retry.py
git commit -m "feat(gudid): retry Timeout/ConnectionError/429 with exponential backoff

Decorates search_gudid_di and fetch_gudid_record with tenacity @retry:
- stop_after_attempt(3)
- wait_exponential(multiplier=1, min=1, max=4) + wait_random jitter
- retries only Timeout, ConnectionError, GudidRateLimitError
- reraise=True so callers see the original exception, not RetryError
- before_sleep_log emits structured retry lines at INFO

4xx other than 429 fail fast on first attempt — bad DIs surface
immediately instead of burning retries. Median cost per device under
normal conditions remains 1 attempt.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3.4: Update `CLAUDE.md`, push, and open PR #1

**Files:**
- Modify: `harvester/src/validators/CLAUDE.md`

- [ ] **Step 1: Document the resilience changes**

Open `harvester/src/validators/CLAUDE.md`. Under the `## GUDID API` section, append:

```markdown

## Error handling and retries

- **Timeout:** 60 s on all three request sites (`REQUEST_TIMEOUT` constant).
- **Retry policy:** 3 attempts, exponential backoff (1–4 s) + jitter. Retries only on
  `requests.Timeout`, `requests.ConnectionError`, and `GudidRateLimitError` (HTTP 429).
  All other 4xx fail fast.
- **Batch isolation:** `orchestrator.run_validation()` catches `requests.RequestException`
  around each `fetch_gudid_record` call. Failed devices are recorded with
  `status: "fetch_error"` in `validationResults` and counted in the new
  `result["errors"]` field. One device's failure never kills the batch.
- **`fetch_error` documents** carry `error_type` (exception class name) and
  `error_message` (first 500 chars). Dashboard shows a neutral "Could not verify"
  banner, no side-by-side comparison.
```

- [ ] **Step 2: Run the full suite one final time**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 3: Push and open PR #1**

```bash
git add harvester/src/validators/CLAUDE.md
git commit -m "docs: document GUDID 60s timeout, retry policy, fetch_error status

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

git push -u origin Jason-gudid-resilience
```

Open the PR using `gh`:

```bash
gh pr create --base Jason --title "fix(gudid): per-device error isolation + timeout bump + retry" --body "$(cat <<'EOF'
## Summary
- Wraps per-device `fetch_gudid_record` in `try/except requests.RequestException` so one transient FDA timeout no longer kills an entire batch validation run (fixes the 551-device failure seen 2026-04-23).
- Bumps the HTTP timeout from 15 s to 60 s via a new `REQUEST_TIMEOUT` constant shared by all three request sites in `gudid_client.py`.
- Adds a `tenacity` retry policy — 3 attempts, exponential backoff with jitter — that retries only `Timeout`, `ConnectionError`, and `GudidRateLimitError` (a new typed exception for HTTP 429). 4xx other than 429 fail fast.
- Surfaces the new `result["errors"]` count in CLI output (yellow when > 0) and renders a neutral "Could not verify" banner on the review dashboard for `status: "fetch_error"` docs.

## Test plan
- [x] `pytest harvester/src/validators/tests/ -v` — all pass
- [x] `pytest harvester/src/tests/test_orchestrator.py -v` — new `TestRunValidationErrorIsolation` passes, existing tests unchanged
- [x] `pytest -q` — full suite green
- [ ] Manual smoke: run interactive CLI, confirm validation summary prints `Errors: 0` line
- [ ] Manual smoke: insert a `fetch_error` doc via `mongosh`, visit `/review/<id>`, confirm neutral banner

Spec: `docs/superpowers/specs/2026-04-23-gudid-validation-resilience-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Record the PR URL**

Save the PR URL returned by `gh pr create` — needed for the review handoff and for the changelog in PR #2.

---

# PR #2 — Parallelization + cache (phases 4–5)

## Task 4.0: Rebase onto merged `Jason` and create PR #2 branch

**Assumes PR #1 has been reviewed, approved, and merged.** Do not start Task 4.1 until that's true.

- [ ] **Step 1: Switch to Jason, pull merged PR #1**

```bash
git checkout Jason
git pull origin Jason
```

Verify PR #1 changes are present:
```bash
grep -n "REQUEST_TIMEOUT" harvester/src/validators/gudid_client.py
```
Expected: match.

- [ ] **Step 2: Create PR #2 branch off the post-merge Jason**

```bash
git checkout -b Jason-gudid-parallel
```

- [ ] **Step 3: Verify**

Run: `git rev-parse --abbrev-ref HEAD`
Expected: `Jason-gudid-parallel`

---

## Task 4.1: Hoist module-level imports in `orchestrator.py` (Phase 4 prep)

**Files:**
- Modify: `harvester/src/orchestrator.py`

The existing `run_validation` does lazy imports of `fetch_gudid_record` and `compare_records` inside the function. Phase 4 will call them from a module-level worker function, so promote the imports.

- [ ] **Step 1: Inspect current imports**

Run: `grep -n "^from\|^import" harvester/src/orchestrator.py | head -30`

Confirm the current top-of-file imports. Note the lazy imports inside `run_validation` (search for `from validators.gudid_client import` and `from validators.comparison_validator import`).

- [ ] **Step 2: Move the lazy imports to module scope**

At the top of the file, below the existing imports, add:

```python
from validators.gudid_client import fetch_gudid_record
from validators.comparison_validator import compare_records
```

Delete the corresponding lazy imports from inside `run_validation` (the lines that say `from validators.gudid_client import fetch_gudid_record` and `from validators.comparison_validator import compare_records` inside the function body).

Keep the lazy `from database.db_connection import get_db` — that one is fine where it is for now (out of scope).

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add harvester/src/orchestrator.py
git commit -m "refactor(orchestrator): hoist fetch_gudid_record + compare_records imports

Promotes the two lazy imports inside run_validation to module scope in
preparation for extracting a module-level worker function that uses them.
No behavior change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4.2: Extract `_derive_outcome` helper

**Files:**
- Modify: `harvester/src/orchestrator.py`

Pure refactor: the existing matched/partial/mismatch status derivation becomes a named helper so the worker function can reuse it.

- [ ] **Step 1: Find the existing status logic**

Inside `run_validation`, find the block that computes `status = "matched" if ... elif ... else "mismatch"` (roughly around the comparison result processing, between the `compare_records()` call and the `validation_col.insert_one` for the comparison path).

- [ ] **Step 2: Add module-level helper**

Add near the other module-level helpers (below `MERGE_FIELDS`, before the `_merge_gudid_into_device` function):

```python
def _derive_outcome(summary: dict) -> str:
    """Translate compare_records summary into the validationResults status string."""
    mp = summary.get("match_percent", 0.0)
    if mp >= 1.0:
        return "matched"
    if mp > 0:
        return "partial_match"
    return "mismatch"
```

- [ ] **Step 3: Replace the inline status logic with the helper**

In `run_validation`, replace the inline `status = ...` block with:

```python
status = _derive_outcome(summary)
```

where `summary` is the second return value of `compare_records()`.

- [ ] **Step 4: Run the full suite — no behavior change**

Run: `pytest -q`
Expected: all pass (including scoring tests).

- [ ] **Step 5: Commit**

```bash
git add harvester/src/orchestrator.py
git commit -m "refactor(orchestrator): extract _derive_outcome helper

Pure refactor. The matched/partial_match/mismatch status derivation is
hoisted into a named module-level function so the upcoming worker
function can share the same logic.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4.3: Add `DeviceValidationResult` dataclass + `_validate_one_device` worker (still called serially)

**Files:**
- Modify: `harvester/src/orchestrator.py`

Introduce the worker function. Call it from the existing serial loop one device at a time — no parallelization yet. This keeps the diff reviewable and tests green.

- [ ] **Step 1: Add imports at the top of the file**

Add to the existing imports at the top of `orchestrator.py`:

```python
from dataclasses import dataclass
from typing import Literal, Optional
```

(If `requests` isn't already imported at module scope, add `import requests` too.)

- [ ] **Step 2: Add the dataclass and worker function**

Below the `_derive_outcome` helper, add:

```python
@dataclass
class DeviceValidationResult:
    device: dict
    di: Optional[str]
    gudid_record: Optional[dict]
    outcome: Literal[
        "matched", "partial_match", "mismatch",
        "not_found", "gudid_deactivated", "fetch_error",
    ]
    comparison: Optional[dict]
    summary: Optional[dict]
    error_type: Optional[str]
    error_message: Optional[str]


def _validate_one_device(device: dict) -> DeviceValidationResult:
    """Pure network + CPU work for one device. No MongoDB writes.

    Safe to run in a thread pool worker.
    """
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
            outcome="fetch_error",
            comparison=None, summary=None,
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
```

- [ ] **Step 3: Don't wire it up yet — just leave it defined**

The existing serial loop keeps working unchanged. This task only adds the new symbols. Task 4.4 will plug them into a `_persist_result` function; Task 4.5 will wire the whole pipeline.

- [ ] **Step 4: Run the full suite — confirm no behavior change**

Run: `pytest -q`
Expected: all pass (new code unreferenced).

- [ ] **Step 5: Commit**

```bash
git add harvester/src/orchestrator.py
git commit -m "refactor(orchestrator): add DeviceValidationResult + _validate_one_device worker

Introduces the pure worker function (network + CPU, no DB writes) and
its return dataclass. Not yet called; tasks 4.4 and 4.5 will wire it
into the main run_validation flow. No behavior change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4.4: Extract `_persist_result` helper

**Files:**
- Modify: `harvester/src/orchestrator.py`

Extract the six DB-write arms (fetch_error / not_found / gudid_deactivated / matched / partial_match / mismatch) from the serial loop into a single helper that takes a `DeviceValidationResult` and writes to MongoDB.

- [ ] **Step 1: Add the helper below `_validate_one_device`**

```python
def _persist_result(
    res: DeviceValidationResult,
    result: dict,
    db,
    validation_col,
    verified_col,
) -> None:
    """Write one DeviceValidationResult to MongoDB and update counters.

    Must be called from the main thread only (pymongo writes are serialized here).
    """
    now = datetime.now(timezone.utc)
    device = res.device

    if res.outcome == "fetch_error":
        result["errors"] += 1
        validation_col.insert_one({
            "device_id": device.get("_id"),
            "brandName": device.get("brandName"),
            "status": "fetch_error",
            "error_type": res.error_type,
            "error_message": res.error_message,
            "matched_fields": None, "total_fields": None,
            "match_percent": None, "weighted_percent": None,
            "description_similarity": None,
            "comparison_result": None,
            "gudid_record": None,
            "gudid_di": None,
            "created_at": now, "updated_at": now,
        })
        return

    if res.outcome == "not_found":
        # Preserve legacy behavior: write as "mismatch", increment "mismatches".
        # (The pre-existing "gudid-not-found-as-mismatch" design from 2026-04-20.)
        result["mismatches"] += 1
        validation_col.insert_one({
            "device_id": device.get("_id"),
            "brandName": device.get("brandName"),
            "status": "mismatch",
            "matched_fields": 0, "total_fields": 0,
            "match_percent": 0.0, "weighted_percent": 0.0,
            "comparison_result": None,
            "gudid_record": None,
            "gudid_di": res.di,
            "created_at": now, "updated_at": now,
        })
        return

    if res.outcome == "gudid_deactivated":
        result["gudid_deactivated"] += 1
        validation_col.insert_one({
            "device_id": device.get("_id"),
            "brandName": device.get("brandName"),
            "status": "gudid_deactivated",
            "matched_fields": None, "total_fields": None,
            "match_percent": None, "weighted_percent": None,
            "description_similarity": None,
            "comparison_result": None,
            "gudid_record": res.gudid_record,
            "gudid_di": res.di,
            "gudid_record_status": "Deactivated",
            "created_at": now, "updated_at": now,
        })
        return

    # Compared path: matched / partial_match / mismatch
    summary = res.summary
    status = res.outcome  # already one of the three

    if status == "matched":
        result["full_matches"] += 1
    elif status == "partial_match":
        result["partial_matches"] += 1
    else:
        result["mismatches"] += 1

    # Harvest-gap diagnostics. These come verbatim from the current loop
    # (orchestrator.py:437–451) — copy them exactly, including the existing
    # `_is_null_list(...)` helper call and the existing log line. Do not redesign.
    if res.gudid_record.get("productCodes") and _is_null_list(device.get("productCodes")):
        logger.info(
            "[harvest-gap] device %s (%s): GUDID productCodes=%r, harvested=null",
            device.get("_id"), device.get("catalogNumber"),
            res.gudid_record["productCodes"],
        )
        result["harvest_gap_product_codes"] += 1
    if res.gudid_record.get("premarketSubmissions") and _is_null_list(device.get("premarketSubmissions")):
        logger.info(
            "[harvest-gap] device %s (%s): GUDID premarketSubmissions=%r, harvested=null",
            device.get("_id"), device.get("catalogNumber"),
            res.gudid_record["premarketSubmissions"],
        )
        result["harvest_gap_premarket"] += 1

    validation_col.insert_one({
        "device_id": device.get("_id"),
        "brandName": device.get("brandName"),
        "status": status,
        "matched_fields": summary.get("matched_fields"),
        "total_fields": summary.get("total_fields"),
        "match_percent": summary.get("match_percent"),
        "weighted_percent": summary.get("weighted_percent"),
        "description_similarity": summary.get("description_similarity"),
        "comparison_result": res.comparison,
        "gudid_record": res.gudid_record,
        "gudid_di": res.di,
        "created_at": now, "updated_at": now,
    })

    if status == "matched":
        # verified_devices upsert — preserve existing shape exactly.
        verified_doc = {k: v for k, v in device.items() if k != "_id"}
        for field in MERGE_FIELDS:
            if verified_doc.get(field) is None and res.gudid_record.get(field) is not None:
                verified_doc[field] = res.gudid_record[field]
        verified_doc["gudid_di"] = res.di
        verified_doc["verified_at"] = now
        verified_doc["source_device_id"] = device.get("_id")
        verified_col.update_one(
            {
                "versionModelNumber": device.get("versionModelNumber"),
                "catalogNumber": device.get("catalogNumber"),
            },
            {"$set": verified_doc},
            upsert=True,
        )

    # Fill null device fields from GUDID (always runs on the compared path).
    _merge_gudid_into_device(db, device, res.gudid_record)
```

**Important — existing-behavior parity.** Before editing, read the existing `run_validation` loop carefully (lines ~373–490) and make sure every field written to `validationResults`, every counter increment, every `verified_devices` upsert, and the final `_merge_gudid_into_device` call match what's there today. The `harvest_gap_*` counters in particular need the same condition logic — if the current code uses a different check, copy it verbatim rather than relying on the example shape above.

Signatures are locked: `_persist_result` receives `db` (the full database handle), `validation_col`, and `verified_col`. Inside it, `_merge_gudid_into_device(db, device, res.gudid_record)` matches the existing helper's `(db, device, gudid_record)` signature at `orchestrator.py:55`.

- [ ] **Step 2: Replace the serial loop body with worker + persist calls**

Inside `run_validation`, the existing `for device in devices:` loop becomes:

```python
for device in devices:
    res = _validate_one_device(device)
    _persist_result(res, result, db, validation_col, verified_col)
```

All the old inline logic (try/except around fetch, status derivation, all three insert paths, verified_devices upsert, merge call) moves into `_validate_one_device` + `_persist_result`. Delete the old inline code.

- [ ] **Step 3: Run the full test suite — all should still pass**

Run: `pytest -q`
Expected: all pass. The refactor is pure; behavior is unchanged.

If any test fails, the most likely cause is a field or counter drift between the old inline code and your `_persist_result`. Diff the before/after by running `git diff HEAD~1 harvester/src/orchestrator.py` and eyeball the validationResults doc shapes side by side.

- [ ] **Step 4: Commit**

```bash
git add harvester/src/orchestrator.py
git commit -m "refactor(orchestrator): extract _persist_result helper

Pulls the six DB-write arms (fetch_error / not_found / gudid_deactivated /
matched / partial_match / mismatch) out of the serial loop into a single
helper that takes a DeviceValidationResult and writes to MongoDB. Serial
loop now calls _validate_one_device() followed by _persist_result().

No behavior change. Sets up the ThreadPoolExecutor swap in the next task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4.5: Swap serial loop for `ThreadPoolExecutor`

**Files:**
- Modify: `harvester/src/orchestrator.py`
- Create: `harvester/src/validators/tests/test_orchestrator_parallel.py`

This is the Phase 4 payload. Workers run concurrently; main thread aggregates and writes serially.

- [ ] **Step 1: Write the failing tests**

Create `harvester/src/validators/tests/test_orchestrator_parallel.py`:

```python
"""ThreadPoolExecutor parallelization tests. No live network."""
import time
import requests
import pytest


def _build_fake_db(devices):
    class FakeCollection:
        def __init__(self): self.docs = []
        def drop(self): self.docs.clear()
        def find(self, *a, **kw): return iter(devices)
        def insert_one(self, doc): self.docs.append(doc)
        def update_one(self, *a, **kw): pass
    class FakeDb(dict):
        def __init__(self):
            self["devices"] = FakeCollection()
            self["validationResults"] = FakeCollection()
            self["verified_devices"] = FakeCollection()
    return FakeDb()


class TestRunValidationParallel:

    def test_runs_workers_concurrently(self, monkeypatch):
        from orchestrator import run_validation

        devices = [{"_id": f"d{i}", "catalogNumber": f"A{i}",
                    "versionModelNumber": f"M{i}", "brandName": f"B{i}"}
                   for i in range(4)]
        fake_db = _build_fake_db(devices)
        monkeypatch.setattr("database.db_connection.get_db", lambda: fake_db)

        per_call_sleep = 0.2

        def slow_fetch(catalog_number=None, version_model_number=None):
            time.sleep(per_call_sleep)
            return (f"DI-{catalog_number}", {
                "brandName": f"B{catalog_number[-1]}",
                "versionModelNumber": version_model_number,
                "catalogNumber": catalog_number,
            })

        monkeypatch.setattr("orchestrator.fetch_gudid_record", slow_fetch)
        monkeypatch.setattr(
            "orchestrator.compare_records",
            lambda h, g: ({}, {"match_percent": 1.0, "weighted_percent": 1.0,
                               "matched_fields": 1, "total_fields": 1,
                               "description_similarity": None}),
        )

        start = time.monotonic()
        result = run_validation(overwrite=True)
        elapsed = time.monotonic() - start

        assert result["success"] is True
        assert result["total"] == 4
        # Serial would be 4 * 0.2 = 0.8s. With 8 workers, expect ~0.2s + overhead.
        assert elapsed < 0.6, f"elapsed={elapsed:.2f}s — workers not concurrent"

    def test_all_results_persisted(self, monkeypatch):
        from orchestrator import run_validation

        devices = [{"_id": f"d{i}", "catalogNumber": f"A{i}",
                    "versionModelNumber": f"M{i}", "brandName": f"B{i}"}
                   for i in range(4)]
        fake_db = _build_fake_db(devices)
        monkeypatch.setattr("database.db_connection.get_db", lambda: fake_db)

        monkeypatch.setattr(
            "orchestrator.fetch_gudid_record",
            lambda catalog_number=None, version_model_number=None: (
                f"DI-{catalog_number}", {
                    "brandName": f"B{catalog_number[-1]}",
                    "versionModelNumber": version_model_number,
                    "catalogNumber": catalog_number,
                }
            ),
        )
        monkeypatch.setattr(
            "orchestrator.compare_records",
            lambda h, g: ({}, {"match_percent": 1.0, "weighted_percent": 1.0,
                               "matched_fields": 1, "total_fields": 1,
                               "description_similarity": None}),
        )

        result = run_validation(overwrite=True)

        assert len(fake_db["validationResults"].docs) == 4
        assert result["full_matches"] == 4

    def test_worker_exception_isolation(self, monkeypatch):
        from orchestrator import run_validation

        devices = [{"_id": f"d{i}", "catalogNumber": f"A{i}",
                    "versionModelNumber": f"M{i}", "brandName": f"B{i}"}
                   for i in range(4)]
        fake_db = _build_fake_db(devices)
        monkeypatch.setattr("database.db_connection.get_db", lambda: fake_db)

        def fetch(catalog_number=None, version_model_number=None):
            if catalog_number == "A2":
                raise requests.Timeout("nope")
            return (f"DI-{catalog_number}", {
                "brandName": f"B{catalog_number[-1]}",
                "versionModelNumber": version_model_number,
                "catalogNumber": catalog_number,
            })

        monkeypatch.setattr("orchestrator.fetch_gudid_record", fetch)
        monkeypatch.setattr(
            "orchestrator.compare_records",
            lambda h, g: ({}, {"match_percent": 1.0, "weighted_percent": 1.0,
                               "matched_fields": 1, "total_fields": 1,
                               "description_similarity": None}),
        )

        result = run_validation(overwrite=True)

        assert result["success"] is True
        assert result["total"] == 4
        assert result["errors"] == 1
        assert result["full_matches"] == 3
        statuses = sorted(d["status"] for d in fake_db["validationResults"].docs)
        assert statuses.count("fetch_error") == 1
        assert statuses.count("matched") == 3
```

- [ ] **Step 2: Run — tests should fail (no concurrency yet)**

Run: `pytest harvester/src/validators/tests/test_orchestrator_parallel.py -v`
Expected: `test_runs_workers_concurrently` fails (`elapsed >= 0.8s`). The other two tests may pass or fail depending on the current serial loop — they will all pass once parallelization is in.

- [ ] **Step 3: Add the imports**

At the top of `harvester/src/orchestrator.py`, add:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
```

- [ ] **Step 4: Replace the serial loop with ThreadPoolExecutor**

Inside `run_validation`, the loop from Task 4.4:

```python
for device in devices:
    res = _validate_one_device(device)
    _persist_result(res, result, db, validation_col, verified_col)
```

Becomes:

```python
results: list[DeviceValidationResult] = []
completed = 0
total = len(devices)

with ThreadPoolExecutor(max_workers=8, thread_name_prefix="gudid") as pool:
    futures = [pool.submit(_validate_one_device, d) for d in devices]
    for fut in as_completed(futures):
        res = fut.result()
        completed += 1
        results.append(res)
        if completed % 25 == 0 or completed == total:
            logger.info("[gudid] %d/%d devices validated", completed, total)

for res in results:
    _persist_result(res, result, db, validation_col, verified_col)
```

All DB writes stay serial on the main thread. The worker function is side-effect-free wrt MongoDB.

- [ ] **Step 5: Run the parallel tests — must pass**

Run: `pytest harvester/src/validators/tests/test_orchestrator_parallel.py -v`
Expected: all 3 pass.

- [ ] **Step 6: Run the full test suite — no regressions**

Run: `pytest -q`
Expected: all pass (539 from PR #1 + 3 new = 542).

- [ ] **Step 7: Commit**

```bash
git add harvester/src/orchestrator.py harvester/src/validators/tests/test_orchestrator_parallel.py
git commit -m "perf(validator): parallelize per-device GUDID validation with ThreadPoolExecutor

Swaps the serial for-loop in run_validation for ThreadPoolExecutor
(max_workers=8, thread_name_prefix='gudid'). Workers do network + CPU
only; main thread aggregates counters and writes MongoDB serially.

- max_workers=8 stays well under NLM's 20 rps ToS cap
  (8 workers * median 1.5s/call ≈ 5 rps steady-state)
- as_completed() drives progress logging every 25 completions
- Worker exceptions isolated via try/except in _validate_one_device
- No counter locks needed; no concurrent MongoDB writes

Expected wall-clock: ~17 min → ~3 min for 551 devices.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5.1: Add `diskcache` dependency + `.gitignore`

**Files:**
- Modify: `requirements.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Add diskcache to requirements**

Open `requirements.txt`. Insert `diskcache>=5.6` in alphabetical order (after `dotenv==0.9.9`):

```
dotenv==0.9.9
diskcache>=5.6
et_xmlfile==2.0.0
```

- [ ] **Step 2: Install locally**

Run: `pip install -r requirements.txt`
Expected: installs diskcache.

Verify: `python -c "from diskcache import Cache; print('ok')"` → `ok`

- [ ] **Step 3: Update `.gitignore`**

Open `.gitignore`. Add `.cache/` after the existing `*.pyc` line:

```
.env
harvester/src/web-scraper/out_html/*.html
!.env.example
venv/
__pycache__/
*.pyc
.cache/
harvester/output/*.json
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt .gitignore
git commit -m "build: add diskcache>=5.6 dependency; ignore .cache/

diskcache backs the upcoming local GUDID lookup cache (24h TTL, SQLite
store at .cache/gudid/). The .gitignore entry prevents committing the
generated cache files.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5.2: Create `gudid_cache.py` module with unit tests

**Files:**
- Create: `harvester/src/validators/gudid_cache.py`
- Create: `harvester/src/validators/tests/test_gudid_cache.py`

- [ ] **Step 1: Write the failing tests**

Create `harvester/src/validators/tests/test_gudid_cache.py`:

```python
"""Unit tests for gudid_cache module."""
import pytest
from unittest.mock import patch


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    """Point gudid_cache at a temp directory and reset enabled state per test."""
    from validators import gudid_cache
    monkeypatch.setattr(gudid_cache, "_CACHE_ROOT", tmp_path / "gudid")
    monkeypatch.setattr(gudid_cache, "_cache", None)
    gudid_cache.set_enabled(True)
    yield gudid_cache
    # diskcache opens a sqlite file; close it to release the handle on Windows.
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
        # Store a cached miss (no DI found, or found but empty device)
        tmp_cache.set("CAT-X", "MOD-X", None, None)
        result = tmp_cache.get("CAT-X", "MOD-X")
        assert result == (None, None)

    def test_set_enabled_false_bypasses(self, tmp_cache):
        tmp_cache.set("CAT-X", "MOD-X", "DI-123", {"brandName": "X"})
        tmp_cache.set_enabled(False)
        assert tmp_cache.get("CAT-X", "MOD-X") is None
        # Disabled set is a no-op (doesn't raise)
        tmp_cache.set("CAT-Y", "MOD-Y", "DI-Y", {"brandName": "Y"})
        tmp_cache.set_enabled(True)
        # CAT-Y was never written
        assert tmp_cache.get("CAT-Y", "MOD-Y") is None

    def test_cache_directory_created_on_first_use(self, tmp_cache, tmp_path):
        assert not (tmp_path / "gudid").exists()
        tmp_cache.set("CAT-X", "MOD-X", "DI-123", {"brandName": "X"})
        assert (tmp_path / "gudid").exists()
```

- [ ] **Step 2: Run — should fail (module doesn't exist)**

Run: `pytest harvester/src/validators/tests/test_gudid_cache.py -v`
Expected: `ImportError: validators.gudid_cache`.

- [ ] **Step 3: Create the cache module**

Create `harvester/src/validators/gudid_cache.py`:

```python
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


def _key(catalog_number: str | None, version_model_number: str | None) -> str:
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
```

- [ ] **Step 4: Run the cache tests — must pass**

Run: `pytest harvester/src/validators/tests/test_gudid_cache.py -v`
Expected: 5 pass.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all pass (542 + 5 = 547).

- [ ] **Step 6: Commit**

```bash
git add harvester/src/validators/gudid_cache.py harvester/src/validators/tests/test_gudid_cache.py
git commit -m "feat(gudid): add diskcache-backed local cache module (24h TTL)

Stores (di, record) tuples keyed on sha1(catalog_number|version_model_number)
at .cache/gudid/. Negative results are cached via a sentinel so repeat runs
do zero HTTP. Module-level enable/disable flag supports --no-cache.

Not yet wired into fetch_gudid_record — that's Task 5.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5.3: Wire cache into `fetch_gudid_record`

**Files:**
- Modify: `harvester/src/validators/gudid_client.py`

- [ ] **Step 1: Add the import**

At the top of `harvester/src/validators/gudid_client.py`:

```python
from validators import gudid_cache
```

- [ ] **Step 2: Add cache read/write in `fetch_gudid_record`**

Modify the body of `fetch_gudid_record`. Read the current implementation first — after Task 3.3 it looks like this (key points only):

```python
@retry(**_RETRY_POLICY)
def fetch_gudid_record(catalog_number=None, version_model_number=None):
    di = search_gudid_di(
        catalog_number=catalog_number,
        version_model_number=version_model_number,
    )
    if not di:
        return None, None

    response = requests.get(LOOKUP_URL, params={"di": di}, timeout=REQUEST_TIMEOUT)
    _raise_for_status_with_rate_limit(response)
    data = response.json()
    device = data.get("gudid", {}).get("device", {})
    if not device:
        return di, None

    # ... build record dict ...
    return di, record
```

Modify it to check the cache first and write to it before every return path:

```python
@retry(**_RETRY_POLICY)
def fetch_gudid_record(catalog_number=None, version_model_number=None):
    cached = gudid_cache.get(catalog_number, version_model_number)
    if cached is not None:
        return cached

    di = search_gudid_di(
        catalog_number=catalog_number,
        version_model_number=version_model_number,
    )
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

    # ... existing record-building code, unchanged ...
    record = { ... }
    gudid_cache.set(catalog_number, version_model_number, di, record)
    return di, record
```

The exact `record = {...}` block is whatever's in the file today; leave it unchanged and add the two `gudid_cache.set(...)` calls at each return statement.

**Important:** do not cache on the exception path. If `requests.get` raises `Timeout`/`ConnectionError`/`429` (which tenacity will retry), and if all retries fail, the exception reraises. We don't want to cache "this failed once" — a later call might succeed.

- [ ] **Step 3: Update retry tests for cache interaction**

The retry tests from Task 3.3 will still pass because they mock `search_gudid_di` and `requests.get`, but they may leak cache entries between tests now that the cache is wired in. Add an autouse fixture to `test_gudid_client_retry.py`:

```python
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
```

Add it at the top of the test file, below the existing `no_retry_sleep` autouse fixture.

- [ ] **Step 4: Run retry tests — must still pass**

Run: `pytest harvester/src/validators/tests/test_gudid_client_retry.py -v`
Expected: 8 pass.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add harvester/src/validators/gudid_client.py harvester/src/validators/tests/test_gudid_client_retry.py
git commit -m "feat(gudid): cache fetch_gudid_record results (24h TTL, positive and negative)

Reads the cache as the first step of fetch_gudid_record; writes on every
successful return path including negative results (no DI found, or DI
found but empty device). Failed calls (Timeout/ConnectionError/429) are
not cached — tenacity retries, and if all retries fail the exception
propagates untouched.

Cache is per-run-directory (.cache/gudid/) and survives across runs.
Repeat validation on the same dataset within 24h does zero HTTP.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5.4: Add `--no-cache` flag to `runner.py`

**Files:**
- Modify: `harvester/src/pipeline/runner.py`

- [ ] **Step 1: Add the argparse flag**

Find the `parser.add_argument(...)` block in `main()` (around lines 616–624). Add:

```python
parser.add_argument(
    "--no-cache",
    action="store_true",
    dest="no_cache",
    help="Bypass the GUDID disk cache for this run.",
)
```

- [ ] **Step 2: Toggle the cache before running validation**

At the top of `main()`, below the existing imports (check if any lazy imports exist — `runner.py` typically imports at module scope), add:

```python
from validators import gudid_cache
```

Then, just before the `if do_validate:` block that calls `run_gudid_validation(...)`, add:

```python
gudid_cache.set_enabled(not args.no_cache)
```

- [ ] **Step 3: Smoke-test the flag**

Run: `python harvester/src/pipeline/runner.py --help`
Expected: `--no-cache` appears in the help output.

- [ ] **Step 4: Run the full suite — no regressions**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add harvester/src/pipeline/runner.py
git commit -m "feat(runner): add --no-cache flag to bypass GUDID disk cache

Sets gudid_cache.set_enabled(False) before run_gudid_validation when the
flag is present. Useful for diagnosing cache staleness or forcing a fresh
FDA round-trip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5.5: Add interactive cache prompt to `cli.py`

**Files:**
- Modify: `harvester/src/pipeline/cli.py`

- [ ] **Step 1: Import and prompt**

Add to the top of `harvester/src/pipeline/cli.py` (near the existing imports from `pipeline.runner`):

```python
from validators import gudid_cache
```

- [ ] **Step 2: Prompt in `collect_options`**

Find `collect_options(mode: dict) -> dict` (around line 153). After the existing `options["verbose"] = prompt_yes_no(...)` line, add:

```python
    if mode["validate"]:
        options["use_cache"] = prompt_yes_no("Use GUDID disk cache?", default=True)
    else:
        options["use_cache"] = True
```

- [ ] **Step 3: Apply the flag before validation runs**

Find `run_mode(mode, options)` (around line 220). Before the validation step (the `if mode["validate"]:` block around line 282), add:

```python
    gudid_cache.set_enabled(options.get("use_cache", True))
```

- [ ] **Step 4: Run full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add harvester/src/pipeline/cli.py
git commit -m "feat(cli): interactive prompt for GUDID cache (Y/n, default yes)

Only prompts when validate mode is selected. Uses the existing
prompt_yes_no helper; default is 'yes' (cache enabled). Applies the
setting via gudid_cache.set_enabled() before run_gudid_validation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5.6: Integration-style test — second run does zero HTTP

**Files:**
- Modify: `harvester/src/tests/test_orchestrator.py`

- [ ] **Step 1: Append the test**

Append to `harvester/src/tests/test_orchestrator.py`:

```python
class TestCacheShortCircuitsHttp:
    """End-to-end: second run_validation pass hits the cache, not the network."""

    def test_second_pass_skips_requests_get(self, monkeypatch, tmp_path):
        import requests
        from orchestrator import run_validation
        from validators import gudid_cache

        # Isolate cache to tmp_path for the test
        monkeypatch.setattr(gudid_cache, "_CACHE_ROOT", tmp_path / "gudid")
        monkeypatch.setattr(gudid_cache, "_cache", None)
        gudid_cache.set_enabled(True)

        devices = [
            {"_id": "d1", "catalogNumber": "A1", "versionModelNumber": "M1", "brandName": "B1"},
            {"_id": "d2", "catalogNumber": "A2", "versionModelNumber": "M2", "brandName": "B2"},
            {"_id": "d3", "catalogNumber": "A3", "versionModelNumber": "M3", "brandName": "B3"},
        ]

        class FakeCollection:
            def __init__(self): self.docs = []
            def drop(self): self.docs.clear()
            def find(self, *a, **kw): return iter(devices)
            def insert_one(self, doc): self.docs.append(doc)
            def update_one(self, *a, **kw): pass
        class FakeDb(dict):
            def __init__(self):
                self["devices"] = FakeCollection()
                self["validationResults"] = FakeCollection()
                self["verified_devices"] = FakeCollection()

        fake_db = FakeDb()
        monkeypatch.setattr("database.db_connection.get_db", lambda: fake_db)

        # Mock the search + lookup paths at the HTTP boundary so we can count calls.
        # Use a minimal fake HTML that search_gudid_di can parse into a DI.
        from unittest.mock import MagicMock

        search_html = (
            '<html><body>'
            '<a href="/devices/00123456789012">result</a>'
            '</body></html>'
        )
        lookup_json = {"gudid": {"device": {"brandName": "X",
                                            "versionModelNumber": "M1",
                                            "catalogNumber": "A1"}}}

        def fake_get(url, *args, **kwargs):
            resp = MagicMock(spec=requests.Response)
            resp.status_code = 200
            if "search" in url:
                resp.text = search_html
            else:
                resp.json.return_value = lookup_json
            resp.raise_for_status.return_value = None
            return resp

        monkeypatch.setattr("validators.gudid_client.requests.get", fake_get)
        monkeypatch.setattr(
            "orchestrator.compare_records",
            lambda h, g: ({}, {"match_percent": 1.0, "weighted_percent": 1.0,
                               "matched_fields": 1, "total_fields": 1,
                               "description_similarity": None}),
        )

        # Count calls
        call_count = {"n": 0}
        real_fake_get = fake_get
        def counting_get(*args, **kwargs):
            call_count["n"] += 1
            return real_fake_get(*args, **kwargs)
        monkeypatch.setattr("validators.gudid_client.requests.get", counting_get)

        # First pass — expect non-zero HTTP calls
        result1 = run_validation(overwrite=True)
        assert result1["success"] is True
        first_pass_calls = call_count["n"]
        assert first_pass_calls > 0

        # Second pass — cache should short-circuit; expect zero new HTTP calls
        call_count["n"] = 0
        result2 = run_validation(overwrite=True)
        assert result2["success"] is True
        assert call_count["n"] == 0, (
            f"Expected 0 HTTP calls on cached run, got {call_count['n']}"
        )
```

- [ ] **Step 2: Run it**

Run: `pytest harvester/src/tests/test_orchestrator.py::TestCacheShortCircuitsHttp -v`
Expected: PASS.

- [ ] **Step 3: Run the full suite — final green check**

Run: `pytest -q`
Expected: 530 + 14 = 544 tests, all pass.

- [ ] **Step 4: Commit**

```bash
git add harvester/src/tests/test_orchestrator.py
git commit -m "test(validator): integration test proving cache short-circuits HTTP

Runs run_validation twice over the same 3-device fixture with the disk
cache enabled. Counts requests.get calls; asserts first pass makes network
calls, second pass makes zero.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5.7: Docs, manual wall-clock benchmark, changelog, open PR #2

**Files:**
- Modify: `harvester/src/validators/CLAUDE.md`
- Modify: `CLAUDE.md` (project root)
- Create: `Senior Project/Changelogs/Changelog - 2026-04-23.md`

- [ ] **Step 1: Update `harvester/src/validators/CLAUDE.md`**

Append under the Error-handling / retries section added in Task 3.4:

```markdown

## Parallelization

`run_validation()` uses `ThreadPoolExecutor(max_workers=8, thread_name_prefix="gudid")`.
Workers run the pure worker function `_validate_one_device()` (network + CPU only);
main thread aggregates counters and writes all MongoDB collections
(`validationResults`, `verified_devices`, `devices`) serially from a list of
`DeviceValidationResult` instances. Thread names appear as `[gudid_0]` … `[gudid_7]`
in logs. `max_workers` is capped at 8 — raising it requires a spec amendment (NLM
ToS is 20 rps/IP across all APIs).

## Local cache

`gudid_cache.py` backs `fetch_gudid_record` with a 24 h `diskcache` store at
`.cache/gudid/`. Key: `sha1(catalog_number|version_model_number)`. Positive and
negative results both cached (negative via `__GUDID_NOT_FOUND__` sentinel). First
run on a 551-device dataset ≈ 3 min; cached re-run within 24 h ≈ a few seconds.
Disable per-run with `--no-cache` (runner) or the interactive "Use GUDID disk
cache?" prompt (cli). Failed HTTP calls (`Timeout`/`ConnectionError`/`429`) are
not cached.
```

- [ ] **Step 2: Update project-root `CLAUDE.md`**

Find the `## Architecture` section. In the high-level flow text (around the "GUDID API validation" line), update to reflect parallelism. Example patch — locate the closest wording and adjust minimally:

From:
```
→ MongoDB (devices) → GUDID API validation → Review Dashboard (FastAPI)
```

To:
```
→ MongoDB (devices) → GUDID API validation (parallel, cached) → Review Dashboard (FastAPI)
```

Then, under `### Validation Scoring`, append a new sentence at the end of the first paragraph:

```
Validation runs through an 8-worker `ThreadPoolExecutor`; results are cached
locally at `.cache/gudid/` with a 24 h TTL (`--no-cache` disables).
```

- [ ] **Step 3: Run the manual benchmark**

Before writing the changelog, capture the wall-clock numbers.

Prerequisites: the 551-device dataset that produced the original failure is already in MongoDB.

```bash
# First run: cold cache. Takes ~3 min under normal conditions.
time python harvester/src/pipeline/runner.py --validate
```

Note the "real" time reported by `time`. Record it.

```bash
# Second run: hot cache. Should complete in <10 seconds.
time python harvester/src/pipeline/runner.py --validate
```

Record that too. If the first run > 5 min: stop and investigate (spec says likely culprits are FDA slowness / `diskcache` contention / `as_completed` bug — do not raise `max_workers`).

- [ ] **Step 4: Create the changelog**

Create `Senior Project/Changelogs/Changelog - 2026-04-23.md`:

```markdown
# Changelog — 2026-04-23

## GUDID Validation Resilience & Parallelization

Two stacked PRs fixed a batch-killing HTTP bug and cut wall-clock from
~17 min to ~3 min on a 551-device run.

### PR #1 — Resilience (`Jason-gudid-resilience` → `Jason`)

- **Per-device error isolation.** `run_validation()` now wraps each
  `fetch_gudid_record` call in `try/except requests.RequestException`.
  Failed devices are recorded as `status: "fetch_error"` in
  `validationResults` and counted in the new `result["errors"]` field.
  One transient timeout no longer kills the batch.
- **HTTP timeout bumped 15s → 60s.** New `REQUEST_TIMEOUT` constant
  shared by all three request sites in `gudid_client.py`.
- **Retry with tenacity.** `search_gudid_di` and `fetch_gudid_record`
  decorated with `@retry(stop_after_attempt(3), wait_exponential + jitter)`.
  Retries only `Timeout`, `ConnectionError`, and `GudidRateLimitError`
  (new typed exception for HTTP 429). 4xx other than 429 fail fast.
- **CLI + dashboard.** New `Errors: N` line (yellow) in validation
  summary. Review page renders a neutral "Could not verify" banner
  for `fetch_error` docs.
- **Tests.** +9 (1 orchestrator, 4 rate-limit/typed-exception, 4 retry).

### PR #2 — Parallelization + cache (`Jason-gudid-parallel` → `Jason`)

- **ThreadPoolExecutor.** `run_validation()` now runs an 8-worker pool
  (`thread_name_prefix="gudid"`). Workers do network + CPU; main thread
  aggregates counters and writes MongoDB serially. `max_workers=8`
  stays under NLM's 20 rps ToS cap.
- **Disk cache.** New `gudid_cache` module (`diskcache`, 24 h TTL,
  `.cache/gudid/`). Positive and negative results cached. `--no-cache`
  on `runner.py` and an interactive prompt in `cli.py` let users bypass.
- **Tests.** +8 (3 parallelization, 5 cache).

### Wall-clock (551-device dataset)

| Run | Before | After |
|---|---|---|
| First run | ~17 min | **~3 min** ← fill in actual from Task 5.7 Step 3 |
| Second run (cached) | ~17 min | **<10 s** ← fill in actual |

### Spec deviations

- Cache is keyed at `fetch_gudid_record` level on
  `sha1(catalog_number|version_model_number)`, not purely on DI as the
  original prompt suggested. Caching by DI alone would still require
  one search HTTP call per device. Confirmed with user during brainstorming.
- The prompt referenced `harvester/src/gudid_client.py`; actual path is
  `harvester/src/validators/gudid_client.py`.
- No pytest marker for network tests — the repo has no `pytest.ini`
  / `conftest.py` / registered markers. All new tests are fully mocked;
  the wall-clock benchmark is a manual step, not committed.

### Test suite

530 → 544 tests. Zero regressions.
```

**Fill in the actual wall-clock numbers** from Step 3 into the "After" column. If you didn't get a clean second-run number, say so ("not measured" or "~2 s — run 'time python runner.py --validate' on a hot cache and update").

- [ ] **Step 5: Final full-suite run**

```bash
pytest -q
```

Expected: all 544 pass.

- [ ] **Step 6: Push and open PR #2**

```bash
git add harvester/src/validators/CLAUDE.md CLAUDE.md "Senior Project/Changelogs/Changelog - 2026-04-23.md"
git commit -m "docs: GUDID validation parallelization + cache; 2026-04-23 changelog

Documents the ThreadPoolExecutor parallelization and the disk cache in
validators/CLAUDE.md and the root CLAUDE.md. Creates the project-level
changelog capturing both PRs and the measured wall-clock improvement.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

git push -u origin Jason-gudid-parallel
```

Open the PR:

```bash
gh pr create --base Jason --title "perf(gudid): parallelize validation + 24h disk cache" --body "$(cat <<'EOF'
## Summary
- Replaces the serial per-device validation loop with `ThreadPoolExecutor(max_workers=8, thread_name_prefix="gudid")`. Workers run a pure `_validate_one_device()` (network + CPU); main thread aggregates counters and writes MongoDB serially. `max_workers=8` stays under NLM's 20 rps ToS cap.
- Adds `gudid_cache` (`diskcache`, 24 h TTL at `.cache/gudid/`) keyed on `sha1(catalog_number|version_model_number)`. Positive and negative lookups cached; failed HTTP calls are not.
- Adds `--no-cache` flag to `runner.py` and an interactive prompt to `cli.py`.
- Wall-clock on the 551-device dataset: ~17 min → ~3 min on a cold cache, < 10 s on a warm cache.

Stacked on PR #1 (`Jason-gudid-resilience`).

## Test plan
- [x] `pytest harvester/src/validators/tests/ -q` — all pass
- [x] `pytest harvester/src/tests/ -q` — all pass
- [x] `pytest -q` — full suite (544 tests) green
- [ ] Manual: `time python harvester/src/pipeline/runner.py --validate` — record wall-clock
- [ ] Manual: re-run with hot cache — confirm <10 s
- [ ] Manual: `--no-cache` flag bypasses the cache (`time` shows comparable to first run)

Spec: `docs/superpowers/specs/2026-04-23-gudid-validation-resilience-design.md`
Changelog: `Senior Project/Changelogs/Changelog - 2026-04-23.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Final report (after PR #2 merges)

Post-merge, summarize to the user:

1. **Files touched per phase** — reproduce the "File Structure" tables from this plan.
2. **Test count delta** — 530 → 544 (+14).
3. **Wall-clock before / after** — numbers from Task 5.7 Step 3.
4. **Spec deviations** — the three items in the "Open questions / deviations" section of the spec, confirmed unchanged during implementation.

---

## Appendix: Common failure modes during implementation

- **Tenacity retry sleeps in tests.** The `no_retry_sleep` autouse fixture in `test_gudid_client_retry.py` patches `time.sleep`. If a test still hangs, tenacity may be using a non-`time.sleep` backend in your installed version — check with `from tenacity.nap import sleep` and monkey-patch that instead.
- **`DeviceValidationResult` field drift.** The dataclass is populated in `_validate_one_device` and consumed in `_persist_result`. If you add a field to one, add it to the other in the same task.
- **`_merge_gudid_into_device` signature.** Takes the full `db` object (see `orchestrator.py:55`). `_persist_result` in this plan receives `db` directly for that reason.
- **`harvest_gap_*` counter conditions.** These are pre-existing. Read the current increment logic verbatim before moving it into `_persist_result`; do not redesign.
- **Cache leaking between tests.** Every cache test and integration test must point `gudid_cache._CACHE_ROOT` at a `tmp_path` and reset `gudid_cache._cache = None`. Use the fixture shown in Task 5.2 Step 1.
- **`compare_records` patched on wrong module.** In parallelization tests, patch `orchestrator.compare_records` (since Task 4.1 hoisted the import to module scope). Patching `validators.comparison_validator.compare_records` won't take effect because `orchestrator` already has a direct reference.
- **MongoDB fake drift from real behavior.** The `FakeCollection` in tests is the minimum to exercise `find/insert_one/update_one`. If you add new MongoDB operations to `_persist_result`, add matching methods to `FakeCollection`.
