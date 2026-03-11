# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Fivos** is a multi-agent AI system that harvests medical device data from manufacturer websites and validates it against the FDA's GUDID database, flagging discrepancies for human review. The core problem: GUDID often doesn't match manufacturer websites (wrong dimensions, outdated brand names), causing errors in patient records and procurement.

- **Client**: Doug Greene — doug.greene@fivoshealth.com — Fivos, 8 Commerce Ave, West Lebanon, NH 03784
- **Team**: Vibe Coders (CIS 497 Senior Design) — started 1/15/2026
- **Python version**: 3.13.7
- **Workflow**: "Collect → Compare → Correct" with AI feedback loop

## Team

| Member | Role | Responsibilities |
|--------|------|-----------------|
| Wyatt Ladner | Web Automation Lead | Playwright headless browser, page nav, retry logic (3x, 5s delays), 30s timeouts, JS rendering, rate limiting |
| Jason Sonith | Data Pipeline & Security | HTML extraction, all normalizers, validation logic, credential security, input sanitization |
| Ryan Tucker | Site Adapters | Per-manufacturer YAML/JSON adapter configs with CSS/XPath selectors |
| Ralph Mouawad | Data Lake & Storage | MongoDB schema, write operations, metadata tracking, indexing, deduplication |
| Jonathan Gammill | Run Management & Logging | Harvest run orchestration, run ID generation (e.g. `HR-10011`), progress tracking, scheduler |

**Data flow by owner:** Jonathan → Wyatt → Ryan → Jason → Ralph

## Commands

### Install dependencies
```bash
pip install -r requirements.txt
playwright install  # Install browser binaries for Playwright
```

### Run tests
```bash
# All tests (normalizers, pipeline, validators, security)
pytest --ignore=harvester/src/pipeline/tests/test_runner.py
# Note: test_runner.py requires pyyaml; exclude it if not installed

# Single test file
pytest harvester/src/pipeline/tests/test_pipeline_e2e.py

# Single test
pytest harvester/src/normalizers/tests/test_units.py::TestWeightConversions::test_kg_to_g
```

### Run the pipeline
```bash
# Batch mode — all adapters, all HTML files (auto-routes by domain)
python harvester/src/pipeline/runner.py --adapter-dir harvester/src/site_adapters --input-dir harvester/src/web-scraper/out_html

# Single file — one adapter, one HTML
python harvester/src/pipeline/runner.py --adapter harvester/src/site_adapters/medtronic/table_wrapper_layout.yaml --input harvester/src/web-scraper/out_html/some_file.html

# Options: --output-dir DIR, --run-id HR-10011, -v (verbose)
```

### Run the dashboard (Interface)
```bash
uvicorn harvester.src.Interface.Interface:app --port 8000
# Or directly:
python harvester/src/Interface/Interface.py
```

## Architecture

```
Site Adapters                    Manufacturing Website
(Config Files)                          ^
        |                               | Page Requests
        | Scraping Rules                |
        v                               |
   Web Scraper  ─────────────────────────
        |
        | Raw HTML File
        v
  Normalization Pipeline
        |
        | Normalized Files
        v
  MongoDB ◄─────────────────────────────────────────┐
  (Harvested Data)                                  |
        |                                    Update Records
        |                                           |
        └──────────────────────────────────────┐    |
  FDA GUDID Database                           |    |
  (Reference Data)                             |    |
        |                                      v    |
        | Compare              ──────> Validator Agent
        └──────────────────────                |
                                               | Flagged Discrepancies
                                               v
                                        Review Dashboard
                                               |
                                               └──────────────────────┘
```

**Data flow labels (from DFD):**
- Site Adapters → Web Scraper: `Scraping Rules`
- Web Scraper ↔ Manufacturing Website: `Page Requests`
- Web Scraper → Normalization Pipeline: `Raw HTML File`
- Normalization Pipeline → MongoDB: `Normalized Files`
- FDA GUDID Database + MongoDB → Validator Agent: `Compare`
- Validator Agent → Review Dashboard: `Flagged Discrepancies`
- Review Dashboard → MongoDB: `Update Records`

### Security Layer (cross-cutting)
`CredentialManager`, HTML sanitization, login/role enforcement, audit logging, rate limiting — all owned by Jason.

