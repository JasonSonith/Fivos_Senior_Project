# Validator Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix four independent validator bugs (F: 1:1 GUDID mapping + upsert, B: dropped catalogNumber, D: null-sentinel filtering, G: dimension comparison) so `run_validation()` produces exactly one `validationResults` doc per device, every device's catalog surfaces in comparisons, failed GUDID lookups don't pollute the review queue, and all 7 measurement fields are compared with unit conversion + tolerance.

**Architecture:** Orchestrator swaps `insert_one` for `update_one(... upsert=True)` keyed by `device_id`. A new `select_best_gudid_di()` in `gudid_client.py` picks the best DI via exact catalog+model match. GUDID DI is cached on `devices._gudid`. A new `extract_gudid_dimensions()` maps GUDID's `deviceSizes` array to canonical field/unit pairs, and `compare_records()` gains 7 dimension comparisons using existing `unit_conversions.py`. Null-sentinel validations get a new `status="invalid_gudid_response"` and are excluded from dashboard stats + tables.

**Tech Stack:** pymongo, FastAPI + Jinja2, pytest, existing `harvester/src/normalizers/unit_conversions.py` (canonical units: mm / g / mL / mmHg).

**Spec:** `docs/superpowers/specs/2026-04-21-validator-correctness-design.md`

**Spec correction:** The spec lists pressure canonical unit as "atm". The project's `unit_conversions.py` uses `mmHg`. Plan uses `mmHg`. Adjust the spec after implementation if desired.

---

## Task 1: F — Upsert + Deterministic DI Selection + DI Caching

**Files:**
- Modify: `harvester/src/orchestrator.py` — `run_validation()` (lines 322-442)
- Modify: `harvester/src/validators/gudid_client.py` — extend `search_gudid_di` to return list; add `select_best_gudid_di`
- Modify: `harvester/src/tests/test_orchestrator.py` — add upsert + confidence tests
- Test: new file `harvester/src/validators/tests/test_gudid_client.py`

---

- [ ] **Step 1.1: Write failing test for upsert idempotency**

File: `harvester/src/tests/test_orchestrator.py` — append a new test class at the end of the file.

```python
class TestRunValidationUpsert:
    """F.1: run_validation upserts by device_id — re-runs don't accumulate."""

    @patch("orchestrator.get_db")
    @patch("orchestrator.fetch_gudid_record")
    def test_rerun_same_device_produces_single_validation_doc(
        self, mock_fetch, mock_get_db
    ):
        from bson import ObjectId
        device_id = ObjectId()
        device = {
            "_id": device_id,
            "versionModelNumber": "XYZ-1",
            "catalogNumber": "CAT-1",
            "brandName": "TestBrand",
            "companyName": "TestCo",
        }
        gudid = {
            "versionModelNumber": "XYZ-1",
            "catalogNumber": "CAT-1",
            "brandName": "TestBrand",
            "companyName": "TestCo",
            "MRISafetyStatus": None, "singleUse": None, "rx": None,
            "deviceDescription": "desc",
        }
        db = MagicMock()
        db["devices"].find.return_value = [device]
        db["validationResults"] = MagicMock()
        db["verified_devices"] = MagicMock()
        mock_get_db.return_value = db
        mock_fetch.return_value = ("DI-123", gudid)

        from orchestrator import run_validation
        run_validation(overwrite=False)
        run_validation(overwrite=False)

        # Both runs must upsert on the SAME device_id filter; never insert_one.
        assert db["validationResults"].insert_one.call_count == 0
        assert db["validationResults"].update_one.call_count == 2
        for call in db["validationResults"].update_one.call_args_list:
            args, kwargs = call
            filter_arg = args[0] if args else kwargs.get("filter")
            assert filter_arg == {"device_id": device_id}
            assert kwargs.get("upsert") is True
```

- [ ] **Step 1.2: Run the test, verify it fails**

```bash
cd /mnt/c/Users/Jason/workspace/Fivos_Senior_Project
PYTHONPATH=harvester/src pytest harvester/src/tests/test_orchestrator.py::TestRunValidationUpsert -v
```

Expected: FAIL — current code calls `insert_one`, not `update_one`.

- [ ] **Step 1.3: Implement upsert in `run_validation()`**

File: `harvester/src/orchestrator.py`

Find both `validation_col.insert_one({...})` calls (around lines 368 and 404).

**First call (when `not gudid_record`, around line 368):** Replace
```python
validation_col.insert_one({
    "device_id": device.get("_id"),
    "brandName": device.get("brandName"),
    "status": "mismatch",
    "matched_fields": 0,
    "total_fields": 0,
    "match_percent": 0.0,
    "comparison_result": None,
    "gudid_record": None,
    "gudid_di": di,
    "created_at": datetime.now(timezone.utc),
    "updated_at": datetime.now(timezone.utc),
})
```
with
```python
_now = datetime.now(timezone.utc)
validation_col.update_one(
    {"device_id": device.get("_id")},
    {
        "$set": {
            "device_id": device.get("_id"),
            "brandName": device.get("brandName"),
            "status": "mismatch",
            "matched_fields": 0,
            "total_fields": 0,
            "match_percent": 0.0,
            "comparison_result": None,
            "gudid_record": None,
            "gudid_di": di,
            "match_confidence": "not_found",
            "updated_at": _now,
        },
        "$setOnInsert": {"created_at": _now},
    },
    upsert=True,
)
```

**Second call (the normal-path insert around line 404):** Replace
```python
validation_col.insert_one({
    "device_id": device.get("_id"),
    ...
    "created_at": datetime.now(timezone.utc),
    "updated_at": datetime.now(timezone.utc),
})
```
with
```python
_now = datetime.now(timezone.utc)
validation_col.update_one(
    {"device_id": device.get("_id")},
    {
        "$set": {
            "device_id": device.get("_id"),
            "brandName": device.get("brandName"),
            "status": status,
            "matched_fields": matched_fields,
            "total_fields": total_fields,
            "match_percent": match_percent,
            "description_similarity": description_similarity,
            "comparison_result": comparison,
            "gudid_record": gudid_record,
            "gudid_di": di,
            "match_confidence": match_confidence,
            "updated_at": _now,
        },
        "$setOnInsert": {"created_at": _now},
    },
    upsert=True,
)
```

