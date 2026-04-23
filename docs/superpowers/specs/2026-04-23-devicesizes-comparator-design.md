# deviceSizes Comparator — Design

**Date:** 2026-04-23
**Owner:** Jason
**Status:** Draft (pending review)

## Problem

The harvester already parses device dimensions (`dimension_parser.py`) and emits them as a GUDID-shaped `deviceSizes` array in each record (`emitter.py:_build_device_sizes`). The GUDID client does not pull GUDID's `deviceSizes`, and the comparison validator has no entry for them in `FIELD_WEIGHTS` or in `compare_records()`. As a result, every dimension the harvester extracts is never validated against the regulatory record — the most common user-visible spec on a manufacturer page silently bypasses the Collect → Compare → Correct loop.

## Goal

Add `deviceSizes` as a scored comparison field: harvested sizes validate against GUDID sizes with unit-aware, tolerance-based matching, surfacing mismatches in the review UI with per-type detail.

## Non-goals

- Changing how the harvester parses dimensions.
- Changing the emitted `deviceSizes` shape.
- Supporting every exotic GUDID unit on day one — we cover the canonical buckets (length, weight, volume, pressure) plus French.
- Storing the per-type sub-statuses in MongoDB long-term — they live on the in-memory result dict for the review UI. (Can be added to `validationResults` later if audit needs it.)

## Architecture

Four files change, one adds French to existing unit conversions, one pulls GUDID's deviceSizes, one adds the comparator, and the review UI renders per-type rows.

| File | Change |
|---|---|
| `harvester/src/normalizers/unit_conversions.py` | Add `"fr"` / `"french"` mapping → `('mm', lambda x: x / 3)` (1 Fr = 1/3 mm). |
| `harvester/src/validators/gudid_client.py` | In `fetch_gudid_record()`, pull `device.deviceSizes.deviceSize[]` and expose under `deviceSizes`. |
| `harvester/src/validators/comparison_validator.py` | Add `deviceSizes` to `FIELD_WEIGHTS` (weight 2). Add two private helpers (`_normalize_gudid_size`, `_compare_device_sizes`). Add deviceSizes block to `compare_records()`. |
| `app/routes/review.py` + review template | Render `per_type` sub-statuses as an expandable row beneath the aggregated deviceSizes row. |

No schema migration — `deviceSizes` already flows through the harvested record end-to-end.

## Data flow

### Harvested side (already works, unchanged)

```
specs_text
  → dimension_parser.parse_dimensions_from_specs
     → {diameter: "3.5 mm", length: "20 mm"}
  → normalizers.normalize_measurement
     → {diameter: {value: 3.5, unit: "mm"}, length: {value: 20, unit: "mm"}}
  → emitter._build_device_sizes
     → [
         {sizeType: "Diameter", size: {unit: "Millimeter", value: "3.5"}, sizeText: null},
         {sizeType: "Length",   size: {unit: "Millimeter", value: "20"},  sizeText: null}
       ]
```

### GUDID side (new)

GUDID API path: `device.deviceSizes.deviceSize[]`. Each entry has the same three keys the harvester emits (`sizeType`, `size: {unit, value}`, `sizeText`). `fetch_gudid_record` plucks the array and adds it to the returned record dict under key `deviceSizes`. No restructuring.

### Comparator side (new)

```
compare_records(harvested, gudid):
  ...
  h_sizes = harvested.get("deviceSizes")
  g_sizes = gudid.get("deviceSizes")
  result = _compare_device_sizes(h_sizes, g_sizes)
  results["deviceSizes"] = result
```

`_compare_device_sizes` applies the subset-match decision tree described below and returns a dict with `status`, `harvested`, `gudid`, and a `per_type` list for the review UI.

## Comparator logic

### Tolerance table (absolute, in canonical units)

| Canonical unit | Tolerance |
|---|---|
| mm | 0.05 |
| g | 0.1 |
| mL | 0.1 |
| mmHg | 0.5 |

Values come from the minimum meaningful precision in medical device spec sheets. If a value falls within tolerance after canonicalization, it's a match.

