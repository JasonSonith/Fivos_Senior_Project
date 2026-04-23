# Validators

Compares harvested device records against the FDA GUDID database and validates record quality.

## Modules

| File | Role | Key Functions |
|------|------|---------------|
| `gudid_client.py` | FDA GUDID API integration | `search_gudid_di()`, `fetch_gudid_record()`, `lookup_by_di()` |
| `comparison_validator.py` | Field-by-field comparison | `compare_records(harvested, gudid)` |
| `record_validator.py` | Local record quality checks | `validate_record(record)` → `(is_valid, issues)` |

## Comparison Scoring

`compare_records()` returns `(per_field, summary)` where each per-field entry has a `status` string from the `FieldStatus` enum:

| Status | Numerator | Denominator | Visual |
|---|---|---|---|
| `match` | +1 | +1 | Green badge |
| `mismatch` | +0 | +1 | Red badge |
| `corporate_alias` | +1 | +1 | Blue badge, shows canonical parent name |
| `not_compared` | — | — | Muted badge (harvested null, asymmetric) |
| `both_null` | — | — | Muted badge (neither side has value) |
| `sku_label_skip` | — | — | Amber badge (deviceDescription only, quality check triggered) |

**Compared fields (unweighted denominator):**

| Field | Weight | Semantic |
|---|---|---|
| `versionModelNumber` | 3 | normalized exact |
| `catalogNumber` | 3 | normalized exact |
| `brandName` | 3 | normalized via clean_brand_name |
| `companyName` | 3 | normalized + alias fallback |
| `gmdnPTName` | 3 | case-insensitive exact |
| `productCodes` | 3 | set(h) ⊆ set(g) |
| `MRISafetyStatus` | 2 | normalize_mri_status |
| `singleUse`, `rx` | 2 each | normalize_boolean |
| `gmdnCode`, `deviceCountInBase`, `issuingAgency` | 2 each | exact |
| `premarketSubmissions` | 2 | set(h) ⊆ set(g) |
| `lotBatch`, `serialNumber`, `manufacturingDate`, `expirationDate` | 1 each | normalize_boolean |
| `deviceDescription` | 1 | Jaccard, quality-gated |
| `deviceSizes` | 2 | subset by sizeType, unit-canonicalized, per-unit absolute tolerance (mm 0.05, g/mL 0.1, mmHg 0.5). Result carries a `per_type` list used by the review UI — sub-rows render only on aggregate `mismatch`. |

**Weighted vs unweighted scoring:** every field contributes `FIELD_WEIGHTS[field]` to the weighted numerator/denominator and `1` to the unweighted counts. Validation status (`matched`/`partial_match`/`mismatch`) is always derived from unweighted — weighted is display/audit only.

**Scoring-eligibility dependency on description quality:** `deviceDescription` contributes to the weighted score *only when the quality classifier returns False* (GUDID value is prose, not a SKU label). Two devices with identical harvested descriptions can have different weighted denominators if their GUDID descriptions differ in quality. Correct behavior, but surprising — the denominator is data-dependent.

**Corporate alias resolution:** when a literal `companyName` mismatch is found, `canonical_company()` resolves both sides via `company_aliases.py`. If both resolve to the same parent (e.g., "Covidien LP" → "Medtronic" and "Medtronic Inc." → "Medtronic"), status is `corporate_alias` and the pair counts as a match. The `alias_group` field on the result carries the canonical parent name.

**GUDID description quality classifier** (`_gudid_description_is_sku_label`): triggers when ANY of:
- length < 40 chars
- contains the device's `versionModelNumber` or `catalogNumber` verbatim
- ≥70% uppercase letter ratio
- fully matches `[A-Z0-9\-_ ]+` (no lowercase, no sentence structure)

On trigger: `status=sku_label_skip`, `similarity=None`, field excluded from both scoring formulas.

Null handling (legacy four identifier fields): harvested null → `not_compared` (asymmetric — present-harvested + null-GUDID still scores `mismatch`). All other fields: either-side null → `not_compared`. Both sides null: `both_null` for every field.

## GUDID deactivated short-circuit

When `fetch_gudid_record()` returns a device with `deviceRecordStatus == "Deactivated"`, `run_validation()` skips `compare_records()` entirely and writes a `validationResults` document with:
- `status: "gudid_deactivated"`
- `matched_fields`, `total_fields`, `match_percent`, `weighted_percent`, `description_similarity`: all `None`
- `comparison_result`: `None`

Deactivated records do NOT populate `verified_devices` and do NOT trigger `_merge_gudid_into_device()` — stale GUDID shouldn't overwrite live harvested data. The review page shows a warning banner and falls back to the `mode="info"` read-only layout.

## GUDID API

- Search (HTML scrape): `https://accessgudid.nlm.nih.gov/devices/search`
- Lookup (JSON): `https://accessgudid.nlm.nih.gov/api/v3/devices/lookup.json?di=...`

## Record Validation

Blocking: missing `device_name`/`manufacturer`/`model_number`, invalid `source_url`.
Non-blocking: out-of-range dimensions, string length, invalid boolean types, invalid MRI enum.
