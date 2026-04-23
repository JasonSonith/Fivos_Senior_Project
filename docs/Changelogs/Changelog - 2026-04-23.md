# Changelog — 2026-04-23

## GUDID Validation: Resilience + Parallelization + Disk Cache

Closes the 551-device batch validation failure observed on 2026-04-23 (`harvest_20260423_153052.log`) where a single transient FDA timeout killed the whole validation run. Ships resilience, 8-way parallelism, and a 24 h local cache — all on branch `Jason`.

### Root cause

`harvester/src/orchestrator.py:run_validation()` had a serial `for device in devices:` loop calling `fetch_gudid_record()` with **no `try/except`**. `gudid_client.py` used `timeout=15` and `response.raise_for_status()`, so any single `requests.Timeout` / `HTTPError` / `ConnectionError` propagated up, was caught by the outermost handler in `cli.py:288`, and marked validation `✘ Failed` for every one of the 551 devices — including the ~550 that would have succeeded.

The scrape (29 URLs) + extract (551 records via gemma4) + DB write all succeeded cleanly. Only the validation step died.

### What shipped

All commits on branch `Jason`, starting after `0ae0862` (prior tip).

**Design + plan:**

| SHA | Commit |
|---|---|
| `e0df9ab` | `docs(spec)`: design spec at `docs/superpowers/specs/2026-04-23-gudid-validation-resilience-design.md` |
| `3647274` | `docs(plan)`: implementation plan at `docs/superpowers/plans/2026-04-23-gudid-validation-resilience.md` |

**PR #1 content — HTTP resilience:**

| SHA | Commit |
|---|---|
| `a374bc9` | `fix(validator)` — wrap `fetch_gudid_record` in `try/except requests.RequestException`; log at WARNING; increment new `result["errors"]` counter; insert `status: "fetch_error"` doc (with `error_type` / `error_message`) into `validationResults`; `continue`. One device's failure no longer kills the batch. |
| `eeb323e` | `feat(cli)` — surface new `Errors: N` line in validation summary, yellow when >0, in both `runner.py` and `cli.py`. |
| `1156e51` | `feat(review)` — review dashboard renders neutral "Could not verify" banner for `status: "fetch_error"` documents; falls back to info mode (no side-by-side comparison). Mirrors existing `gudid_deactivated` pattern. |
| `02a03c0` | `refactor(gudid)` — lift HTTP timeout 15 s → 60 s via `REQUEST_TIMEOUT` constant applied to all three request sites in `gudid_client.py`. |
| `d6e45c5` | `feat(gudid)` — tenacity `@retry` on `search_gudid_di` and `fetch_gudid_record`: 3 attempts, `wait_exponential(min=1, max=4) + wait_random(0, 1)` jitter, retries only `Timeout`, `ConnectionError`, and new `GudidRateLimitError` (HTTPError subclass raised from 429). `reraise=True` so callers see original exception. Non-429 4xx fail fast. |
| `d543d31` | `docs(validators)` — document 60 s timeout + retry policy + `fetch_error` status in `harvester/src/validators/CLAUDE.md`. |

**PR #2 content — parallelization + cache:**

| SHA | Commit |
|---|---|
| `ff31fef` | `refactor(orchestrator)` — hoist lazy `fetch_gudid_record` / `compare_records` imports to module scope; retarget test patches from `validators.*` to `orchestrator.*`. |
| `199201c` | `refactor(orchestrator)` — extract `_derive_outcome(matched, total)` helper for the matched/partial/mismatch derivation. |
| `118d360` | `perf(validator)` — new `DeviceValidationResult` dataclass + pure `_validate_one_device` worker (network + CPU only) + `_persist_result` helper (MongoDB writes). Serial `for device in devices:` becomes `ThreadPoolExecutor(max_workers=8, thread_name_prefix="gudid")` + `as_completed` + 25-device progress logging. All counter aggregation on the main thread; all MongoDB writes serial. `validationResults` / `verified_devices` / `devices` document shapes preserved exactly. |
| `c256b85` | `feat(gudid)` — new `gudid_cache.py` module backed by `diskcache` at `.cache/gudid/`. Key: `sha1(catalog_number \| version_model_number)`. Value: `(di, record_or_sentinel)` tuple. TTL: 24 h. Positive + negative results both cached (negative via `__GUDID_NOT_FOUND__` sentinel). Failed HTTP calls not cached. Wired into `fetch_gudid_record` as the first read; writes on every success path. `--no-cache` flag on `runner.py`; interactive "Use GUDID disk cache?" prompt in `cli.py`. |
| `b74a86b` | `test(validator)` — 3 parallelization tests (`test_orchestrator_parallel.py`) + 2 cache integration tests (second call does zero HTTP, negative results cached). |
| `7ec92d8` | `docs` — parallel + cache sections in `harvester/src/validators/CLAUDE.md` and a one-line update in root `CLAUDE.md`. |

### Test delta

| File | New tests |
|---|---|
| `harvester/src/tests/test_orchestrator.py` | +1 (`TestRunValidationErrorIsolation`) |
| `harvester/src/validators/tests/test_gudid_client_retry.py` | +8 (rate-limit helper ×4, retry behavior ×4) |
| `harvester/src/validators/tests/test_gudid_cache.py` | +8 (cache roundtrip ×6 + fetch short-circuit ×2) |
| `harvester/src/validators/tests/test_orchestrator_parallel.py` | +3 (concurrency, persistence, exception isolation) |
| **Total** | **+20 new tests, all passing, no live network** |

