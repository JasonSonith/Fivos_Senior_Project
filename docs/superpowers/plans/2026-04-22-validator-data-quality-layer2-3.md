# Validator Data-Quality Layers 2+3 — Implementation Plan (PR2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Depends on:** PR1 (2026-04-22-validator-data-quality-layer1) must be merged first. This plan imports `FieldStatus`, `FIELD_WEIGHTS`, the `(per_field, summary)` return shape, and the `_is_null()` helper from PR1.

**Goal:** Extend the harvester + validator to cover eight new GUDID fields, the GUDID-deactivated short-circuit, three new LLM-extracted fields, regex-based premarket submission extraction with keyword-context hardening, harvest-gap observability, the PXB35 integration test, and all remaining docs/changelog work from the 2026-04-22 spec.

**Architecture:** Add eight fetch paths to `gudid_client.fetch_gudid_record()` using the `or`-fallback unwrap pattern (prevents the April-8 null-intermediate crash class). Extend `MERGE_FIELDS`, `COMPARED_FIELDS`, and `FIELD_WEIGHTS` in lockstep. New compare blocks in `compare_records()` for the nine compared fields (set-subset semantics for `productCodes` and `premarketSubmissions`). Orchestrator gains a pre-compare guard on `deviceRecordStatus == "Deactivated"` plus harvest-gap counters. LLM schema gets three string fields added and `premarketSubmissions` removed; regex parser gains a keyword-context-hardened extractor wired into `extract_all_fields()` after the LLM pass.

**Tech Stack:** Python 3.13, pytest, existing LLM chain + JSON-schema validation, existing `regulatory_parser.py` regex patterns.

**Spec:** `docs/superpowers/specs/2026-04-22-validator-harvester-data-quality-design.md` §3(a)(d)(e), §4, §5, §6 (deactivated banner + publishDate tile + Additional Information panel + Dashboard deactivated card), §7 (integration test + docs updates).

---

## Task 1: Verify GUDID paths against real responses

**Files:**
- Create (throwaway): `scripts/verify_gudid_paths.py`
- Document findings in the plan notes section at the bottom of this file

This is a **read-only verification task** — no code under `harvester/src/` changes. Run a script against stored `gudid_record` snapshots in the `validationResults` collection to print resolved values for each new path on 5–10 real devices. Document any path that differs from the spec.

- [ ] **Step 1.1: Write the verification script**

Create `scripts/verify_gudid_paths.py`:

```python
"""Throwaway script — query Atlas for 5-10 validationResults docs, print
resolved GUDID paths. Flags any path that fails to resolve on real data."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "harvester" / "src"))

from database.db_connection import get_db

PATHS_TO_CHECK = [
    ("gmdnPTName", lambda d: (d.get("gmdnTerms") or {}).get("gmdn") and
                             (d.get("gmdnTerms") or {}).get("gmdn")[0].get("gmdnPTName")),
    ("gmdnCode",   lambda d: (d.get("gmdnTerms") or {}).get("gmdn") and
                             (d.get("gmdnTerms") or {}).get("gmdn")[0].get("gmdnCode")),
    ("productCodes",     lambda d: [pc.get("productCode") for pc in
                                    ((d.get("productCodes") or {}).get("fdaProductCode") or [])
                                    if pc.get("productCode")]),
    ("deviceCountInBase",  lambda d: d.get("deviceCountInBase")),
    ("publishDate",        lambda d: d.get("publishDate") or d.get("devicePublishDate")),
    ("deviceRecordStatus", lambda d: d.get("deviceRecordStatus")),
    ("issuingAgency",      lambda d: ((d.get("identifiers") or {}).get("identifier") or [{}])[0].get("issuingAgency")),
    ("lotBatch",           lambda d: ((d.get("identifiers") or {}).get("identifier") or [{}])[0].get("lotBatch")),
    ("serialNumber",       lambda d: ((d.get("identifiers") or {}).get("identifier") or [{}])[0].get("serialNumber")),
    ("manufacturingDate",  lambda d: ((d.get("identifiers") or {}).get("identifier") or [{}])[0].get("manufacturingDate")),
    ("expirationDate",     lambda d: ((d.get("identifiers") or {}).get("identifier") or [{}])[0].get("expirationDate")),
]


def main():
    db = get_db()
    samples = list(db["validationResults"].find(
        {"gudid_record": {"$ne": None}},
        {"gudid_record": 1, "gudid_di": 1, "brandName": 1},
    ).limit(10))

    if not samples:
        print("No validationResults with gudid_record found. Run a validation first.")
        return

    print(f"Checking {len(samples)} real GUDID responses:\n")
    for doc in samples:
        gudid = doc.get("gudid_record") or {}
        print(f"=== {doc.get('brandName')} (DI: {doc.get('gudid_di')}) ===")
        for path_name, resolver in PATHS_TO_CHECK:
            try:
                value = resolver(gudid)
                print(f"  {path_name:<22} = {value!r}")
            except Exception as e:
                print(f"  {path_name:<22} = EXCEPTION: {type(e).__name__}: {e}")
        print()


if __name__ == "__main__":
    main()
```

- [ ] **Step 1.2: Run the script**

```
python scripts/verify_gudid_paths.py
```

Expected output: each path prints a concrete value or `None` for each sample device; no exceptions. Skim the output for:
- `gmdnPTName` / `gmdnCode` — resolves to non-null strings on most records
- `productCodes` — resolves to a list of 3-letter strings (e.g., `["DYB", "OXM"]`)
- `publishDate` vs `devicePublishDate` — whichever one resolves, note it
- `deviceRecordStatus` — typically `"Published"`; check whether `"Deactivated"` ever appears in the sample
- Identifier booleans — string values like `"true"`/`"false"` or actual booleans, confirm

- [ ] **Step 1.3: Document findings and update the spec if paths differ**

Create a notes section at the bottom of this plan file (after all tasks) with the sample output. If any path differs from the spec's `device.X.Y` mapping, update the spec and re-commit it before writing code in Task 2.

- [ ] **Step 1.4: Commit (the throwaway script)**

```bash
git add scripts/verify_gudid_paths.py
git commit -m "$(cat <<'EOF'
chore: add one-shot GUDID path verification script

Queries validationResults.gudid_record snapshots and prints resolved
values for each new path planned in PR2. Used once to confirm spec
paths match real responses before Task 2. Safe to delete after PR2 merges.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Extend `gudid_client.fetch_gudid_record()` with 8 new fields

**Files:**
- Modify: `harvester/src/validators/gudid_client.py`
- Modify: `harvester/src/validators/tests/test_gudid_client.py` (create if missing)

- [ ] **Step 2.1: Check/create gudid_client test file**

```
ls harvester/src/validators/tests/
```
If `test_gudid_client.py` doesn't exist, this task creates it. If it exists, extend.

- [ ] **Step 2.2: Write failing tests for defensive extraction**

Add to `harvester/src/validators/tests/test_gudid_client.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from validators.gudid_client import _extract_new_fields  # new helper from Step 2.3


class TestDefensiveExtraction:
    def test_happy_path_all_fields_resolve(self):
        device = {
            "gmdnTerms": {"gmdn": [{"gmdnPTName": "Stent", "gmdnCode": "12345"}]},
            "productCodes": {"fdaProductCode": [{"productCode": "DYB"}, {"productCode": "OXM"}]},
            "deviceCountInBase": 1,
            "publishDate": "2023-01-15",
            "deviceRecordStatus": "Published",
            "identifiers": {"identifier": [{
                "issuingAgency": "GS1",
                "lotBatch": "true", "serialNumber": "false",
                "manufacturingDate": "true", "expirationDate": "true",
            }]},
        }
        result = _extract_new_fields(device)
        assert result["gmdnPTName"] == "Stent"
        assert result["gmdnCode"] == "12345"
        assert result["productCodes"] == ["DYB", "OXM"]
        assert result["deviceCountInBase"] == 1
        assert result["publishDate"] == "2023-01-15"
        assert result["deviceRecordStatus"] == "Published"
        assert result["issuingAgency"] == "GS1"
        assert result["lotBatch"] == "true"
        assert result["serialNumber"] == "false"
        assert result["manufacturingDate"] == "true"
        assert result["expirationDate"] == "true"

    def test_missing_keys_return_none(self):
        result = _extract_new_fields({})
        for key in ("gmdnPTName", "gmdnCode", "deviceCountInBase",
                    "publishDate", "deviceRecordStatus", "issuingAgency",
                    "lotBatch", "serialNumber", "manufacturingDate", "expirationDate"):
            assert result[key] is None, f"{key} should be None on empty input"
        assert result["productCodes"] is None

    def test_null_intermediate_gmdn_terms(self):
        # The key exists but is null — this is the April-8 bug class
        device = {"gmdnTerms": None}
        result = _extract_new_fields(device)
        assert result["gmdnPTName"] is None
        assert result["gmdnCode"] is None

    def test_null_gmdn_list(self):
        device = {"gmdnTerms": {"gmdn": None}}
        result = _extract_new_fields(device)
        assert result["gmdnPTName"] is None

    def test_empty_gmdn_list(self):
        device = {"gmdnTerms": {"gmdn": []}}
        result = _extract_new_fields(device)
        assert result["gmdnPTName"] is None
        assert result["gmdnCode"] is None

    def test_null_identifiers(self):
        device = {"identifiers": None}
        result = _extract_new_fields(device)
        assert result["issuingAgency"] is None
        assert result["lotBatch"] is None

    def test_empty_identifier_list(self):
        device = {"identifiers": {"identifier": []}}
        result = _extract_new_fields(device)
        assert result["issuingAgency"] is None

    def test_null_product_codes(self):
        device = {"productCodes": None}
        result = _extract_new_fields(device)
        assert result["productCodes"] is None

    def test_product_codes_with_null_entries(self):
        device = {"productCodes": {"fdaProductCode": [{"productCode": "DYB"}, {}, {"productCode": None}]}}
        result = _extract_new_fields(device)
        assert result["productCodes"] == ["DYB"]

    def test_publishDate_fallback_to_devicePublishDate(self):
        device = {"devicePublishDate": "2023-05-01"}
        result = _extract_new_fields(device)
        assert result["publishDate"] == "2023-05-01"