### GUDID unit reverse map

`_normalize_gudid_size` maps GUDID long-form units back to the short codes in `unit_conversions.py`:

| GUDID unit | Short |
|---|---|
| Millimeter | mm |
| Centimeter | cm |
| Meter | m |
| Inch | in |
| French | Fr |
| Gram | g |
| Kilogram | kg |
| Milliliter | mL |
| Millimeter Mercury | mmHg |

After the reverse map, the size goes through `normalize_measurement(f"{value} {short_unit}")` which converts to canonical mm/g/mL/mmHg. If either map-step returns None, the per-type row becomes `not_compared`.

### Decision tree

```
harvested is null/empty AND gudid is null/empty  → BOTH_NULL       (not scored)
harvested is null/empty                          → NOT_COMPARED    (not scored, asymmetric)
gudid is null/empty (harvested has some)         → MISMATCH        (scored)

else, build per_type list by iterating harvested entries:
  for each h in harvested_sizes:
    if h has no numeric size (sizeText-only)
        → skip entry (not added to per_type)
    find g in gudid_sizes where g.sizeType == h.sizeType
    if no g found
        → per_type.append({status: mismatch, reason: "harvester-only type"})
    elif g has no numeric size
        → per_type.append({status: not_compared})
    else:
        canonicalize both to same unit
        if canonicalization failed for either
            → per_type.append({status: not_compared})
        elif |h.value - g.value| <= tolerance[canonical_unit]
            → per_type.append({status: match})
        else
            → per_type.append({status: mismatch})

aggregate:
  comparable = [p for p in per_type if p.status in {match, mismatch}]
  if not comparable                      → NOT_COMPARED
  if all comparable are match            → MATCH
  else                                   → MISMATCH
```

This is the same subset-match semantics as `productCodes` and `premarketSubmissions`: harvester must not claim anything that isn't in GUDID; GUDID having extra types is fine.

### Result dict shape

```python
results["deviceSizes"] = {
    "harvested": [...],            # original harvested list (unchanged)
    "gudid": [...],                # original gudid list (unchanged)
    "status": "match" | "mismatch" | "not_compared" | "both_null",
    "per_type": [
        {"sizeType": "Diameter", "status": "match",       "harvested": "3.5 mm", "gudid": "3.5 mm"},
        {"sizeType": "Length",   "status": "mismatch",    "harvested": "20 mm",  "gudid": "18 mm"},
    ]
}
```

`per_type` values are pre-formatted strings (`"<value> <short_unit>"`) for direct display. The raw numeric comparison happens before formatting.

### Scoring

`deviceSizes` added to `FIELD_WEIGHTS` with weight **2**:

```python
FIELD_WEIGHTS = {
    ...
    "deviceSizes": 2,
}
```

Standard scoring rules in `_build_summary` apply: `match` / `mismatch` statuses contribute to the weighted and unweighted denominators; `match` contributes to numerators; `not_compared` / `both_null` are skipped.

### Edge cases

- **Ranges on harvested side** (e.g. `"4.0 to 7.0 mm diameter"`): `normalize_measurement` already stores the midpoint with `is_range: true, range_low, range_high`. The comparator uses the midpoint. Rationale: ranges usually indicate the manufacturer page did not break out per SKU — using the midpoint is as good as any single-value choice and keeps the comparator simple. Can revisit if real-world data shows false mismatches.
- **Unknown units on either side:** if the reverse map misses a GUDID unit or `normalize_measurement` can't parse, per-type row is `not_compared` — doesn't fail the aggregate unless the harvester side has nothing else.
- **sizeText-only entries** (no numeric `size`): skipped entirely. The entry doesn't appear in `per_type` and doesn't count toward match or mismatch. These are rare GUDID cases like `sizeText: "N/A"` or `sizeText: "Variable"`.
- **Duplicate size types in either list:** compare against the first GUDID entry of that type. Duplicates on the harvester side are unexpected (emitter iterates over a dict with unique keys) but compared independently if they occur.

## Scoring impact

