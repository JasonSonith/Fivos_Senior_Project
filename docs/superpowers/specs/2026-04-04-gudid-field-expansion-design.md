# GUDID Field Expansion & Fallback Merge — Design Spec

**Date:** 2026-04-04  
**Author:** Jason Sonith  
**Status:** Approved

---

## Goal

Build the most accurate, up-to-date database of medical devices by:
1. Extracting more fields from manufacturer websites (which are more current than GUDID)
2. Filling any null harvested fields with GUDID values as a fallback

**Conflict resolution:** Harvested value always wins. If harvested is null, use GUDID.

---

## New Fields to Extract from Manufacturer Sites

### `regulatory_parser.py` — Regex-based booleans (fire against `warning_text`)

| Field | GUDID key | Trigger phrases |
|-------|-----------|-----------------|
| NRL present | `labeledContainsNRL` | "contains natural rubber latex", "made with natural rubber latex", "contains latex" |
| NRL absent | `labeledNoNRL` | "latex-free", "does not contain natural rubber latex", "not made with natural rubber latex" |
| Sterilize before use | `sterilizationPriorToUse` | "sterilize before use", "must be sterilized", "requires sterilization" |
| Over-the-counter | `otc` | "over the counter", "over-the-counter", "OTC", "without a prescription" |

### `llm_extractor.py` — Semantic fields added to PAGE_FIELDS_SCHEMA + PAGE_FIELDS_PROMPT

| Field | GUDID key | Type | Extraction notes |
|-------|-----------|------|-----------------|
| Is a kit | `deviceKit` | `boolean\|null` | True if sold as a system/kit with multiple components |
| 510k/PMA numbers | `premarketSubmissions` | `string[]\|null` | e.g. `["K123456", "P210034"]`. GUDID stores objects — `gudid_client.py` extracts just the `submissionNumber` strings for consistency. |
| Storage conditions | `environmentalConditions` | `object\|null` | `{storageTemperature: "15-30°C", storageHumidity: "< 85%"}` |

---

## GUDID-Fallback Merge

### When it runs
In `orchestrator.py` → `run_validation()`, after `fetch_gudid_record()` returns, before the validation result is written to MongoDB.

### Logic
```python
for field in MERGE_FIELDS:
    if device[field] is None and gudid[field] is not None:
        db.devices.update_one({_id}, {$set: {field: gudid[field]}})
        track field in gudid_sourced_fields list
```

### MERGE_FIELDS
```python
MERGE_FIELDS = [
    "catalogNumber",
    "labeledContainsNRL", "labeledNoNRL",
    "sterilizationPriorToUse", "otc",
    "deviceKit",
    "premarketSubmissions",
    "environmentalConditions",
    "brandName", "versionModelNumber", "companyName", "deviceDescription",
    "MRISafetyStatus", "singleUse", "rx",
]
```

### Traceability
Each device document gets a `gudid_sourced_fields: ["catalogNumber", ...]` array recording which values came from GUDID vs. the manufacturer page.

---

## Data Flow

```
Playwright scrape → sanitize → parse HTML
  → llm_extractor.extract_page_fields()     [+ deviceKit, premarketSubmissions, environmentalConditions]
  → regulatory_parser.parse_regulatory()    [+ labeledContainsNRL, labeledNoNRL, sterilizationPriorToUse, otc]
  → normalize → emitter.package_gudid_record()
  → MongoDB (devices)
  → run_validation():
      fetch_gudid_record()                  [expanded to return full field set]
      _merge_gudid_into_device()            [null harvested ← GUDID value]
      comparison_validator.compare_records()
      insert validation result
```

---

## Files Changed

| File | Change |
|------|--------|
| `harvester/src/pipeline/regulatory_parser.py` | Add 4 regex patterns: NRL present/absent, sterilizationPriorToUse, otc |
| `harvester/src/pipeline/llm_extractor.py` | Expand PAGE_FIELDS_SCHEMA + PAGE_FIELDS_PROMPT with deviceKit, premarketSubmissions, environmentalConditions |
| `harvester/src/pipeline/runner.py` | Ensure new regulatory fields are passed through to the record |
| `harvester/src/validators/gudid_client.py` | Expand fetch_gudid_record() to return all MERGE_FIELDS from API response |
| `harvester/src/orchestrator.py` | Add _merge_gudid_into_device() helper, call in run_validation() |
| `harvester/src/pipeline/emitter.py` | Include new fields in package_gudid_record() output |

---

## Schema Notes

No MongoDB migration needed — schemaless. New fields appear on new records. Existing records get null for new fields; they will be backfilled on the next validation run via the GUDID merge.

---

## Out of Scope

- GUDID-only fields (deviceId/DI barcodes, dunsNumber, DMExempt, gmdnTerms, fdaProductCode) — not extractable from manufacturer sites, not worth storing from GUDID
- Review dashboard UI changes — existing `/review` workflow handles discrepancies as-is
- Backfill script for existing records — next validation run handles this naturally
