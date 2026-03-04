## Purpose

This file helps AI coding agents get productive in this repository quickly by documenting the runtime contract, key files, and developer workflows specific to the scraper component.

**Big Picture**
- `BrowserEngine` (see [src/scraper.py](src/scraper.py)): single Chromium instance per run, reused across fetches.
- `FetchResult` (dataclass): the canonical output contract your code must return to downstream extractors: `{ok, html, final_url, status, error, attempts, elapsed_ms}`.
- Rate limiting and concurrency: `AsyncRateLimiter` + `max_concurrency` semaphore enforce politeness and parallelism (defaults in `src/scraper.py`).
- Extraction is separate: extractor code consumes `FetchResult.html` and `final_url` for parsing (see [src/web-scraper/scraperDescription.txt](src/web-scraper/scraperDescription.txt)).

**How to run / dev workflow (explicit)**
- Install Playwright and browsers (required):

```bash
python -m pip install playwright
python -m playwright install chromium
```

- Run the sample driver in `src/scraper.py`:

```bash
python src/scraper.py
```

- Toggle headless / timeouts / concurrency by editing the `BrowserEngine(...)` call inside `main()` in `src/scraper.py`.

**Conventions & patterns (project-specific)**
- One long-lived browser process: do not create a browser per URL. Use the provided `BrowserEngine` context manager to open/close the browser once.
- Isolation per fetch: each `fetch` creates a fresh browser context + page (helps avoid shared state/cookies leaking).
- Non-fatal wait strategy: code uses `page.goto(..., wait_until="domcontentloaded")` and then tries `networkidle` but does not fail if `networkidle` times out — this is intentional (see `page.wait_for_load_state("networkidle")` logic).
- Error handling: callers should not expect exceptions for navigational failures — failures are encoded in `FetchResult.ok==False`.

**Integration notes for AI agents**
- If implementing a consumer, follow this pattern:

```python
result = await engine.fetch(url)
if result.ok and result.html:
    data = jason_extract(result.html, base_url=result.final_url or result.url)
else:
    # record/log failure using result.error
```

- Upstream: URLs may come from a seed list, queue, or crawler. Keep the contract small (string URL in, `FetchResult` out).
- Downstream: extraction and storage live outside `src/scraper.py` — preserve the returned metadata to support retries and observability.

**Debugging tips**
- Set `headless=False` in the `BrowserEngine` constructor to view the browser during debugging.
- Increase `page_timeout_ms` to diagnose slow-loading sites; use `print(asdict(result))` (the sample driver already prints results).

**Files to inspect first**
- [src/scraper.py](src/scraper.py) — core engine, rate limiter, and sample `main()`.
- [src/web-scraper/scraperDescription.txt](src/web-scraper/scraperDescription.txt) — human-readable explanation of flow and contracts.

If anything here is unclear or you want additional examples (CI commands, requirements file, or an extractor stub), tell me which part to expand.
