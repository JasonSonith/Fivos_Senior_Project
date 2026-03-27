# Web Scraper

Playwright-based async browser automation for fetching manufacturer product pages.

## Modules

| File | Role | Key Functions |
|------|------|---------------|
| `scraper.py` | Async scraper with rate limiting | `BrowserEngine`, `fetch_page_html()`, `safe_filename_from_url()` |

## BrowserEngine

- Async context manager (`async with BrowserEngine() as engine:`)
- Configurable: `max_concurrency`, `page_timeout_ms`, `retries`, `retry_delay_s`, `rate_limit_delay_s`
- Global rate limiter: minimum 2s between requests
- Waits for `domcontentloaded` + `networkidle`

## Output

HTML files saved to `harvester/src/web-scraper/out_html/` as `{host}__{path}__{hash}.html`.

## Integration

Called by `pipeline/runner.py --urls` for end-to-end pipeline. Also used standalone for manual scraping.

## URL List

Target URLs are maintained in `harvester/src/urls.txt` (one per line, `#` comments supported).
