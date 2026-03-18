# Pipeline Layer

Transforms raw HTML/JSON/XML from the web scraper into GUDID-aligned JSON records.

**Data flow:** Web Scraper → **Pipeline** → MongoDB

## Modules

| File | Role | Key Functions |
|------|------|---------------|
| `runner.py` | Orchestrator / CLI entry point | `process_single()`, `process_batch()`, `run_stage()` |
| `parser.py` | Raw content → typed objects | `parse_html()` → BS4, `parse_json()` → dict, `parse_xml()` → Element |
| `extractor.py` | CSS selector extraction via adapter YAML | `extract_fields(parsed, adapter_config)` → `dict[str, str]` |
| `dimension_parser.py` | Mine measurements from `specs_container` text | `parse_dimensions(specs_text)` → `dict[str, str]` |
| `regulatory_parser.py` | Regex booleans from `warning_text` | `parse_regulatory_flags(warning_text)` → `dict[str, bool]` |
| `emitter.py` | Build + write GUDID output | `package_gudid_record()`, `write_record_json()` |

`dimension_parser.py` handles 3 formats: tabular (`Length\t4.5 cm`), key-value (`Length: 4.5 cm`), and embedded description strings (Terumo-style).

## Pipeline Stages (runner.py)

```
sanitize → parse → extract → normalize → validate → package
```

1. **sanitize** — strip malformed HTML, normalize whitespace
2. **parse** — `parser.py` → BeautifulSoup / dict / Element
3. **extract** — `extractor.py` → `{field: raw_string}`
4. **normalize** — `dimension_parser.py` + `regulatory_parser.py` → `{field: typed_value}`
5. **validate** — check required fields, populate `issues` list
6. **package** — `emitter.py` → GUDID dict → `output/*.json`

## Field Classification

```python
TEXT_FIELDS        = {"description", "brand_name", "product_type", "specs_container", "warning_text"}
MODEL_FIELDS       = {"model_number", "catalog_number", "sku"}
DATE_FIELDS        = {"approval_date", "clearance_date", "expiration_date"}
MEASUREMENT_FIELDS = {"length", "width", "height", "diameter", "weight", "volume", "pressure"}
BOOLEAN_FIELDS     = {"singleUse", "deviceSterile", "sterilizationPriorToUse", "rx", "otc"}
ENUM_FIELDS        = {"MRISafetyStatus"}
```

`MEASUREMENT_FIELDS` → `{"value": float, "unit": str}` | `DATE_FIELDS` → ISO 8601 | `MODEL_FIELDS` → uppercased

## Error Handling ("never crash the run")

All errors are caught in `run_stage()`. The run always continues to the next record.

| Stage | Failure | Behavior |
|-------|---------|----------|
| parse | Malformed content | Log + store raw HTML + skip |
| extract | Selector miss | Log; emit partial if required fields present |
| normalize | Unparseable value | Keep in `raw_<field>` + flag |
| validate critical | Required field missing | Reject + log |
| validate non-critical | Suspicious value | Emit with `issues` list |

## Running

See root `CLAUDE.md` for full CLI reference.

```bash
python harvester/src/pipeline/runner.py --adapter <yaml> --input <html>
python harvester/src/pipeline/runner.py --adapter-dir harvester/src/site_adapters --input-dir harvester/src/web-scraper/out_html
# --output-dir DIR  --run-id HR-10011  -v
```

## Adding a New Field

1. Add selector to the adapter YAML in `harvester/src/site_adapters/`
2. Add field name to the correct set in `runner.py`
3. Add normalization logic: dimension → `dimension_parser.py`, boolean → `regulatory_parser.py`, other → inline in `runner.py`
4. Add GUDID mapping in `emitter.py`'s `package_gudid_record()`
5. Add a test in `tests/test_pipeline_e2e.py`