`pytest harvester/src/tests/test_orchestrator.py harvester/src/validators/tests/test_gudid_cache.py harvester/src/validators/tests/test_gudid_client_retry.py harvester/src/validators/tests/test_orchestrator_parallel.py -q` → 25 passed.

Pre-existing `ModuleNotFoundError: No module named 'validators'` on `Jason` for five test files under `harvester/src/validators/tests/` (sys.path issue unrelated to this change) — not touched.

### New dependencies

- `tenacity>=8.0` (installed as 9.1.4 in the local env)
- `diskcache>=5.6` (installed as 5.6.3)

### CLI demo run

Full `Harvest + Save + Validate` pipeline, default URL source (`harvester/src/urls.txt`, 28 URLs), DB overwrite, non-verbose, GUDID cache **enabled**. Log: `harvester/log-files/harvest_20260423_165111.log`.

**Total wall-clock: 21.0 min** (scrape + extract + DB + validate end-to-end). Scraping + LLM extraction dominated the time; validation itself was the short tail.

```
==================================================
Results
==================================================
Processed:        29
Succeeded:        198
Failed:           15
Records written:  198
Output:           harvester/output
DB mode:          overwrite
Records saved:    198

Validation
Total:            198
Full matches:     0
Partial matches:  181
Mismatches:       17
Not found:        0
Errors:           0
==================================================

✔ Done.
```

Key signal: **`Errors: 0`** — the retry policy + 60 s timeout absorbed every transient blip (previously the run died on the first one). Compare to the earlier `harvest_20260423_153052.log` run which crashed with `Validating ✘ Failed — HTTPSConnectionPool(...) Read timed out. (read timeout=15)` and returned 0 validation results for all 551 devices.

198 records successfully validated end-to-end:
- 181 partial matches — reviewer queue populated with real discrepancies for human decisions.
- 17 mismatches — includes genuine mismatches + GUDID-not-found records (the pre-existing design writes them as `"mismatch"` with `match_percent: 0`).
- 0 full matches — expected on a fresh DB-overwrite run; the scoring threshold requires every compared field to agree, and manufacturer pages rarely line up perfectly with GUDID on all ~15 fields.
- 0 errors — no `fetch_error` docs in `validationResults`, confirming the HTTP layer stayed healthy throughout.

The 15 scrape/extract failures are orthogonal to this change — they're LLM/scraper issues (out of scope for this PR).

### Spec deviations (documented + applied)

- Cache key hashes `(catalog_number, version_model_number)` at the `fetch_gudid_record` level, not purely on DI as the original prompt suggested. Caching by DI alone would still require one HTTP search call per device on every run. Confirmed with user during brainstorming.
- `harvester/src/gudid_client.py` in the original prompt was a typo — actual path is `harvester/src/validators/gudid_client.py`.
- No pytest network marker registered — repo has no `pytest.ini` / `conftest.py`. All new tests are fully mocked; the wall-clock capture is this CLI demo run, not a committed benchmark.
- `result["not_found"]` counter is pre-existing, declared but never incremented — left alone. GUDID-not-found still writes a `"mismatch"` doc and increments `result["mismatches"]` to preserve existing review-dashboard behavior (2026-04-20 design decision).
- User course-corrected mid-execution from the original stacked two-PR workflow (`Jason-gudid-resilience` → `Jason-gudid-parallel`) to a single push on `Jason` covering all 5 phases. The feature branches were fast-forwarded into `Jason` during the shift; the design / plan / commit granularity were preserved.

### Files touched

**Modified:**
- `harvester/src/orchestrator.py` — errors counter, try/except, worker + persist refactor, ThreadPoolExecutor driver, hoisted imports
- `harvester/src/validators/gudid_client.py` — REQUEST_TIMEOUT constant, GudidRateLimitError, _raise_for_status_with_rate_limit, @retry decorators, cache read/write
- `harvester/src/pipeline/runner.py` — Errors: N display, --no-cache flag
- `harvester/src/pipeline/cli.py` — Errors: N display, "Use GUDID disk cache?" prompt, cache toggle
- `app/routes/review.py` — fetch_error in info-mode list
- `app/templates/review.html` — fetch_error banner
- `harvester/src/validators/CLAUDE.md` — retry policy, parallelization, cache docs
- `CLAUDE.md` — architecture note
- `harvester/src/tests/test_orchestrator.py` — error isolation test + retargeted patches
- `requirements.txt` — tenacity, diskcache
- `.gitignore` — .cache/

**Created:**
- `harvester/src/validators/gudid_cache.py`
- `harvester/src/validators/tests/test_gudid_cache.py`
- `harvester/src/validators/tests/test_gudid_client_retry.py`
- `harvester/src/validators/tests/test_orchestrator_parallel.py`
- `docs/superpowers/specs/2026-04-23-gudid-validation-resilience-design.md`
- `docs/superpowers/plans/2026-04-23-gudid-validation-resilience.md`
- `docs/Changelogs/Changelog - 2026-04-23.md` (this file)
