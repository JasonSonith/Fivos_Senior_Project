# Design: Validator Correctness

**Date:** 2026-04-21
**Author:** Jason
**Status:** Approved

## Problem

An Atlas audit on 2026-04-21 surfaced four independent bugs in `run_validation()` and `compare_records()` that together explain most of the dashboard's reported discrepancies:

1. **Non-deterministic mapping.** A single harvested device can accumulate multiple `validationResults` documents, each pointing at a different `gudid_di`. Root cause: `run_validation()` calls `insert_one()` on every device every run with no upsert, and `search_gudid_di()` returns the first `/devices/<digits>` link in DOM order regardless of whether that DI matches the harvested catalog/model.
2. **`catalogNumber` silently dropped for 40 devices.** The device doc has the catalog populated, but `validationResults.comparison_result.catalogNumber.harvested` is null. Affects Zilver PTX (16), Zilver 635 (13), Diamondback 360 (10), PALMAZ GENESIS (1).
3. **3 Supera `mismatch` rows are all-null sentinels.** Every field in `comparison_result` has `harvested=None`, `gudid=None`, `match=None`. Failed validations getting written to the review queue instead of filtered.
4. **Dimensions are never compared.** `compare_records()` compares 7 identifier fields + description Jaccard. GUDID's `deviceSizes` array is ignored. Every harvested dimension (diameter, length, etc.) could be wrong and the validator would never flag it.

## Goals

- One harvested device maps to exactly one `validationResults` document and one specific GUDID DI, deterministic across re-runs.
- Re-validating an already-validated device updates the existing doc in place; does not accumulate.
- `catalogNumber` surfaces in `comparison_result` for every device where `devices.catalogNumber` is populated.
- Null-sentinel validations are excluded from the dashboard's review queue but remain inspectable.
- Dimension comparison (7 fields, unit-converted, tolerance-aware) added to `compare_records()`.
- Validator stays deterministic — no LLM in the validation path.

## Non-Goals

- Semantic description similarity (replacing Jaccard). Out of scope — pursue in a future spec if brand/description normalization becomes demo-critical.
- Brand/company name aliasing via LLM or synonym dictionaries. Out of scope.
- Changing the harvester side (rx extraction, Zilver 518 swap, dimension extraction quality). Those live in a separate Spec 1.

---

## F — One device → one GUDID DI, persisted

### F.1 Upsert by `device_id`

Replace every `validation_col.insert_one({...})` in `harvester/src/orchestrator.py:run_validation()` with:

```python
validation_col.update_one(
    {"device_id": device.get("_id")},
    {"$set": {..., "updated_at": datetime.now(timezone.utc)},
     "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
    upsert=True,
)
```

The `{"device_id": ...}` filter guarantees one doc per device. `updated_at` moves on every run; `created_at` stays set to first insert.

### F.2 Remove `validation_col.drop()` under `overwrite=True`

The current `if overwrite: validation_col.drop(); verified_col.drop()` nukes every historical entry, including devices that aren't in the current run. Replace with per-device DI refresh:

```python
if overwrite:
    # Force re-lookup of GUDID DI by clearing the cached identifier on every in-scope device
    devices_col.update_many(query, {"$unset": {"_gudid": ""}})
```

`verified_devices` continues to be upserted by `(versionModelNumber, catalogNumber)` (existing behavior) — no drop needed there either.

### F.3 GUDID DI caching on `devices`

Add a `_gudid` subdocument to each device doc:

```python
device["_gudid"] = {
    "di": "00733132637607",
    "resolved_at": datetime.now(timezone.utc),
    "match_confidence": "exact",   # or "low", "not_found"
}
```

On subsequent `run_validation()` calls, for each device:

1. If `device._gudid.di` exists and `force_rematch` is False → call `lookup_by_di(di)` directly, skip the search.
2. Else → run the full DI selection flow (F.4), then write the result back to `device._gudid`.

### F.4 Deterministic DI selection

Add `select_best_gudid_di(harvested, max_candidates=3)` in `harvester/src/validators/gudid_client.py`:

