# Plan: Fivos Overhaul — Fix Data Flow, Add GUDID API, Correct Adapter Role

## What's Wrong Right Now

### Problem 1: The harvester page is backwards

The harvester form asks the user to **pick an adapter + enter a URL**, then scrapes that URL live with Playwright. This is wrong because:

- The HTML files are **already scraped** and sitting in `harvester/src/web-scraper/out_html/` (28 files from 7 manufacturers)
- Adapters are **not for web scraping**. They define CSS selectors that tell the pipeline **where to find fields** on an already-downloaded HTML page (device_name, model_number, specs_container, etc.)
- The scraper (`web_scraper/scraper.py`) is a **separate, standalone tool** that Wyatt runs to fetch HTML. It has nothing to do with the adapters.

### Problem 2: The GUDID API is underutilized

`gudid_client.py` currently:
1. Scrapes the GUDID *HTML search page* to find a Device Identifier (DI)
2. Calls the JSON API with that DI
3. Converts the structured JSON **back into plaintext**
4. Sends that plaintext to **Ollama (local LLM)** to re-extract the 5 fields that were already in the JSON

This is a 4-step Rube Goldberg machine. The GUDID JSON API (`/api/v3/devices/lookup.json`) returns structured data directly. No HTML scraping, no LLM needed.

### Problem 3: Harvested data is incorrect

The pipeline output (the "harvested data" in MongoDB) is likely wrong because:
- `orchestrator.run_harvest()` scrapes a URL live, writes to a temp file, and runs the pipeline — but the adapter may not match the actual page layout of the URL the user entered
- The pipeline was designed to work on the **pre-downloaded HTML files** in `out_html/`, not on arbitrary URLs
- The correct flow is: run the pipeline on the existing HTML files using the batch mode (`process_batch`), which auto-matches each file to the right adapter by domain name

### Problem 4: CLAUDE.md is misleading

The architecture diagram and data flow description don't accurately reflect the role of adapters. The current description implies adapters drive scraping. They don't — they drive **parsing and extraction**.

---

## Proposed Fix

### Change 1: Fix the Harvester Page — Process Existing HTML Files

**Instead of:** "Pick adapter + enter URL + scrape live"

**Do this:** "Run the pipeline on the existing HTML files in `out_html/`"

The harvester page should:
1. Show a list of HTML files available in `harvester/src/web-scraper/out_html/`
2. Let the user select which files (or all) to process
3. Run `pipeline/runner.py`'s `process_batch()` which auto-matches each file to the right adapter by domain
4. Show the results (how many processed, succeeded, failed)

This matches how the pipeline was actually designed to work (see `runner.py:process_batch` and `resolve_adapter`).

**Files to change:**
- `harvester/src/orchestrator.py` — Replace `run_harvest(url, adapter_path)` with `run_batch(file_paths=None)` that calls `process_batch` on the `out_html/` directory
- `app/routes/harvester.py` — Replace the URL+adapter form with a file-selection + "Run Pipeline" button
- `app/templates/harvester.html` — Show available HTML files, checkboxes, run button

### Change 2: Add GUDID API Lookup as a Primary Data Source

Add a new page/feature: **"GUDID Lookup"** that lets users query the FDA GUDID database directly via the JSON API.

The GUDID Device Lookup API (`https://accessgudid.nlm.nih.gov/api/v3/devices/lookup.json`) accepts:
- `di` — Device Identifier (a numeric string)
- `udi` — Full UDI barcode string

And returns structured JSON with all device fields: `brandName`, `versionModelNumber`, `catalogNumber`, `companyName`, `deviceDescription`, `MRISafetyStatus`, sterilization info, regulatory status (Rx/OTC), GMDN terms, and more.

**What to build:**
- `harvester/src/gudid_api.py` — New module that wraps the GUDID v3 JSON API. Functions:
  - `lookup_by_di(di: str) -> dict | None` — Direct lookup by Device Identifier
  - `search_by_model(model_number: str) -> str | None` — Find DI by model/catalog number (replaces the HTML-scraping approach in `gudid_client.py`)
  - `lookup_device(model_number: str) -> dict | None` — Convenience: search for DI, then fetch full record
- `app/routes/gudid.py` — New route for GUDID lookup page
  - `GET /gudid` — Form to enter DI or model number
  - `POST /gudid/lookup` — Calls the API, displays results, optionally saves to MongoDB
- `app/templates/gudid.html` — GUDID lookup page with search form + results display

### Change 3: Fix the Validator — Skip Ollama, Use Structured JSON Directly

The current validator flow is needlessly complex:

```
Current:  HTML scrape for DI → JSON API → convert to plaintext → Ollama LLM → extract fields → compare
Fixed:    Search for DI → JSON API → use structured fields directly → compare
```

