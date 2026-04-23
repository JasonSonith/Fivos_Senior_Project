# deviceSizes Comparator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `deviceSizes` as a scored comparison field between harvested records and GUDID, with unit-aware tolerance matching and per-type detail for the review UI.

**Architecture:** The harvester already emits GUDID-shaped `deviceSizes`; the GUDID client does not pull the GUDID side. This plan extends the GUDID client to pull `deviceSizes`, adds French (Fr) to the unit conversions, adds a subset-match comparator with per-unit absolute tolerance, wires it into `compare_records()` with weight 2, and renders per-type sub-statuses on the review page.

**Tech Stack:** Python 3.13, pytest, FastAPI, Jinja2. No new dependencies.

---

## File Structure

**Modify:**
- `harvester/src/normalizers/unit_conversions.py` — add Fr to the `unit_conversions` dict.
- `harvester/src/normalizers/tests/test_units.py` — add Fr test.
- `harvester/src/validators/gudid_client.py` — pull `deviceSizes` from API response.
- `harvester/src/validators/tests/test_gudid_client.py` — add test for `deviceSizes` extraction.
- `harvester/src/validators/comparison_validator.py` — add two helpers + comparator block + `FIELD_WEIGHTS` entry.
- `harvester/src/validators/tests/test_comparison_validator.py` — add `TestDeviceSizes` class.
- `app/routes/review.py` — pass `per_type` detail through to the template.
- `app/templates/review.html` — render per-type sub-rows.

**Create:** none.

---

## Task 1: Add French (Fr) to unit conversions

**Files:**
- Modify: `harvester/src/normalizers/unit_conversions.py`
- Test: `harvester/src/normalizers/tests/test_units.py`

1 Fr = 1/3 mm. Needed because catheter/sheath diameters are routinely quoted in French units on both manufacturer pages and GUDID.

- [ ] **Step 1: Write the failing tests**

Append to `harvester/src/normalizers/tests/test_units.py`:

```python
class TestFrenchConversion:

    def test_french_to_mm(self):
        result = normalize_measurement('6 Fr')
        assert result['unit'] == 'mm'
        assert result['value'] == pytest.approx(2.0, abs=1e-3)

    def test_french_lowercase(self):
        result = normalize_measurement('6 fr')
        assert result['unit'] == 'mm'
        assert result['value'] == pytest.approx(2.0, abs=1e-3)

    def test_french_word(self):
        result = normalize_measurement('9 french')
        assert result['unit'] == 'mm'
        assert result['value'] == pytest.approx(3.0, abs=1e-3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest harvester/src/normalizers/tests/test_units.py::TestFrenchConversion -v`
Expected: 3 failures (Fr unit not recognized; result `unit` is `'Fr'` not `'mm'`).

- [ ] **Step 3: Add Fr to `unit_conversions` dict**

In `harvester/src/normalizers/unit_conversions.py`, add the French entries to the length section, right after the inch entries and before the weight section (around line 14):

```python
    #French (catheter/sheath sizing): 1 Fr = 1/3 mm
    'fr': ('mm', lambda x: x / 3),
    'french': ('mm', lambda x: x / 3),
```

- [ ] **Step 4: Make unit lookup case-insensitive**

`normalize_measurement` captures the unit via `unit = match.group(2).strip().rstrip(".")` and looks it up in `unit_conversions` directly. The dict keys are lowercase, but GUDID/manufacturer sources use mixed case (`Fr`, `French`, `IN`, `MM`). Change the two lookup sites in `normalize_measurement` (one in the range branch, one in the single-value branch) to lowercase the key before lookup.

Range branch (around line 137):

```python
        unit = range_match.group(3).strip().rstrip(".")
        midpoint = round((low + high) / 2, 4)

        unit_key = unit.lower()
        if unit_key in unit_conversions:
            canonical_unit, converter = unit_conversions[unit_key]
            return {
                'value': round(converter(midpoint), 4),
                'unit': canonical_unit,
                'is_range': True,
                'range_low': round(converter(low), 4),
                'range_high': round(converter(high), 4)
            }
```

Single-value branch (around line 160):

```python
    value = float(match.group(1))
    unit = match.group(2).strip().rstrip(".")

    unit_key = unit.lower()
    if unit_key in unit_conversions:
        canonical_unit, converter = unit_conversions[unit_key]
        return {
            "value": round(converter(value), 4),
            "unit": canonical_unit,
            "raw": raw_value,
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest harvester/src/normalizers/tests/test_units.py -v`
Expected: all previous tests still pass, 3 new French tests pass.