Note: `match_confidence` is added here; will be populated from the DI-selection function in Step 1.6. For now, default it: add this line near the top of the per-device loop:
```python
match_confidence = "exact"  # overwritten in Step 1.6
```

Remove both `datetime.now(timezone.utc)` duplicates — the `_now` variable is used twice in each upsert.

- [ ] **Step 1.4: Replace the `drop()` behavior for `overwrite=True`**

Currently (around lines 344-346):
```python
if overwrite:
    validation_col.drop()
    verified_col.drop()
```

Replace with:
```python
if overwrite:
    # Force re-resolution of GUDID DI for every in-scope device; DO NOT drop the
    # validationResults collection (upsert by device_id makes this unnecessary,
    # and dropping would wipe unrelated historical runs).
    devices_col.update_many(query, {"$unset": {"_gudid": ""}})
```

- [ ] **Step 1.5: Run the upsert test, verify it passes**

```bash
PYTHONPATH=harvester/src pytest harvester/src/tests/test_orchestrator.py::TestRunValidationUpsert -v
```

Expected: PASS.

Also run the full validator test suite to confirm no regression:
```bash
PYTHONPATH=harvester/src pytest harvester/src/ -v
```

Expected: all previous tests still pass (413+).

- [ ] **Step 1.6: Write failing test for `select_best_gudid_di` exact-match**

File: `harvester/src/validators/tests/__init__.py` — ensure exists (create empty if missing).

File: `harvester/src/validators/tests/test_gudid_client.py` — create new file.

```python
"""Tests for gudid_client.select_best_gudid_di."""

from unittest.mock import patch, MagicMock


class TestSelectBestGudidDi:
    """F.4: picks the DI whose record exact-matches harvested catalog + model."""

    @patch("validators.gudid_client.lookup_by_di")
    @patch("validators.gudid_client.search_gudid_di")
    def test_picks_exact_match_over_first_candidate(self, mock_search, mock_lookup):
        mock_search.return_value = ["11111111111111", "22222222222222", "33333333333333"]
        mock_lookup.side_effect = [
            {"catalogNumber": "WRONG", "versionModelNumber": "BXA095901A"},
            {"catalogNumber": "BXA095902A", "versionModelNumber": "BXA095902A"},
            {"catalogNumber": "BXA095902A", "versionModelNumber": "WRONG"},
        ]

        from validators.gudid_client import select_best_gudid_di
        harvested = {"catalogNumber": "BXA095902A", "versionModelNumber": "BXA095902A"}
        di, record, confidence = select_best_gudid_di(harvested, max_candidates=3)

        assert di == "22222222222222"
        assert confidence == "exact"
        assert record["catalogNumber"] == "BXA095902A"

    @patch("validators.gudid_client.lookup_by_di")
    @patch("validators.gudid_client.search_gudid_di")
    def test_returns_low_confidence_when_no_exact_match(self, mock_search, mock_lookup):
        mock_search.return_value = ["11111111111111"]
        mock_lookup.return_value = {"catalogNumber": "WRONG", "versionModelNumber": "WRONG"}

        from validators.gudid_client import select_best_gudid_di
        harvested = {"catalogNumber": "CAT", "versionModelNumber": "MODEL"}
        di, record, confidence = select_best_gudid_di(harvested)

        assert di == "11111111111111"
        assert confidence == "low"

    @patch("validators.gudid_client.search_gudid_di")
    def test_returns_not_found_when_search_empty(self, mock_search):
        mock_search.return_value = []

        from validators.gudid_client import select_best_gudid_di
        di, record, confidence = select_best_gudid_di(
            {"catalogNumber": "X", "versionModelNumber": "Y"}
        )

        assert di is None
        assert record is None
        assert confidence == "not_found"
```

Run: `PYTHONPATH=harvester/src pytest harvester/src/validators/tests/test_gudid_client.py -v`
Expected: FAIL — `select_best_gudid_di` doesn't exist; `search_gudid_di` returns a string not a list.

- [ ] **Step 1.7: Modify `search_gudid_di` to return a list, add `select_best_gudid_di`**

File: `harvester/src/validators/gudid_client.py`

Replace the existing `search_gudid_di` body:

```python
def search_gudid_di(catalog_number=None, version_model_number=None, max_candidates=3):
    """Search GUDID HTML search page and return up to max_candidates DIs in DOM order.

    Returns a list of DI strings (may be empty). Previously returned a single
    DI string; callers that need just the first can take index 0.
    """
    query = catalog_number or version_model_number
    if not query:
        return []

    response = requests.get(SEARCH_URL, params={"query": query}, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    dis: list[str] = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("/devices/"):
            di = href.split("/devices/")[-1].strip()
            if di.isdigit() and di not in dis:
                dis.append(di)
                if len(dis) >= max_candidates:
                    break
    return dis
```

Then update `fetch_gudid_record` (preserve public API for backwards compat):
```python
def fetch_gudid_record(catalog_number=None, version_model_number=None):
    """Backwards-compatible single-DI lookup. New callers should use select_best_gudid_di."""
    dis = search_gudid_di(
        catalog_number=catalog_number,
        version_model_number=version_model_number,
        max_candidates=1,
    )
    if not dis:
        return None, None
    di = dis[0]

    response = requests.get(LOOKUP_URL, params={"di": di}, timeout=15)
    response.raise_for_status()
    data = response.json()
    device = data.get("gudid", {}).get("device", {})
    if not device:
        return di, None

    # ... rest unchanged (sterilization, submissions, return dict)
```

