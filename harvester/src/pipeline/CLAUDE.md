# Pipeline Layer

Transforms raw HTML from the web scraper into GUDID-aligned JSON records.

**Data flow:** Web Scraper → **Pipeline** → JSON → MongoDB → Validation

## Modules

| File | Role | Key Functions |
|------|------|---------------|
| `runner.py` | CLI entry point, end-to-end orchestration | `process_batch()`, `main()`, `scrape_urls()`, `write_records_to_db()` |
| `llm_extractor.py` | **Primary extractor.** LLM two-pass extraction | `extract_all_fields()`, `extract_page_fields()`, `extract_product_rows()` |
| `parser.py` | Raw content → typed objects | `parse_html()` → BS4 |
| `extractor.py` | CSS selector extraction (legacy `--adapter` path) | `extract_fields(parsed, adapter_config)` |
| `dimension_parser.py` | Mine measurements from specs text | `parse_dimensions_from_specs()` |
| `regulatory_parser.py` | Regex booleans from warning text | `parse_regulatory_from_text()` |
| `emitter.py` | Build + write GUDID output | `package_gudid_record()`, `write_record_json()` |

## Pipeline Stages

```
sanitize → parse → extract (Ollama) → normalize → validate → package → JSON
```

Extraction uses Ollama by default (two-pass: page-level fields + product table rows). CSS adapters are a legacy override via `--adapter` flag.

## End-to-End CLI

```bash
# Full pipeline: scrape → extract → DB (append) → validate
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt

# With DB overwrite
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --overwrite

# Extract only (no scrape, no DB)
python harvester/src/pipeline/runner.py

# Extract + DB + validate
python harvester/src/pipeline/runner.py --db --validate

# Single file
python harvester/src/pipeline/runner.py --input file.html
```

**Flags:** `--urls FILE`, `--db`, `--overwrite`, `--validate`, `--no-validate`, `--input`, `--input-dir`, `--output-dir`, `--run-id`, `-v`

`--urls` triggers end-to-end mode (scrape + DB + validate all on by default). Extraction is sequential (Ollama handles one page at a time).

## Field Classification

```python
TEXT_FIELDS        = {"description", "brand_name", "product_type", "specs_container", "warning_text"}
MODEL_FIELDS       = {"model_number", "catalog_number", "sku"}
DATE_FIELDS        = {"approval_date", "clearance_date", "expiration_date"}
MEASUREMENT_FIELDS = {"length", "width", "height", "diameter", "weight", "volume", "pressure"}
```

## Premarket Submission Extraction

`premarketSubmissions` (K-numbers, PMA numbers, DEN-numbers) are extracted via regex in `regulatory_parser.extract_premarket_submissions()`, NOT via the LLM. The regex requires a regulatory keyword (510(k), premarket, PMA, FDA clearance, K-number, cleared by FDA) within ±40 characters of each match — this prevents false positives on catalog SKUs that happen to start with `K` followed by 6–7 digits.

The LLM pipeline (`extract_all_fields`) invokes the regex extractor over the concatenation of `warning_text`, `description`, and `indicationsForUse` after the page-fields pass returns. `premarketSubmissions` is attached to each record before insertion into MongoDB.

## LLM Schema Fields (Pass 1 — page-level)

`extract_page_fields()` prompts the LLM for:
- `device_name`, `manufacturer`, `description`, `warning_text`
- `MRISafetyStatus` (enum string)
- `deviceKit` (bool)
- `environmentalConditions` (object with conditions array)
- `indicationsForUse` (free text; added PR2)
- `contraindications` (free text; added PR2)
- `deviceClass` (enum "I"/"II"/"III"; added PR2)

`premarketSubmissions` is NOT in the LLM schema — populated by regex post-processing after the pass returns.

## Error Handling ("never crash the run")

| Stage | Failure | Behavior |
|-------|---------|----------|
| parse | Malformed content | Log + skip |
| extract | Ollama timeout/error | Log + skip file |
| normalize | Unparseable value | Keep in `raw_<field>` + flag |
| validate critical | Required field missing | Reject + log |
| validate non-critical | Suspicious value | Emit with `issues` list |
| DB write | MongoDB unavailable | Log warning, JSON files already saved |
