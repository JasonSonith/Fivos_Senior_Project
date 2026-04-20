# Validator Field Expansion (MRI / Single-Use / Rx) — Design Spec

**Date:** 2026-04-20
**Author:** Jason Sonith
**Status:** Approved

---

## Goal

Extend `compare_records()` so the GUDID validator checks three additional fields beyond the current four identifier fields:

- `MRISafetyStatus` (enum)
- `singleUse` (boolean)
- `rx` (boolean — prescription use)

All three are already harvested by the pipeline and already fetched from GUDID. Only the comparison layer needs to change.

---

## Current State

`harvester/src/validators/comparison_validator.py` compares four identifier fields plus a similarity score:

| Field | Strategy |
|-------|----------|
| `versionModelNumber` | Normalized exact (strip spaces/hyphens/dots, uppercase) |
| `catalogNumber` | Normalized exact (same as above) |
| `brandName` | Case-insensitive, strip trademark symbols |
| `companyName` | Uppercase, strip punctuation |
| `deviceDescription` | Jaccard word-set similarity (float 0.0–1.0) |

Null handling: if the harvested value is missing, the field result is `{"match": None}` and is excluded from the score denominator in `orchestrator.run_validation()`.

---

## Changes

### 1. `comparison_validator.py`

Add three new entries to the result dict produced by `compare_records()`.

**`MRISafetyStatus`** — normalize both sides through `normalize_mri_status()` from `harvester/src/normalizers/booleans.py`, then exact string compare.

**`singleUse`** — normalize both sides through `normalize_boolean()` from the same module, then compare `True == True` / `False == False`.

**`rx`** — same strategy as `singleUse`.

Null rule: if **either** side normalizes to `None`, set `{"match": None}` and skip from score denominator. This intentionally differs from the existing four identifier fields, where a present-harvested / null-GUDID case scores as mismatch. The new fields are often missing on one side or the other (unlike the identifier fields), so skipping on either-side null keeps `match_percent` meaningful.

GUDID side may arrive as either a raw string (`"true"`, `"Yes"`, `"MR Conditional"`) or already a bool/enum — pushing both sides through the normalizer handles either case.

### 2. `orchestrator.py`

No code change required. `run_validation()` already filters `compared = {k: v for k, v in comparison.items() if k != "deviceDescription" and v.get("match") is not None}` and computes `match_percent = matched_fields / total_fields * 100`. The denominator grows automatically from 4 to up-to-7 as the new fields are added.

Status thresholds stay unchanged:
- `matched_fields == total_fields` → `matched`
- `matched_fields > 0` → `partial_match`
- else → `mismatch`

**Behavioral note:** Records that previously scored `matched` (4/4) may drop to `partial_match` if they harvested one of the new fields and it disagrees with GUDID. This is the intended effect — the validator is catching discrepancies that were previously invisible.

### 3. `app/routes/review.py`

Extend the `COMPARED_FIELDS` list (drives both the template rendering and the POST form-field iteration):

```python
COMPARED_FIELDS = [
    ("versionModelNumber", "Version / Model Number"),
    ("catalogNumber", "Catalog Number"),
    ("brandName", "Brand Name"),
    ("companyName", "Company Name"),
    ("deviceDescription", "Device Description"),
    ("MRISafetyStatus", "MRI Safety Status"),
    ("singleUse", "Single Use"),
    ("rx", "Prescription (Rx)"),
]
```

No template change needed — `review.html` already iterates `fields` generically.

### 4. `harvester/src/validators/tests/test_comparison_validator.py` (new file)

No test file exists for this module today. Create one covering:

- Four-identifier baseline still works (regression)
- `MRISafetyStatus` match (`"MR Safe"` vs `"MR Safe"`)
- `MRISafetyStatus` mismatch (`"MR Safe"` vs `"MR Conditional"`)
- `MRISafetyStatus` variant normalization (`"mri safe"` harvested vs `"MR Safe"` GUDID → match)
- `singleUse` match (`True`/`True`, `False`/`False`)
- `singleUse` mismatch (`True` vs `False`)
- `singleUse` GUDID-as-string (`True` harvested vs `"true"` GUDID → match)
- `rx` match and mismatch
- Null skip: harvested `None` → `match: None` for each new field
- Null skip: GUDID `None` → `match: None` for each new field
- Null skip: both sides `None` → `match: None`

### 5. `harvester/src/validators/CLAUDE.md`

Update the Comparison Scoring section to list 7 match fields instead of 4. One-line edit.

---

## Non-Goals

- No change to `_merge_gudid_into_device()` — the three new fields are already in `MERGE_FIELDS`, so null-backfill from GUDID already works.
- No weighting — all seven match fields count equally toward `match_percent`.
- No new UI fields beyond the three rows added via `COMPARED_FIELDS`.
- No migration of existing `validationResults` documents. New runs produce new results; stale rows keep their old shape until revalidated.

---

## Testing Plan

1. Unit tests in new `test_comparison_validator.py` (see section 4 above).
2. Existing `test_record_validator.py` suite continues to pass.
3. End-to-end: re-run validation on an existing harvest where at least one device has harvested `MRISafetyStatus`. Confirm new field appears in `validationResults.comparison_result` and on the review page.

---

## Files Changed

| File | Change |
|------|--------|
| `harvester/src/validators/comparison_validator.py` | Add 3 fields to `compare_records()`, import `normalize_boolean` + `normalize_mri_status` |
| `app/routes/review.py` | Add 3 entries to `COMPARED_FIELDS` |
| `harvester/src/validators/tests/test_comparison_validator.py` | **New** — unit tests |
| `harvester/src/validators/CLAUDE.md` | Update comparison scoring line (4 → 7 fields) |