Add the new function after `fetch_gudid_record`:

```python
import re

def _norm_model(value):
    """Identifier normalizer — mirrors comparison_validator._norm_model."""
    if not value:
        return ""
    return re.sub(r"[\s\-\.]", "", str(value)).upper()


def select_best_gudid_di(
    harvested: dict,
    max_candidates: int = 3,
) -> tuple[str | None, dict | None, str]:
    """Return (di, gudid_record, match_confidence).

    Tries up to max_candidates DIs from the search, scores each by exact match
    on (catalogNumber, versionModelNumber), and returns the best.

    match_confidence: "exact" (both identifiers match), "partial" (one matches),
    "low" (neither matches — top candidate returned), "not_found" (no candidates).
    """
    dis = search_gudid_di(
        catalog_number=harvested.get("catalogNumber"),
        version_model_number=harvested.get("versionModelNumber"),
        max_candidates=max_candidates,
    )
    if not dis:
        return None, None, "not_found"

    h_cat = _norm_model(harvested.get("catalogNumber"))
    h_model = _norm_model(harvested.get("versionModelNumber"))

    scored: list[tuple[int, str, dict]] = []
    for di in dis:
        record = lookup_by_di(di)
        if not record:
            continue
        score = 0
        if h_cat and _norm_model(record.get("catalogNumber")) == h_cat:
            score += 1
        if h_model and _norm_model(record.get("versionModelNumber")) == h_model:
            score += 1
        scored.append((score, di, record))
        if score == 2:
            break  # Early exit on perfect match

    if not scored:
        return dis[0], None, "low"

    scored.sort(key=lambda t: (-t[0], t[1]))  # highest score, then smallest DI
    best_score, best_di, best_record = scored[0]
    confidence = {2: "exact", 1: "partial", 0: "low"}[best_score]

    # `lookup_by_di` returns raw GUDID; convert to the structured shape used elsewhere.
    # Reuse the same transform as fetch_gudid_record.
    structured = _structure_gudid_record(best_record)
    return best_di, structured, confidence


def _structure_gudid_record(device: dict) -> dict:
    """Transform raw GUDID lookup JSON into our canonical dict shape.

    Mirrors the transform inside fetch_gudid_record so both paths produce
    identical downstream shapes.
    """
    sterilization = device.get("sterilization") or {}
    pmk = device.get("premarketSubmissions") or {}
    submissions = pmk.get("premarketSubmission") or []
    submission_numbers = [
        s["submissionNumber"] for s in submissions if s.get("submissionNumber")
    ]
    return {
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
    }
```

Also refactor `fetch_gudid_record` to use `_structure_gudid_record` instead of duplicating the transform inline.

- [ ] **Step 1.8: Run the new tests, verify they pass**

```bash
PYTHONPATH=harvester/src pytest harvester/src/validators/tests/test_gudid_client.py -v
```

Expected: 3 PASS.

Run full suite to check regressions:
```bash
PYTHONPATH=harvester/src pytest harvester/src/ -v
```

Expected: previous 413 tests still pass.

- [ ] **Step 1.9: Wire `select_best_gudid_di` + DI caching into `run_validation`**

File: `harvester/src/orchestrator.py` — `run_validation()`

Replace the `fetch_gudid_record` import at the top of the function:
```python
from validators.gudid_client import fetch_gudid_record
```
with
```python
from validators.gudid_client import select_best_gudid_di, lookup_by_di
from validators.gudid_client import _structure_gudid_record
```

Inside the `for device in devices:` loop, replace the call:
```python
di, gudid_record = fetch_gudid_record(
    catalog_number=device.get("catalogNumber"),
    version_model_number=device.get("versionModelNumber"),
)
```
with:
```python
cached_gudid = device.get("_gudid") or {}
cached_di = cached_gudid.get("di")

if cached_di:
    raw_record = lookup_by_di(cached_di)
    if raw_record:
        di = cached_di
        gudid_record = _structure_gudid_record(raw_record)
        match_confidence = cached_gudid.get("match_confidence", "exact")
    else:
        di, gudid_record, match_confidence = select_best_gudid_di(device)
else:
    di, gudid_record, match_confidence = select_best_gudid_di(device)

# Cache the resolved DI on the device document (only when we resolved or refreshed).
if di:
    devices_col.update_one(
        {"_id": device["_id"]},
        {"$set": {"_gudid": {
            "di": di,
            "resolved_at": datetime.now(timezone.utc),
            "match_confidence": match_confidence,
        }}},
    )
```

The `match_confidence` variable is now set in every branch; remove the placeholder default from Step 1.3.

- [ ] **Step 1.10: Run full test suite, verify no regressions**

```bash
PYTHONPATH=harvester/src pytest harvester/src/ -v
```

Expected: all tests pass. The upsert test from Step 1.1 and the new DI-selection tests from Step 1.6 both pass. No prior test regressed.

- [ ] **Step 1.11: Commit Task 1**

```bash
cd /mnt/c/Users/Jason/workspace/Fivos_Senior_Project
git add harvester/src/orchestrator.py harvester/src/validators/gudid_client.py harvester/src/tests/test_orchestrator.py harvester/src/validators/tests/
git commit -m "$(cat <<'EOF'
feat(validator): upsert validationResults, deterministic GUDID DI selection

Replace insert_one with update_one upsert by device_id so re-runs of
run_validation don't accumulate duplicates. Replace the blunt collection
drop under overwrite=True with a per-device _gudid cache unset.

New select_best_gudid_di() picks the DI whose record exact-matches
harvested catalog + model (up to K=3 candidates). Result cached on
devices._gudid so subsequent validations skip the search and use
lookup_by_di directly. match_confidence ("exact" / "partial" / "low" /
"not_found") persisted on validationResults for downstream UI use.
EOF
)"
```

---

