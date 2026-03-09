# Jason — Implementation Checklist

Based on: *Jason - Independent Work Plan & Implementation Guide.md*

Check off each item as you complete it.

---

## Stage 1 — Project Setup

- [x] Create and activate virtual environment (`venv/`)
- [x] Create `requirements.txt` with pinned versions
- [x] Add `.gitignore` (`.env`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `venv/`)
- [x] Add `pytest.ini` with `pythonpath = harvester/src` so tests can be run from project root
- [x] Create `.env.example` (commit this — not the real `.env`)

---

## Stage 2 — Normalizers (`harvester/src/normalizers/`)

### Unit Conversions
- [x] `unit_conversions.py` — `normalize_measurement()` for length → mm, weight → g, volume → mL, pressure → mmHg
- [x] `tests/test_units.py` — length, weight, volume, pressure, range values, edge cases (34 tests passing)

### Manufacturer Names
- [x] `manufacturers.py` — `normalize_manufacturer()` with alias map for all 8 Batch-01 manufacturers
- [x] `tests/test_manufacturers.py` — all variant spellings, case-insensitivity, unknown fallback, empty input

### Model Numbers
- [x] `model_numbers.py` — `clean_model_number()` strips prefixes (Model:, Cat. No., REF, SKU, Part Number, P/N), uppercases, collapses whitespace
- [x] `tests/test_model_numbers.py` — each prefix type, uppercase, whitespace collapse, empty/None input, prefix-only → None

### Text Fields
- [x] `text.py` — `clean_text()` HTML entity decode, NFKC unicode normalize, remove invisible chars, collapse whitespace
- [x] `tests/test_text.py` — HTML entities, zero-width spaces, BOM, non-breaking spaces, whitespace, empty input

### Date Normalization
- [x] `dates.py` — `normalize_date()` → ISO 8601 (YYYY-MM-DD), handles 11+ input formats including European
- [x] `tests/test_dates.py` — US format, ISO passthrough, long/short month names, European day-first, compact, unparseable → None

---

## Stage 3 — Validation (`harvester/src/validators/`)

- [ ] `record_validator.py` — `validate_record(record) → (bool, list[str])`: required fields, numeric ranges, string lengths, URL validity
- [ ] `tests/test_record_validator.py` — missing required fields, invalid dimensions, suspicious ranges, bad URLs, clean record

---

## Stage 4 — Security (`harvester/src/security/`)

- [ ] `credentials.py` — `CredentialManager` class using `python-dotenv`, naming: `FIVOS_{MANUFACTURER}_{FIELD}`, never logs values
- [ ] `sanitizer.py` — `sanitize_html()` strips `<script>`, `<iframe>`, `<object>`, `<embed>`, `<form>`, all `on*` event attributes
- [ ] `tests/test_sanitizer.py` — XSS via script tag, iframe, onerror attr, clean HTML passthrough

---

## Stage 5 — Pipeline (`harvester/src/pipeline/`)

- [x] `parser.py` — `parse_html()`, `parse_json()`, `parse_xml()`, `parse_document(raw, fmt)` — multi-format routing (html/json/xml); errors return safe empty/None values, never raise
- [x] `extractor.py` — `extract_fields(parsed_data, adapter, fmt)` — CSS selectors (HTML), dot-path (JSON), XPath (XML); missing fields → log warning + None
- [x] `tests/test_parser.py` — valid HTML / empty / malformed; valid JSON dict / JSON list / invalid JSON; valid XML / malformed XML; `parse_document` routing; unknown format raises ValueError
- [x] `tests/test_extractor.py` — HTML: field found / missing / multiple; JSON: top-level / nested dot-path / missing key; XML: XPath hit / miss / nested

---

## Stage 6 — End-to-End Integration Test

- [ ] Save a real manufacturer HTML page to `tests/fixtures/medtronic_sample.html`
- [ ] Create `tests/fixtures/mock_adapters.py` with CSS selectors matching the saved HTML
- [ ] `tests/test_pipeline_e2e.py` — full pipeline: saved HTML → parse → extract → normalize → validate → result dict

---

## Stage 7 — Emit / Metadata Packaging (Stage 5 of normalization pipeline)

- [ ] Add `package_record()` function that wraps normalized record with:
  - `harvest_run_id` (from Jonathan's run manager — mock it for now)
  - `harvested_at` (UTC timestamp)
  - `source_url`
  - `adapter_version`
  - `normalization_version`
  - `validation_issues`
  - SHA-256 hash of raw HTML

---

## Waiting on Teammates

| When Ready | What You Need |
|---|---|
| **Wyatt** | Real rendered HTML flowing into `parse_html()` |
| **Ryan** | Real YAML/JSON adapter configs replacing mock adapters |
| **Ralph** | `save_record(record: dict)` function to call from Stage 5 |
| **Jonathan** | Real `harvest_run_id` injected into metadata packaging |