**Files to change:**
- `harvester/src/validators/gudid_client.py` — Rewrite to:
  - Keep `search_gudid_di()` (but clean it up — it HTML-scrapes the search page, which is the only way to find a DI by model number since the API doesn't support text search)
  - Replace `fetch_gudid_raw_text()` with `fetch_gudid_record(di)` that returns a **parsed dict** directly from the JSON API (not plaintext)
- `harvester/src/validators/run_validator.py` — Remove the Ollama step entirely. Instead:
  - Call `fetch_gudid_record(di)` to get structured data
  - Pass it directly to `compare_records(harvested, gudid_record)`
  - No LLM needed — the API already returns the exact fields we compare
- `harvester/src/validators/ollama_client.py` — Can be removed or kept as optional fallback

This eliminates the Ollama dependency for validation. The Ollama health-check and error handling in the orchestrator also simplifies.

### Change 4: Fix `orchestrator.py` — Two Clear Operations

Replace the current `run_harvest(url, adapter_path)` with two distinct operations:

```python
# Operation 1: Process existing HTML files through the pipeline
def run_pipeline_batch(file_paths: list[str] | None = None) -> dict:
    """Run the extraction pipeline on HTML files in out_html/.

    If file_paths is None, processes all HTML files.
    Auto-matches each file to the correct adapter by domain.
    Inserts results into MongoDB.

    Returns: {"processed": int, "succeeded": int, "failed": int, "skipped": int, "records": list}
    """

# Operation 2: Look up a device via GUDID API and store it
def lookup_gudid_device(model_number: str = None, di: str = None) -> dict:
    """Query GUDID API for a device, store result in MongoDB.

    Returns: {"success": bool, "record": dict | None, "error": str | None}
    """
```

### Change 5: Fix CLAUDE.md

Update the architecture diagram and data flow description to correctly show:
- **Adapters** = CSS selector configs for **parsing** HTML, not for scraping
- **Web Scraper** = standalone tool (Playwright) that fetches HTML and saves to `out_html/`
- **Pipeline** = reads HTML from `out_html/`, uses adapters to extract fields, normalizes, validates, packages
- **GUDID API** = reference data source for validation AND direct device lookup

Updated architecture:

```
Manufacturing Website
        ^
        | Page Requests (Playwright)
        |
   Web Scraper (standalone)
        |
        | Raw HTML Files (out_html/)
        v
   Site Adapters ──────> Extraction Pipeline
   (CSS Selectors)       (parse → extract → normalize → validate → package)
        |                        |
        |                        | GUDID-format JSON records
        |                        v
        |                   MongoDB (devices collection)
        |                        |
        |                        v
        |               Validator ◄──── FDA GUDID API (v3 JSON)
        |                   |              (reference data)
        |                   |
        |                   | Flagged Discrepancies
        |                   v
        |             Review Dashboard
        |                   |
        |                   └──── Human approves/rejects ──── MongoDB updated
```

### Change 6: Update Nav + Dashboard

- **Sidebar nav:** Dashboard | Harvester (process HTML) | GUDID Lookup | Validation | Results
- **Dashboard:** Show count of HTML files in `out_html/`, devices in MongoDB, validation results
- **Harvester page:** List HTML files, run pipeline batch
- **GUDID Lookup page:** Search by DI or model number, display GUDID record, optionally store
- **Validation page:** Compare harvested vs GUDID, show matches/mismatches
- **Results page:** All devices + validation results from MongoDB

---

## File Changes Summary

| File | Action | What Changes |
|------|--------|-------------|
| `CLAUDE.md` | Edit | Fix architecture diagram, clarify adapter role, add GUDID API info |
| `harvester/src/orchestrator.py` | Rewrite | Replace `run_harvest(url, adapter)` with `run_pipeline_batch()` + `lookup_gudid_device()` |
| `harvester/src/gudid_api.py` | **Create** | Clean GUDID v3 JSON API wrapper (lookup_by_di, search_by_model, lookup_device) |
| `harvester/src/validators/gudid_client.py` | Rewrite | Return structured dict from API, not plaintext |
| `harvester/src/validators/run_validator.py` | Edit | Remove Ollama dependency, use structured GUDID data directly |
| `app/routes/harvester.py` | Rewrite | File-selection UI + run pipeline batch |
| `app/templates/harvester.html` | Rewrite | Show HTML files, run pipeline, display batch results |
| `app/routes/gudid.py` | **Create** | GUDID lookup page routes |
| `app/templates/gudid.html` | **Create** | GUDID search form + results display |
| `app/main.py` | Edit | Add gudid router, remove adapter loading at startup |
| `app/templates/base.html` | Edit | Update nav links |
| `app/routes/dashboard.py` | Edit | Show HTML file count + device count |
| `app/templates/dashboard.html` | Edit | Update stats cards |

---

## Priority Order

| # | What | Why |
|---|------|-----|
| 1 | Fix CLAUDE.md | Correct the documentation so the team understands the real architecture |
| 2 | Rewrite orchestrator.py | Replace the broken `run_harvest(url, adapter)` with `run_pipeline_batch()` |
| 3 | Rewrite harvester page | Let users process existing HTML files instead of entering URLs |
| 4 | Create gudid_api.py | Clean GUDID v3 API wrapper |
| 5 | Fix validators (remove Ollama dependency) | Use GUDID JSON directly instead of LLM extraction |
| 6 | Create GUDID lookup page | New page for direct GUDID device lookup |
| 7 | Update dashboard + nav | Reflect the new architecture |

---

## What This Does NOT Change

- **The pipeline itself** (`runner.py`, `extractor.py`, `parser.py`, `emitter.py`, `dimension_parser.py`, `regulatory_parser.py`) — stays exactly the same. It's correct.
- **The normalizers** — all working correctly, 304 tests pass.
- **The site adapters (YAML files)** — stay the same. They correctly define CSS selectors for each manufacturer's page layout.
- **The web scraper** (`scraper.py`) — stays as a standalone tool. Not called from the UI.
- **The record validator** (`record_validator.py`) — stays the same. It validates field presence and ranges.
- **MongoDB schema** — no changes to how records are stored.