## Task 2: B — Restore `catalogNumber` in `comparison_result`

**Files:**
- Investigate + modify: likely `harvester/src/validators/comparison_validator.py` or `harvester/src/orchestrator.py`
- Modify: `harvester/src/validators/tests/test_comparison_validator.py`

---

- [ ] **Step 2.1: Write failing test replicating the Diamondback 360 drop**

File: `harvester/src/validators/tests/test_comparison_validator.py` — append:

```python
class TestCatalogNumberPreserved:
    """B: devices with populated catalogNumber must surface it in comparison_result."""

    def test_diamondback_shape_catalog_populated(self):
        # Shape matches real doc 69e6a2be8281d5c55f290fff (Diamondback 360, audit-confirmed drop)
        harvested = {
            "versionModelNumber": "DBP-150CLASS145",
            "catalogNumber": "7-10057-08",
            "brandName": "Diamondback 360",
            "companyName": "Cardiovascular Systems, Inc.",
        }
        gudid = {
            "versionModelNumber": "DBP-150CLASS145",
            "catalogNumber": "7-10057-08",
            "brandName": "Diamondback 360",
            "companyName": "Cardiovascular Systems, Inc.",
            "MRISafetyStatus": None, "singleUse": None, "rx": None,
            "deviceDescription": "",
        }
        from validators.comparison_validator import compare_records
        result = compare_records(harvested, gudid)

        assert result["catalogNumber"]["harvested"] == "7-10057-08"
        assert result["catalogNumber"]["match"] is True
```

Run: `PYTHONPATH=harvester/src pytest harvester/src/validators/tests/test_comparison_validator.py::TestCatalogNumberPreserved -v`

Expected: UNKNOWN. Before implementing, run it to see the actual failure mode. Two possibilities:
- **Fails** → the bug is in `compare_records()` itself; fix there.
- **Passes** → the bug is between the DB read and the call to `compare_records()`. Investigate `devices_col.find(query)` in `orchestrator.py:352`, look for projections, look for transformation steps that strip fields.

- [ ] **Step 2.2: Investigate based on test outcome**

If the test PASSES, the bug isn't in `compare_records`. Trace:
1. Load one affected device (e.g., Diamondback 360) directly from Atlas via a temp Python script. Confirm the raw `devices` doc has `catalogNumber` populated.
2. In `run_validation()`, add a temporary `print(device.get("catalogNumber"))` just before the `compare_records` call. Re-run against that device to see if the field is there at that point.
3. If still null at that point, the bug is in how the device is loaded (find query, projection, or a pre-processing step). If populated at that point, the bug is downstream.

Most likely candidate: nothing in the orchestrator strips it. The Diamondback `catalogNumber` is `"7-10057-08"` — non-empty string. `compare_records()` should handle this.

If the test FAILS, the bug IS in `compare_records`. Look at line 58: `if not h`. For `"7-10057-08"`, `not h` is False, so we take the else branch. That should work. The only way it'd fail is if something else.

Don't propose a fix until you've reproduced and understood the root cause.

- [ ] **Step 2.3: Apply the fix at root cause**

Depends on investigation. When unclear, prefer the smallest change that makes the test pass AND doesn't introduce new behavior elsewhere.

- [ ] **Step 2.4: Run test + full suite**

```bash
PYTHONPATH=harvester/src pytest harvester/src/validators/tests/test_comparison_validator.py::TestCatalogNumberPreserved -v
PYTHONPATH=harvester/src pytest harvester/src/ -v
```

Both pass.

- [ ] **Step 2.5: Commit Task 2**

```bash
git add <files-changed>
git commit -m "fix(validator): preserve catalogNumber in comparison_result

<one-line description of the root cause>"
```

---

## Task 3: D — Null-Sentinel Filtering + Admin View

**Files:**
- Modify: `harvester/src/orchestrator.py` — `run_validation()`, `get_all_dashboard_records()`, `get_dashboard_stats()`
- Modify: `app/routes/admin.py`
- Create: `app/templates/admin/invalid_validations.html`
- Modify: `harvester/src/tests/test_orchestrator.py`

---

- [ ] **Step 3.1: Failing test for null-sentinel detection**

File: `harvester/src/tests/test_orchestrator.py` — append:

```python
class TestNullSentinelDetection:
    """D: validations where every field is null should be marked invalid_gudid_response."""

    @patch("orchestrator.get_db")
    @patch("orchestrator.select_best_gudid_di")
    def test_all_null_comparison_marked_invalid(self, mock_select, mock_get_db):
        from bson import ObjectId
        device = {
            "_id": ObjectId(),
            "versionModelNumber": None,
            "catalogNumber": None,
            "brandName": None,
            "companyName": None,
            "MRISafetyStatus": None, "singleUse": None, "rx": None,
            "deviceDescription": None,
        }
        gudid = {k: None for k in device}
        mock_select.return_value = ("DI-x", gudid, "low")

        db = MagicMock()
        db["devices"].find.return_value = [device]
        db["validationResults"] = MagicMock()
        db["verified_devices"] = MagicMock()
        mock_get_db.return_value = db

        from orchestrator import run_validation
        run_validation(overwrite=False)

        assert db["validationResults"].update_one.call_count == 1
        _, kwargs = db["validationResults"].update_one.call_args
        set_doc = kwargs["update"]["$set"] if "update" in kwargs else kwargs["$set"] if "$set" in kwargs else None
        # Access the $set dict robustly whether positional or keyword
        call_args_tuple = db["validationResults"].update_one.call_args
        set_doc = call_args_tuple[0][1]["$set"]
        assert set_doc["status"] == "invalid_gudid_response"
```

Run: expected FAIL — current code would mark this as `mismatch` with matched_fields=0.

- [ ] **Step 3.2: Implement sentinel detection in `run_validation`**

File: `harvester/src/orchestrator.py`