1. Search GUDID with `harvested.catalogNumber` (falls back to `versionModelNumber` if catalog is missing). Collect up to `max_candidates` candidate DIs from the search-results page in DOM order.
2. For each candidate, call `lookup_by_di(di)` to get the full record.
3. Score each candidate:
   - Both `_norm_model(catalogNumber)` and `_norm_model(versionModelNumber)` match → confidence `"exact"`, score 2.
   - Exactly one matches → confidence `"partial"`, score 1.
   - Neither matches → confidence `"low"`, score 0.
4. Return the highest-score candidate. Ties broken by smallest DI (lexicographic) for determinism.
5. If the search returns zero candidates → return `(None, None, "not_found")`.

Function signature:

```python
def select_best_gudid_di(
    harvested: dict,
    max_candidates: int = 3,
) -> tuple[str | None, dict | None, str]:
    """Returns (di, gudid_record, match_confidence)."""
```

### F.5 Handle the three confidence levels in `run_validation()`

```python
di, gudid_record, match_confidence = select_best_gudid_di(device)

if match_confidence == "not_found":
    # No GUDID candidates at all — store a sentinel, see F.6
    ...
elif match_confidence == "low":
    # Top candidate matched neither identifier — store with flag, surface in UI
    ...
elif match_confidence in ("partial", "exact"):
    comparison = compare_records(device, gudid_record)
    ...
```

Persist `match_confidence` on the `validationResults` doc. The dashboard + review UI render a badge when `match_confidence != "exact"` so reviewers know to double-check the pairing.

---

## B — Restore `catalogNumber` in `comparison_result`

Root cause is unknown until implementation-phase investigation. Hypotheses ranked by likelihood:

1. **A projection is dropping the field.** Somewhere between `devices_col.find(query)` and the call to `compare_records()`, the catalog value is stripped. Check for `.project()` calls, for copies that only whitelist certain keys.
2. **The field is stored under a different key on a subset of devices.** Perhaps `_harvest.catalogNumber` or a mistyped key name (e.g., `catalog_number` vs `catalogNumber`) for some manufacturers.
3. **Empty-string vs null.** `if not h` in `compare_records()` line 58 is falsy for `""` — if the 40 devices have empty-string catalogs rather than real values, it'd hit the `None` branch. But the audit said "`devices.catalogNumber` is populated," so this is unlikely.

### Implementation approach

1. Pick one representative device from the audit's list (e.g., Diamondback 360 `69e6a2be8281d5c55f290fff`, catalog `7-10057-08`).
2. Write a failing pytest that loads this exact device's fields as a dict, calls `compare_records(device, fake_gudid)`, and asserts `result["catalogNumber"]["harvested"] == "7-10057-08"`.
3. Run the test, confirm it fails.
4. Trace the code path. Fix at the root — whichever layer is dropping the field.
5. Confirm the test passes. Verify no regression on the other 40 devices' manufacturers.

**Acceptance:** every device where `devices.catalogNumber` is a non-empty string ends up with `validationResults.comparison_result.catalogNumber.harvested == devices.catalogNumber`.

---

## D — Filter null-sentinel validations

When `compare_records()` returns, check whether **all** comparable fields resolved to `match=None` AND description similarity is 0 AND the device identifier fields (`versionModelNumber`, `catalogNumber`) have `harvested=None`. This is the shape the audit found on the 3 Supera records.

### Handling

- `status = "invalid_gudid_response"` (new status value)
- Store in `validationResults` with normal fields but this sentinel status
- `get_all_dashboard_records()` and `get_dashboard_stats()` exclude rows with `status == "invalid_gudid_response"` from the review queue counters and from the discrepancy table
- Add an admin-only query (new route or bypass: `GET /admin/invalid-validations`) to surface them for manual inspection

### Why not just skip the insert

Skipping means the devices re-appear in the validate queue on every run with no record they were already attempted. Users have no visibility into "why isn't this device in the list?" The sentinel status preserves traceability.

---

## G-validator — Dimension comparison (7 fields)

### Fields compared

Same seven fields as `MEASUREMENT_FIELDS` in the pipeline:

