# Pipeline Layer

Transforms raw HTML from the web scraper into GUDID-aligned JSON records.

**Data flow:** Web Scraper → **Pipeline** → JSON → MongoDB → Validation

## Modules

| File | Role | Key Functions |
|------|------|---------------|
| `runner.py` | CLI entry point, end-to-end orchestration | `process_batch()`, `main()`, `scrape_urls()`, `write_records_to_db()` |
| `ollama_extractor.py` | **Primary extractor.** LLM two-pass extraction | `extract_all_fields()`, `extract_page_fields()`, `extract_product_rows()` |
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

**Flags:** `--urls FILE`, `--db`, `--overwrite`, `--validate`, `--no-validate`, `--workers N`, `--input`, `--input-dir`, `--output-dir`, `--run-id`, `-v`

`--urls` triggers end-to-end mode (scrape + DB + validate all on by default). `--workers` controls concurrent Ollama extraction threads (default: 4).

## Field Classification

```python
TEXT_FIELDS        = {"description", "brand_name", "product_type", "specs_container", "warning_text"}
MODEL_FIELDS       = {"model_number", "catalog_number", "sku"}
DATE_FIELDS        = {"approval_date", "clearance_date", "expiration_date"}
MEASUREMENT_FIELDS = {"length", "width", "height", "diameter", "weight", "volume", "pressure"}
```

## Error Handling ("never crash the run")

| Stage | Failure | Behavior |
|-------|---------|----------|
| parse | Malformed content | Log + skip |
| extract | Ollama timeout/error | Log + skip file |
| normalize | Unparseable value | Keep in `raw_<field>` + flag |
| validate critical | Required field missing | Reject + log |
| validate non-critical | Suspicious value | Emit with `issues` list |
| DB write | MongoDB unavailable | Log warning, JSON files already saved |