Before: 18 fields in `FIELD_WEIGHTS` (Layer-1 + Layer-2), max weighted denominator 37 when every field is populated on both sides. After: 19 fields, max weighted denominator 39. A device that previously matched 100% and now mismatches only on dimensions drops to roughly 95% weighted (37/39). Intentional — dimension disagreements are meaningful and shouldn't be invisible.

Devices where the harvester extracted no dimensions get `not_compared` for this field, which means no denominator change for them — they score the same as before.

## Error handling

Follows the project's "never crash the run" rule:
- GUDID API returns malformed `deviceSizes` array → `fetch_gudid_record` exposes `deviceSizes: None`; comparator treats as null.
- Harvested entry missing expected keys → treated as sizeText-only (skipped).
- Tolerance lookup miss (unknown canonical unit) → per-type row `not_compared`.
- Every step has a null fallback; no raised exceptions from the comparator.

## Testing

### `harvester/src/validators/tests/test_comparison_validator.py` — new `TestDeviceSizes` class

| Test | Asserts |
|---|---|
| `test_both_null` | Harvested=None, GUDID=None → `both_null`, not scored |
| `test_harvested_null_gudid_has_sizes` | Harvested=None, GUDID=[Diameter] → `not_compared`, not scored |
| `test_gudid_null_harvested_has_sizes` | Harvested=[Diameter], GUDID=None → `mismatch`, scored |
| `test_exact_match` | Both `[Diameter 3.5 mm]` → `match`, `per_type[0].status == "match"` |
| `test_within_tolerance` | Harvested 3.5 mm vs GUDID 3.52 mm → `match` (0.02 < 0.05) |
| `test_outside_tolerance` | Harvested 3.5 mm vs GUDID 3.6 mm → `mismatch` |
| `test_unit_conversion` | Harvested 3 cm (→30 mm) vs GUDID 1.181 Inch (→30 mm) → `match` |
| `test_french_unit` | Harvested 6 Fr (→2.0 mm) vs GUDID French 6 (→2.0 mm) → `match` |
| `test_harvester_subset` | Harvested `[Diameter]`, GUDID `[Diameter, Length, Weight]`, Diameter matches → `match` |
| `test_harvester_has_extra_type` | Harvested `[Diameter, Length]`, GUDID `[Diameter]` → `mismatch` (Length harvester-only) |
| `test_one_type_mismatches` | Harvested `[Diameter=3.5, Length=20]` vs GUDID `[Diameter=3.5, Length=18]` → aggregate `mismatch`, per_type shows Diameter match + Length mismatch |
| `test_sizeText_only_entry_skipped` | Harvested has sizeText-only entry → skipped, doesn't fail match |
| `test_range_midpoint_comparison` | Harvested range 4–6 mm (midpoint 5) vs GUDID 5 mm → `match` |
| `test_unknown_gudid_unit_not_compared` | GUDID unit string not in reverse map → per-type `not_compared`, aggregate ignores |
| `test_weight_applied_in_summary` | Summary numerator/denominator reflects weight=2 when status is match/mismatch |

### `harvester/src/validators/tests/test_gudid_client.py` — add

| Test | Asserts |
|---|---|
| `test_fetch_includes_deviceSizes` | Mock GUDID response with `deviceSizes.deviceSize[]` → returned dict has flattened `deviceSizes` list |

### `harvester/src/normalizers/tests/test_unit_conversions.py` — add

| Test | Asserts |
|---|---|
| `test_french_converts_to_mm` | `normalize_measurement("6 Fr")` → `{value: 2.0, unit: "mm"}` |

### Manual integration check

Run one real Abbott catheter URL through the pipeline end-to-end. Confirm the review page renders per-type Diameter/Length sub-rows with the right colors. Catheter chosen because it exercises Fr-unit handling plus multi-dimension matching.

## Rollout

Single PR. Changes are additive — no existing test will break because `deviceSizes` is a new field in `compare_records`. Existing devices in MongoDB will get the new comparison row the next time validation runs against them.

## Open questions

None blocking. The range-handling and duplicate-size-type choices are deliberate defaults; both can be tightened later if real data shows problems.