### Key components and owners

| Component | File | Owner | Status |
|-----------|------|-------|--------|
| Browser automation | `harvester/src/web-scraper/scraper.py` | Wyatt | Complete |
| Normalization engine | `harvester/src/normalizers/unit_conversions.py` | Jason | Complete |
| Model number normalizer | `harvester/src/normalizers/model_numbers.py` | Jason | Complete |
| Date normalizer | `harvester/src/normalizers/dates.py` | Jason | Complete |
| HTML sanitizer | `harvester/src/security/sanitizer.py` | Jason | Complete |
| Credential manager | `harvester/src/security/credentials.py` | Jason | Complete |
| Record validator | `harvester/src/validators/record_validator.py` | Jason | Complete |
| HTML parser | `harvester/src/pipeline/parser.py` | Jason | Complete |
| Field extractor | `harvester/src/pipeline/extractor.py` | Jason | Complete |
| Pipeline runner | `harvester/src/pipeline/runner.py` | Jason | Complete — 19 tests passing |
| Dimension parser | `harvester/src/pipeline/dimension_parser.py` | Jason | Complete — 24 tests passing |
| Regulatory parser | `harvester/src/pipeline/regulatory_parser.py` | Jason | Complete — 16 tests passing |
| Boolean normalizer | `harvester/src/normalizers/booleans.py` | Jason | Complete — 24 tests passing |
| GUDID emitter | `harvester/src/pipeline/emitter.py` | Jason | Complete — 35 tests passing |
| E2E integration test | `harvester/src/pipeline/tests/test_pipeline_e2e.py` | Jason | Complete — 8 tests passing (real Medtronic HTML) |
| Unit tests | `harvester/src/normalizers/tests/test_units.py` | Jason | Complete — 69 tests passing |
| Model number tests | `harvester/src/normalizers/tests/test_model_numbers.py` | Jason | Complete — 10 tests passing |
| Date tests | `harvester/src/normalizers/tests/test_dates.py` | Jason | Complete — 18 tests passing |
| HITL Dashboard | `harvester/src/Interface/Interface.py` | Jonathan | Skeleton complete |
| Site adapter configs | `harvester/src/site_adapters/` | Ryan | Complete — 7/8 manufacturers (Boston Scientific placeholder) |
| MongoDB storage | Not yet created | Ralph | Pending |
| Validator Agent | Not yet created | — | Pending |

## Normalization Pipeline (Jason — `harvester/src/normalizers/`)

7 discrete, independently testable stages:

**Stage 1 — HTML Parsing** (`BeautifulSoup4` + `lxml`, fallback to `html.parser`). Input is already JS-rendered by Wyatt's Playwright.

**Stage 2 — Field Extraction** — Uses Ryan's YAML adapter configs (CSS selectors per manufacturer). Missing fields: log warning, set `None`, continue.

**Stage 2.5 — Dimension Parsing** (`dimension_parser.py`) — Extracts measurements from specs tables. Supports 3 formats: **Format A (Tabular)** — headers like "Diameter (mm)" with value rows (Abbott, Cook, Cordis, Gore, Shockwave, Terumo); **Format B (Key-value)** — labels like "Balloon diameters 4.0 to 7.0 mm" (Medtronic); **Format C (Description)** — inline "6 mm x 40 mm" patterns (Terumo R2P). Tab-separated text from the runner ensures reliable cell-boundary detection.

**Stage 2.7 — Warning Text Aggregation** — Re-extracts `warning_text` using `select()` (all matches) instead of `select_one()` (first match only), joining text from all matching elements. This ensures regulatory disclaimers at the bottom of pages aren't missed when the CSS selector matches multiple elements (e.g. Terumo's `div.cmp-richtext` matches specs tables before the "RX ONLY" disclaimer).