After the `compare_records(device, gudid_record)` call, and before the existing `compared = {k: v for ...}` line, add:

```python
# D — detect null-sentinel GUDID response (every comparable field is None on both sides).
_identifier_fields = ("versionModelNumber", "catalogNumber", "brandName", "companyName",
                      "MRISafetyStatus", "singleUse", "rx")
_all_null = all(
    (comparison.get(f, {}).get("harvested") is None
     and comparison.get(f, {}).get("gudid") is None)
    for f in _identifier_fields
)
if _all_null:
    _now = datetime.now(timezone.utc)
    validation_col.update_one(
        {"device_id": device.get("_id")},
        {
            "$set": {
                "device_id": device.get("_id"),
                "brandName": device.get("brandName"),
                "status": "invalid_gudid_response",
                "matched_fields": 0,
                "total_fields": 0,
                "match_percent": 0.0,
                "comparison_result": comparison,
                "gudid_record": gudid_record,
                "gudid_di": di,
                "match_confidence": match_confidence,
                "updated_at": _now,
            },
            "$setOnInsert": {"created_at": _now},
        },
        upsert=True,
    )
    result["mismatches"] += 0  # intentionally not counted
    continue
```

The `continue` skips the existing upsert for this device.

- [ ] **Step 3.3: Exclude sentinel rows from dashboard stats + records**

File: `harvester/src/orchestrator.py`

In `get_all_dashboard_records()`, around line 580 where discrepancy_docs are queried:

Change
```python
discrepancy_docs = list(db["validationResults"].find(
    {"status": {"$in": ["partial_match", "mismatch"]}}
).sort("updated_at", -1))
```
(no change needed — it already only queries partial_match + mismatch, so invalid_gudid_response is naturally excluded.)

In `get_dashboard_stats()` (find the function — probably near `get_all_dashboard_records`), ensure mismatches count excludes invalid_gudid_response. Likely fine if the query is already `{"status": "mismatch"}`.

Verify by reading the function signatures and queries.

- [ ] **Step 3.4: Add admin route for invalid validations**

File: `app/routes/admin.py`

Add a new route:
```python
@router.get("/invalid-validations")
def invalid_validations(request: Request):
    user, redirect = require_roles(request, ["admin"])
    if redirect:
        return redirect

    from orchestrator import get_invalid_validations
    rows = get_invalid_validations()
    return templates.TemplateResponse(
        request,
        "admin/invalid_validations.html",
        context={"rows": rows, "current_user": user},
    )
```

File: `harvester/src/orchestrator.py` — add helper:
```python
def get_invalid_validations() -> list[dict]:
    """Return all validationResults docs with status=invalid_gudid_response."""
    from database.db_connection import get_db
    try:
        db = get_db()
        docs = list(db["validationResults"].find(
            {"status": "invalid_gudid_response"}
        ).sort("updated_at", -1))
        return [_serialize_record(d) for d in docs]
    except Exception as e:
        logger.warning("get_invalid_validations: %s", e)
        return []
```

- [ ] **Step 3.5: Create admin template**

File: `app/templates/admin/invalid_validations.html` — create new.

```jinja
{% extends "base.html" %}

{% block content %}
<section class="hero">
    <div>
        <p class="eyebrow">Admin</p>
        <h1 class="page-title">Invalid GUDID Validations</h1>
        <p class="page-description">
            Validations whose GUDID response was empty or all-null. Not included in the review queue.
            Use this list to manually re-lookup or mark as known-bad.
        </p>
    </div>
    <div class="hero-actions">
        <a href="/admin/users" class="btn btn-secondary">User Management</a>
    </div>
</section>

<section class="panel">
    <div class="panel-header">
        <div>
            <h3>Invalid validations ({{ rows|length }})</h3>
        </div>
    </div>

    {% if rows %}
    <div class="table-wrap">
        <table class="data-table">
            <thead>
                <tr>
                    <th>Brand</th>
                    <th>Device ID</th>
                    <th>GUDID DI</th>
                    <th>Confidence</th>
                    <th>Updated</th>
                </tr>
            </thead>
            <tbody>
                {% for r in rows %}
                <tr>
                    <td>{{ r.brandName or "N/A" }}</td>
                    <td class="mono">{{ r.device_id }}</td>
                    <td class="mono">{{ r.gudid_di or "—" }}</td>
                    <td>{{ r.match_confidence or "N/A" }}</td>
                    <td>{{ r.updated_at }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% else %}
    <div class="empty-state">
        <p>No invalid GUDID validations. All responses are valid.</p>
    </div>
    {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 3.6: Run tests + commit Task 3**

```bash
PYTHONPATH=harvester/src pytest harvester/src/tests/test_orchestrator.py::TestNullSentinelDetection -v
PYTHONPATH=harvester/src pytest harvester/src/ -v
```

Both pass. Commit:
```bash
git add harvester/src/orchestrator.py harvester/src/tests/test_orchestrator.py app/routes/admin.py app/templates/admin/
git commit -m "feat(validator): filter null-sentinel GUDID responses, add admin view