- [ ] **Step 6: Commit**

```bash
git add harvester/src/normalizers/unit_conversions.py harvester/src/normalizers/tests/test_units.py
git commit -m "feat(normalizers): add French (Fr) unit conversion"
```

---

## Task 2: Extract `deviceSizes` from GUDID API response

**Files:**
- Modify: `harvester/src/validators/gudid_client.py`
- Test: `harvester/src/validators/tests/test_gudid_client.py`

GUDID API puts device sizes at `device.deviceSizes.deviceSize[]`, each with `{sizeType, size: {unit, value}, sizeText}`. We flatten to a plain list.

- [ ] **Step 1: Write the failing test**

Append to `harvester/src/validators/tests/test_gudid_client.py`:

```python
class TestDeviceSizesExtraction:
    def test_flattens_deviceSizes_array(self):
        from validators.gudid_client import _extract_device_sizes
        device = {
            "deviceSizes": {
                "deviceSize": [
                    {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "3.5"}, "sizeText": None},
                    {"sizeType": "Length",   "size": {"unit": "Millimeter", "value": "20"},  "sizeText": None},
                ]
            }
        }
        sizes = _extract_device_sizes(device)
        assert sizes == [
            {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "3.5"}, "sizeText": None},
            {"sizeType": "Length",   "size": {"unit": "Millimeter", "value": "20"},  "sizeText": None},
        ]

    def test_missing_key_returns_none(self):
        from validators.gudid_client import _extract_device_sizes
        assert _extract_device_sizes({}) is None
        assert _extract_device_sizes({"deviceSizes": None}) is None
        assert _extract_device_sizes({"deviceSizes": {}}) is None
        assert _extract_device_sizes({"deviceSizes": {"deviceSize": None}}) is None
        assert _extract_device_sizes({"deviceSizes": {"deviceSize": []}}) is None

    def test_malformed_entries_filtered(self):
        from validators.gudid_client import _extract_device_sizes
        device = {"deviceSizes": {"deviceSize": [
            {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "3.5"}, "sizeText": None},
            "not a dict",
            {"not_a_size_type": "bad"},
        ]}}
        sizes = _extract_device_sizes(device)
        assert len(sizes) == 1
        assert sizes[0]["sizeType"] == "Diameter"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest harvester/src/validators/tests/test_gudid_client.py::TestDeviceSizesExtraction -v`
Expected: 3 failures (ImportError: `_extract_device_sizes` not defined).

- [ ] **Step 3: Add `_extract_device_sizes` helper**

In `harvester/src/validators/gudid_client.py`, after `_extract_storage_conditions` (around line 46), add:

```python
def _extract_device_sizes(device: dict) -> list[dict] | None:
    """Flatten GUDID deviceSizes.deviceSize[] into a list.

    Returns None when the array is missing or empty. Filters out non-dict
    entries and entries missing sizeType. Never raises.
    """
    sizes_obj = device.get("deviceSizes") or {}
    if not isinstance(sizes_obj, dict):
        return None
    size_list = sizes_obj.get("deviceSize") or []
    if not isinstance(size_list, list):
        return None
    flattened = [
        entry for entry in size_list
        if isinstance(entry, dict) and entry.get("sizeType")
    ]
    return flattened if flattened else None
```

- [ ] **Step 4: Wire it into `fetch_gudid_record`**

In the same file, in the dict returned by `fetch_gudid_record` (around line 131-149), add `"deviceSizes": _extract_device_sizes(device),` right after the `"environmentalConditions"` line:

```python
    return di, {
        "brandName": device.get("brandName"),
        ...
        "environmentalConditions": _extract_storage_conditions(device),
        "deviceSizes": _extract_device_sizes(device),
        **_extract_new_fields(device),
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest harvester/src/validators/tests/test_gudid_client.py -v`
Expected: all existing tests still pass, 3 new tests pass.

- [ ] **Step 6: Commit**

```bash
git add harvester/src/validators/gudid_client.py harvester/src/validators/tests/test_gudid_client.py
git commit -m "feat(validators): pull deviceSizes from GUDID API response"
```

---

## Task 3: Add `_canonicalize_size_entry` helper

**Files:**
- Modify: `harvester/src/validators/comparison_validator.py`
- Test: `harvester/src/validators/tests/test_comparison_validator.py`

