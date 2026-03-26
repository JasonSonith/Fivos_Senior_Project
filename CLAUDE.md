# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Fivos** is a multi-agent AI system that harvests medical device data from manufacturer websites and validates it against the FDA's GUDID database, flagging discrepancies for human review.

- **Client**: Doug Greene — doug.greene@fivoshealth.com — Fivos, 8 Commerce Ave, West Lebanon, NH 03784
- **Team**: Vibe Coders (CIS 497 Senior Design) — started 1/15/2026
- **Python version**: 3.13.7
- **Workflow**: "Collect → Compare → Correct" with AI feedback loop

**Data flow by owner:** Jonathan (orchestration) → Wyatt (scraping) → Ryan (adapters) → Jason (pipeline + security) → Ralph (storage)

## Commands

```bash
# Install
pip install -r requirements.txt
playwright install

# Test
pytest                                    # all tests
pytest harvester/src/pipeline/tests/test_pipeline_e2e.py  # single file
pytest harvester/src/normalizers/tests/test_units.py::TestWeightConversions::test_kg_to_g  # single test

# Run pipeline (processes pre-downloaded HTML files using site adapters for extraction)
python harvester/src/pipeline/runner.py --adapter-dir harvester/src/site_adapters --input-dir harvester/src/web-scraper/out_html  # batch
python harvester/src/pipeline/runner.py --adapter <yaml> --input <html>  # single file
# Options: --output-dir DIR, --run-id HR-10011, -v

# Dashboard
uvicorn app.main:app --port 8000
```

## Environment
Copy `.env.example` → `.env` and fill in credentials before running.
Required vars are listed in `.env.example`.

## Architecture

### Data Flow

```
Manufacturing Website
        ^
        | Page Requests (Playwright, standalone)
        |
   Web Scraper (harvester/src/web_scraper/scraper.py)
        |
        | Raw HTML Files saved to harvester/src/web-scraper/out_html/
        v
   Extraction Pipeline (harvester/src/pipeline/runner.py)
        |
        | Uses Site Adapters (YAML CSS-selector configs) to locate fields on each page
        | Adapters are for PARSING, not scraping. They tell the pipeline WHERE
        | to find device_name, model_number, specs_container, etc. in the HTML.
        |
        | Steps: sanitize → parse → extract (via adapter selectors) → normalize → validate → package
        |
        | GUDID-format JSON records
        v
   MongoDB (devices collection)
        |
        v
   Validator ◄──── FDA GUDID API (v3 JSON, https://accessgudid.nlm.nih.gov/api/v3/devices/lookup.json)
        |              (reference data for comparison)
        |
        | Flagged Discrepancies (match / partial_match / mismatch)
        v
   Review Dashboard (FastAPI web UI)
        |
        └──── Human approves/rejects ──── MongoDB updated
```

### Key Distinction: Scraper vs Adapters vs Pipeline

| Component | Role | Triggered by |
|-----------|------|-------------|
| **Web Scraper** (`web_scraper/scraper.py`) | Fetches and renders HTML pages from manufacturer websites using Playwright. Saves to `web-scraper/out_html/`. | Standalone CLI tool (run separately) |
| **Site Adapters** (`site_adapters/*.yaml`) | CSS selector configs that tell the pipeline WHERE to find fields (device_name, model_number, specs_container, warning_text) on each manufacturer's HTML page layout. **NOT for scraping.** | Read by the pipeline at extraction time |
| **Pipeline** (`pipeline/runner.py`) | Reads HTML from `out_html/`, applies adapter selectors to extract data, normalizes values, validates, packages into GUDID-format JSON. | CLI or web UI |
| **GUDID API** | FDA's device lookup API. Used for validation (compare harvested vs official) and direct device lookup. | Validator or GUDID lookup page |

### Module Map

- `pipeline/` — Core extraction: parser, extractor, dimension_parser, regulatory_parser, emitter, runner
- `normalizers/` — Field-specific cleaners: text, model_numbers, dates, unit_conversions, booleans
- `validators/` — GUDID comparison: gudid_client, comparison_validator, record_validator, ollama_client
- `security/` — Input sanitization, credential management
- `database/` — MongoDB connection, JSON import, run aggregation
- `web_scraper/` — Playwright-based browser automation (standalone)
- `site_adapters/` — YAML config files with CSS selectors per manufacturer layout
- `app/` — FastAPI web dashboard

**Other modules:** `security/` (input sanitization, credential handling) · `validators/` (GUDID record validation) · `database/` (MongoDB import/build utilities)

## Error Handling Philosophy: "Never crash the run"

- Parsing failure → log + store raw HTML + skip record
- Extraction failure → log per missing field + emit partial if required fields present
- Normalization failure → keep raw value in `raw_*` field + flag for review
- Validation failure (critical) → reject + log; (non-critical) → emit with issues list

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Browser automation | Python + Playwright + asyncio |
| HTML parsing | BeautifulSoup4 + lxml |
| Site adapters | YAML config files (CSS selectors for extraction) |
| Data lake | MongoDB (NoSQL) |
| Validation reference | FDA GUDID API v3 (JSON) |
| Web UI | FastAPI + Jinja2 |
| AI (local, optional) | Ollama (for unstructured text extraction fallback) |
| Source control | Git / GitHub |

## Detailed Documentation

For deeper context, reference these files as needed:

- `docs/Fivos Multi-Agent AI System for Automated Medical Device Data Harvesting and Regulatory Validation` — High level overview of the project.
- `docs/Team Roles -Harvester Agent.md` - For roles of the project, who does what, etc.
- `docs/Jason - Todo.md` - Jason's todo list.
- `docs/Target Brands.xlsx` - Brands that we are scraping the manufacturing websites for.
- `docs/Fivos System Architecture Diagram.md` - Architecture of our entire system.