Responses with every identifier null on both sides now get status
invalid_gudid_response and are excluded from the dashboard review
queue. New admin-only route /admin/invalid-validations surfaces them
for manual inspection."
```

---

## Task 4: G — Dimension Comparison

**Files:**
- Modify: `harvester/src/validators/gudid_client.py` — add `extract_gudid_dimensions`, `_SIZE_TYPE_MAP`, `_GUDID_UNIT_MAP`
- Modify: `harvester/src/validators/comparison_validator.py` — add `_within_tolerance`, dimension comparisons, `_DIMENSION_RULES`
- Modify: `harvester/src/orchestrator.py` — enrich GUDID record with dimensions before compare
- Modify: `harvester/src/validators/tests/test_gudid_client.py` — tests for extract_gudid_dimensions
- Modify: `harvester/src/validators/tests/test_comparison_validator.py` — dimension comparison tests
- Modify: `app/routes/review.py` — extend `COMPARED_FIELDS`
- Modify: `app/templates/review.html` — render match_confidence badge
- Modify: `harvester/src/validators/CLAUDE.md` — update scoring doc

---

- [ ] **Step 4.1: Failing test for `extract_gudid_dimensions`**

File: `harvester/src/validators/tests/test_gudid_client.py` — append:

```python
class TestExtractGudidDimensions:
    """G: parse GUDID deviceSizes array into canonical field/unit pairs."""

    def test_maps_diameter_and_length(self):
        record = {
            "deviceSizes": {
                "deviceSize": [
                    {"sizeType": "Labeled Stent Diameter", "size": "9", "unit": "Millimeter"},
                    {"sizeType": "Labeled Stent Length", "size": "79", "unit": "Millimeter"},
                ]
            }
        }
        from validators.gudid_client import extract_gudid_dimensions
        dims = extract_gudid_dimensions(record)
        assert dims["diameter"] == {"value": 9.0, "unit": "mm"}
        assert dims["length"] == {"value": 79.0, "unit": "mm"}

    def test_prefers_labeled_over_outer(self):
        record = {
            "deviceSizes": {
                "deviceSize": [
                    {"sizeType": "Outer Diameter", "size": "10", "unit": "Millimeter"},
                    {"sizeType": "Labeled Stent Diameter", "size": "9", "unit": "Millimeter"},
                ]
            }
        }
        from validators.gudid_client import extract_gudid_dimensions
        dims = extract_gudid_dimensions(record)
        assert dims["diameter"] == {"value": 9.0, "unit": "mm"}

    def test_unknown_sizeType_ignored(self):
        record = {
            "deviceSizes": {
                "deviceSize": [
                    {"sizeType": "Fenestration Diameter", "size": "5", "unit": "Millimeter"},
                ]
            }
        }
        from validators.gudid_client import extract_gudid_dimensions
        dims = extract_gudid_dimensions(record)
        assert dims == {}

    def test_empty_devicesizes_returns_empty_dict(self):
        from validators.gudid_client import extract_gudid_dimensions
        assert extract_gudid_dimensions({}) == {}
        assert extract_gudid_dimensions({"deviceSizes": {}}) == {}
```

Run — expected FAIL (function doesn't exist).

- [ ] **Step 4.2: Implement `extract_gudid_dimensions`**

File: `harvester/src/validators/gudid_client.py` — add after `_structure_gudid_record`:

```python
# G: GUDID sizeType → our canonical field. Higher-priority synonyms first.
# If multiple GUDID entries map to the same field, the first one wins.
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

# GUDID verbose unit names → short form used by normalizers/unit_conversions.
_GUDID_UNIT_MAP = {
    "millimeter": "mm", "millimeters": "mm", "mm": "mm",
    "centimeter": "cm", "centimeters": "cm", "cm": "cm",
    "meter": "m", "meters": "m", "m": "m",
    "inch": "in", "inches": "in", "in": "in",
    "gram": "g", "grams": "g", "g": "g",
    "kilogram": "kg", "kilograms": "kg", "kg": "kg",
    "milliliter": "ml", "milliliters": "ml", "ml": "ml",
    "liter": "l", "liters": "l", "l": "l",
    "millimeter of mercury": "mmhg", "mmhg": "mmhg",
    "kilopascal": "kpa", "kpa": "kpa",
    "atmosphere": "atm", "atm": "atm",
    "bar": "bar",
    "pound per square inch": "psi", "psi": "psi",
}


def _normalize_gudid_unit(unit_str):
    if not unit_str:
        return None
    return _GUDID_UNIT_MAP.get(str(unit_str).strip().lower())


def extract_gudid_dimensions(gudid_record: dict) -> dict:
    """Map GUDID deviceSizes array → {field: {value: float, unit: canonical}}.

    Uses normalize_measurement's unit_conversions table to canonicalize to
    mm / g / mL / mmHg. Returns {} if no recognized dimensions present.
    """
    from normalizers.unit_conversions import unit_conversions

    sizes = gudid_record.get("deviceSizes") or {}
    entries = sizes.get("deviceSize") or []
    if isinstance(entries, dict):
        entries = [entries]

    # Build (sizeType, entry) pairs, then iterate in _SIZE_TYPE_MAP priority order.
    by_type: dict[str, dict] = {}
    for entry in entries:
        stype = (entry.get("sizeType") or "").strip()
        if stype and stype not in by_type:
            by_type[stype] = entry

    out: dict[str, dict] = {}
    for gudid_type, our_field in _SIZE_TYPE_MAP:
        if our_field in out:
            continue  # Already populated with a higher-priority synonym
        entry = by_type.get(gudid_type)
        if not entry:
            continue
        try:
            value = float(entry.get("size"))
        except (TypeError, ValueError):
            continue
        raw_unit = _normalize_gudid_unit(entry.get("unit"))
        if not raw_unit or raw_unit not in unit_conversions:
            continue
        canonical_unit, converter = unit_conversions[raw_unit]
        out[our_field] = {"value": round(converter(value), 4), "unit": canonical_unit}

    return out
```

- [ ] **Step 4.3: Run tests**

```bash
PYTHONPATH=harvester/src pytest harvester/src/validators/tests/test_gudid_client.py::TestExtractGudidDimensions -v
```

Expected: 4 PASS.

- [ ] **Step 4.4: Failing test for `_within_tolerance` + dimension comparison**

File: `harvester/src/validators/tests/test_comparison_validator.py` — append:

```python
class TestWithinTolerance:
    """G: _within_tolerance matches values inside ±tolerance, None if either side null."""

    def test_within_absolute_tolerance(self):
        from validators.comparison_validator import _within_tolerance
        assert _within_tolerance(9.05, 9.00, rel=0.01, abs_=0.1) is True

    def test_outside_tolerance(self):
        from validators.comparison_validator import _within_tolerance
        assert _within_tolerance(9.5, 9.0, rel=0.01, abs_=0.1) is False

    def test_relative_tolerance_used_when_larger(self):
        from validators.comparison_validator import _within_tolerance
        # 200 ± 1% = ±2, 200 vs 201.5 should match (1.5 < 2)
        assert _within_tolerance(201.5, 200.0, rel=0.01, abs_=0.1) is True

    def test_none_returns_none(self):
        from validators.comparison_validator import _within_tolerance
        assert _within_tolerance(None, 9.0, 0.01, 0.1) is None
        assert _within_tolerance(9.0, None, 0.01, 0.1) is None