```

- [ ] **Step 2.3: Run tests, verify failures**

```
pytest harvester/src/validators/tests/test_gudid_client.py -v
```
Expected: FAIL — `_extract_new_fields` doesn't exist.

- [ ] **Step 2.4: Implement `_extract_new_fields` and wire into `fetch_gudid_record`**

In `harvester/src/validators/gudid_client.py`, add the helper above `fetch_gudid_record`:

```python
def _extract_new_fields(device: dict) -> dict:
    """Extract Layer-2 fields from a GUDID device dict using the `or`-fallback
    unwrap pattern (handles missing keys, null intermediates, empty lists)."""
    gmdn_terms = device.get("gmdnTerms") or {}
    gmdn_list = gmdn_terms.get("gmdn") or []
    first_gmdn = gmdn_list[0] if gmdn_list and isinstance(gmdn_list[0], dict) else {}

    product_codes_obj = device.get("productCodes") or {}
    fda_codes = product_codes_obj.get("fdaProductCode") or []
    product_codes = [
        pc.get("productCode") for pc in fda_codes
        if isinstance(pc, dict) and pc.get("productCode")
    ] or None

    identifiers_obj = device.get("identifiers") or {}
    identifier_list = identifiers_obj.get("identifier") or []
    first_id = identifier_list[0] if identifier_list and isinstance(identifier_list[0], dict) else {}

    return {
        "gmdnPTName": first_gmdn.get("gmdnPTName"),
        "gmdnCode": first_gmdn.get("gmdnCode"),
        "productCodes": product_codes,
        "deviceCountInBase": device.get("deviceCountInBase"),
        "publishDate": device.get("publishDate") or device.get("devicePublishDate"),
        "deviceRecordStatus": device.get("deviceRecordStatus"),
        "issuingAgency": first_id.get("issuingAgency"),
        "lotBatch": first_id.get("lotBatch"),
        "serialNumber": first_id.get("serialNumber"),
        "manufacturingDate": first_id.get("manufacturingDate"),
        "expirationDate": first_id.get("expirationDate"),
    }
```

Then update `fetch_gudid_record` to include these in the returned dict. Find the existing return statement (around line 79) and extend:

```python
return di, {
    "brandName": device.get("brandName"),
    "versionModelNumber": device.get("versionModelNumber"),
    "catalogNumber": device.get("catalogNumber"),
    "companyName": device.get("companyName"),
    "deviceDescription": device.get("deviceDescription"),
    "MRISafetyStatus": device.get("MRISafetyStatus"),
    "singleUse": device.get("singleUse"),
    "rx": device.get("rx"),
    "otc": device.get("otc"),
    "labeledContainsNRL": device.get("labeledContainsNRL"),
    "labeledNoNRL": device.get("labeledNoNRL"),
    "sterilizationPriorToUse": sterilization.get("sterilizationPriorToUse"),
    "deviceSterile": sterilization.get("deviceSterile"),
    "deviceKit": device.get("deviceKit"),
    "premarketSubmissions": submission_numbers or None,
    "environmentalConditions": _extract_storage_conditions(device),
    **_extract_new_fields(device),
}
```

- [ ] **Step 2.5: Run tests, verify pass**

```
pytest harvester/src/validators/tests/test_gudid_client.py -v
```
Expected: all 10 tests PASS.

- [ ] **Step 2.6: Commit**

```bash
git add harvester/src/validators/gudid_client.py \
        harvester/src/validators/tests/test_gudid_client.py
git commit -m "$(cat <<'EOF'
feat(gudid): fetch 8 new Layer-2 fields with defensive extraction

Added gmdnPTName, gmdnCode, productCodes, deviceCountInBase, publishDate
(with devicePublishDate fallback), deviceRecordStatus, issuingAgency,
and four labeled-identifier booleans (lotBatch, serialNumber,
manufacturingDate, expirationDate). All paths use or-fallback unwrap
to prevent null-intermediate crashes (April 8 bug class). 10 unit tests
cover happy / missing / null-intermediate / empty-list / null-entry /
devicePublishDate-fallback cases.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Layer 2 compare logic + `MERGE_FIELDS` + `COMPARED_FIELDS` + weights

**Files:**
- Modify: `harvester/src/validators/comparison_validator.py`
- Modify: `harvester/src/orchestrator.py`
- Modify: `app/routes/review.py`
- Create: `harvester/src/validators/tests/test_comparison_new_fields.py`

- [ ] **Step 3.1: Write failing tests**

Create `harvester/src/validators/tests/test_comparison_new_fields.py`:

```python
from validators.comparison_validator import compare_records


def _with_defaults(overrides):
    base = {"versionModelNumber": "X"}
    base.update(overrides)
    return base


class TestGmdnFields:
    def test_gmdnPTName_match_case_insensitive(self):
        h = _with_defaults({"gmdnPTName": "stent, coronary"})
        g = _with_defaults({"gmdnPTName": "Stent, Coronary"})
        per_field, _ = compare_records(h, g)
        assert per_field["gmdnPTName"]["status"] == "match"

    def test_gmdnPTName_mismatch(self):
        h = _with_defaults({"gmdnPTName": "Stent"})
        g = _with_defaults({"gmdnPTName": "Balloon"})
        per_field, _ = compare_records(h, g)
        assert per_field["gmdnPTName"]["status"] == "mismatch"

    def test_gmdnCode_exact_match(self):
        h = _with_defaults({"gmdnCode": "12345"})
        g = _with_defaults({"gmdnCode": "12345"})
        per_field, _ = compare_records(h, g)
        assert per_field["gmdnCode"]["status"] == "match"

    def test_gmdn_harvested_null_is_not_compared(self):
        h = _with_defaults({"gmdnPTName": None})
        g = _with_defaults({"gmdnPTName": "Stent"})
        per_field, _ = compare_records(h, g)
        assert per_field["gmdnPTName"]["status"] == "not_compared"

    def test_gmdn_both_null(self):
        h = _with_defaults({"gmdnPTName": None})
        g = _with_defaults({"gmdnPTName": None})
        per_field, _ = compare_records(h, g)
        assert per_field["gmdnPTName"]["status"] == "both_null"


class TestProductCodesSubsetMatch:
    def test_equal_sets_match(self):
        h = _with_defaults({"productCodes": ["DYB", "OXM"]})
        g = _with_defaults({"productCodes": ["DYB", "OXM"]})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "match"

    def test_harvested_subset_of_gudid_match(self):
        h = _with_defaults({"productCodes": ["DYB"]})
        g = _with_defaults({"productCodes": ["DYB", "OXM"]})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "match"

    def test_harvested_has_extra_mismatch(self):
        h = _with_defaults({"productCodes": ["DYB", "ZZZ"]})
        g = _with_defaults({"productCodes": ["DYB"]})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "mismatch"

    def test_disjoint_mismatch(self):
        h = _with_defaults({"productCodes": ["ZZZ"]})
        g = _with_defaults({"productCodes": ["DYB"]})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "mismatch"

    def test_harvested_null_not_compared(self):
        h = _with_defaults({"productCodes": None})
        g = _with_defaults({"productCodes": ["DYB"]})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "not_compared"

    def test_both_empty_both_null(self):
        h = _with_defaults({"productCodes": []})
        g = _with_defaults({"productCodes": []})
        per_field, _ = compare_records(h, g)
        assert per_field["productCodes"]["status"] == "both_null"


class TestDeviceCountInBase:
    def test_equal_integers_match(self):
        h = _with_defaults({"deviceCountInBase": 1})
        g = _with_defaults({"deviceCountInBase": 1})
        per_field, _ = compare_records(h, g)
        assert per_field["deviceCountInBase"]["status"] == "match"

    def test_different_integers_mismatch(self):
        h = _with_defaults({"deviceCountInBase": 1})
        g = _with_defaults({"deviceCountInBase": 5})
        per_field, _ = compare_records(h, g)
        assert per_field["deviceCountInBase"]["status"] == "mismatch"


class TestIssuingAgency:
    def test_exact_match(self):
        h = _with_defaults({"issuingAgency": "GS1"})
        g = _with_defaults({"issuingAgency": "GS1"})
        per_field, _ = compare_records(h, g)
        assert per_field["issuingAgency"]["status"] == "match"

    def test_mismatch(self):
        h = _with_defaults({"issuingAgency": "GS1"})
        g = _with_defaults({"issuingAgency": "HIBCC"})
        per_field, _ = compare_records(h, g)
        assert per_field["issuingAgency"]["status"] == "mismatch"


class TestLabeledBooleans:
    def test_lotBatch_match_string_both(self):
        h = _with_defaults({"lotBatch": "true"})
        g = _with_defaults({"lotBatch": "true"})
        per_field, _ = compare_records(h, g)
        assert per_field["lotBatch"]["status"] == "match"

    def test_lotBatch_mismatch(self):
        h = _with_defaults({"lotBatch": True})
        g = _with_defaults({"lotBatch": False})
        per_field, _ = compare_records(h, g)
        assert per_field["lotBatch"]["status"] == "mismatch"

    def test_serialNumber_null_harvested_not_compared(self):
        h = _with_defaults({"serialNumber": None})
        g = _with_defaults({"serialNumber": "false"})
        per_field, _ = compare_records(h, g)
        assert per_field["serialNumber"]["status"] == "not_compared"
```

