# Validators

Compares harvested device records against the FDA GUDID database and validates record quality.

## Modules

| File | Role | Key Functions |
|------|------|---------------|
| `gudid_client.py` | FDA GUDID API integration | `search_gudid_di()`, `fetch_gudid_record()`, `lookup_by_di()` |
| `comparison_validator.py` | Field-by-field comparison | `compare_records(harvested, gudid)` |
| `record_validator.py` | Local record quality checks | `validate_record(record)` → `(is_valid, issues)` |

## Comparison Scoring

`compare_records()` compares 4 boolean fields + 1 similarity score:

- `versionModelNumber`, `catalogNumber`: normalized exact match (strip spaces/hyphens/dots, uppercase)
- `brandName`: case-insensitive, strip trademark symbols
- `companyName`: uppercase, strip punctuation
- `deviceDescription`: Jaccard word-set similarity (float 0.0–1.0)

Fields where harvested value is `None` → `match: None` (excluded from score denominator).

## GUDID API

- Search (HTML scrape): `https://accessgudid.nlm.nih.gov/devices/search`
- Lookup (JSON): `https://accessgudid.nlm.nih.gov/api/v3/devices/lookup.json?di=...`

## Record Validation

Blocking: missing `device_name`/`manufacturer`/`model_number`, invalid `source_url`.
Non-blocking: out-of-range dimensions, string length, invalid boolean types, invalid MRI enum.