Converts one `{sizeType, size: {unit, value}, sizeText}` dict into a canonical `{sizeType, value: float, canonical_unit: str}` triple. Returns `None` for sizeText-only or unparseable entries.

- [ ] **Step 1: Write the failing tests**

Append to `harvester/src/validators/tests/test_comparison_validator.py`:

```python
class TestCanonicalizeSizeEntry:
    def test_millimeter_passes_through(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "3.5"}, "sizeText": None}
        assert _canonicalize_size_entry(entry) == {
            "sizeType": "Diameter", "value": 3.5, "canonical_unit": "mm"
        }

    def test_inch_converts_to_mm(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Length", "size": {"unit": "Inch", "value": "1"}, "sizeText": None}
        result = _canonicalize_size_entry(entry)
        assert result["canonical_unit"] == "mm"
        assert result["value"] == 25.4

    def test_french_converts_to_mm(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "size": {"unit": "French", "value": "6"}, "sizeText": None}
        result = _canonicalize_size_entry(entry)
        assert result["canonical_unit"] == "mm"
        assert result["value"] == pytest.approx(2.0, abs=1e-3)

    def test_centimeter_converts_to_mm(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Length", "size": {"unit": "Centimeter", "value": "3"}, "sizeText": None}
        result = _canonicalize_size_entry(entry)
        assert result["canonical_unit"] == "mm"
        assert result["value"] == 30.0

    def test_gram_passes_through(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Weight", "size": {"unit": "Gram", "value": "5"}, "sizeText": None}
        result = _canonicalize_size_entry(entry)
        assert result["canonical_unit"] == "g"
        assert result["value"] == 5.0

    def test_sizeText_only_returns_none(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "size": None, "sizeText": "N/A"}
        assert _canonicalize_size_entry(entry) is None

    def test_missing_size_returns_none(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "sizeText": None}
        assert _canonicalize_size_entry(entry) is None

    def test_unknown_unit_returns_none(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "size": {"unit": "SomeMadeUpUnit", "value": "1"}, "sizeText": None}
        assert _canonicalize_size_entry(entry) is None

    def test_non_numeric_value_returns_none(self):
        from validators.comparison_validator import _canonicalize_size_entry
        entry = {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "abc"}, "sizeText": None}
        assert _canonicalize_size_entry(entry) is None
```

Make sure `import pytest` is at the top of `test_comparison_validator.py`. If the file starts with `from validators.comparison_validator import compare_records` and has no `import pytest`, add it as a new line above that import.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest harvester/src/validators/tests/test_comparison_validator.py::TestCanonicalizeSizeEntry -v`
Expected: 9 failures (ImportError: `_canonicalize_size_entry` not defined).

- [ ] **Step 3: Add the helper**

In `harvester/src/validators/comparison_validator.py`, after the existing `_compare_normalized` helper (around line 68) and before `_SKU_PATTERN_RE`, add:

```python
# GUDID long-form unit → short code recognized by normalize_measurement.
_GUDID_UNIT_SHORT = {
    "Millimeter": "mm",
    "Centimeter": "cm",
    "Meter": "m",
    "Inch": "in",
    "French": "Fr",
    "Gram": "g",
    "Kilogram": "kg",
    "Milliliter": "mL",
    "Millimeter Mercury": "mmHg",
}