| Field | Canonical unit | Tolerance rule |
|---|---|---|
| `length` | mm | `max(1% relative, 0.1mm absolute)` |
| `width` | mm | `max(1% relative, 0.1mm absolute)` |
| `height` | mm | `max(1% relative, 0.1mm absolute)` |
| `diameter` | mm | `max(1% relative, 0.1mm absolute)` |
| `weight` | g | 5% relative |
| `volume` | mL | 5% relative |
| `pressure` | atm | 5% relative |

### GUDID-side extraction

GUDID returns dimensions in a `deviceSizes` array. Each element: `{"sizeType": "Outer Diameter", "size": "9", "unit": "Millimeter"}`.

Build a new helper in `harvester/src/validators/gudid_client.py`:

```python
# GUDID sizeType → our field name. Higher-priority synonyms first;
# if multiple GUDID entries map to the same field, the first one wins.
_SIZE_TYPE_MAP = [
    ("Labeled Stent Diameter", "diameter"),
    ("Balloon Diameter", "diameter"),
    ("Outer Diameter", "diameter"),
    ("Labeled Stent Length", "length"),
    ("Catheter Working Length", "length"),
    ("Device Length", "length"),
    ("Width", "width"),
    ("Height", "height"),
    ("Weight", "weight"),
    ("Volume", "volume"),
    ("Rated Burst Pressure", "pressure"),
    ("Pressure", "pressure"),
]

def extract_gudid_dimensions(gudid_record: dict) -> dict:
    """Parse deviceSizes into canonical {field: {value: float, unit: str}}."""
```

Returns e.g. `{"diameter": {"value": 9.0, "unit": "mm"}, "length": {"value": 79.0, "unit": "mm"}}`.

The returned dict is added to `gudid_record` before it's passed to `compare_records()`.

### Harvester-side values

The harvester already extracts these fields (see `pipeline/dimension_parser.py`). Values land on the device doc as numbers with units, e.g. `{"diameter": 9.0, "diameter_unit": "mm"}`. Confirm the exact shape during implementation; adapt the comparison to match.

### Unit conversion

Use existing `harvester/src/normalizers/unit_conversions.py`. Canonicalize both harvested and GUDID values to the canonical unit in the table above before compare.

If `unit_conversions.py` lacks a conversion (e.g., "Fr" to "mm" for French gauge), **do not compare** — return `match=None` for that field. Do not guess.

### Tolerance check

```python
def _within_tolerance(h: float, g: float, rel: float, abs_: float = 0.0) -> bool:
    if h is None or g is None:
        return None
    tolerance = max(abs(g) * rel, abs_)
    return abs(h - g) <= tolerance
```

### Comparison output shape

Extend `compare_records()` return value with 7 new keys:

```python
for field, (canonical_unit, rel_tol, abs_tol) in _DIMENSION_RULES.items():
    h_val = harvested.get(field)
    h_unit = harvested.get(f"{field}_unit")
    g_dim = gudid_dims.get(field)
    if h_val is None or g_dim is None:
        match = None
    else:
        h_canonical = convert(h_val, h_unit, canonical_unit)
        g_canonical = convert(g_dim["value"], g_dim["unit"], canonical_unit)
        if h_canonical is None or g_canonical is None:
            match = None
        else:
            match = _within_tolerance(h_canonical, g_canonical, rel_tol, abs_tol)
    results[field] = {"harvested": h_val, "gudid": g_dim, "match": match}
```

### Null-handling

Consistent with the existing "new-fields" pattern: if either harvested or GUDID has no value for a dimension, `match=None` (skipped from the score denominator).

### Score denominator update

No change needed. `run_validation()` already filters `v.get("match") is not None` when computing `match_percent`. The denominator naturally grows from up-to-8 to up-to-15 for devices with populated dimensions.

### Review UI

`app/routes/review.py:COMPARED_FIELDS` gains seven new `(field_key, display_label)` tuples:

```python
("diameter", "Diameter"),
("length", "Length"),
("width", "Width"),
("height", "Height"),
("weight", "Weight"),
("volume", "Volume"),
("pressure", "Pressure"),
```