class TestDimensionComparison:
    """G: compare_records includes 7 dimension fields with unit-converted tolerance."""

    def _base(self):
        return {
            "versionModelNumber": "X", "catalogNumber": "X", "brandName": "B",
            "companyName": "C", "deviceDescription": "", "MRISafetyStatus": None,
            "singleUse": None, "rx": None,
        }

    def test_diameter_match_same_unit(self):
        from validators.comparison_validator import compare_records
        h = {**self._base(), "diameter": 9.0, "diameter_unit": "mm"}
        g = {**self._base(), "diameter": {"value": 9.0, "unit": "mm"}}
        # compare_records reads dimensions from gudid["_dimensions"] (injected by orchestrator);
        # caller is expected to put the parsed structure there.
        g_with_dims = dict(g)
        g_with_dims["_dimensions"] = {"diameter": {"value": 9.0, "unit": "mm"}}
        result = compare_records(h, g_with_dims)
        assert result["diameter"]["match"] is True

    def test_diameter_mismatch_different_units_converted(self):
        from validators.comparison_validator import compare_records
        h = {**self._base(), "diameter": 9.0, "diameter_unit": "mm"}
        g = {**self._base()}
        g["_dimensions"] = {"diameter": {"value": 1.5, "unit": "cm"}}  # 15 mm
        result = compare_records(h, g)
        assert result["diameter"]["match"] is False

    def test_missing_harvested_returns_none(self):
        from validators.comparison_validator import compare_records
        h = self._base()
        g = {**self._base(), "_dimensions": {"diameter": {"value": 9.0, "unit": "mm"}}}
        result = compare_records(h, g)
        assert result["diameter"]["match"] is None
```

Run — expected FAIL.

- [ ] **Step 4.5: Implement `_within_tolerance` + dimension compares**

File: `harvester/src/validators/comparison_validator.py`

Add near the top, after imports:
```python
# G: (canonical_unit, relative_tolerance, absolute_tolerance_in_canonical_unit).
_DIMENSION_RULES: dict[str, tuple[str, float, float]] = {
    "length": ("mm", 0.01, 0.1),
    "width": ("mm", 0.01, 0.1),
    "height": ("mm", 0.01, 0.1),
    "diameter": ("mm", 0.01, 0.1),
    "weight": ("g", 0.05, 0.0),
    "volume": ("mL", 0.05, 0.0),
    "pressure": ("mmHg", 0.05, 0.0),
}


def _within_tolerance(h, g, rel, abs_):
    if h is None or g is None:
        return None
    try:
        h_f, g_f = float(h), float(g)
    except (TypeError, ValueError):
        return None
    tolerance = max(abs(g_f) * rel, abs_)
    return abs(h_f - g_f) <= tolerance


def _convert_to_canonical(value, raw_unit, canonical_unit):
    """Return (converted_value, ok). ok=False if no conversion path exists."""
    from normalizers.unit_conversions import unit_conversions
    if value is None:
        return None, False
    if not raw_unit:
        return None, False
    key = str(raw_unit).strip().lower()
    if key not in unit_conversions:
        return None, False
    mapped_unit, converter = unit_conversions[key]
    if mapped_unit != canonical_unit:
        return None, False
    try:
        return round(converter(float(value)), 4), True
    except (TypeError, ValueError):
        return None, False
```

At the end of `compare_records(...)`, before the final `return results`, add:

```python
    # G: dimension comparison. GUDID dimensions must already be structured by
    # extract_gudid_dimensions() and attached to gudid as "_dimensions".
    gudid_dims = gudid.get("_dimensions") or {}
    for field, (canonical_unit, rel_tol, abs_tol) in _DIMENSION_RULES.items():
        h_val = harvested.get(field)
        h_unit = harvested.get(f"{field}_unit") or canonical_unit
        g_entry = gudid_dims.get(field)

        if h_val is None or g_entry is None:
            results[field] = {"harvested": h_val, "gudid": g_entry, "match": None}
            continue

        h_canonical, h_ok = _convert_to_canonical(h_val, h_unit, canonical_unit)
        g_canonical, g_ok = _convert_to_canonical(
            g_entry.get("value"), g_entry.get("unit"), canonical_unit
        )
        if not (h_ok and g_ok):
            results[field] = {"harvested": h_val, "gudid": g_entry, "match": None}
            continue

        results[field] = {
            "harvested": h_val,
            "gudid": g_entry,
            "match": _within_tolerance(h_canonical, g_canonical, rel_tol, abs_tol),
        }
```

- [ ] **Step 4.6: Wire dimension enrichment into `run_validation`**

File: `harvester/src/orchestrator.py`

Import at top of the function:
```python
from validators.gudid_client import extract_gudid_dimensions
```

Just before `comparison = compare_records(device, gudid_record)`:
```python
gudid_record = dict(gudid_record)
gudid_record["_dimensions"] = extract_gudid_dimensions(gudid_record)
```

(Copy-on-write to avoid mutating the cached record.)

- [ ] **Step 4.7: Run tests**

```bash
PYTHONPATH=harvester/src pytest harvester/src/validators/tests/ -v
PYTHONPATH=harvester/src pytest harvester/src/ -v
```

All pass.

- [ ] **Step 4.8: Add dimension fields to review UI + match_confidence badge**

File: `app/routes/review.py`

Extend `COMPARED_FIELDS`:
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
    ("diameter", "Diameter"),
    ("length", "Length"),
    ("width", "Width"),
    ("height", "Height"),
    ("weight", "Weight"),
    ("volume", "Volume"),
    ("pressure", "Pressure"),
]
```