def _canonicalize_size_entry(entry: dict) -> dict | None:
    """Convert a GUDID-shaped size entry to {sizeType, value, canonical_unit}.

    Returns None when the entry lacks a numeric size, has an unknown unit,
    or has an unparseable value.
    """
    from normalizers.unit_conversions import normalize_measurement

    if not isinstance(entry, dict):
        return None
    size_type = entry.get("sizeType")
    size = entry.get("size")
    if not size_type or not isinstance(size, dict):
        return None
    raw_unit = size.get("unit")
    raw_value = size.get("value")
    if raw_unit is None or raw_value is None:
        return None
    short_unit = _GUDID_UNIT_SHORT.get(raw_unit)
    if short_unit is None:
        return None
    normalized = normalize_measurement(f"{raw_value} {short_unit}")
    value = normalized.get("value")
    canonical_unit = normalized.get("unit")
    if value is None or canonical_unit is None:
        return None
    return {
        "sizeType": size_type,
        "value": float(value),
        "canonical_unit": canonical_unit,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest harvester/src/validators/tests/test_comparison_validator.py::TestCanonicalizeSizeEntry -v`
Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add harvester/src/validators/comparison_validator.py harvester/src/validators/tests/test_comparison_validator.py
git commit -m "feat(validators): add _canonicalize_size_entry helper"
```

---

## Task 4: Add `_compare_device_sizes` helper

**Files:**
- Modify: `harvester/src/validators/comparison_validator.py`
- Test: `harvester/src/validators/tests/test_comparison_validator.py`

Implements the decision tree from the spec: subset match with per-unit absolute tolerance, returning an aggregate status plus a `per_type` list.

- [ ] **Step 1: Write the failing tests**

Append to `harvester/src/validators/tests/test_comparison_validator.py`:

```python
class TestCompareDeviceSizes:

    def _mm(self, t, v):
        return {"sizeType": t, "size": {"unit": "Millimeter", "value": str(v)}, "sizeText": None}

    def test_both_null(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes(None, None)
        assert result["status"] == "both_null"
        assert result["per_type"] == []

    def test_harvested_null(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes(None, [self._mm("Diameter", 3.5)])
        assert result["status"] == "not_compared"

    def test_harvested_empty_list(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes([], [self._mm("Diameter", 3.5)])
        assert result["status"] == "not_compared"

    def test_gudid_null_harvested_has(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes([self._mm("Diameter", 3.5)], None)
        assert result["status"] == "mismatch"

    def test_exact_match(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5)],
            [self._mm("Diameter", 3.5)],
        )
        assert result["status"] == "match"
        assert len(result["per_type"]) == 1
        assert result["per_type"][0]["sizeType"] == "Diameter"
        assert result["per_type"][0]["status"] == "match"

    def test_within_tolerance(self):
        from validators.comparison_validator import _compare_device_sizes
        # 3.5 vs 3.52 → diff 0.02, tolerance 0.05 → match
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5)],
            [self._mm("Diameter", 3.52)],
        )
        assert result["status"] == "match"

    def test_outside_tolerance(self):
        from validators.comparison_validator import _compare_device_sizes
        # 3.5 vs 3.6 → diff 0.1, tolerance 0.05 → mismatch
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5)],
            [self._mm("Diameter", 3.6)],
        )
        assert result["status"] == "mismatch"
        assert result["per_type"][0]["status"] == "mismatch"

    def test_unit_conversion_match(self):
        from validators.comparison_validator import _compare_device_sizes
        # Harvester has 30 Millimeter; GUDID has 3 Centimeter
        gudid_cm = {"sizeType": "Length", "size": {"unit": "Centimeter", "value": "3"}, "sizeText": None}
        result = _compare_device_sizes(
            [self._mm("Length", 30)],
            [gudid_cm],
        )
        assert result["status"] == "match"

    def test_french_unit_match(self):
        from validators.comparison_validator import _compare_device_sizes
        # Harvester has 2 Millimeter (after normalize_measurement on "6 Fr");
        # GUDID has 6 French → also 2 mm canonical
        gudid_fr = {"sizeType": "Diameter", "size": {"unit": "French", "value": "6"}, "sizeText": None}
        result = _compare_device_sizes(
            [self._mm("Diameter", 2.0)],
            [gudid_fr],
        )
        assert result["status"] == "match"

    def test_harvester_subset_of_gudid(self):
        from validators.comparison_validator import _compare_device_sizes
        # Harvester: only Diameter. GUDID: Diameter, Length, Weight. All match.
        gudid = [
            self._mm("Diameter", 3.5),
            self._mm("Length", 20),
            {"sizeType": "Weight", "size": {"unit": "Gram", "value": "5"}, "sizeText": None},
        ]
        result = _compare_device_sizes([self._mm("Diameter", 3.5)], gudid)
        assert result["status"] == "match"
        assert len(result["per_type"]) == 1

    def test_harvester_has_extra_type(self):
        from validators.comparison_validator import _compare_device_sizes
        # Harvester: Diameter + Length. GUDID: only Diameter. Length is harvester-only.
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5), self._mm("Length", 20)],
            [self._mm("Diameter", 3.5)],
        )
        assert result["status"] == "mismatch"
        # Length should appear in per_type as mismatch
        length_entry = next(p for p in result["per_type"] if p["sizeType"] == "Length")
        assert length_entry["status"] == "mismatch"

    def test_one_type_mismatches(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5), self._mm("Length", 20)],
            [self._mm("Diameter", 3.5), self._mm("Length", 18)],
        )
        assert result["status"] == "mismatch"
        per_type_by_name = {p["sizeType"]: p["status"] for p in result["per_type"]}
        assert per_type_by_name["Diameter"] == "match"
        assert per_type_by_name["Length"] == "mismatch"

    def test_sizeText_only_harvested_skipped(self):
        from validators.comparison_validator import _compare_device_sizes
        h = [
            self._mm("Diameter", 3.5),
            {"sizeType": "Length", "size": None, "sizeText": "Variable"},
        ]
        g = [self._mm("Diameter", 3.5)]
        result = _compare_device_sizes(h, g)
        assert result["status"] == "match"
        assert len(result["per_type"]) == 1
        assert result["per_type"][0]["sizeType"] == "Diameter"

    def test_sizeText_only_gudid_not_compared(self):
        from validators.comparison_validator import _compare_device_sizes
        h = [self._mm("Diameter", 3.5)]
        g = [{"sizeType": "Diameter", "size": None, "sizeText": "Variable"}]
        result = _compare_device_sizes(h, g)
        # No comparable entries → not_compared
        assert result["status"] == "not_compared"
        assert result["per_type"][0]["status"] == "not_compared"

    def test_unknown_gudid_unit_not_compared(self):
        from validators.comparison_validator import _compare_device_sizes
        h = [self._mm("Diameter", 3.5)]
        g = [{"sizeType": "Diameter", "size": {"unit": "NotAUnit", "value": "3.5"}, "sizeText": None}]
        result = _compare_device_sizes(h, g)
        assert result["status"] == "not_compared"

    def test_per_type_formatted_strings(self):
        from validators.comparison_validator import _compare_device_sizes
        result = _compare_device_sizes(
            [self._mm("Diameter", 3.5)],
            [self._mm("Diameter", 3.5)],
        )
        pt = result["per_type"][0]
        assert pt["harvested"] == "3.5 mm"
        assert pt["gudid"] == "3.5 mm"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest harvester/src/validators/tests/test_comparison_validator.py::TestCompareDeviceSizes -v`
Expected: 16 failures (ImportError: `_compare_device_sizes` not defined).

- [ ] **Step 3: Implement the helper**

In `harvester/src/validators/comparison_validator.py`, after `_canonicalize_size_entry` (from Task 3), add:

```python
# Absolute tolerance per canonical unit.
_SIZE_TOLERANCE = {
    "mm": 0.05,
    "g": 0.1,
    "mL": 0.1,
    "mmHg": 0.5,
}


def _format_canonical(canon: dict) -> str:
    """Format a canonicalized entry as '<value> <unit>' for display."""
    v = canon["value"]
    # Strip trailing zeros for cleaner display: 3.5 not 3.50, 30 not 30.0
    if float(v).is_integer():
        value_str = str(int(v))
    else:
        value_str = f"{v:g}"
    return f"{value_str} {canon['canonical_unit']}"


def _compare_device_sizes(h_sizes, g_sizes):
    """Subset-match comparator for deviceSizes with per-unit absolute tolerance.

    Returns a dict with status, harvested, gudid, and a per_type list suitable
    for the review UI (hybrid: one scored status, per-type detail exposed).
    """
    h_null = _is_null(h_sizes)
    g_null = _is_null(g_sizes)
    if h_null and g_null:
        return {"harvested": h_sizes, "gudid": g_sizes,
                "status": FieldStatus.BOTH_NULL, "per_type": []}
    if h_null:
        return {"harvested": h_sizes, "gudid": g_sizes,
                "status": FieldStatus.NOT_COMPARED, "per_type": []}
    if g_null:
        return {"harvested": h_sizes, "gudid": g_sizes,
                "status": FieldStatus.MISMATCH, "per_type": []}

    per_type = []
    for h_entry in h_sizes:
        h_canon = _canonicalize_size_entry(h_entry)
        if h_canon is None:
            # sizeText-only or unparseable harvested entry → skip entirely
            continue
        size_type = h_canon["sizeType"]
        g_entry = next(
            (g for g in g_sizes
             if isinstance(g, dict) and g.get("sizeType") == size_type),
            None,
        )
        if g_entry is None:
            # Harvester has a type GUDID does not — subset violation
            per_type.append({
                "sizeType": size_type,
                "status": FieldStatus.MISMATCH,
                "harvested": _format_canonical(h_canon),
                "gudid": None,
            })
            continue
        g_canon = _canonicalize_size_entry(g_entry)
        if g_canon is None:
            # GUDID entry is sizeText-only or has unknown unit — not comparable
            per_type.append({
                "sizeType": size_type,
                "status": FieldStatus.NOT_COMPARED,
                "harvested": _format_canonical(h_canon),
                "gudid": None,
            })
            continue
        if g_canon["canonical_unit"] != h_canon["canonical_unit"]:
            # Different canonical buckets (e.g. mm vs g) — can't compare
            per_type.append({
                "sizeType": size_type,
                "status": FieldStatus.NOT_COMPARED,
                "harvested": _format_canonical(h_canon),
                "gudid": _format_canonical(g_canon),
            })
            continue
        tolerance = _SIZE_TOLERANCE.get(h_canon["canonical_unit"])
        if tolerance is None:
            per_type.append({
                "sizeType": size_type,
                "status": FieldStatus.NOT_COMPARED,
                "harvested": _format_canonical(h_canon),
                "gudid": _format_canonical(g_canon),
            })
            continue
        matched = abs(h_canon["value"] - g_canon["value"]) <= tolerance
        per_type.append({
            "sizeType": size_type,
            "status": FieldStatus.MATCH if matched else FieldStatus.MISMATCH,
            "harvested": _format_canonical(h_canon),
            "gudid": _format_canonical(g_canon),
        })

    comparable = [p for p in per_type if p["status"] in (FieldStatus.MATCH, FieldStatus.MISMATCH)]
    if not comparable:
        aggregate = FieldStatus.NOT_COMPARED
    elif all(p["status"] == FieldStatus.MATCH for p in comparable):
        aggregate = FieldStatus.MATCH
    else:
        aggregate = FieldStatus.MISMATCH

    return {
        "harvested": h_sizes,
        "gudid": g_sizes,
        "status": aggregate,
        "per_type": per_type,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest harvester/src/validators/tests/test_comparison_validator.py::TestCompareDeviceSizes -v`
Expected: all 16 tests pass.

- [ ] **Step 5: Commit**

```bash
git add harvester/src/validators/comparison_validator.py harvester/src/validators/tests/test_comparison_validator.py
git commit -m "feat(validators): add _compare_device_sizes with subset + tolerance matching"
```

---

## Task 5: Wire `deviceSizes` into `compare_records` and `FIELD_WEIGHTS`

**Files:**
- Modify: `harvester/src/validators/comparison_validator.py`
- Test: `harvester/src/validators/tests/test_comparison_validator.py`

- [ ] **Step 1: Write the failing tests**

Append to `harvester/src/validators/tests/test_comparison_validator.py`:

```python
class TestDeviceSizesIntegration:
    def _mm(self, t, v):
        return {"sizeType": t, "size": {"unit": "Millimeter", "value": str(v)}, "sizeText": None}

    def test_deviceSizes_appears_in_per_field_on_match(self):
        h = {**BASE_HARVESTED, "deviceSizes": [self._mm("Diameter", 3.5)]}
        g = {**BASE_GUDID, "deviceSizes": [self._mm("Diameter", 3.5)]}
        per_field, _ = compare_records(h, g)
        assert "deviceSizes" in per_field
        assert per_field["deviceSizes"]["status"] == "match"
        assert per_field["deviceSizes"]["per_type"][0]["sizeType"] == "Diameter"

    def test_deviceSizes_mismatch_contributes_weight_2(self):
        from validators.comparison_validator import FIELD_WEIGHTS
        assert FIELD_WEIGHTS["deviceSizes"] == 2

        h = {**BASE_HARVESTED, "deviceSizes": [self._mm("Diameter", 3.5)]}
        g = {**BASE_GUDID, "deviceSizes": [self._mm("Diameter", 3.6)]}
        _, summary = compare_records(h, g)
        # Baseline (no deviceSizes) weighted denom = 19 (4 identifiers × weight 3, plus description 1, plus MRI/singleUse/rx null → not scored).
        # With a deviceSizes mismatch: denominator includes +2 for deviceSizes, numerator unchanged.
        # The exact number depends on BASE_HARVESTED/BASE_GUDID fields; we just check
        # that deviceSizes mismatch *added* 2 to denominator.
        h_no_sizes = {**BASE_HARVESTED}
        g_no_sizes = {**BASE_GUDID}
        _, summary_baseline = compare_records(h_no_sizes, g_no_sizes)
        assert summary["denominator"] == summary_baseline["denominator"] + 2
        assert summary["numerator"] == summary_baseline["numerator"]

    def test_deviceSizes_match_contributes_to_numerator(self):
        h = {**BASE_HARVESTED, "deviceSizes": [self._mm("Diameter", 3.5)]}
        g = {**BASE_GUDID, "deviceSizes": [self._mm("Diameter", 3.5)]}
        _, summary = compare_records(h, g)

        h_no = {**BASE_HARVESTED}
        g_no = {**BASE_GUDID}
        _, summary_baseline = compare_records(h_no, g_no)
        assert summary["numerator"] == summary_baseline["numerator"] + 2
        assert summary["denominator"] == summary_baseline["denominator"] + 2

    def test_deviceSizes_not_compared_when_harvested_null(self):
        h = {**BASE_HARVESTED}  # no deviceSizes key
        g = {**BASE_GUDID, "deviceSizes": [self._mm("Diameter", 3.5)]}
        per_field, summary = compare_records(h, g)
        assert per_field["deviceSizes"]["status"] == "not_compared"
        # not_compared → no denominator contribution
        h_no = {**BASE_HARVESTED}
        g_no = {**BASE_GUDID}
        _, summary_baseline = compare_records(h_no, g_no)
        assert summary["denominator"] == summary_baseline["denominator"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest harvester/src/validators/tests/test_comparison_validator.py::TestDeviceSizesIntegration -v`
Expected: 4 failures (deviceSizes not in per_field, or FIELD_WEIGHTS missing key).

- [ ] **Step 3: Add deviceSizes to FIELD_WEIGHTS**

In `harvester/src/validators/comparison_validator.py`, add to the `FIELD_WEIGHTS` dict (around line 17-28):

```python
FIELD_WEIGHTS = {
    "versionModelNumber": 3, "catalogNumber": 3,
    "brandName": 3,          "companyName": 3,
    "MRISafetyStatus": 2, "singleUse": 2, "rx": 2,
    "deviceDescription": 1,
    # Layer-2 additions
    "gmdnPTName": 3, "gmdnCode": 2, "productCodes": 3,
    "deviceCountInBase": 2, "issuingAgency": 2,
    "lotBatch": 1, "serialNumber": 1,
    "manufacturingDate": 1, "expirationDate": 1,
    "premarketSubmissions": 2,
    "deviceSizes": 2,
}
```

- [ ] **Step 4: Wire the comparator into `compare_records`**

In the same file, inside `compare_records`, after the `premarketSubmissions` block (around line 321-333) and before `summary = _build_summary(results)`, add:

```python
    # deviceSizes — subset match with per-unit absolute tolerance
    results["deviceSizes"] = _compare_device_sizes(
        harvested.get("deviceSizes"),
        gudid.get("deviceSizes"),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest harvester/src/validators/tests/test_comparison_validator.py -v`
Expected: all existing tests still pass, 4 new integration tests pass.

- [ ] **Step 6: Run full validator test suite**

Run: `pytest harvester/src/validators/tests/ -v`
Expected: all tests pass (existing regression tests should be unaffected).

- [ ] **Step 7: Commit**

```bash
git add harvester/src/validators/comparison_validator.py harvester/src/validators/tests/test_comparison_validator.py
git commit -m "feat(validators): wire deviceSizes into compare_records with weight 2"
```

---

## Task 6: Render `deviceSizes` per-type detail in the review page

**Files:**
- Modify: `app/routes/review.py`
- Modify: `app/templates/review.html`

- [ ] **Step 1: Add `deviceSizes` to `COMPARED_FIELDS`**

In `app/routes/review.py`, append to the `COMPARED_FIELDS` list (line 21-40), after `premarketSubmissions`:

```python
COMPARED_FIELDS = [
    ...
    ("premarketSubmissions", "Premarket Submissions"),
    ("deviceSizes", "Device Sizes"),
]
```

- [ ] **Step 2: Pass `per_type` through to the template**

In the same file, in the `for field_key, field_label in COMPARED_FIELDS:` loop (around line 63-92), add `per_type` to the field dict:

```python
        fields.append({
            "key": field_key,
            "label": field_label,
            "harvested": harvested_val,
            "gudid": gudid_val,
            "status": status,
            "alias_group": comp.get("alias_group"),
            "similarity": similarity,
            "per_type": comp.get("per_type") if field_key == "deviceSizes" else None,
        })
```

- [ ] **Step 3: Render `deviceSizes` specially in the template**

In `app/templates/review.html`, find the `{% for f in fields %}` block (around line 111) and add a per-type sub-render after the main field row. Insert a new block immediately after the closing `</div>` of the main `review-field-row` div (line 154) and before `{% endfor %}`:

```html
        {% if f.key == 'deviceSizes' and f.per_type %}
            {% for pt in f.per_type %}
            <div class="review-field-row review-subrow" style="padding-left: 24px; background: var(--subrow-bg, #fafafa); font-size: 13px;">
                <div class="review-field-name">
                    &rarr; {{ pt.sizeType }}
                    <br>
                    {% if pt.status == 'match' %}
                        <span class="match-status match">Match</span>
                    {% elif pt.status == 'mismatch' %}
                        <span class="match-status mismatch">Mismatch</span>
                    {% elif pt.status == 'not_compared' %}
                        <span class="match-status not-compared">Not Compared</span>
                    {% endif %}
                </div>
                <div class="review-value harvested">
                    {% if pt.harvested is none %}N/A{% else %}{{ pt.harvested }}{% endif %}
                </div>
                <div class="review-value gudid">
                    {% if pt.gudid is none %}N/A{% else %}{{ pt.gudid }}{% endif %}
                </div>
                <div class="review-pick">
                    <span style="color: var(--muted); font-size: 12px;">&ndash;</span>
                </div>
            </div>
            {% endfor %}
        {% endif %}
```

The sub-rows are informational only — the user still accepts/rejects the aggregate `deviceSizes` row via the existing `choice_deviceSizes` radio. No per-type picker.

- [ ] **Step 4: Manual smoke test**

Start the dev server and load a known-mismatching device's review page:

```bash
python run.py
# Visit http://localhost:8500/review/<validation_id> with a device known to have deviceSizes on both sides
```

Expected:
- "Device Sizes" row appears in the comparison table with a match/mismatch badge.
- Indented sub-rows appear under it showing each size type (Diameter, Length, etc.) with its own badge and formatted values.
- Harvested and GUDID columns show `"3.5 mm"` / `"3.6 mm"` style strings.
- The aggregate row has a pick radio (Keep Harvested / Use GUDID) when mismatched; sub-rows have `–` in the pick column.

If no validation has `deviceSizes` on both sides yet, run the pipeline on one Abbott or Cordis URL to generate one: `python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt` with a URL list containing a stent/catheter page, then reload the dashboard.

- [ ] **Step 5: Commit**

```bash
git add app/routes/review.py app/templates/review.html
git commit -m "feat(review): render deviceSizes per-type sub-rows in review page"
```

---

## Task 7: Final verification and cleanup

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest`
Expected: all tests pass, no regressions. If anything fails in a module we did not touch (orchestrator, scoring, dashboard), investigate — that's a signal we broke a contract.

- [ ] **Step 2: Run linting / type checks if configured**

```bash
ruff check harvester/src/validators/ harvester/src/normalizers/ app/routes/review.py 2>/dev/null || true
```

Expected: no new errors introduced (pre-existing errors in other files are OK).

- [ ] **Step 3: End-to-end manual validation**

Pick one Abbott catheter page (which uses French-unit diameters) and one stent page (Millimeter-only). Run the pipeline and validate:

```bash
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt
```

Load the dashboard, pick the validated device, open the review page. Confirm:
- `deviceSizes` row appears with aggregate status.
- Per-type sub-rows render with formatted values.
- Match/mismatch badges are consistent with the actual harvested vs GUDID numbers.
- Catheter case specifically exercises Fr → mm conversion (both sides canonicalize to mm, comparison is done in mm space).

- [ ] **Step 4: Commit any small touch-ups from verification**

If the manual check revealed small template tweaks or rounding-format adjustments, commit them:

```bash
git add <files>
git commit -m "polish(review): adjust deviceSizes sub-row display"
```

- [ ] **Step 5: Summary commit log check**

```bash
git log --oneline origin/Jason..HEAD
```

Expected to see (roughly):
- `feat(normalizers): add French (Fr) unit conversion`
- `feat(validators): pull deviceSizes from GUDID API response`
- `feat(validators): add _canonicalize_size_entry helper`
- `feat(validators): add _compare_device_sizes with subset + tolerance matching`
- `feat(validators): wire deviceSizes into compare_records with weight 2`
- `feat(review): render deviceSizes per-type sub-rows in review page`

Plus optional polish commit. That's the full set — time to open a PR or merge.
