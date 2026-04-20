# Validators

Compares harvested device records against the FDA GUDID database and validates record quality.

## Modules

| File | Role | Key Functions |
|------|------|---------------|
| `gudid_client.py` | FDA GUDID API integration | `search_gudid_di()`, `fetch_gudid_record()`, `lookup_by_di()` |
| `comparison_validator.py` | Field-by-field comparison | `compare_records(harvested, gudid)` |
| `record_validator.py` | Local record quality checks | `validate_record(record)` → `(is_valid, issues)` |

## Comparison Scoring

`compare_records()` compares 7 boolean fields + 1 similarity score:

- `versionModelNumber`, `catalogNumber`: normalized exact match (strip spaces/hyphens/dots, uppercase)
- `brandName`: case-insensitive, strip trademark symbols
- `companyName`: uppercase, strip punctuation
- `deviceDescription`: Jaccard word-set similarity (float 0.0–1.0)
- `MRISafetyStatus`: normalize both sides via `normalize_mri_status()`, exact compare
- `singleUse`, `rx`: normalize both sides via `normalize_boolean()`, exact compare

Null handling:
- Identifier fields (`versionModelNumber`, `catalogNumber`, `brandName`, `companyName`) → `match: None` only if **harvested** is null
- New fields (`MRISafetyStatus`, `singleUse`, `rx`) → `match: None` if **either** side normalizes to null

Fields with `match: None` are excluded from the score denominator in `orchestrator.run_validation()`.

## GUDID API

- Search (HTML scrape): `https://accessgudid.nlm.nih.gov/devices/search`
- Lookup (JSON): `https://accessgudid.nlm.nih.gov/api/v3/devices/lookup.json?di=...`

## Record Validation

Blocking: missing `device_name`/`manufacturer`/`model_number`, invalid `source_url`.
Non-blocking: out-of-range dimensions, string length, invalid boolean types, invalid MRI enum.