`review.html` iterates `COMPARED_FIELDS` generically (confirmed earlier today) — new rows render automatically. Dimension values render as `"{value} {unit}"` e.g. `"9.0 mm"`.

---

## Changes summary

| File | Change |
|---|---|
| `harvester/src/orchestrator.py` — `run_validation()` | Upsert by `device_id`; replace `drop()` with per-device `_gudid` unset; call `select_best_gudid_di()` instead of `fetch_gudid_record()`; handle three `match_confidence` branches; detect null-sentinels and assign `status="invalid_gudid_response"`; enrich `gudid_record` with `extract_gudid_dimensions()` before compare. |
| `harvester/src/orchestrator.py` — `get_all_dashboard_records()` / `get_dashboard_stats()` | Exclude `status="invalid_gudid_response"` from review queue counts and discrepancy table. |
| `harvester/src/validators/gudid_client.py` | New: `select_best_gudid_di()`, `extract_gudid_dimensions()`. Modify `search_gudid_di()` to return a list of candidate DIs (cap K=3). Add `_SIZE_TYPE_MAP`, `_DIMENSION_RULES`. |
| `harvester/src/validators/comparison_validator.py` | Extend `compare_records()` with 7 dimension comparisons. Add `_within_tolerance()` helper. Import `unit_conversions`. |
| `harvester/src/validators/CLAUDE.md` | Update Comparison Scoring section: 7 → 14 compared fields. Document DI caching, confidence levels, dimension tolerance rules. |
| `harvester/src/validators/tests/test_comparison_validator.py` | New: tests for dimension comparison with matching units, mismatched units, out-of-tolerance values, null harvested, null GUDID. |
| `harvester/src/tests/test_orchestrator.py` | New tests for upsert idempotency (same device validated twice → one doc), `match_confidence` storage, `invalid_gudid_response` sentinel behavior, `_gudid` caching round-trip. |
| `app/routes/review.py` | Add 7 dimension tuples to `COMPARED_FIELDS`. Pass `match_confidence` to template context. |
| `app/templates/review.html` | Render a `match_confidence` badge when value is not `"exact"`. |
| `app/templates/dashboard.html` | Optional: badge on rows whose validation has `match_confidence != "exact"`. |
| `app/routes/admin.py` | New route `GET /admin/invalid-validations` — lists rows where `status="invalid_gudid_response"`. Admin-only. |
| `app/templates/admin/invalid_validations.html` | New template listing the sentinel rows. |

## Testing plan

- **TDD for every new comparison function.** `_within_tolerance` (in/out of range, absolute vs relative, null inputs). `extract_gudid_dimensions` (mapping priority, multiple entries, unknown sizeType fallback).
- **Dimension comparison unit tests.** One per field, one mismatch-unit case (e.g., harvested `9 mm` vs GUDID `0.9 cm` → match), one out-of-tolerance case.
- **Upsert idempotency integration test.** Run validation twice on the same device; assert exactly one `validationResults` doc exists for it.
- **DI caching round-trip.** First call populates `_gudid.di`; second call skips search, uses cached DI.
- **B regression test.** Load Diamondback 360 fixture (`69e6a2be8281d5c55f290fff`); assert `catalogNumber.harvested == "7-10057-08"`.
- **D sentinel test.** Construct a device whose GUDID lookup returns an empty dict; assert `status="invalid_gudid_response"` and the doc is absent from `get_all_dashboard_records()` output.
- **Manual smoke test post-Spec 1 + re-harvest.** Dashboard match rate should noticeably improve (40 Zilver/Diamondback catalogs start matching; dimension rows render on review page; no duplicate validationResults per device).

## Out of scope

- LLM-assisted validation (brand aliasing, semantic description similarity). Future spec if desired.
- Changing the harvester extraction layer. Covered by Spec 1.
- The operational re-harvest (step E). Runs after both specs land.
- New manufacturers or new URLs. Covered by ongoing normal harvester work.
- Automatic re-pulling of `_gudid` when GUDID itself updates a record. If GUDID updates in place, our cached DI is stale; we'd need a periodic refresh job — out of scope for this spec.