In the `review_page()` function, include `match_confidence`:
```python
context={
    ...existing...
    "match_confidence": validation.get("match_confidence", "exact"),
}
```

File: `app/templates/review.html`

After the stats-grid section, add a confidence badge (both modes):
```jinja
{% if match_confidence and match_confidence != "exact" %}
<div class="alert-error" style="background: var(--warning-soft, #fff7e6); color: var(--warning); margin: 16px 0;">
    <strong>Match confidence: {{ match_confidence }}.</strong>
    {% if match_confidence == "low" %}
    GUDID search returned this record but neither catalog nor model matched our harvested values exactly.
    {% elif match_confidence == "partial" %}
    GUDID search returned this record with only one of (catalog, model) matching our harvested values.
    {% elif match_confidence == "not_found" %}
    GUDID search returned no candidates for this device.
    {% endif %}
</div>
{% endif %}
```

Dimension rows render automatically — `review.html` already iterates `COMPARED_FIELDS`. For dimension `.gudid` cells, the value is a dict `{value, unit}` — the template must stringify. Update the `{{ f.gudid }}` cell (around line 81) to handle dicts:

```jinja
<div class="review-value gudid">
    {% if f.gudid is none %}
        N/A
    {% elif f.gudid is mapping %}
        {{ f.gudid.value }} {{ f.gudid.unit }}
    {% else %}
        {{ f.gudid }}
    {% endif %}
</div>
```

Similarly for harvested (dimensions stored as separate `value`/`unit` keys in the device doc — the template already receives just `harvested.get(field)` which is the value; unit lives in `{field}_unit`). To show the unit, you can either:
- (a) Extend `compare_records` to return `{harvested_display: "9.0 mm"}` alongside the raw value.
- (b) Keep it simple: just show the value for harvested. Reviewers can see the unit in the GUDID column.

Choose (b) for now. If reviewers complain, upgrade later.

- [ ] **Step 4.9: Update validators CLAUDE.md**

File: `harvester/src/validators/CLAUDE.md`

Find the "Comparison Scoring" section and update:

```markdown
## Comparison Scoring

`compare_records()` compares 15 boolean fields + 1 similarity score:

- `versionModelNumber`, `catalogNumber`: normalized exact match (strip spaces/hyphens/dots, uppercase)
- `brandName`: case-insensitive, strip trademark symbols
- `companyName`: uppercase, strip punctuation
- `deviceDescription`: Jaccard word-set similarity (float 0.0–1.0)
- `MRISafetyStatus`: normalize both sides via `normalize_mri_status()`, exact compare
- `singleUse`, `rx`: normalize both sides via `normalize_boolean()`, exact compare
- `length`, `width`, `height`, `diameter`: canonical unit mm; tolerance max(1% relative, 0.1mm absolute)
- `weight`: canonical unit g; tolerance 5% relative
- `volume`: canonical unit mL; tolerance 5% relative
- `pressure`: canonical unit mmHg; tolerance 5% relative

Null handling:
- Identifier fields → `match: None` only if harvested is null
- Boolean/enum/dimension fields → `match: None` if either side is null

Fields with `match: None` are excluded from the score denominator.

## GUDID DI selection

`select_best_gudid_di(harvested, max_candidates=3)` returns `(di, record, confidence)`:

- `exact` — GUDID catalog AND model both exact-match harvested (normalized)
- `partial` — one of (catalog, model) matches
- `low` — neither matches; returns top search candidate anyway
- `not_found` — GUDID search returned no candidates

The chosen DI is cached on `devices._gudid` so subsequent validations
skip the search and use `lookup_by_di` directly. `run_validation(overwrite=True)`
clears the cache per-device (does NOT drop the validationResults collection).
```

- [ ] **Step 4.10: Run full suite + commit Task 4**

```bash
PYTHONPATH=harvester/src pytest harvester/src/ -v
```

All pass.

```bash
git add harvester/src/validators/ harvester/src/orchestrator.py app/routes/review.py app/templates/review.html
git commit -m "feat(validator): compare 7 dimension fields against GUDID with unit+tolerance

Adds extract_gudid_dimensions() mapping GUDID's deviceSizes array to
canonical {field: {value, unit}} pairs using priority-ordered sizeType
synonyms. compare_records() gains length/width/height/diameter/weight/
volume/pressure comparisons via _within_tolerance() with per-field rel
and absolute tolerance rules.

Review UI renders the new dimension rows automatically and surfaces a
match_confidence warning badge for validations where the GUDID DI
selection was partial / low / not_found."
```

---

## End-of-Plan Verification

- [ ] **Step E.1: Full pytest suite passes**

```bash
PYTHONPATH=harvester/src pytest harvester/src/ -v
```

Target: ≥430 tests (413 existing + ~17 new across Tasks 1–4), 0 failures.

- [ ] **Step E.2: Visual smoke test**

```bash
cd /mnt/c/Users/Jason/workspace/Fivos_Senior_Project/docker
docker compose up --build -d
```

Check `http://localhost:8500`:
- Dashboard status counts are non-zero (no regression in discrepancy listing).
- Click a partial-match row → review page renders with all 15 comparison rows (old 7 + 7 new dimension rows + description), OR shows "N/A" where dimension data is missing.
- If any validation has `match_confidence != "exact"`, a warning badge appears on the review page.
- `/admin/invalid-validations` (logged in as admin) renders the new admin page.

This plan leaves the re-harvest (operational step E) for after Spec 1 (harvester reliability) also lands.