- [ ] **Step 3.2: Run tests, verify failures**

```
pytest harvester/src/validators/tests/test_comparison_new_fields.py -v
```
Expected: many FAIL — new fields aren't in `compare_records` yet.

- [ ] **Step 3.3: Extend `FIELD_WEIGHTS`**

In `harvester/src/validators/comparison_validator.py`, extend the `FIELD_WEIGHTS` dict added in PR1 Task 1:

```python
FIELD_WEIGHTS = {
    # ...existing PR1 entries...
    # Layer-2 additions
    "gmdnPTName": 3, "gmdnCode": 2, "productCodes": 3,
    "deviceCountInBase": 2, "issuingAgency": 2,
    "lotBatch": 1, "serialNumber": 1,
    "manufacturingDate": 1, "expirationDate": 1,
    # Layer-3 — added in later task
}
```

- [ ] **Step 3.4: Add subset-match helper + compare blocks**

Add a helper to `comparison_validator.py` near other helpers:

```python
def _subset_match(h_list, g_list):
    """Returns 'match' if set(harvested) is a subset of set(gudid), else 'mismatch'.
    Assumes both lists are non-empty (callers handle null/empty cases)."""
    if set(h_list) <= set(g_list):
        return FieldStatus.MATCH
    return FieldStatus.MISMATCH
```

Add compare blocks in `compare_records()`, after the existing field blocks:

```python
    # --- Layer 2 fields ---

    # GMDN fields — case-insensitive exact
    for field in ("gmdnPTName",):
        h = harvested.get(field); g = gudid.get(field)
        if _is_null(h) and _is_null(g):
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.BOTH_NULL}
            continue
        if _is_null(h):
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.NOT_COMPARED}
            continue
        match = bool(g and isinstance(h, str) and isinstance(g, str)
                     and h.strip().lower() == g.strip().lower())
        results[field] = {
            "harvested": h, "gudid": g,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }

    # gmdnCode, issuingAgency — case-sensitive exact
    for field in ("gmdnCode", "issuingAgency"):
        h = harvested.get(field); g = gudid.get(field)
        if _is_null(h) and _is_null(g):
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.BOTH_NULL}
            continue
        if _is_null(h):
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.NOT_COMPARED}
            continue
        match = bool(g and str(h).strip() == str(g).strip())
        results[field] = {
            "harvested": h, "gudid": g,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }

    # productCodes — subset match
    h_pc = harvested.get("productCodes"); g_pc = gudid.get("productCodes")
    if _is_null(h_pc) and _is_null(g_pc):
        results["productCodes"] = {"harvested": h_pc, "gudid": g_pc, "status": FieldStatus.BOTH_NULL}
    elif _is_null(h_pc):
        results["productCodes"] = {"harvested": h_pc, "gudid": g_pc, "status": FieldStatus.NOT_COMPARED}
    elif _is_null(g_pc):
        # Harvested present, GUDID empty → mismatch
        results["productCodes"] = {"harvested": h_pc, "gudid": g_pc, "status": FieldStatus.MISMATCH}
    else:
        results["productCodes"] = {
            "harvested": h_pc, "gudid": g_pc,
            "status": _subset_match(h_pc, g_pc),
        }

    # deviceCountInBase — integer equality
    h_count = harvested.get("deviceCountInBase"); g_count = gudid.get("deviceCountInBase")
    if _is_null(h_count) and _is_null(g_count):
        results["deviceCountInBase"] = {"harvested": h_count, "gudid": g_count, "status": FieldStatus.BOTH_NULL}
    elif _is_null(h_count):
        results["deviceCountInBase"] = {"harvested": h_count, "gudid": g_count, "status": FieldStatus.NOT_COMPARED}
    else:
        match = False
        try:
            match = int(h_count) == int(g_count) if g_count is not None else False
        except (TypeError, ValueError):
            match = False
        results["deviceCountInBase"] = {
            "harvested": h_count, "gudid": g_count,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }

    # Labeled-identifier booleans — normalize and compare
    for field in ("lotBatch", "serialNumber", "manufacturingDate", "expirationDate"):
        h = harvested.get(field); g = gudid.get(field)
        if _is_null(h) and _is_null(g):
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.BOTH_NULL}
            continue
        match, _, _ = _compare_normalized(h, g, normalize_boolean)
        results[field] = {
            "harvested": h, "gudid": g,
            "status": _status_from_bool(match),
        }
```

- [ ] **Step 3.5: Extend `MERGE_FIELDS` in orchestrator**

In `harvester/src/orchestrator.py`, extend `MERGE_FIELDS`:

```python
MERGE_FIELDS = [
    # ...existing fields (catalogNumber, brandName, etc.)...
    # Layer-2 additions
    "gmdnPTName", "gmdnCode", "productCodes",
    "deviceCountInBase",
    "publishDate", "deviceRecordStatus",
    "issuingAgency",
    "lotBatch", "serialNumber", "manufacturingDate", "expirationDate",
]
```

- [ ] **Step 3.6: Extend `COMPARED_FIELDS` in review.py**

In `app/routes/review.py`:

```python
COMPARED_FIELDS = [
    # ...existing entries from PR1 + April 20...
    # Layer-2 additions (weight-ordered)
    ("gmdnPTName", "GMDN Term"),
    ("gmdnCode", "GMDN Code"),
    ("productCodes", "FDA Product Codes"),
    ("deviceCountInBase", "Pack Quantity"),
    ("issuingAgency", "Issuing Agency"),
    ("lotBatch", "Labeled: Lot / Batch"),
    ("serialNumber", "Labeled: Serial Number"),
    ("manufacturingDate", "Labeled: Manufacturing Date"),
    ("expirationDate", "Labeled: Expiration Date"),
]
```

- [ ] **Step 3.7: Run full suite**

```
pytest
```
Expected: all pass, including the new Layer-2 compare tests.

- [ ] **Step 3.8: Commit**

```bash
git add harvester/src/validators/comparison_validator.py \
        harvester/src/orchestrator.py \
        app/routes/review.py \
        harvester/src/validators/tests/test_comparison_new_fields.py
git commit -m "$(cat <<'EOF'
feat(validators): compare 9 Layer-2 GUDID fields

Adds compare blocks for gmdnPTName (case-insensitive), gmdnCode +
issuingAgency (exact), productCodes (subset-match), deviceCountInBase
(integer equality), and 4 labeled-identifier booleans. MERGE_FIELDS +
COMPARED_FIELDS + FIELD_WEIGHTS extended in lockstep. Null-asymmetric
semantics match the April 20 MRI/singleUse/rx treatment.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: GUDID-deactivated short-circuit + banner UI + publishDate tile

**Files:**
- Modify: `harvester/src/orchestrator.py`
- Modify: `app/templates/review.html`
- Create: `harvester/src/validators/tests/test_orchestrator_deactivated.py`

- [ ] **Step 4.1: Write failing tests**

Create `harvester/src/validators/tests/test_orchestrator_deactivated.py`:

```python
import pytest
from unittest.mock import MagicMock, patch


def test_deactivated_short_circuit_writes_status_and_skips_compare():
    """run_validation sees deviceRecordStatus=Deactivated → inserts
    validationResult with status=gudid_deactivated, does not call
    compare_records, does not call _merge_gudid_into_device."""
    from orchestrator import run_validation

    # Mock db, validation_col, devices_col
    mock_db = MagicMock()
    mock_device = {
        "_id": "device-123",
        "brandName": "TestDevice",
        "catalogNumber": "CAT-1",
        "versionModelNumber": "MODEL-1",
    }
    mock_gudid = {
        "deviceRecordStatus": "Deactivated",
        "brandName": "TestDevice",
        "publishDate": "2020-01-01",
    }
    mock_db["devices"].find.return_value = [mock_device]
    mock_db["validationResults"].insert_one = MagicMock()
    mock_db["validationResults"].drop = MagicMock()

    with patch("orchestrator.get_db", return_value=mock_db), \
         patch("orchestrator.fetch_gudid_record",
               return_value=("DI-123", mock_gudid)), \
         patch("orchestrator._merge_gudid_into_device") as mock_merge, \
         patch("orchestrator.compare_records") as mock_compare:
        result = run_validation(overwrite=False)

    # Confirm compare_records was NOT called
    mock_compare.assert_not_called()
    # Confirm merge was NOT called
    mock_merge.assert_not_called()
    # Confirm insert_one was called with status=gudid_deactivated
    assert mock_db["validationResults"].insert_one.called
    call_arg = mock_db["validationResults"].insert_one.call_args[0][0]
    assert call_arg["status"] == "gudid_deactivated"
    assert call_arg["matched_fields"] is None
    assert call_arg["total_fields"] is None
    # Confirm result counter
    assert result.get("gudid_deactivated") == 1
