# Design: Treat GUDID Not Found as Mismatch

**Date:** 2026-04-20  
**Author:** Jason  
**Status:** Approved

## Problem

When GUDID lookup fails to find a matching record for a harvested device, `run_validation()` stores `status: "gudid_not_found"` in `validationResults`. These records are excluded from all dashboard stats and the validation results table, making them invisible to reviewers.

## Goal

GUDID not-found devices should appear in the Mismatches count and table on the dashboard, with a Review link, identical to true mismatches.

## Approach

Store `"mismatch"` instead of `"gudid_not_found"` in `validationResults`. No frontend changes are needed — the dashboard already handles `"mismatch"` records correctly throughout.

## Changes

### 1. `harvester/src/orchestrator.py` — `run_validation()`

- Change `status: "gudid_not_found"` → `status: "mismatch"` in the `validation_col.insert_one()` call for the not-found path (line ~372)
- Move the increment from `result["not_found"] += 1` → `result["mismatches"] += 1`
- Keep `"not_found": 0` in the return dict for backwards compatibility

### 2. `harvester/src/orchestrator.py` — `migrate_gudid_not_found()`

Add a one-time migration helper:

```python
def migrate_gudid_not_found() -> dict:
    from database.db_connection import get_db
    db = get_db()
    r = db["validationResults"].update_many(
        {"status": "gudid_not_found"},
        {"$set": {"status": "mismatch"}},
    )
    return {"matched": r.matched_count, "modified": r.modified_count}
```

### 3. Migration trigger

Call `migrate_gudid_not_found()` once from the validate route (`app/routes/validate.py`) on startup or as a one-time admin action. Alternatively, run directly from the Python REPL.

## No Frontend Changes Required

| Component | Why no change needed |
|-----------|---------------------|
| `get_dashboard_stats()` | Already queries `{"status": "mismatch"}` |
| `get_all_dashboard_records()` | Already queries `$in: ["partial_match", "mismatch"]` |
| Dashboard template | Already renders danger badge + Review link for `"mismatch"` |

## Data Integrity

- The `not_found` return key is preserved (set to 0) so any callers reading that field don't break.
- `gudid_record: null` and `comparison_result: null` remain on the mismatch documents — the Review page already handles null comparison gracefully (the review route only shows the Review button for partial_match/mismatch, which these now are).
- No device document changes needed.

## Out of Scope

- Distinguishing "no GUDID record found" vs "fields compared but all failed" in the UI — user explicitly wants them identical.
- Adding a separate "Not Found" metric card.
