# Validator Field Expansion (MRI / Single-Use / Rx) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `compare_records()` to compare three additional fields — `MRISafetyStatus`, `singleUse`, `rx` — against GUDID, surfacing discrepancies that are currently invisible.

**Architecture:** Minimal extension to the existing field-by-field compare dict. Both sides are pushed through the already-existing `normalize_mri_status()` and `normalize_boolean()` helpers before compare. If either side normalizes to `None`, the field is skipped from the score denominator (same pattern `description_similarity` already uses). The `orchestrator.run_validation()` score math requires no change — its denominator filter `v.get("match") is not None` already handles the new fields. Review UI picks them up via the `COMPARED_FIELDS` list in `app/routes/review.py`.

**Tech Stack:** Python 3.13, pytest, existing `harvester/src/normalizers/booleans.py` helpers.

**Test command:** `PYTHONPATH=harvester/src python3 -m pytest harvester/src/validators/tests/ -v`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `harvester/src/validators/tests/test_comparison_validator.py` | Create | Unit tests for all 7 field comparisons (4 existing + 3 new) |
| `harvester/src/validators/comparison_validator.py` | Modify | Add 3 new fields to `compare_records()` output dict |
| `app/routes/review.py` | Modify | Add 3 entries to `COMPARED_FIELDS` list |
| `harvester/src/validators/CLAUDE.md` | Modify | Update comparison scoring description (4 → 7 fields) |

---

## Task 1: Write failing tests for new field comparisons

**Files:**
- Create: `harvester/src/validators/tests/test_comparison_validator.py`

- [ ] **Step 1: Create the test file**

Create `harvester/src/validators/tests/test_comparison_validator.py` with this content:

```python
from validators.comparison_validator import compare_records


BASE_HARVESTED = {
    "versionModelNumber": "ADM-35-40-130",
    "catalogNumber": "CAT-001",
    "brandName": "Admiral",
    "companyName": "Medtronic, Inc.",
    "deviceDescription": "Drug-coated balloon for peripheral arterial disease",
}

BASE_GUDID = {
    "versionModelNumber": "ADM-35-40-130",
    "catalogNumber": "CAT-001",
    "brandName": "Admiral",
    "companyName": "MEDTRONIC INC",
    "deviceDescription": "Drug-coated balloon for peripheral arterial disease",
}


class TestIdentifierFieldsRegression:
    """Existing four identifier fields + description similarity must keep working."""

    def test_all_four_identifiers_match(self):
        result = compare_records(BASE_HARVESTED, BASE_GUDID)
        assert result["versionModelNumber"]["match"] is True
        assert result["catalogNumber"]["match"] is True
        assert result["brandName"]["match"] is True
        assert result["companyName"]["match"] is True

    def test_model_number_mismatch(self):
        harvested = {**BASE_HARVESTED, "versionModelNumber": "XYZ"}
        result = compare_records(harvested, BASE_GUDID)
        assert result["versionModelNumber"]["match"] is False

    def test_description_similarity_present(self):
        result = compare_records(BASE_HARVESTED, BASE_GUDID)
        assert "description_similarity" in result["deviceDescription"]
        assert result["deviceDescription"]["description_similarity"] == 1.0

    def test_harvested_model_none_skips(self):
        harvested = {**BASE_HARVESTED, "versionModelNumber": None}
        result = compare_records(harvested, BASE_GUDID)
        assert result["versionModelNumber"]["match"] is None


class TestMRISafetyStatus:

    def test_match_exact(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "MR Safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Safe"}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is True

    def test_match_variant_normalization(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "mri safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Safe"}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is True

    def test_mismatch(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "MR Safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Conditional"}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is False

    def test_harvested_null_skips(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": None}
        gudid = {**BASE_GUDID, "MRISafetyStatus": "MR Safe"}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is None

    def test_gudid_null_skips(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": "MR Safe"}
        gudid = {**BASE_GUDID, "MRISafetyStatus": None}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is None

    def test_both_null_skips(self):
        harvested = {**BASE_HARVESTED, "MRISafetyStatus": None}
        gudid = {**BASE_GUDID, "MRISafetyStatus": None}
        result = compare_records(harvested, gudid)
        assert result["MRISafetyStatus"]["match"] is None


class TestSingleUse:

    def test_match_true(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": True}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is True

    def test_match_false(self):
        harvested = {**BASE_HARVESTED, "singleUse": False}
        gudid = {**BASE_GUDID, "singleUse": False}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is True

    def test_mismatch(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": False}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is False

    def test_gudid_string_true_normalizes(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": "true"}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is True

    def test_harvested_null_skips(self):
        harvested = {**BASE_HARVESTED, "singleUse": None}
        gudid = {**BASE_GUDID, "singleUse": True}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is None

    def test_gudid_null_skips(self):
        harvested = {**BASE_HARVESTED, "singleUse": True}
        gudid = {**BASE_GUDID, "singleUse": None}
        result = compare_records(harvested, gudid)
        assert result["singleUse"]["match"] is None


class TestRx:

    def test_match_true(self):
        harvested = {**BASE_HARVESTED, "rx": True}
        gudid = {**BASE_GUDID, "rx": True}
        result = compare_records(harvested, gudid)
        assert result["rx"]["match"] is True

    def test_match_false(self):
        harvested = {**BASE_HARVESTED, "rx": False}
        gudid = {**BASE_GUDID, "rx": False}
        result = compare_records(harvested, gudid)
        assert result["rx"]["match"] is True

    def test_mismatch(self):
        harvested = {**BASE_HARVESTED, "rx": True}
        gudid = {**BASE_GUDID, "rx": False}
        result = compare_records(harvested, gudid)
        assert result["rx"]["match"] is False

    def test_gudid_string_false_normalizes(self):
        harvested = {**BASE_HARVESTED, "rx": False}
        gudid = {**BASE_GUDID, "rx": "false"}
        result = compare_records(harvested, gudid)
        assert result["rx"]["match"] is True

    def test_both_null_skips(self):
        harvested = {**BASE_HARVESTED, "rx": None}
        gudid = {**BASE_GUDID, "rx": None}
        result = compare_records(harvested, gudid)
        assert result["rx"]["match"] is None
```