**Stage 3 — Normalization** — All normalizers Jason owns:
- `normalize_measurement(raw_value: str)` — canonical units: length→mm, weight→g, volume→mL, pressure→mmHg. Returns `{value, unit, is_range, range_low?, range_high?}` or `None`.
- `normalize_manufacturer(raw: str)` — maps all known aliases to 8 canonical manufacturer names.
- `normalize_date(raw: str)` — ISO 8601 output (YYYY-MM-DD), handles 11+ input formats including European. Returns `None` for unparseable.
- `clean_model_number(raw: str)` (`model_numbers.py`) — strips prefixes (Model:, Cat. No., REF, SKU, Part Number, P/N, Item #), uppercases, collapses whitespace.
- `normalize_text(raw: str)` — HTML entity decode, NFKC unicode, removes invisible chars (zero-width spaces, BOM, soft hyphens), collapses whitespace.
- `normalize_boolean(raw: str)` (`booleans.py`) — maps yes/true/1/y/on → `True`, no/false/0/n/off → `False`. Returns `None` for unrecognized.
- `normalize_mri_status(raw: str)` (`booleans.py`) — maps to GUDID enum: `"MR Safe"`, `"MR Conditional"`, `"MR Unsafe"`, `"Labeling does not contain MRI Safety Information"`.

**Stage 3.5 — Regulatory Parsing** (`regulatory_parser.py`) — Extracts GUDID boolean fields (`singleUse`, `rx`, `deviceSterile`) from warning/precaution text via regex patterns (e.g. "single use", "prescription only", "supplied sterile"). Only emits fields when patterns match.

**Stage 4 — Validation** — `validate_record(record: dict) -> tuple[bool, list[str]]`. Checks required fields (`device_name`, `manufacturer`, `model_number`), numeric ranges for dimensions, string lengths, URL validity. Critical failures reject; warnings emit with issues list.

**Stage 5 — Emit** — Packages record with GUDID-aligned field names via `package_gudid_record()`. Field mapping: `device_name` → `brandName`, `model_number` → `versionModelNumber`, `catalog_number` → `catalogNumber`, `manufacturer` → `companyName`, `description` → `deviceDescription`. Measurements → `deviceSizes` array with `sizeType` and `unit` (mm → Millimeter, g → Gram, etc.). Regulatory booleans (`singleUse`, `rx`, `deviceSterile`, `otc`, `sterilizationPriorToUse`) and `MRISafetyStatus` are passed through. Harvest metadata nested under `_harvest` key: `harvest_run_id`, `harvested_at` (UTC), `source_url`, `adapter_version`, `normalization_version`, `validation_issues`, `raw_html_sha256`.

### Pipeline module (`harvester/src/pipeline/`)

- `runner.py` — CLI orchestrator. Single-file (`--adapter` + `--input`) and batch (`--adapter-dir` + `--input-dir`) modes. Auto-routes HTML files to adapters by matching filename host segments to adapter `base_url` domains. Field-type classification for normalizer routing: `TEXT_FIELDS`, `MODEL_FIELDS`, `DATE_FIELDS`, `MEASUREMENT_FIELDS`, `BOOLEAN_FIELDS`, `ENUM_FIELDS`. Re-extracts both `specs_container` (step 3.5, tab-separated) and `warning_text` (step 3.6, `select()` aggregation) before normalization to handle multi-element selectors.
- `dimension_parser.py` — Specs table mining. 3 formats: tabular (header + value rows), key-value (label + inline values), description (inline "D mm x L mm"). Label map covers diameter/length/width/height/weight/volume/pressure with skip-list for non-device dimensions (shaft length, catheter length, etc.).
- `regulatory_parser.py` — Warning text pattern matching for GUDID booleans. Regex patterns for `singleUse` (single-use, disposable, do not reuse), `rx` (federal law restricts, prescription only), `deviceSterile` (supplied sterile, sterile-packaged).
- `emitter.py` — GUDID-aligned record packaging via `package_gudid_record()`. Also provides legacy `package_record()`, `write_record_json()`, and `write_batch_json()`. Unit mapping: mm→Millimeter, cm→Centimeter, g→Gram, kg→Kilogram, mL→Milliliter, mmHg→Millimeter Mercury.
- `parser.py` — `parse_html()`, `parse_json()`, `parse_xml()`, `parse_document(raw, fmt)`. Multi-format routing; errors return safe empty/None values, never raise.
- `extractor.py` — `extract_fields(parsed_data, adapter, fmt)`. Adapter dict must have `"extraction"` key mapping field names to selectors. CSS selectors (HTML), dot-path (JSON), XPath (XML). Missing fields → log warning + `None`.
- `tests/fixtures/medtronic_sample.html` — copy of Wyatt's real scraped Medtronic IN.PACT Admiral page (used as e2e fixture).
- `tests/fixtures/mock_adapters.py` — `MEDTRONIC_INPACT_ADAPTER` dict with confirmed CSS selectors.
- `tests/test_pipeline_e2e.py` — 8 e2e tests: real HTML → sanitize → parse → extract → normalize → validate → result dict.

### Error handling philosophy: "Never crash the run"
- Parsing failure → log + store raw HTML + skip record
- Extraction failure → log per missing field + emit partial if required fields present
- Normalization failure → keep raw value in `raw_*` field + flag for review
- Validation failure (critical) → reject + log; (non-critical) → emit with issues list

### Site Adapters (`harvester/src/site_adapters/`)

8 YAML adapter configs (1 per manufacturer), each with `manufacturer`, `product_type`, `base_url`, `seed_urls`, and `extraction` selectors:

| Manufacturer | File | Key Selectors |
|---|---|---|
| Abbott | `abbott/ordering_layout.yaml` | Hero banner + ordering tables |
| Boston Scientific | `boston_scientific/product_page_layout.yaml` | Placeholder selectors (pending real HTML) |
| Cook | `cook/specifications_layout.yaml` | `.specifications-table` class |
| Cordis | `cordis/product_page_layout.yaml` | Hero section + `.sort-sku` |
| Gore | `gore/specifications_layout.yaml` | Dark-themed tables + MRI badge |
| Medtronic | `medtronic/table_wrapper_layout.yaml` | `.table-wrapper` + `.cfnDetailLink` |
| Shockwave | `shockwave/product_page_layout.yaml` | `.table-container` wrapper |
| Terumo | `terumo/product_page_layout.yaml` | `.cmp-richtext` tables |

### GUDID Output Schema

Each pipeline output JSON follows this structure:
```json
{
  "brandName": "...",
  "versionModelNumber": "...",
  "catalogNumber": "...",
  "companyName": "...",
  "deviceDescription": "...",
  "deviceSizes": [
    {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "6.0"}, "sizeText": null}
  ],
  "singleUse": true,
  "rx": true,
  "deviceSterile": true,
  "MRISafetyStatus": "MR Conditional",
  "_harvest": {
    "harvest_run_id": "HR-10011",
    "harvested_at": "2026-03-11T12:00:00Z",
    "source_url": "https://...",
    "adapter_version": "medtronic-table_wrapper_layout",
    "normalization_version": "1.0.0",
    "validation_issues": [],
    "raw_html_sha256": "..."
  }
}
```

### Runner Field Classification

The runner routes each extracted field to the correct normalizer based on these sets:
- **TEXT_FIELDS**: `description`, `brand_name`, `product_type`, `specs_container`, `warning_text` (note: `device_name` is NOT here — it has its own `elif` branch using `clean_brand_name`)
- **MODEL_FIELDS**: `model_number`, `catalog_number`, `sku`
- **DATE_FIELDS**: `approval_date`, `clearance_date`, `expiration_date`
- **MEASUREMENT_FIELDS**: `length`, `width`, `height`, `diameter`, `weight`, `volume`, `pressure`
- **BOOLEAN_FIELDS**: `singleUse`, `deviceSterile`, `sterilizationPriorToUse`, `rx`, `otc`
- **ENUM_FIELDS**: `MRISafetyStatus`

## Security (Jason)

- **Credentials**: All secrets in env vars via `python-dotenv`. `.env` never committed. `CredentialManager` class centralizes access, never logs values. Naming: `FIVOS_{MANUFACTURER}_{FIELD}`.
- **Input sanitization**: Strip `<script>`, `<iframe>`, `<object>`, `<embed>`, `<form>`, all `on*` event attributes. PyMongo parameterized queries (NoSQL injection prevention). Path traversal prevention.
- **Rate limiting**: Respect `robots.txt`, 2s default delay (up to 10s for sensitive sites), honest User-Agent strings, immediate backoff on HTTP 429.
- **Dependencies**: All pinned to exact versions in `requirements.txt`. Run `pip audit` regularly.
- **HIPAA**: No patient data scraped/stored. No credential values in logs. HTTPS only.

## Scraper (`scraper.py`)

`BrowserEngine` is an async context manager. Per-request browser contexts for isolation. Returns `FetchResult` dataclasses. Config: 5 concurrent pages max, 2s rate limit, 3 retries with exponential backoff, 30s page timeout.

## Interface (`Interface.py`)

FastAPI app on port 8000. Two roles: **Administrator** (GUDID import, user management, advanced reports) and **Reviewer** (view flagged discrepancies, Approve/Reject/Edit with reason codes). Uses in-memory storage (no DB yet). Full audit trail of reviewer decisions with timestamps.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Browser automation | Python + Playwright + asyncio |
| HTML parsing | BeautifulSoup4 + lxml |
| Site adapters | YAML/JSON config files |
| Data lake | MongoDB (NoSQL) |
| Validation DB | PostgreSQL |
| Web UI | FastAPI (current); React/Next.js (planned) |
| AI (local) | Ollama (open source, runs locally) |
| Source control | Git / GitHub |

## Functional Requirements (priority order)

1. **Harvester Agent** — Scrape dynamic manufacturer sites into MongoDB data lake
2. **Validator Agent** — Compare harvested vs GUDID, flag mismatches with confidence scores and severity
3. **Review Dashboard** — Side-by-side FDA vs manufacturer data, reviewer-only access
4. **Feedback System** — Reviewer decisions improve Validator over time
5. **Data Storage** — Admin setup and maintenance
6. **GUDID Import** — Admin-triggered FDA data import (file upload or API)
7. **Login & Permissions** — Role-based access (Reviewer vs Administrator)
8. **Reports & Stats** — Reviewers: volume/accuracy metrics; Admins: confidence distributions, false positive/negative rates, processing times

## Non-Functional Requirements

- **Performance**: Reasonable harvest times, fast dashboard loads, timeout/retry for slow sites
- **Reliability**: Handle failures without crashing, log errors, retry, continue to next device/site
- **Accuracy**: Normalize before comparing to avoid false flags; include confidence scores and explanations
- **Traceability**: Every value traceable to source URL + timestamp; all reviewer actions logged (who, when, why)
- **Security**: Role-based permissions enforced, no hardcoded credentials
- **Maintainability**: Modular to add new manufacturers; documented for future teams
- **Usability**: Simple Approve/Reject/Edit buttons, reason codes, filters and sorting by priority
- **Cost**: Open-source / free tools only; runnable locally on a dev machine

## Target manufacturer sites

Source: `docs/Target Brands.xlsx` — Batch-01 (42 products across 8 manufacturers)

GUDID database: https://accessgudid.nlm.nih.gov/

| Manufacturer | Brand Names |
|---|---|
| Medtronic (10) | IN.PACT ADMIRAL, PROTEGE EVERFLEX, HAWKONE, EVERFLEX, IN.PACT, VISI-PRO, PROTEGE GPS, IN.PACT AV, RESOLUTE ONYX, SILVERHAWK, TURBOHAWK |
| Abbott Vascular (8) | DIAMONDBACK PERIPHERAL, OMNILINK ELITE, ABSOLUTE PRO, DIAMONDBACK 360, SUPERA, SUPERA VERITAS, ESPRIT, XIENCE SKYPOINT |
| Boston Scientific (8) | RANGER, ELUVIA, INNOVA VASCULAR, EXPRESS LD BILIARY, JETSTREAM XC, EPIC VASCULAR, SYNERGY XD, FLEXTOME |
| Shockwave Medical (5) | SHOCKWAVE M5, SHOCKWAVE E8, SHOCKWAVE S4, LITHOPLASTY, SHOCKWAVE L6 |
| Cook (4) | ZILVER PTX, ZILVER 635, ZILVER 518, ZILVER FLEX 35 |
| W L Gore & Associates (3) | VIABAHN VBX, VIABAHN, TIGRIS VASCULAR STENT |
| Cordis (2) | S.M.A.R.T. CONTROL, PALMAZ GENESIS |
| Terumo (1) | R2P MISAGO |