```

- [ ] **Step 4.2: Run test, verify failure**

```
pytest harvester/src/validators/tests/test_orchestrator_deactivated.py -v
```
Expected: FAIL — no short-circuit exists yet.

- [ ] **Step 4.3: Add short-circuit to `run_validation`**

In `harvester/src/orchestrator.py`, locate the per-device loop inside `run_validation()`. Immediately after `fetch_gudid_record` returns a `gudid_record`, add the guard (before any call to `compare_records` or `_merge_gudid_into_device`):

```python
record_status = (gudid_record or {}).get("deviceRecordStatus")
if record_status == "Deactivated":
    validation_col.insert_one({
        "device_id": device["_id"],
        "brandName": device.get("brandName"),
        "status": "gudid_deactivated",
        "matched_fields": None,
        "total_fields": None,
        "match_percent": None,
        "weighted_percent": None,
        "description_similarity": None,
        "comparison_result": None,
        "gudid_record": gudid_record,
        "gudid_di": di,
        "gudid_record_status": record_status,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    result["gudid_deactivated"] = result.get("gudid_deactivated", 0) + 1
    continue
```

Initialize the counter near the top of `run_validation` where other counters live:

```python
result = {
    "full_matches": 0, "partial_matches": 0, "mismatches": 0,
    "gudid_not_found": 0, "gudid_deactivated": 0,
    ...
}
```

- [ ] **Step 4.4: Run test, verify pass**

```
pytest harvester/src/validators/tests/test_orchestrator_deactivated.py -v
```
Expected: PASS.

- [ ] **Step 4.5: Add banner to `review.html`**

In `app/templates/review.html`, between the hero `</section>` and the `<section class="stats-grid">` (after line 24), add:

```html
{% if validation.status == "gudid_deactivated" %}
<div class="banner banner-warning" style="padding: 14px 18px; border-left: 4px solid var(--warning); background: var(--warning-bg); margin-bottom: 20px;">
    <strong>GUDID record deactivated.</strong>
    The FDA has deactivated this device's GUDID entry
    ({{ validation.gudid_di or "N/A" }}{% if validation.gudid_record and validation.gudid_record.publishDate %}, last published {{ validation.gudid_record.publishDate }}{% endif %}).
    The harvested data below is the live source &mdash; no per-field comparison was run.
</div>
{% endif %}
```

Also wrap the existing field-comparison form so it only renders when `validation.status != "gudid_deactivated"`. Find the `{% else %}` branch of the `{% if mode == "info" %}` block at line 55. Before the `<form>` (line 79), add:

```html
{% if validation.status != "gudid_deactivated" %}
```

And close this new if at the end of that form block (before the final `{% endif %}` at line 141). The `mode="info"` branch (lines 55-77) renders when validation.status == "matched"; we want a similar read-only layout for `gudid_deactivated`, so extend its condition:

Change line 55:
```html
{% if mode == "info" %}
```
to:
```html
{% if mode == "info" or validation.status == "gudid_deactivated" %}
```

This causes the deactivated case to reuse the existing read-only 2-column harvested table.

- [ ] **Step 4.6: Add `publishDate` tile to stats grid**

In `app/templates/review.html`, inside the existing `<section class="stats-grid">` block (lines 26-53), add one more metric card right before the closing `</section>`:

```html
<div class="metric-card small">
    <p class="metric-label">GUDID Updated</p>
    <h3 class="metric-value mono" style="font-size: 15px;">
        {% if validation.gudid_record and validation.gudid_record.publishDate %}{{ validation.gudid_record.publishDate }}{% else %}N/A{% endif %}
    </h3>
</div>
```

- [ ] **Step 4.7: Smoke-test manually**

Find a device in Atlas with `deviceRecordStatus == "Deactivated"` (or manually insert one into validationResults for smoke testing). Navigate to `/review/<id>`. Confirm banner renders, read-only table shows harvested values, no comparison form.

- [ ] **Step 4.8: Commit**

```bash
git add harvester/src/orchestrator.py \
        app/templates/review.html \
        harvester/src/validators/tests/test_orchestrator_deactivated.py
git commit -m "$(cat <<'EOF'
feat(validators): short-circuit validation for Deactivated GUDID records

run_validation now checks deviceRecordStatus before compare_records.
Deactivated records write validationResults with status=gudid_deactivated,
null scoring fields, and are skipped for merge + verified_devices.
Review page shows a warning banner + reuses the existing mode=info
read-only table. New publishDate tile in the stats grid.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Harvest-gap observability counters

**Files:**
- Modify: `harvester/src/orchestrator.py`

- [ ] **Step 5.1: Write failing test**

Add to `harvester/src/validators/tests/test_orchestrator_deactivated.py` (reuse file):

```python
def test_harvest_gap_counters_fire():
    """When GUDID has productCodes or premarketSubmissions but device is null,
    counters increment and log is emitted."""
    from orchestrator import run_validation
    import logging

    mock_db = MagicMock()
    mock_device = {
        "_id": "device-456", "brandName": "X", "catalogNumber": "Y",
        "versionModelNumber": "Z",
        # Harvested has no productCodes or premarketSubmissions
    }
    mock_gudid = {
        "brandName": "X", "versionModelNumber": "Z",
        "productCodes": ["DYB"],
        "premarketSubmissions": ["K123456"],
        "deviceRecordStatus": "Published",
    }
    mock_db["devices"].find.return_value = [mock_device]
    mock_db["validationResults"].insert_one = MagicMock()
    mock_db["validationResults"].drop = MagicMock()

    with patch("orchestrator.get_db", return_value=mock_db), \
         patch("orchestrator.fetch_gudid_record",
               return_value=("DI-456", mock_gudid)), \
         patch("orchestrator._merge_gudid_into_device"):
        result = run_validation(overwrite=False)

    assert result.get("harvest_gap_product_codes") == 1
    assert result.get("harvest_gap_premarket") == 1
```

- [ ] **Step 5.2: Run test, verify failure**

Expected: FAIL — counters don't exist.

- [ ] **Step 5.3: Add counters and logging in orchestrator**

In `harvester/src/orchestrator.py`, in `run_validation()`, after `compare_records` returns and before `validation_col.insert_one`, add:

```python
if gudid_record.get("productCodes") and _is_null_list(device.get("productCodes")):
    logger.info(
        "[harvest-gap] device %s (%s): GUDID productCodes=%r, harvested=null",
        device.get("_id"), device.get("brandName"),
        gudid_record["productCodes"],
    )
    result["harvest_gap_product_codes"] = result.get("harvest_gap_product_codes", 0) + 1

if gudid_record.get("premarketSubmissions") and _is_null_list(device.get("premarketSubmissions")):
    logger.info(
        "[harvest-gap] device %s (%s): GUDID premarketSubmissions=%r, harvested=null",
        device.get("_id"), device.get("brandName"),
        gudid_record["premarketSubmissions"],
    )
    result["harvest_gap_premarket"] = result.get("harvest_gap_premarket", 0) + 1
```

Add a local helper at top of orchestrator.py:

```python
def _is_null_list(value) -> bool:
    return value is None or (isinstance(value, list) and len(value) == 0)
```

Initialize counters:

```python
result["harvest_gap_product_codes"] = 0
result["harvest_gap_premarket"] = 0
```

- [ ] **Step 5.4: Run test, verify pass**

```
pytest harvester/src/validators/tests/test_orchestrator_deactivated.py -v
```
Expected: PASS.

- [ ] **Step 5.5: Commit**

```bash
git add harvester/src/orchestrator.py \
        harvester/src/validators/tests/test_orchestrator_deactivated.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): harvest-gap observability for productCodes/premarket

INFO-level log + counter increment when GUDID has non-empty values for
productCodes or premarketSubmissions but the harvested device doc is
null/empty. Counters (harvest_gap_product_codes, harvest_gap_premarket)
appear on the run-result dict for quantifying harvester-extraction gaps.
No UI surface yet — logs + counters only per spec §3.e.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: LLM schema + prompt — add 3 new fields, remove `premarketSubmissions`

**Files:**
- Modify: `harvester/src/pipeline/llm_extractor.py`
- Modify: `harvester/src/pipeline/tests/test_llm_extractor_env.py` (extend existing or create new)

- [ ] **Step 6.1: Write failing test**

Add to `harvester/src/pipeline/tests/test_llm_extractor_schema.py` (create if missing):

```python
import pytest
from pipeline.llm_extractor import PAGE_FIELDS_SCHEMA


def test_schema_includes_new_fields():
    props = PAGE_FIELDS_SCHEMA["properties"]
    assert "indicationsForUse" in props
    assert "contraindications" in props
    assert "deviceClass" in props


def test_schema_no_longer_has_premarket_submissions():
    """premarketSubmissions moved to regex in Task 8; LLM no longer sees it."""
    assert "premarketSubmissions" not in PAGE_FIELDS_SCHEMA["properties"]


def test_deviceClass_enum_restriction():
    props = PAGE_FIELDS_SCHEMA["properties"]
    assert props["deviceClass"]["enum"] == ["I", "II", "III", None]
```

- [ ] **Step 6.2: Run tests, verify failures**

```
pytest harvester/src/pipeline/tests/test_llm_extractor_schema.py -v
```
Expected: FAIL — schema doesn't have the new fields, still has premarketSubmissions.

- [ ] **Step 6.3: Update `PAGE_FIELDS_SCHEMA`**

In `harvester/src/pipeline/llm_extractor.py`, update the schema (lines 65-89):

```python
PAGE_FIELDS_SCHEMA = {
    "type": "object",
    "properties": {
        "device_name": {"type": ["string", "null"]},
        "manufacturer": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "warning_text": {"type": ["string", "null"]},
        "MRISafetyStatus": {"type": ["string", "null"]},
        "deviceKit": {"type": ["boolean", "null"]},
        "environmentalConditions": {
            "type": ["object", "null"],
            "properties": {
                "conditions": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
            },
        },
        # Layer-3 additions
        "indicationsForUse": {"type": ["string", "null"]},
        "contraindications": {"type": ["string", "null"]},
        "deviceClass": {"type": ["string", "null"], "enum": ["I", "II", "III", None]},
        # REMOVED (moved to regex): "premarketSubmissions"
    },
    "required": ["device_name", "manufacturer", "description"],
}
```

- [ ] **Step 6.4: Update `PAGE_FIELDS_PROMPT`**

Find `PAGE_FIELDS_PROMPT` (around line 134). Replace the rules block by:
1. Removing the `premarketSubmissions` bullet (6 lines around line 151-154)
2. Appending three new bullets after the existing `environmentalConditions` rule:

```python
PAGE_FIELDS_PROMPT = """\
You are extracting medical device data from a manufacturer's product page for the FDA GUDID database.

Extract these fields from the page text below. Return valid JSON.

Rules:
- device_name: The commercial product name / brand name (e.g., "IN.PACT ADMIRAL", "ZILVER PTX"). \
NOT the manufacturer name. NOT a description or tagline.
- manufacturer: The company that makes this device. Use the legal entity name if visible \
(e.g., "Medtronic, Inc." not just "Medtronic").
- description: One factual, clinical sentence describing what this device IS and what it DOES. \
Focus on: device type, anatomy/condition treated, mechanism of action. \
Ignore: marketing claims, clinical trial results, testimonials.
- warning_text: Copy any warning, caution, or regulatory text verbatim from the page. \
Include text about single-use, Rx only, sterility, contraindications. null if none found.
- MRISafetyStatus: One of "MR Safe", "MR Conditional", "MR Unsafe", or null if not stated on the page.
- deviceKit: true if this product is sold as a kit or system containing multiple distinct components \
packaged together, false if it is a single standalone device, null if unclear.
- environmentalConditions: An object with a "conditions" array of storage/handling condition strings \
found on the page (e.g. {{"conditions": ["Store between 15-30°C", "Keep away from humidity > 85%"]}}). \
null if storage conditions are not stated on the page.
- indicationsForUse: Copy the "Indications for Use" section verbatim as free text. \
Typically appears as a paragraph near the top of the page. null if not present.
- contraindications: Copy the "Contraindications" section verbatim as free text. \
null if not present.
- deviceClass: FDA device class ("I", "II", or "III") if explicitly stated on the page. \
null if not stated. Only return one of those three literal values.

Page text:
{visible_text}"""
```

- [ ] **Step 6.5: Run tests, verify pass**

```
pytest harvester/src/pipeline/tests/test_llm_extractor_schema.py -v
```
Expected: PASS.

- [ ] **Step 6.6: Commit**

```bash
git add harvester/src/pipeline/llm_extractor.py \
        harvester/src/pipeline/tests/test_llm_extractor_schema.py
git commit -m "$(cat <<'EOF'
feat(llm): add indicationsForUse, contraindications, deviceClass fields

Three new page-level string fields in PAGE_FIELDS_SCHEMA + PAGE_FIELDS_PROMPT.
deviceClass enum-restricted to "I"/"II"/"III"/null. premarketSubmissions
removed from the schema — moves to regex extraction in regulatory_parser
(next task).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Regex premarket extraction with keyword-context hardening

**Files:**
- Modify: `harvester/src/pipeline/regulatory_parser.py`
- Modify: `harvester/src/pipeline/tests/test_regulatory_parser.py` (create if missing)
- Modify: `harvester/src/pipeline/llm_extractor.py`

- [ ] **Step 7.1: Write failing tests**

Add to `harvester/src/pipeline/tests/test_regulatory_parser.py` (create if missing):

```python
import pytest
from pipeline.regulatory_parser import extract_premarket_submissions


class TestPremarketSubmissionsExtraction:
    def test_positive_with_510k_keyword(self):
        text = "510(k) clearance K123456 granted in 2023"
        assert extract_premarket_submissions(text) == ["K123456"]

    def test_positive_with_pma_keyword(self):
        text = "PMA P210034 approved by FDA"
        assert extract_premarket_submissions(text) == ["P210034"]

    def test_positive_cleared_by_fda(self):
        text = "Cleared by FDA under K123456 and K789012"
        assert sorted(extract_premarket_submissions(text)) == ["K123456", "K789012"]

    def test_positive_k_number_keyword(self):
        text = "K-number K123456 is on file"
        assert extract_premarket_submissions(text) == ["K123456"]

    def test_positive_den_number(self):
        text = "De novo clearance: DEN123456 premarket"
        assert extract_premarket_submissions(text) == ["DEN123456"]

    def test_negative_catalog_like_no_keyword(self):
        """K1234567 appearing as a catalog number must NOT be extracted."""
        text = "K1234567 STENT VISI PRO"
        assert extract_premarket_submissions(text) is None

    def test_negative_product_code_context_doesnt_count(self):
        text = "Product code K1234567 in our catalog"
        assert extract_premarket_submissions(text) is None

    def test_multiple_matches_each_needs_own_keyword(self):
        """K1 has keyword within 30 chars, K2 doesn't — only K1 extracted."""
        text = "Our 510(k) K111111 was filed. Later we made K2222222 for inventory."
        assert extract_premarket_submissions(text) == ["K111111"]

    def test_empty_returns_none(self):
        assert extract_premarket_submissions("") is None
        assert extract_premarket_submissions(None) is None

    def test_deduplicates_and_sorts(self):
        text = "510(k) K222222 and also K111111 and K111111 again premarket"
        assert extract_premarket_submissions(text) == ["K111111", "K222222"]
```

- [ ] **Step 7.2: Run tests, verify failures**

```
pytest harvester/src/pipeline/tests/test_regulatory_parser.py -v
```
Expected: FAIL — function doesn't exist.

- [ ] **Step 7.3: Implement `extract_premarket_submissions`**

Add to `harvester/src/pipeline/regulatory_parser.py`:

```python
_PREMARKET_RE = re.compile(r"\b(K\d{6,7}|P\d{6}|DEN\d{6})\b")
_REG_KEYWORDS = re.compile(
    r"510\s*\(\s*k\s*\)|premarket|\bPMA\b|FDA\s+clearance|K[- ]number|cleared\s+by\s+FDA",
    re.IGNORECASE,
)


def extract_premarket_submissions(text: str | None) -> list[str] | None:
    """Extract K-numbers, PMA numbers, and DEN-numbers that appear within ±30
    characters of a regulatory keyword. Returns sorted deduplicated list, or
    None if no qualifying matches found.

    Keyword context (within ±30 chars of each match):
      - "510(k)" (with any whitespace/case variation)
      - "premarket"
      - "PMA" (word-bounded)
      - "FDA clearance"
      - "K-number" / "K number"
      - "cleared by FDA"
    """
    if not text:
        return None
    found = set()
    for match in _PREMARKET_RE.finditer(text):
        start, end = match.span()
        window = text[max(0, start - 30):min(len(text), end + 30)]
        if _REG_KEYWORDS.search(window):
            found.add(match.group(1))
    return sorted(found) or None
```

- [ ] **Step 7.4: Wire into `extract_all_fields`**

In `harvester/src/pipeline/llm_extractor.py`, find `extract_all_fields` (line 434). After `page_fields = extract_page_fields(visible_text)` (line 436), add:

```python
# Extract premarketSubmissions via regex (replaces former LLM extraction)
from pipeline.regulatory_parser import extract_premarket_submissions
combined_text = " ".join(filter(None, [
    page_fields.get("warning_text"),
    page_fields.get("description"),
    page_fields.get("indicationsForUse"),
]))
page_fields["premarketSubmissions"] = extract_premarket_submissions(combined_text)
```

Place the import at the top of the file if not already imported.

- [ ] **Step 7.5: Run full suite**

```
pytest
```
Expected: pass.

- [ ] **Step 7.6: Commit**

```bash
git add harvester/src/pipeline/regulatory_parser.py \
        harvester/src/pipeline/llm_extractor.py \
        harvester/src/pipeline/tests/test_regulatory_parser.py
git commit -m "$(cat <<'EOF'
feat(regulatory): regex premarket extraction with keyword context

New extract_premarket_submissions function. Matches K-numbers, PMA
numbers, DEN-numbers but only when a regulatory keyword appears within
±30 chars (510(k), premarket, PMA, FDA clearance, K-number, cleared by
FDA). Avoids false positives on catalog-like SKUs (e.g., "K1234567 STENT"
is excluded when no regulatory keyword is nearby). Wired into
extract_all_fields — runs over concatenation of warning_text, description,
and indicationsForUse after the LLM pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `premarketSubmissions` compare logic + weight + COMPARED_FIELDS entry

**Files:**
- Modify: `harvester/src/validators/comparison_validator.py`
- Modify: `app/routes/review.py`
- Modify: `harvester/src/validators/tests/test_comparison_new_fields.py`

- [ ] **Step 8.1: Write failing tests**

Add to `test_comparison_new_fields.py`:

```python
class TestPremarketSubmissionsSubsetMatch:
    def test_harvested_subset_match(self):
        h = _with_defaults({"premarketSubmissions": ["K123456"]})
        g = _with_defaults({"premarketSubmissions": ["K123456", "K789012"]})
        per_field, _ = compare_records(h, g)
        assert per_field["premarketSubmissions"]["status"] == "match"

    def test_harvested_claims_unfiled_mismatch(self):
        h = _with_defaults({"premarketSubmissions": ["K999999"]})
        g = _with_defaults({"premarketSubmissions": ["K123456"]})
        per_field, _ = compare_records(h, g)
        assert per_field["premarketSubmissions"]["status"] == "mismatch"

    def test_harvested_null_not_compared(self):
        h = _with_defaults({"premarketSubmissions": None})
        g = _with_defaults({"premarketSubmissions": ["K123456"]})
        per_field, _ = compare_records(h, g)
        assert per_field["premarketSubmissions"]["status"] == "not_compared"

    def test_both_empty_both_null(self):
        h = _with_defaults({"premarketSubmissions": []})
        g = _with_defaults({"premarketSubmissions": []})
        per_field, _ = compare_records(h, g)
        assert per_field["premarketSubmissions"]["status"] == "both_null"
```

- [ ] **Step 8.2: Run tests, verify failures**

```
pytest harvester/src/validators/tests/test_comparison_new_fields.py::TestPremarketSubmissionsSubsetMatch -v
```
Expected: FAIL — field not in `compare_records`.

- [ ] **Step 8.3: Add compare block + weight**

In `FIELD_WEIGHTS` (comparison_validator.py):
```python
    "premarketSubmissions": 2,
```

In `compare_records()`, after the Layer-2 productCodes block, add:

```python
    # premarketSubmissions — subset match (same semantics as productCodes)
    h_pm = harvested.get("premarketSubmissions"); g_pm = gudid.get("premarketSubmissions")
    if _is_null(h_pm) and _is_null(g_pm):
        results["premarketSubmissions"] = {"harvested": h_pm, "gudid": g_pm, "status": FieldStatus.BOTH_NULL}
    elif _is_null(h_pm):
        results["premarketSubmissions"] = {"harvested": h_pm, "gudid": g_pm, "status": FieldStatus.NOT_COMPARED}
    elif _is_null(g_pm):
        results["premarketSubmissions"] = {"harvested": h_pm, "gudid": g_pm, "status": FieldStatus.MISMATCH}
    else:
        results["premarketSubmissions"] = {
            "harvested": h_pm, "gudid": g_pm,
            "status": _subset_match(h_pm, g_pm),
        }
```

In `app/routes/review.py`, add to `COMPARED_FIELDS`:
```python
    ("premarketSubmissions", "Premarket Submissions"),
```

- [ ] **Step 8.4: Run full suite**

```
pytest
```
Expected: pass.

- [ ] **Step 8.5: Commit**

```bash
git add harvester/src/validators/comparison_validator.py \
        app/routes/review.py \
        harvester/src/validators/tests/test_comparison_new_fields.py
git commit -m "$(cat <<'EOF'
feat(validators): compare premarketSubmissions with subset semantics

Added to compare_records + FIELD_WEIGHTS (weight 2) + COMPARED_FIELDS.
Same subset rules as productCodes: mismatch if harvester claims clearances
GUDID doesn't have on file; match if harvested is a subset of GUDID.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Review UI — "Additional Information" panel for Layer-3 harvest-only fields

**Files:**
- Modify: `app/templates/review.html`

- [ ] **Step 9.1: Add the panel below the comparison form**

In `app/templates/review.html`, after the closing `</form>` (around line 140, before the final `{% endif %}`), add a new section that renders Layer-3 harvest-only fields:

```html
{% if device.indicationsForUse or device.contraindications or device.deviceClass %}
<section class="panel" style="margin-top: 20px;">
    <div class="panel-header">
        <div>
            <h3>Additional Information</h3>
            <p>Fields harvested from the manufacturer page. Not compared against GUDID.</p>
        </div>
    </div>
    {% if device.deviceClass %}
    <div class="review-field-row info-mode">
        <div class="review-field-name">FDA Device Class</div>
        <div class="review-value harvested">Class {{ device.deviceClass }}</div>
    </div>
    {% endif %}
    {% if device.indicationsForUse %}
    <div class="review-field-row info-mode">
        <div class="review-field-name">Indications for Use</div>
        <div class="review-value harvested" style="white-space: pre-wrap;">{{ device.indicationsForUse }}</div>
    </div>
    {% endif %}
    {% if device.contraindications %}
    <div class="review-field-row info-mode">
        <div class="review-field-name">Contraindications</div>
        <div class="review-value harvested" style="white-space: pre-wrap;">{{ device.contraindications }}</div>
    </div>
    {% endif %}
</section>
{% endif %}
```

This renders on both `mode="review"` and `mode="info"` reviews (any non-deactivated state), as long as at least one of the three fields has a value.

- [ ] **Step 9.2: Smoke-test**

Run a fresh harvest on a URL that has "Indications for Use" content. Revalidate. Open the review page — confirm the panel renders below the comparison form.

- [ ] **Step 9.3: Commit**

```bash
git add app/templates/review.html
git commit -m "$(cat <<'EOF'
feat(review): Additional Information panel for Layer-3 harvest-only fields

Renders indicationsForUse, contraindications, and deviceClass below the
comparison form when any of the three are populated. Uses existing
info-mode row styling; whitespace preserved for multi-line clinical text.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Dashboard — "Deactivated" metric card

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `harvester/src/orchestrator.py` (`get_dashboard_stats`)

- [ ] **Step 10.1: Extend `get_dashboard_stats`**

In `harvester/src/orchestrator.py`, locate `get_dashboard_stats` (grep for the function name). Add a deactivated count alongside matched/partial/mismatch:

```python
# Inside get_dashboard_stats:
deactivated_count = db["validationResults"].count_documents({"status": "gudid_deactivated"})
# ...existing code...
return {
    "matches": matched_count,
    "partial_matches": partial_count,
    "mismatches": mismatch_count,
    "deactivated": deactivated_count,  # new
    # ...existing fields...
}
```

- [ ] **Step 10.2: Add metric card to `dashboard.html`**

In `app/templates/dashboard.html`, locate the metric cards grid (grep for `metric-card`). After the existing Mismatch card, add:

```html
<div class="metric-card">
    <p class="metric-label">Deactivated</p>
    <h3 class="metric-value" style="color: var(--warning);">{{ stats.deactivated or 0 }}</h3>
    <p class="metric-sublabel">GUDID entries marked deactivated by FDA</p>
</div>
```

No filter wiring (non-filterable for this pass per spec).

- [ ] **Step 10.3: Smoke-test**

Open dashboard. Confirm the "Deactivated" card renders with the count (may be 0 if no deactivated records exist yet).

- [ ] **Step 10.4: Commit**

```bash
git add harvester/src/orchestrator.py \
        app/templates/dashboard.html
git commit -m "$(cat <<'EOF'
feat(dashboard): Deactivated metric card

Non-filterable tile shows the count of validationResults with
status=gudid_deactivated. Styled with warning color. Populated via a
new count_documents call in get_dashboard_stats.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: PXB35 integration test + fixtures

**Files:**
- Create: `tests/fixtures/pxb35_harvested.json`
- Create: `tests/fixtures/pxb35_gudid_response.json`
- Create: `tests/test_pxb35_integration.py`

- [ ] **Step 11.1: Create fixture files**

Create `tests/fixtures/` directory if it doesn't exist:

```
mkdir -p tests/fixtures
```

Create `tests/fixtures/pxb35_harvested.json`:

```json
{
    "versionModelNumber": "PXB35-09-17-080",
    "catalogNumber": "PXB35-09-17-080",
    "brandName": "Visi-Pro™",
    "companyName": "Medtronic Inc.",
    "deviceDescription": "A peripheral vascular self-expanding nitinol stent system designed for the treatment of peripheral arterial disease in the superficial femoral artery.",
    "MRISafetyStatus": "MR Conditional",
    "singleUse": true,
    "rx": true,
    "productCodes": ["DYB"],
    "premarketSubmissions": ["K123456"]
}
```

Create `tests/fixtures/pxb35_gudid_response.json`:

```json
{
    "versionModelNumber": "PXB35-09-17-080",
    "catalogNumber": "PXB35-09-17-080",
    "brandName": "Visi-Pro",
    "companyName": "Covidien LP",
    "deviceDescription": "PXB35-09-17-080 STENT NITINOL",
    "MRISafetyStatus": "MR Conditional",
    "singleUse": "true",
    "rx": "true",
    "productCodes": ["DYB", "OXM"],
    "premarketSubmissions": ["K123456", "K789012"],
    "gmdnPTName": "Stent, Peripheral",
    "gmdnCode": "12345",
    "deviceCountInBase": 1,
    "publishDate": "2023-01-15",
    "deviceRecordStatus": "Published",
    "issuingAgency": "GS1",
    "lotBatch": "true",
    "serialNumber": "false",
    "manufacturingDate": "true",
    "expirationDate": "true"
}
```

- [ ] **Step 11.2: Create the integration test**

Create `tests/test_pxb35_integration.py`:

```python
"""End-to-end compare_records test against the PXB35-09-17-080 device.

This device exhibits three of the new Layer-1 behaviors simultaneously:
  - Corporate alias on companyName (Medtronic vs Covidien LP)
  - GUDID description is a SKU label (short + contains model number)
  - Trademark symbol stripping on brandName (Visi-Pro™ vs Visi-Pro)
Plus a subset-match on productCodes + premarketSubmissions.
"""

import json
from pathlib import Path

import pytest

from validators.comparison_validator import compare_records, FieldStatus


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def harvested():
    with open(FIXTURES / "pxb35_harvested.json") as f:
        return json.load(f)


@pytest.fixture
def gudid():
    with open(FIXTURES / "pxb35_gudid_response.json") as f:
        return json.load(f)


def test_companyName_is_corporate_alias(harvested, gudid):
    per_field, _ = compare_records(harvested, gudid)
    assert per_field["companyName"]["status"] == FieldStatus.CORPORATE_ALIAS
    assert per_field["companyName"]["alias_group"] == "Medtronic"


def test_deviceDescription_is_sku_label_skip(harvested, gudid):
    per_field, _ = compare_records(harvested, gudid)
    assert per_field["deviceDescription"]["status"] == FieldStatus.SKU_LABEL_SKIP
    assert per_field["deviceDescription"]["similarity"] is None


def test_brandName_matches_after_trademark_strip(harvested, gudid):
    per_field, _ = compare_records(harvested, gudid)
    assert per_field["brandName"]["status"] == FieldStatus.MATCH


def test_productCodes_subset_match(harvested, gudid):
    per_field, _ = compare_records(harvested, gudid)
    # harvested ["DYB"] ⊆ GUDID ["DYB", "OXM"] → match
    assert per_field["productCodes"]["status"] == FieldStatus.MATCH


def test_premarketSubmissions_subset_match(harvested, gudid):
    per_field, _ = compare_records(harvested, gudid)
    # harvested ["K123456"] ⊆ GUDID ["K123456", "K789012"] → match
    assert per_field["premarketSubmissions"]["status"] == FieldStatus.MATCH


def test_summary_unweighted_all_match(harvested, gudid):
    """All compared fields should resolve to match or corporate_alias,
    which both count toward the numerator."""
    per_field, summary = compare_records(harvested, gudid)
    assert summary["unweighted_numerator"] == summary["unweighted_denominator"]
    assert summary["unweighted_denominator"] > 0


def test_summary_weighted_equals_denominator(harvested, gudid):
    """Same as unweighted — everything matches (counting alias as match)."""
    _per_field, summary = compare_records(harvested, gudid)
    assert summary["numerator"] == summary["denominator"]
```

- [ ] **Step 11.3: Run integration test**

```
pytest tests/test_pxb35_integration.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 11.4: Commit**

```bash
git add tests/fixtures/pxb35_harvested.json \
        tests/fixtures/pxb35_gudid_response.json \
        tests/test_pxb35_integration.py
git commit -m "$(cat <<'EOF'
test: PXB35-09-17-080 integration test + fixtures

End-to-end compare_records assertions on hand-built fixtures that
exercise three Layer-1 behaviors simultaneously (corporate alias,
SKU-label-skip on description, trademark strip on brand) plus subset
matches on productCodes + premarketSubmissions. Stubbed rather than
live Atlas query so CI stays deterministic.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Docs + changelog

**Files:**
- Modify: `harvester/src/validators/CLAUDE.md`
- Modify: `harvester/src/pipeline/CLAUDE.md`
- Modify: `CLAUDE.md` (project root)
- Create: Obsidian vault file `Senior Project/Changelogs/Changelog - 2026-04-22.md`

- [ ] **Step 12.1: Update `harvester/src/validators/CLAUDE.md`**

Append/revise the scoring section to reference the Layer-2 fields added in PR2. Extend the compared-fields table to include the 9 new fields with their weights and statuses. Add a subsection titled "GUDID deactivated short-circuit" documenting the skip semantics.

Edit the "Compared fields" table inside `## Comparison Scoring`:

```markdown
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
```

Add a section at the end:

```markdown
## GUDID deactivated short-circuit

When `fetch_gudid_record()` returns a device with `deviceRecordStatus == "Deactivated"`, `run_validation()` skips `compare_records()` entirely and writes a `validationResults` document with:
- `status: "gudid_deactivated"`
- `matched_fields`, `total_fields`, `match_percent`, `weighted_percent`, `description_similarity`: all `None`
- `comparison_result`: `None`

Deactivated records do **not** populate `verified_devices` and do **not** trigger `_merge_gudid_into_device()` — stale GUDID shouldn't overwrite live harvested data. The review page renders a warning banner and falls back to the `mode="info"` read-only layout.
```

- [ ] **Step 12.2: Update `harvester/src/pipeline/CLAUDE.md`**

Append a subsection on regex premarket extraction:

```markdown
## Premarket Submission Extraction

`premarketSubmissions` (K-numbers, PMA numbers, DEN-numbers) are extracted via regex in `regulatory_parser.extract_premarket_submissions()`, not via the LLM. The regex requires a regulatory keyword (510(k), premarket, PMA, FDA clearance, K-number, cleared by FDA) within ±30 characters of each match — this prevents false positives on catalog SKUs that happen to start with `K` followed by 6–7 digits.

The LLM pipeline (`extract_all_fields`) invokes the regex extractor over the concatenation of `warning_text`, `description`, and `indicationsForUse` after the page-fields pass returns. `premarketSubmissions` is attached to each record before insertion into MongoDB.
```

And update the schema section to list the three new LLM fields:

```markdown
## PAGE_FIELDS_SCHEMA

Page-level extractions (LLM):
- `device_name`, `manufacturer`, `description`, `warning_text`
- `MRISafetyStatus` (enum string)
- `deviceKit` (bool)
- `environmentalConditions` (object with conditions array)
- `indicationsForUse` (free text; Layer-3)
- `contraindications` (free text; Layer-3)
- `deviceClass` (enum "I"/"II"/"III"; Layer-3)

`premarketSubmissions` is NOT in the LLM schema — it's populated by regex post-processing.
```

- [ ] **Step 12.3: Update root `CLAUDE.md` Validation Scoring section**

In `CLAUDE.md` at repo root, locate the "Validation Scoring" section. Replace with:

```markdown
### Validation Scoring

`comparison_validator.py` returns `(per_field, summary)`. Per-field `status` is one of six values: `match` / `mismatch` / `corporate_alias` / `not_compared` / `both_null` / `sku_label_skip`. Compared fields:

- **Identifier (weight 3):** `versionModelNumber`, `catalogNumber`, `brandName`, `companyName`, `gmdnPTName`, `productCodes` (subset match)
- **Enum / regulatory (weight 2):** `MRISafetyStatus`, `singleUse`, `rx`, `gmdnCode`, `deviceCountInBase`, `issuingAgency`, `premarketSubmissions` (subset)
- **Labeling (weight 1):** `lotBatch`, `serialNumber`, `manufacturingDate`, `expirationDate`, `deviceDescription` (Jaccard, quality-gated)

Scoring produces both `match_percent` (unweighted count) and `weighted_percent` (using FIELD_WEIGHTS). Status thresholds (`matched`/`partial_match`/`mismatch`) drive from unweighted only; weighted is display + audit.

Corporate-alias match on `companyName` resolves via `company_aliases.py` — six seed parent groups (Medtronic, Boston Scientific, BD, Abbott, Johnson & Johnson, Stryker). Alias matches count +1 toward both numerator and denominator.

GUDID deactivated short-circuit: when `deviceRecordStatus == "Deactivated"`, validation skips comparison and records `status: "gudid_deactivated"`. No merge, no verified_devices.
```

- [ ] **Step 12.4: Create Obsidian changelog**

Use the Obsidian MCP tools (or manually via the Obsidian app) to create `Senior Project/Changelogs/Changelog - 2026-04-22.md`. Format matching the April 20/21 entries:

```markdown
# Changelog - April 22, 2026

## Session Summary

Shipped the validator + harvester data-quality expansion from the 2026-04-22 spec across two PRs. PR1 (Layer 1) replaced the tri-state match boolean with a six-state status enum, added company alias resolution, GUDID description quality classifier, trademark normalization wiring, both-null handling, and weighted scoring. PR2 (Layers 2 + 3) added eight new GUDID fields, the deactivated short-circuit, three new LLM extractions, regex-based premarket submission extraction with keyword-context hardening, harvest-gap observability counters, and the PXB35 integration test.

Final state: 430+ tests passing (baseline 407 + new), no regressions. Two PRs landed on the `Jason` branch.

---

## PR1 — Validator UX + Scoring (Layer 1)

### Why

Reviewing the PXB35-09-17-080 record surfaced four systemic issues in the comparison validator: (1) Medtronic-vs-Covidien-LP scoring as mismatch despite being the same corporate entity after the 2015 acquisition; (2) Jaccard similarity against short SKU-style GUDID descriptions producing noise percentages (3–8%) that looked like catastrophic mismatches; (3) trademark symbols (™®©℠) and smart quotes not stripped in the compare path despite `clean_brand_name` existing; (4) reviewers clicking through mandatory radio pickers on rows where both sides were null.

### Design decisions

- **Status enum replaces tri-state bool.** The existing `match: True|False|None` couldn't cleanly model the new states (both_null, corporate_alias, sku_label_skip). Replaced with a string enum on every per-field result. Orchestrator + review route migrated; legacy fallback in review.py handles pre-migration validationResults documents.
- **Alias matches count toward numerator.** Corporate-alias pairs (e.g., Medtronic vs Covidien LP) count as +1 match in both unweighted and weighted scoring. The `alias_group` field on the per-field result carries the canonical parent name for the UI badge.
- **Quality classifier gates description comparison.** Four heuristics (length < 40, contains model/catalog, ≥70% uppercase, SKU pattern) detect when GUDID stores a SKU in deviceDescription instead of prose. On trigger, similarity is suppressed and the field is excluded from scoring.
- **Weighted scoring display-only.** FIELD_WEIGHTS introduced (identifier=3, regulatory=2, labeling=1, description=1) and `weighted_percent` recorded on validationResults, but validation status (matched/partial/mismatch) still derives from unweighted. Dashboard default sort stays unweighted for the capstone demo.

### Files modified (PR1)

[list of files]

### Commits (PR1)

[list of commits]

---

## PR2 — GUDID Fields + Harvester Extensions (Layers 2 + 3)

### Why

Coordinated extension following PR1: eight new GUDID fields the validator wasn't reading, three new manufacturer-page extractions (indications, contraindications, device class), and a regex-based premarket submission extractor to replace the LLM's hallucination-prone K-number extraction. Deactivated-GUDID short-circuit added so stale FDA records stop poisoning live device fields via the merge helper.

### Design decisions

- **Defensive extraction mandatory.** The April 8 validator crash (null-intermediate `AttributeError` on `environmentalConditions.storageHandling`) set the pattern: every new GUDID path uses `or`-fallback unwrap (`device.get("key") or default`), never the two-argument `.get()` form. Unit tests cover happy/missing/null-intermediate/empty-list/wrong-type per path. First task of PR2 ran a verification script against 10 real GUDID responses before any field was added.
- **Subset-match for productCodes + premarketSubmissions.** Manufacturer pages often advertise only the primary FDA classification code or a single 510(k) clearance even when GUDID has multiple. Rule: match if harvested ⊆ GUDID; mismatch if harvested has elements not in GUDID (manufacturer claiming a clearance not on file).
- **Regex premarket extraction with keyword context.** Raw K-number regex false-positives on catalog SKUs (K1234567 stent). Hardened to require "510(k)" / "premarket" / "PMA" / "FDA clearance" / "K-number" / "cleared by FDA" within ±30 chars of each match.
- **Deactivated short-circuit skips merge.** `_merge_gudid_into_device()` is skipped for deactivated records — GUDID data is stale by definition in that state, so copying it into live device fields would poison the dataset.
- **Harvest-gap observability.** The subset-match rules return `not_compared` when harvested is empty, masking extraction misses. INFO logs + counters (`harvest_gap_product_codes`, `harvest_gap_premarket`) let us quantify gaps without adding UI surface.

### Files modified (PR2)

[list of files]

### Commits (PR2)

[list of commits]

---

## Verification

- 430+ tests pass
- Manual: corporate-alias record (Medtronic/Covidien) renders with blue ALIAS badge
- Manual: SKU-label GUDID description renders with amber badge and no % similar
- Manual: deactivated GUDID record renders banner + read-only harvested table
- Manual: new "Additional Information" panel renders indications/contraindications/deviceClass when populated
- Manual: dashboard "Deactivated" tile renders with correct count
- CSP still functional (no inline JS added)
- CSRF still enforced on /review/<id>/save

## Deferred to a later pass (flagged for post-demo)

- Default dashboard sort flip to weighted-desc
- UI surface for harvest_gap_* counters (currently logs-only)
- Expanded COMPANY_ALIASES seed list beyond the six initial groups — draw from observed mismatches in the production dataset
```

Fill in the `[list of files]` and `[list of commits]` placeholders by running `git log --oneline <PR-start>..HEAD` for each PR range and `git diff --stat <PR-start>..HEAD`.

- [ ] **Step 12.5: Commit the docs updates**

```bash
git add harvester/src/validators/CLAUDE.md \
        harvester/src/pipeline/CLAUDE.md \
        CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: sync CLAUDE.md trio with PR1+PR2 validator/harvester changes

validators/CLAUDE.md: scoring section rewritten for 6-status enum, 17
compared fields with weights, corporate alias block, deactivated
short-circuit section. pipeline/CLAUDE.md: regex premarket extraction
subsection, three new LLM schema fields. Root CLAUDE.md: Validation
Scoring section reflects new field list + weighted scoring + deactivated
behavior.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

The Obsidian changelog is saved via the Obsidian app/MCP — not a git-tracked file, no commit needed.

---

## Post-PR2 checklist

Before merging PR2 to `main`:

- [ ] Full `pytest` green (430+ tests)
- [ ] Manual: deactivated-GUDID short-circuit exercised on a known deactivated record
- [ ] Manual: harvest-gap log lines appear in the log file when running validation on a device where GUDID has productCodes + harvested doesn't
- [ ] Manual: PXB35 integration test passes: `pytest tests/test_pxb35_integration.py -v`
- [ ] CSP, CSRF, and all security headers still pass: `curl -sI http://localhost:8500/auth/login`
- [ ] API keys rotated (outstanding from April 20 — operational, not this PR)
- [ ] Changelog entry written in Obsidian

---

## Task 1 path verification findings (fill in after running)

**Important note:** `gudid_record` stored in `validationResults` is a *normalized projection*
(16 comparison fields only), not the raw API response. Running the script against stored docs
yields null for all 11 paths. The real-data check was done by querying the live GUDID API
directly for 3 known DIs (10705032057615, 00195451000539, 00195451000201).

```
DI 10705032057615 (PALMAZ GENESIS):
  gmdnPTName             = 'Bare-metal biliary stent'          → resolves cleanly
  gmdnCode               = '43691'                             → resolves cleanly
  productCodes           = ['FGE']                             → resolves cleanly
  deviceCountInBase      = None  (actual key: deviceCount=1)   → SPEC PATH WRONG
  publishDate            = None  (actual key: devicePublishDate='2024-07-31T00:00:00.000Z') → SPEC PATH WRONG
  deviceRecordStatus     = 'Published'                         → resolves cleanly
  issuingAgency          = None  (actual key: deviceIdIssuingAgency='GS1')  → SPEC PATH WRONG
  lotBatch               = None  (lives at device.lotBatch=True, not identifier) → SPEC PATH WRONG
  serialNumber           = None  (lives at device.serialNumber=False)        → SPEC PATH WRONG
  manufacturingDate      = None  (lives at device.manufacturingDate=False)   → SPEC PATH WRONG
  expirationDate         = None  (lives at device.expirationDate=True)       → SPEC PATH WRONG

DI 00195451000539 (Shockwave E8):
  gmdnPTName = 'Intravascular lithotripsy system catheter, balloon, peripheral' → resolves cleanly
  gmdnCode   = '66729'                  → resolves cleanly
  productCodes = ['PPN', 'OEZ', 'JAA'] → resolves cleanly (multiple codes)
  deviceCount=1, devicePublishDate='2024-04-17T...', deviceRecordStatus='Published'
  deviceIdIssuingAgency='GS1', lotBatch=True, serialNumber=True

DI 00195451000201 (Shockwave M5+):
  gmdnCode='66729', productCodes=['JAA', 'OEZ', 'PPN']
  deviceCount=1, devicePublishDate='2021-05-11T...', deviceRecordStatus='Published'
  deviceIdIssuingAgency='GS1', lotBatch=True, serialNumber=False
```

Any paths that differed from the spec:

```
5 path corrections required. Spec updated in:
docs/superpowers/specs/2026-04-22-validator-harvester-data-quality-design.md

1. deviceCountInBase
   Spec: device.deviceCountInBase
   Real: device.deviceCount  (deviceCountInBase always null; deviceCount=1 for all samples)

2. publishDate
   Spec: device.publishDate (fallback: device.devicePublishDate)
   Real: device.publishDate is always null. device.devicePublishDate always populates.
         Spec updated to use device.devicePublishDate directly (no fallback needed).

3. issuingAgency
   Spec: device.identifiers.identifier[0].issuingAgency
   Real: device.identifiers.identifier[Primary].deviceIdIssuingAgency
         Key name is deviceIdIssuingAgency; should select Primary-type identifier,
         not blindly take index 0 (index 0 may be a Package identifier).

4. lotBatch / serialNumber / manufacturingDate / expirationDate
   Spec: device.identifiers.identifier[0].<field>
   Real: device.<field>  (top-level booleans, not inside identifiers)
         All four live directly on the device object.
         lotBatch and expirationDate = True; serialNumber and manufacturingDate = False
         for the tested samples. These are boolean flags, as the spec expected.

5 paths confirmed correct without changes:
   gmdnPTName, gmdnCode, productCodes, deviceRecordStatus — all resolve cleanly.
   deviceRecordStatus = "Published" across all tested samples (Deactivated branch
   will not be exercised by current data, but the path is correct).
```