- [ ] **Step 2: Run tests and verify the new-field tests fail**

Run: `PYTHONPATH=harvester/src python3 -m pytest harvester/src/validators/tests/test_comparison_validator.py -v`

Expected: `TestIdentifierFieldsRegression` passes (4 tests). All `TestMRISafetyStatus` / `TestSingleUse` / `TestRx` tests fail with `KeyError: 'MRISafetyStatus'` (or `'singleUse'`, `'rx'`) because those keys do not yet exist in the result dict.

- [ ] **Step 3: Commit the failing tests**

```bash
git add harvester/src/validators/tests/test_comparison_validator.py
git commit -m "test(validators): failing tests for MRISafetyStatus/singleUse/rx compare"
```

---

## Task 2: Implement the three new field comparisons

**Files:**
- Modify: `harvester/src/validators/comparison_validator.py`

- [ ] **Step 1: Rewrite `comparison_validator.py`**

Replace the entire file content with:

```python
import re

from normalizers.booleans import normalize_boolean, normalize_mri_status


def _norm_model(value):
    if not value:
        return ""
    return re.sub(r"[\s\-\.]", "", str(value)).upper()


def _norm_brand(value):
    if not value:
        return ""
    cleaned = re.sub(r"[™®†°]", "", str(value))
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def _norm_company(value):
    if not value:
        return ""
    cleaned = re.sub(r"[,\.&']", "", str(value))
    return re.sub(r"\s+", " ", cleaned).strip().upper()


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    s1 = set(str(a).lower().split())
    s2 = set(str(b).lower().split())
    union = s1 | s2
    if not union:
        return 0.0
    return round(len(s1 & s2) / len(union), 4)


def _compare_normalized(harvested, gudid, normalizer):
    """Normalize both sides then exact-compare.

    Returns (match, h_norm, g_norm). match is None if either side
    normalizes to None (skipped from score denominator).
    """
    h_norm = normalizer(harvested) if harvested is not None else None
    g_norm = normalizer(gudid) if gudid is not None else None
    if h_norm is None or g_norm is None:
        return None, h_norm, g_norm
    return h_norm == g_norm, h_norm, g_norm


def compare_records(harvested, gudid):
    results = {}

    # Model number fields — normalize (uppercase, strip spaces/hyphens/dots)
    # match=None means "not compared" (harvested value missing)
    for field in ("versionModelNumber", "catalogNumber"):
        h = harvested.get(field)
        g = gudid.get(field)
        if not h:
            results[field] = {"harvested": h, "gudid": g, "match": None}
        else:
            results[field] = {
                "harvested": h,
                "gudid": g,
                "match": bool(g and _norm_model(h) == _norm_model(g)),
            }

    # Brand name — case-insensitive, strip trademark symbols
    h_brand = harvested.get("brandName")
    g_brand = gudid.get("brandName")
    if not h_brand:
        results["brandName"] = {"harvested": h_brand, "gudid": g_brand, "match": None}
    else:
        results["brandName"] = {
            "harvested": h_brand,
            "gudid": g_brand,
            "match": bool(g_brand and _norm_brand(h_brand) == _norm_brand(g_brand)),
        }

    # Company name — uppercase, strip punctuation
    h_company = harvested.get("companyName")
    g_company = gudid.get("companyName")
    if not h_company:
        results["companyName"] = {"harvested": h_company, "gudid": g_company, "match": None}
    else:
        results["companyName"] = {
            "harvested": h_company,
            "gudid": g_company,
            "match": bool(g_company and _norm_company(h_company) == _norm_company(g_company)),
        }

    # Device description — Jaccard similarity score, not a boolean match
    h_desc = harvested.get("deviceDescription")
    g_desc = gudid.get("deviceDescription")
    results["deviceDescription"] = {
        "harvested": h_desc,
        "gudid": g_desc,
        "description_similarity": _jaccard(h_desc, g_desc),
    }

    # MRI safety status — enum; normalize both sides. Skip if either normalizes to None.
    h_mri = harvested.get("MRISafetyStatus")
    g_mri = gudid.get("MRISafetyStatus")
    match, _, _ = _compare_normalized(h_mri, g_mri, normalize_mri_status)
    results["MRISafetyStatus"] = {"harvested": h_mri, "gudid": g_mri, "match": match}

    # Single use — boolean; normalize both sides. Skip if either normalizes to None.
    h_su = harvested.get("singleUse")
    g_su = gudid.get("singleUse")
    match, _, _ = _compare_normalized(h_su, g_su, normalize_boolean)
    results["singleUse"] = {"harvested": h_su, "gudid": g_su, "match": match}

    # Prescription (Rx) — boolean; same strategy as singleUse.
    h_rx = harvested.get("rx")
    g_rx = gudid.get("rx")
    match, _, _ = _compare_normalized(h_rx, g_rx, normalize_boolean)
    results["rx"] = {"harvested": h_rx, "gudid": g_rx, "match": match}

    return results
```

