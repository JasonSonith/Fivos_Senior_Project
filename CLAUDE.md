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

# Run pipeline — end-to-end
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt            # scrape → extract → DB (append) → validate
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --overwrite # same, but wipe DB first
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --no-validate  # skip GUDID validation

# Run pipeline — extract only (from existing HTML)
python harvester/src/pipeline/runner.py              # batch, default paths
python harvester/src/pipeline/runner.py --db         # extract + write to DB (append)
python harvester/src/pipeline/runner.py --db --overwrite --validate  # extract + DB overwrite + validate
python harvester/src/pipeline/runner.py --input <html>  # single file
python harvester/src/pipeline/runner.py --adapter <yaml> --input <html>  # CSS adapter override
# Options: --input-dir DIR, --output-dir DIR, --run-id HR-10011, --workers N, -v

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
        | runner.py --urls (Playwright scraping)
        |
   Web Scraper (harvester/src/web_scraper/scraper.py)
        |
        | Raw HTML Files → harvester/src/web-scraper/out_html/
        v
   Extraction Pipeline (harvester/src/pipeline/runner.py)
        |
        | Ollama extracts ALL fields (multithreaded, --workers N)
        | Two-pass: page-level fields, then product rows from tables
        | Produces one GUDID record per SKU
        |
        | → normalize → validate → package
        |
        | GUDID-format JSON records → harvester/output/
        v
   MongoDB (devices collection)          ← --db flag (append default, --overwrite to drop first)
        |
        v
   Validator ◄──── FDA GUDID API         ← --validate flag
        |
        | Flagged Discrepancies (match / partial_match / mismatch)
        v
   Review Dashboard (FastAPI web UI)
        |
        └──── Human approves/rejects ──── MongoDB updated
```

### Key Distinction: Scraper vs Adapters vs Ollama vs Pipeline

| Component | Role | Triggered by |
|-----------|------|-------------|
| **Web Scraper** (`web_scraper/scraper.py`) | Fetches and renders HTML pages from manufacturer websites using Playwright. Saves to `web-scraper/out_html/`. | `runner.py --urls` or standalone |
| **Ollama Extractor** (`pipeline/ollama_extractor.py`) | **Primary extractor.** LLM-based extraction for all pages. Extracts all fields (device_name, model_number, dimensions, description, warnings) via structured JSON output. Two-pass: page-level fields + product table rows. | Called by pipeline for every file |
| **Site Adapters** (`site_adapters/*.yaml`) | CSS selector configs. **Optional override** — only used when explicitly passed via `--adapter` flag. Not used in default batch mode. | Manual CLI override |
| **Pipeline** (`pipeline/runner.py`) | End-to-end: scrape → extract → normalize → validate → JSON → DB → GUDID validation. Multithreaded extraction via `concurrent.futures`. | CLI (`--urls` for e2e) or web UI |
| **GUDID API** | FDA's device lookup API. Used for validation (compare harvested vs official) and direct device lookup. | Validator or GUDID lookup page |

### Ollama Extraction (LLM-Powered)

Ollama serves two roles in the pipeline:

1. **Full extraction (primary path):** The pipeline uses Ollama to extract ALL fields from every page. This is a two-pass process:
   - **Pass 1 (page-level):** Extracts device_name, manufacturer, description, warning_text, MRISafetyStatus from the full page text.
   - **Pass 2 (product rows):** Extracts individual SKUs (model_number, catalog_number, dimensions) from the largest table on the page. Produces one GUDID record per SKU.

   This makes the pipeline work on **any manufacturer website** without per-site configuration.

2. **Description fallback (CSS override path):** When a CSS adapter is explicitly used via `--adapter` flag and doesn't have a `description` selector, Ollama generates a clinical-style `deviceDescription` from the page text.

If Ollama is not running, the pipeline produces no records (counted as `failed`). The `_harvest` metadata tracks the extraction source:
- `extraction_method`: `"css"` or `"ollama"` — how the entire record was extracted
- `extraction_model`: `"llama3.2"` or null — which Ollama model was used
- `description_source`: `"css"`, `"ollama"`, or null — specifically how the description was obtained

### Validation Scoring

`comparison_validator.py` compares harvested records against GUDID on 4 boolean fields (`versionModelNumber`, `catalogNumber`, `brandName`, `companyName`) plus a `description_similarity` Jaccard score. Fields where the harvested value is `None` are marked `match: None` (skipped) and excluded from the score denominator. This prevents missing fields from inflating mismatch rates. `catalogNumber` is stored as `None` when the adapter doesn't extract it (no model_number fallback).

### Module Map

- `pipeline/` — Core extraction: parser, extractor, dimension_parser, regulatory_parser, ollama_extractor, emitter, runner
- `normalizers/` — Field-specific cleaners: text, model_numbers, dates, unit_conversions, booleans
- `validators/` — GUDID comparison: gudid_client, comparison_validator, record_validator
- `security/` — Input sanitization, credential management
- `database/` — MongoDB connection (`db_connection.py`)
- `web_scraper/` — Playwright-based browser automation (standalone)
- `site_adapters/` — YAML config files with CSS selectors per manufacturer layout
- `app/` — FastAPI web dashboard

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
| AI (local) | Ollama — primary extractor for adapterless pages; description fallback for adapter pages |
| Source control | Git / GitHub |

## Detailed Documentation

For deeper context, reference these files as needed:

- `docs/Fivos Multi-Agent AI System for Automated Medical Device Data Harvesting and Regulatory Validation` — High level overview of the project.
- `docs/Team Roles -Harvester Agent.md` - For roles of the project, who does what, etc.
- `docs/Jason - Todo.md` - Jason's todo list.
- `docs/Target Brands.xlsx` - Brands that we are scraping the manufacturing websites for.
- `docs/Fivos System Architecture Diagram.md` - Architecture of our entire system.