- [ ] **Step 2: Run the new test module and verify all pass**

Run: `PYTHONPATH=harvester/src python3 -m pytest harvester/src/validators/tests/test_comparison_validator.py -v`

Expected: All tests pass (4 regression + 6 MRI + 6 singleUse + 5 rx = 21 tests).

- [ ] **Step 3: Run the full validator test suite to verify no regressions**

Run: `PYTHONPATH=harvester/src python3 -m pytest harvester/src/validators/tests/ -v`

Expected: All tests pass including `test_record_validator.py`.

- [ ] **Step 4: Run the full project test suite**

Run: `PYTHONPATH=harvester/src python3 -m pytest harvester/src/ -q`

Expected: All tests pass. Any pre-existing failures should match the state before this change — note them if present but do not investigate unless the `comparison_validator` tests or orchestrator-related tests fail.

- [ ] **Step 5: Commit**

```bash
git add harvester/src/validators/comparison_validator.py
git commit -m "feat(validators): compare MRISafetyStatus, singleUse, rx against GUDID"
```

---

## Task 3: Surface new fields in the review UI

**Files:**
- Modify: `app/routes/review.py:10-16`

- [ ] **Step 1: Extend the `COMPARED_FIELDS` list**

In `app/routes/review.py`, locate this block:

```python
COMPARED_FIELDS = [
    ("versionModelNumber", "Version / Model Number"),
    ("catalogNumber", "Catalog Number"),
    ("brandName", "Brand Name"),
    ("companyName", "Company Name"),
    ("deviceDescription", "Device Description"),
]
```

Replace with:

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

No template change — `app/templates/review.html` already iterates `{% for f in fields %}` generically. The three new fields will render as additional comparison rows with the same match/mismatch/N/A display treatment. The POST handler also iterates `COMPARED_FIELDS`, so the save-corrections form will accept `choice_MRISafetyStatus` / `choice_singleUse` / `choice_rx` automatically.

- [ ] **Step 2: Run the application test suite to verify no regressions**

Run: `PYTHONPATH=harvester/src python3 -m pytest -q`

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add app/routes/review.py
git commit -m "feat(review): show MRI/singleUse/rx rows on review page"
```

---

## Task 4: Update validators module docs

**Files:**
- Modify: `harvester/src/validators/CLAUDE.md`

- [ ] **Step 1: Update the Comparison Scoring section**

In `harvester/src/validators/CLAUDE.md`, locate this block:

```markdown
## Comparison Scoring

`compare_records()` compares 4 boolean fields + 1 similarity score:

- `versionModelNumber`, `catalogNumber`: normalized exact match (strip spaces/hyphens/dots, uppercase)
- `brandName`: case-insensitive, strip trademark symbols
- `companyName`: uppercase, strip punctuation
- `deviceDescription`: Jaccard word-set similarity (float 0.0–1.0)

Fields where harvested value is `None` → `match: None` (excluded from score denominator).
```

Replace with:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add harvester/src/validators/CLAUDE.md
git commit -m "docs(validators): document 7-field comparison and null handling"
```

---

## Task 5: Final verification

- [ ] **Step 1: Run the full test suite one more time**

Run: `PYTHONPATH=harvester/src python3 -m pytest -q`

Expected: All tests pass (prior count + 21 new tests).

- [ ] **Step 2: Confirm all four commits are on the branch**

Run: `git log --oneline -5`

Expected: Four new commits at the top:
1. `docs(validators): document 7-field comparison and null handling`
2. `feat(review): show MRI/singleUse/rx rows on review page`
3. `feat(validators): compare MRISafetyStatus, singleUse, rx against GUDID`
4. `test(validators): failing tests for MRISafetyStatus/singleUse/rx compare`

- [ ] **Step 3: Done**

Nothing else needed. No database migration — new `validationResults` documents will include the new fields; existing documents keep their old shape until revalidated.
