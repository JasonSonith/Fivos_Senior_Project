# Validator Data-Quality Layer 1 — Implementation Plan (PR1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the validator-layer UX + scoring improvements from the 2026-04-22 spec — status enum replacing tri-state, company alias map, description quality classifier, trademark normalization, both-null handling, weighted scoring, and the review UI state rendering. No new GUDID fields, no harvester changes; those land in PR2.

**Architecture:** Replace `compare_records()` per-field `match: True|False|None` with `status: str` enum (6 values). Add `FIELD_WEIGHTS` and return `(per_field, summary)` tuple. Orchestrator computes both unweighted and weighted percentages from the summary. Review route + template render status-keyed badges. All logic centralized in `harvester/src/validators/comparison_validator.py` plus one new sibling module `company_aliases.py`.

**Tech Stack:** Python 3.13, pytest, FastAPI + Jinja2, existing `normalizers/text.py` + `normalizers/booleans.py`.

**Spec:** `docs/superpowers/specs/2026-04-22-validator-harvester-data-quality-design.md` §1, §2, §3(b)(c), §6 (badge rendering portion only; deactivated banner + publishDate tile + Dashboard deactivated card land in PR2).

---

## Task 1: `FieldStatus` enum + `FIELD_WEIGHTS` + new return shape

**Files:**
- Modify: `harvester/src/validators/comparison_validator.py`
- Modify: `harvester/src/validators/tests/test_comparison_validator.py`

Refactor only — no new behavior. Status values map 1:1 to legacy: `True → "match"`, `False → "mismatch"`, `None → "not_compared"`. `compare_records()` returns `(per_field_dict, summary_dict)`. Summary carries `{numerator, denominator, unweighted_numerator, unweighted_denominator}` — all zero until Task 2 onward adds the new statuses that actually differ.

- [ ] **Step 1.1: Write failing test for new return shape**

Add to `harvester/src/validators/tests/test_comparison_validator.py`:

```python
def test_compare_records_returns_tuple_with_summary():
    harvested = {"versionModelNumber": "ABC-123", "brandName": "X"}
    gudid = {"versionModelNumber": "ABC123", "brandName": "X"}
    per_field, summary = compare_records(harvested, gudid)
    assert per_field["versionModelNumber"]["status"] == "match"
    assert per_field["brandName"]["status"] == "match"
    assert summary["unweighted_numerator"] >= 2
    assert summary["unweighted_denominator"] >= 2
    assert summary["numerator"] >= summary["unweighted_numerator"]  # weighted >= unweighted count
    assert summary["denominator"] >= summary["unweighted_denominator"]
```

- [ ] **Step 1.2: Run test, verify failure**

```
pytest harvester/src/validators/tests/test_comparison_validator.py::test_compare_records_returns_tuple_with_summary -v
```
Expected: FAIL — either `TypeError: cannot unpack non-iterable dict` or missing `status` key.

- [ ] **Step 1.3: Define `FieldStatus` and `FIELD_WEIGHTS` constants**

Add near top of `harvester/src/validators/comparison_validator.py`, after imports:

```python
class FieldStatus:
    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_COMPARED = "not_compared"
    BOTH_NULL = "both_null"
    CORPORATE_ALIAS = "corporate_alias"
    SKU_LABEL_SKIP = "sku_label_skip"


FIELD_WEIGHTS = {
    # Identifier-level (high)
    "versionModelNumber": 3, "catalogNumber": 3,
    "brandName": 3,          "companyName": 3,
    # Enum + regulatory (medium)
    "MRISafetyStatus": 2, "singleUse": 2, "rx": 2,
    # Description (low; quality-gated — see Task 6)
    "deviceDescription": 1,
}

_SCORED_STATUSES = {FieldStatus.MATCH, FieldStatus.CORPORATE_ALIAS, FieldStatus.MISMATCH}
_NUMERATOR_STATUSES = {FieldStatus.MATCH, FieldStatus.CORPORATE_ALIAS}
```

- [ ] **Step 1.4: Rewrite `compare_records()` to return `(per_field, summary)` with the new status enum**

Replace the entire `compare_records()` function in `harvester/src/validators/comparison_validator.py` with:

```python
def _status_from_bool(match: bool | None) -> str:
    if match is True:
        return FieldStatus.MATCH
    if match is False:
        return FieldStatus.MISMATCH
    return FieldStatus.NOT_COMPARED


def _build_summary(per_field: dict) -> dict:
    numerator = 0
    denominator = 0
    unweighted_num = 0
    unweighted_den = 0
    for field, result in per_field.items():
        status = result.get("status")
        if field == "deviceDescription":
            # deviceDescription only contributes to weighted; never to unweighted denominator (legacy rule)
            if status == FieldStatus.MATCH:
                weight = FIELD_WEIGHTS.get(field, 1)
                numerator += weight
                denominator += weight
            elif status == FieldStatus.MISMATCH:
                # A mismatch on description would require weight; currently we never set MISMATCH on description
                denominator += FIELD_WEIGHTS.get(field, 1)
            continue
        if status in _SCORED_STATUSES:
            unweighted_den += 1
            weight = FIELD_WEIGHTS.get(field, 1)
            denominator += weight
            if status in _NUMERATOR_STATUSES:
                unweighted_num += 1
                numerator += weight
    return {
        "numerator": numerator,
        "denominator": denominator,
        "unweighted_numerator": unweighted_num,
        "unweighted_denominator": unweighted_den,
    }


def compare_records(harvested, gudid):
    results = {}

    for field in ("versionModelNumber", "catalogNumber"):
        h = harvested.get(field)
        g = gudid.get(field)
        if not h:
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.NOT_COMPARED}
        else:
            match = bool(g and _norm_model(h) == _norm_model(g))
            results[field] = {
                "harvested": h, "gudid": g,
                "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
            }

    h_brand = harvested.get("brandName"); g_brand = gudid.get("brandName")
    if not h_brand:
        results["brandName"] = {"harvested": h_brand, "gudid": g_brand, "status": FieldStatus.NOT_COMPARED}
    else:
        match = bool(g_brand and _norm_brand(h_brand) == _norm_brand(g_brand))
        results["brandName"] = {
            "harvested": h_brand, "gudid": g_brand,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }

    h_company = harvested.get("companyName"); g_company = gudid.get("companyName")
    if not h_company:
        results["companyName"] = {"harvested": h_company, "gudid": g_company, "status": FieldStatus.NOT_COMPARED}
    else:
        match = bool(g_company and _norm_company(h_company) == _norm_company(g_company))
        results["companyName"] = {
            "harvested": h_company, "gudid": g_company,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }

    h_desc = harvested.get("deviceDescription"); g_desc = gudid.get("deviceDescription")
    sim = _jaccard(h_desc, g_desc)
    results["deviceDescription"] = {
        "harvested": h_desc, "gudid": g_desc,
        "status": FieldStatus.MATCH,  # overridden by Task 6 quality classifier
        "similarity": sim,
    }

    for field, normalizer in (
        ("MRISafetyStatus", normalize_mri_status),
        ("singleUse", normalize_boolean),
        ("rx", normalize_boolean),
    ):
        h = harvested.get(field); g = gudid.get(field)
        match, _, _ = _compare_normalized(h, g, normalizer)
        results[field] = {
            "harvested": h, "gudid": g,
            "status": _status_from_bool(match),
        }

    summary = _build_summary(results)
    return results, summary
```

- [ ] **Step 1.5: Migrate existing test assertions from `match` to `status`**

Every assertion in `harvester/src/validators/tests/test_comparison_validator.py` that reads `.get("match")` or checks `match=True/False/None` must be updated to check `status`.

Example existing assertion pattern:
```python
assert result["versionModelNumber"]["match"] is True
```
Becomes:
```python
per_field, _ = compare_records(harvested, gudid)  # unpack the new tuple
assert per_field["versionModelNumber"]["status"] == "match"
```

Also change every `result = compare_records(...)` call site to `per_field, summary = compare_records(...)` and read from `per_field`.

- [ ] **Step 1.6: Update orchestrator consumer — minimal shim only**

In `harvester/src/orchestrator.py`, the scoring loop currently does:

```python
comparison = compare_records(device, gudid_record)
compared = {k: v for k, v in comparison.items() if k != "deviceDescription" and v.get("match") is not None}
matched_fields = sum(1 for v in compared.values() if v["match"])
total_fields = len(compared)
```

Replace with:

```python
comparison, summary = compare_records(device, gudid_record)
matched_fields = summary["unweighted_numerator"]
total_fields = summary["unweighted_denominator"]
```

`match_percent` calculation stays the same. Weighted percent added in Task 2.

- [ ] **Step 1.7: Update review.py consumer — legacy fallback**

In `app/routes/review.py`, the review page builds `fields` from `comparison`. Add a helper at top of the file:

```python
def _field_status(comp_entry: dict) -> str:
    """Read status from the comparison entry. Falls back to deriving from
    legacy `match` field for pre-Task-1 validationResults documents."""
    if "status" in comp_entry:
        return comp_entry["status"]
    legacy = comp_entry.get("match")
    if legacy is True:
        return "match"
    if legacy is False:
        return "mismatch"
    return "not_compared"
```

In the `review_page` function, where `fields.append({...})` sets `match_status`, change:

```python
match_status = comp.get("match")
```
to:
```python
match_status = _field_status(comp)
```

Rename the key `"match"` → `"status"` in the appended dict. Downstream template reads `f.status` in Task 9.

- [ ] **Step 1.8: Run full test suite, verify green**

```
pytest
```
Expected: all existing tests pass (after assertion migration in Step 1.5). The new test from Step 1.1 passes. Orchestrator continues to produce valid `validationResults` documents.

- [ ] **Step 1.9: Commit**

```bash
git add harvester/src/validators/comparison_validator.py \
        harvester/src/validators/tests/test_comparison_validator.py \
        harvester/src/orchestrator.py \
        app/routes/review.py
git commit -m "$(cat <<'EOF'
feat(validators): FieldStatus enum + FIELD_WEIGHTS + summary return shape

compare_records() now returns (per_field, summary) where per_field uses
string status values instead of tri-state match booleans, and summary
carries weighted + unweighted numerator/denominator. Existing behavior
preserved; new statuses (both_null, corporate_alias, sku_label_skip) land
in later tasks. Orchestrator + review route migrated; legacy fallback
added to review.py for pre-migration validationResults documents.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Orchestrator adds `weighted_percent` to validationResults

**Files:**
- Modify: `harvester/src/orchestrator.py`
- Modify: `harvester/src/validators/tests/test_orchestrator_scoring.py` (new)

- [ ] **Step 2.1: Write failing test**

Create `harvester/src/validators/tests/test_orchestrator_scoring.py`:

```python
from unittest.mock import MagicMock
import pytest

from validators.comparison_validator import compare_records


def test_summary_weighted_differs_from_unweighted():
    """Weighted score should differ from unweighted when weights are not all equal."""
    # All high-weight fields match, one medium-weight mismatches
    harvested = {
        "versionModelNumber": "X", "catalogNumber": "Y",
        "brandName": "Z",           "companyName": "Q",
        "MRISafetyStatus": "MR Safe", "singleUse": True, "rx": True,
    }
    gudid = {
        "versionModelNumber": "X", "catalogNumber": "Y",
        "brandName": "Z",           "companyName": "Q",
        "MRISafetyStatus": "MR Unsafe", "singleUse": True, "rx": True,
    }
    _per_field, summary = compare_records(harvested, gudid)
    # 4 high (weight 3) all match → 12 numerator, 12 denominator
    # 2 medium (weight 2) match → +4 numerator, +4 denominator → 16/16
    # 1 medium (weight 2) mismatch → +0 numerator, +2 denominator → 16/18
    assert summary["numerator"] == 16
    assert summary["denominator"] == 18
    # Unweighted: 6/7
    assert summary["unweighted_numerator"] == 6
    assert summary["unweighted_denominator"] == 7
```

- [ ] **Step 2.2: Run test, verify failure**

```
pytest harvester/src/validators/tests/test_orchestrator_scoring.py -v
```
Expected: this test should PASS already if Task 1's `_build_summary` + `FIELD_WEIGHTS` are implemented. If it fails, debug `_build_summary` before proceeding.

- [ ] **Step 2.3: Update orchestrator to write `weighted_percent`**

In `harvester/src/orchestrator.py`, locate the `validation_col.insert_one({...})` call inside `run_validation()` (around line 404). The current shape:

```python
validation_col.insert_one({
    "device_id": device.get("_id"),
    "brandName": device.get("brandName"),
    "status": status,
    "matched_fields": matched_fields,
    "total_fields": total_fields,
    "match_percent": match_percent,
    "description_similarity": description_similarity,
    ...
})
```

Add the weighted percent calculation just after `match_percent`:

```python
weighted_percent = round(
    (summary["numerator"] / summary["denominator"]) * 100, 2
) if summary["denominator"] else 0.0
```

And add `"weighted_percent": weighted_percent,` to the insert payload, right after `match_percent`.

- [ ] **Step 2.4: Run full suite**

```
pytest
```
Expected: all pass, including the new test.

- [ ] **Step 2.5: Commit**

```bash
git add harvester/src/orchestrator.py \
        harvester/src/validators/tests/test_orchestrator_scoring.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): record weighted_percent on validationResults

Computed from the summary dict returned by compare_records(). Does NOT
drive validation status (which stays unweighted per spec §3.b). Populated
for every non-deactivated run; dashboard column wiring lands in Task 10.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Both-null detection across all compared fields

**Files:**
- Modify: `harvester/src/validators/comparison_validator.py`
- Modify: `harvester/src/validators/tests/test_comparison_validator.py`

- [ ] **Step 3.1: Write failing test**

Add to `test_comparison_validator.py`:

```python
def test_both_null_brand_name_yields_both_null_status():
    per_field, _ = compare_records(
        {"brandName": None, "versionModelNumber": "X"},
        {"brandName": None, "versionModelNumber": "X"},
    )
    assert per_field["brandName"]["status"] == "both_null"


def test_both_empty_string_company_yields_both_null():
    per_field, _ = compare_records(
        {"companyName": "", "versionModelNumber": "X"},
        {"companyName": "", "versionModelNumber": "X"},
    )
    assert per_field["companyName"]["status"] == "both_null"


def test_both_null_excluded_from_denominator():
    per_field, summary = compare_records(
        {"brandName": None, "versionModelNumber": "X"},
        {"brandName": None, "versionModelNumber": "X"},
    )
    # versionModelNumber matches (counts), brandName both-null (excluded)
    assert summary["unweighted_denominator"] == 1
```

- [ ] **Step 3.2: Run tests, verify failures**

```
pytest harvester/src/validators/tests/test_comparison_validator.py::test_both_null_brand_name_yields_both_null_status -v
```
Expected: FAIL — brandName would be `not_compared` today (harvested null triggers that branch).

- [ ] **Step 3.3: Add `_is_null()` helper and both-null guards**

Add to `harvester/src/validators/comparison_validator.py`, near the other helpers:

```python
def _is_null(value) -> bool:
    """A field is considered null if it's None, empty string, empty list, or
    a string that normalizes to empty."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, tuple)) and len(value) == 0:
        return True
    return False
```

Then prepend a both-null guard to each per-field block in `compare_records()`. For the identifier loop:

```python
for field in ("versionModelNumber", "catalogNumber"):
    h = harvested.get(field); g = gudid.get(field)
    if _is_null(h) and _is_null(g):
        results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.BOTH_NULL}
        continue
    if _is_null(h):
        results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.NOT_COMPARED}
    else:
        match = bool(g and _norm_model(h) == _norm_model(g))
        results[field] = {
            "harvested": h, "gudid": g,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }
```

Apply the same both-null-first pattern to brandName, companyName, and the MRI/singleUse/rx loop. For the MRI/singleUse/rx loop:

```python
for field, normalizer in (
    ("MRISafetyStatus", normalize_mri_status),
    ("singleUse", normalize_boolean),
    ("rx", normalize_boolean),
):
    h = harvested.get(field); g = gudid.get(field)
    if _is_null(h) and _is_null(g):
        results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.BOTH_NULL}
        continue
    match, _, _ = _compare_normalized(h, g, normalizer)
    results[field] = {
        "harvested": h, "gudid": g,
        "status": _status_from_bool(match),
    }
```

For `deviceDescription`:

```python
h_desc = harvested.get("deviceDescription"); g_desc = gudid.get("deviceDescription")
if _is_null(h_desc) and _is_null(g_desc):
    results["deviceDescription"] = {
        "harvested": h_desc, "gudid": g_desc,
        "status": FieldStatus.BOTH_NULL,
        "similarity": None,
    }
else:
    sim = _jaccard(h_desc, g_desc)
    results["deviceDescription"] = {
        "harvested": h_desc, "gudid": g_desc,
        "status": FieldStatus.MATCH,  # Task 6 overrides when quality check fires
        "similarity": sim,
    }
```

- [ ] **Step 3.4: Update `_build_summary` to exclude BOTH_NULL**

`_SCORED_STATUSES` already excludes `BOTH_NULL`, so `_build_summary` will correctly skip both-null fields. Confirm by re-reading `_build_summary` — no change needed if Task 1 was implemented per spec.

- [ ] **Step 3.5: Run full suite**

```
pytest
```
Expected: new tests pass. Existing tests pass. `test_both_null_excluded_from_denominator` confirms `BOTH_NULL` doesn't inflate denominators.

- [ ] **Step 3.6: Commit**

```bash
git add harvester/src/validators/comparison_validator.py \
        harvester/src/validators/tests/test_comparison_validator.py
git commit -m "$(cat <<'EOF'
feat(validators): detect both-null on every compared field

Both sides null (including empty string / empty list) → status=both_null,
excluded from numerator and denominator. Applies to all 7 identifier +
enum fields and deviceDescription. Review UI informational-only rendering
lands in Task 9.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `company_aliases.py` module + `canonical_company()`

**Files:**
- Create: `harvester/src/validators/company_aliases.py`
- Create: `harvester/src/validators/tests/test_company_aliases.py`

- [ ] **Step 4.1: Write failing tests**

Create `harvester/src/validators/tests/test_company_aliases.py`:

```python
import pytest
from validators.company_aliases import canonical_company, COMPANY_ALIASES


class TestCanonicalCompany:
    def test_exact_match_returns_canonical(self):
        assert canonical_company("Medtronic") == "Medtronic"

    def test_case_insensitive(self):
        assert canonical_company("medtronic") == "Medtronic"
        assert canonical_company("MEDTRONIC") == "Medtronic"

    def test_strips_inc_suffix(self):
        assert canonical_company("Medtronic Inc.") == "Medtronic"

    def test_strips_lp_suffix(self):
        assert canonical_company("Covidien LP") == "Medtronic"

    def test_strips_llc_suffix(self):
        assert canonical_company("Bard LLC") == "BD"

    def test_strips_corporation_suffix(self):
        assert canonical_company("Stryker Corporation") == "Stryker"

    def test_strips_ltd_suffix(self):
        assert canonical_company("BTG Ltd.") == "Boston Scientific"

    def test_covidien_maps_to_medtronic(self):
        assert canonical_company("Covidien") == "Medtronic"

    def test_bard_maps_to_bd(self):
        assert canonical_company("Bard") == "BD"
        assert canonical_company("C R Bard") == "BD"

    def test_st_jude_maps_to_abbott(self):
        assert canonical_company("St Jude Medical") == "Abbott"

    def test_ethicon_maps_to_jnj(self):
        assert canonical_company("Ethicon") == "Johnson & Johnson"

    def test_wright_medical_maps_to_stryker(self):
        assert canonical_company("Wright Medical") == "Stryker"

    def test_unknown_company_returns_none(self):
        assert canonical_company("Never Heard Of This Co") is None

    def test_empty_returns_none(self):
        assert canonical_company("") is None
        assert canonical_company(None) is None

    def test_whitespace_collapsed(self):
        assert canonical_company("  Medtronic   Inc.  ") == "Medtronic"

    def test_punctuation_stripped(self):
        assert canonical_company("Johnson, & Johnson") == "Johnson & Johnson"


def test_alias_map_has_all_seed_groups():
    for parent in ("Medtronic", "Boston Scientific", "BD", "Abbott",
                   "Johnson & Johnson", "Stryker"):
        assert parent in COMPANY_ALIASES
```

- [ ] **Step 4.2: Run tests, verify failures**

```
pytest harvester/src/validators/tests/test_company_aliases.py -v
```
Expected: all FAIL — module doesn't exist yet.

- [ ] **Step 4.3: Create `company_aliases.py`**

Write `harvester/src/validators/company_aliases.py`:

```python
"""Parent/subsidiary company alias map for GUDID comparison.

When comparing harvested companyName against GUDID companyName, a
mismatch on raw strings may still represent the same corporate entity
(e.g., Medtronic on the manufacturer site vs Covidien LP on GUDID,
because Medtronic acquired Covidien). canonical_company() resolves
both sides to the canonical parent name; if both resolve and agree,
the validator treats it as a match via alias.
"""

import re


COMPANY_ALIASES = {
    "Medtronic":         ["Medtronic", "Covidien LP", "Covidien"],
    "Boston Scientific": ["Boston Scientific", "BTG"],
    "BD":                ["BD", "Bard", "C R Bard", "Becton Dickinson"],
    "Abbott":            ["Abbott", "St Jude Medical"],
    "Johnson & Johnson": ["Johnson & Johnson", "J&J", "Synthes", "DePuy", "Ethicon"],
    "Stryker":           ["Stryker", "Wright Medical"],
}

_SUFFIX_RE = re.compile(
    r"\b(Inc\.?|LP|LLC|Ltd\.?|Corp\.?|Corporation|Company|Co\.?)\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[,\.&']")
_WS_RE = re.compile(r"\s+")


def _normalize(raw: str) -> str:
    """Strip suffixes, punctuation, case-fold, collapse whitespace."""
    text = _SUFFIX_RE.sub("", raw)
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip().lower()
    return text


# Build reverse index at import time: {normalized_variant: canonical}
_REVERSE_INDEX = {}
for canonical, variants in COMPANY_ALIASES.items():
    for variant in variants:
        _REVERSE_INDEX[_normalize(variant)] = canonical


def canonical_company(raw: str | None) -> str | None:
    """Resolve a raw company name to its canonical parent name, or None if
    not in the alias map.

    Matching is case-insensitive, tolerates Inc./LP/LLC/Ltd./Corp./
    Corporation/Company/Co. suffixes, and strips commas/periods/ampersands/
    apostrophes before lookup.
    """
    if not raw or not isinstance(raw, str):
        return None
    normalized = _normalize(raw)
    if not normalized:
        return None
    return _REVERSE_INDEX.get(normalized)
```

Note: `_normalize("Johnson & Johnson")` yields `"johnson  johnson"` (two spaces after the & is stripped), then collapses to `"johnson johnson"`. The reverse index entry for the canonical `"Johnson & Johnson"` also goes through `_normalize`, so they match. Same applies to `"Johnson, & Johnson"` — normalizes to `"johnson johnson"`.

- [ ] **Step 4.4: Run tests, verify all pass**

```
pytest harvester/src/validators/tests/test_company_aliases.py -v
```
Expected: all 17 tests PASS.

- [ ] **Step 4.5: Commit**

```bash
git add harvester/src/validators/company_aliases.py \
        harvester/src/validators/tests/test_company_aliases.py
git commit -m "$(cat <<'EOF'
feat(validators): company_aliases module with canonical_company()

Parent/subsidiary resolution for six medical device corporate groups
(Medtronic, Boston Scientific, BD, Abbott, Johnson & Johnson, Stryker).
Reverse-index built at import time for O(1) lookup. Normalization
tolerates Inc./LP/LLC/Ltd./Corp. suffixes and common punctuation. Wiring
into compare_records lands in Task 5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Wire corporate alias check into `companyName` compare

**Files:**
- Modify: `harvester/src/validators/comparison_validator.py`
- Modify: `harvester/src/validators/tests/test_comparison_validator.py`

- [ ] **Step 5.1: Write failing tests**

Add to `test_comparison_validator.py`:

```python
def test_medtronic_vs_covidien_scores_as_corporate_alias():
    per_field, _ = compare_records(
        {"companyName": "Medtronic Inc.", "versionModelNumber": "X"},
        {"companyName": "Covidien LP",    "versionModelNumber": "X"},
    )
    assert per_field["companyName"]["status"] == "corporate_alias"
    assert per_field["companyName"]["alias_group"] == "Medtronic"


def test_alias_match_counts_toward_numerator():
    per_field, summary = compare_records(
        {"companyName": "Medtronic Inc.", "versionModelNumber": "X"},
        {"companyName": "Covidien LP",    "versionModelNumber": "X"},
    )
    # 2 scored fields, both counted as matches
    assert summary["unweighted_numerator"] == 2
    assert summary["unweighted_denominator"] == 2


def test_cross_family_mismatch_not_alias():
    per_field, _ = compare_records(
        {"companyName": "Medtronic", "versionModelNumber": "X"},
        {"companyName": "Stryker",   "versionModelNumber": "X"},
    )
    assert per_field["companyName"]["status"] == "mismatch"


def test_exact_company_match_does_not_set_alias_group():
    per_field, _ = compare_records(
        {"companyName": "Medtronic", "versionModelNumber": "X"},
        {"companyName": "Medtronic", "versionModelNumber": "X"},
    )
    assert per_field["companyName"]["status"] == "match"
    assert "alias_group" not in per_field["companyName"]
```

- [ ] **Step 5.2: Run tests, verify failures**

```
pytest harvester/src/validators/tests/test_comparison_validator.py -k "alias or cross_family" -v
```
Expected: FAIL — `status` is `mismatch` for the Medtronic/Covidien pair today.

- [ ] **Step 5.3: Import `canonical_company` and wire into companyName block**

At the top of `harvester/src/validators/comparison_validator.py`:

```python
from validators.company_aliases import canonical_company
```

Replace the companyName block in `compare_records()`:

```python
h_company = harvested.get("companyName"); g_company = gudid.get("companyName")
if _is_null(h_company) and _is_null(g_company):
    results["companyName"] = {"harvested": h_company, "gudid": g_company, "status": FieldStatus.BOTH_NULL}
elif _is_null(h_company):
    results["companyName"] = {"harvested": h_company, "gudid": g_company, "status": FieldStatus.NOT_COMPARED}
else:
    if g_company and _norm_company(h_company) == _norm_company(g_company):
        results["companyName"] = {"harvested": h_company, "gudid": g_company, "status": FieldStatus.MATCH}
    else:
        h_canonical = canonical_company(h_company)
        g_canonical = canonical_company(g_company)
        if h_canonical and g_canonical and h_canonical == g_canonical:
            results["companyName"] = {
                "harvested": h_company, "gudid": g_company,
                "status": FieldStatus.CORPORATE_ALIAS,
                "alias_group": h_canonical,
            }
        else:
            results["companyName"] = {
                "harvested": h_company, "gudid": g_company,
                "status": FieldStatus.MISMATCH,
            }
```

- [ ] **Step 5.4: Run tests, verify all pass**

```
pytest harvester/src/validators/tests/test_comparison_validator.py -v
```
Expected: all pass, including the 4 new alias tests.

- [ ] **Step 5.5: Commit**

```bash
git add harvester/src/validators/comparison_validator.py \
        harvester/src/validators/tests/test_comparison_validator.py
git commit -m "$(cat <<'EOF'
feat(validators): corporate alias match on companyName

When normalized exact compare fails, resolve both sides via
canonical_company() and if both agree on the same parent name,
status=corporate_alias with alias_group=<canonical>. Counts +1 toward
numerator and +1 toward denominator (spec §1 scoring rule).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: GUDID description quality classifier + wire into `deviceDescription` compare

**Files:**
- Modify: `harvester/src/validators/comparison_validator.py`
- Create: `harvester/src/validators/tests/test_description_quality.py`

- [ ] **Step 6.1: Write failing tests**

Create `harvester/src/validators/tests/test_description_quality.py`:

```python
import pytest
from validators.comparison_validator import _gudid_description_is_sku_label


class TestSkuLabelClassifier:
    # Real-prose examples — should be False
    @pytest.mark.parametrize("desc", [
        "A peripheral vascular stent designed for the treatment of occluded arteries in the lower extremities.",
        "Drug-eluting coronary stent system for the treatment of patients with coronary artery disease.",
        "Self-expanding nitinol endoprosthesis intended for the treatment of peripheral arterial disease.",
    ])
    def test_prose_returns_false(self, desc):
        assert _gudid_description_is_sku_label(desc, "MODEL1", "CAT1") is False

    # Short descriptions (<40 chars) — should be True
    @pytest.mark.parametrize("desc", [
        "STENT",
        "Drug-eluting balloon",
        "Coronary stent kit",
    ])
    def test_short_returns_true(self, desc):
        assert _gudid_description_is_sku_label(desc, "MODEL1", "CAT1") is True

    # Contains model or catalog number verbatim — should be True
    def test_contains_model_number_returns_true(self):
        assert _gudid_description_is_sku_label(
            "PXB35-09-17-080 peripheral stent system for vascular treatment",
            "PXB35-09-17-080", None,
        ) is True

    def test_contains_catalog_number_returns_true(self):
        assert _gudid_description_is_sku_label(
            "Catalog ABC-123 drug-eluting stent for peripheral arteries",
            None, "ABC-123",
        ) is True

    # ≥70% uppercase — should be True
    @pytest.mark.parametrize("desc", [
        "PERIPHERAL VASCULAR STENT SYSTEM DRUG-ELUTING BALLOON EXP",
        "NITINOL ENDOPROSTHESIS CORONARY STENT BALLOON CATHETER",
        "DRUG-ELUTING STENT SYSTEM BALLOON EXPANDABLE VASCULAR",
    ])
    def test_all_caps_returns_true(self, desc):
        assert _gudid_description_is_sku_label(desc, "M", "C") is True

    # All-caps + digits + hyphens only — should be True via regex fullmatch
    def test_sku_pattern_returns_true(self):
        assert _gudid_description_is_sku_label(
            "PXB35-09-17-080 STENT NITINOL SYSTEM",
            "NONMATCHING", "OTHER",
        ) is True

    # Edge: None input
    def test_none_returns_false(self):
        assert _gudid_description_is_sku_label(None, "M", "C") is False

    def test_empty_returns_false(self):
        assert _gudid_description_is_sku_label("", "M", "C") is False
```

And add to `test_comparison_validator.py`:

```python
def test_deviceDescription_sku_label_skip_status():
    per_field, _ = compare_records(
        {"deviceDescription": "A peripheral stent for treating arterial disease.",
         "versionModelNumber": "PXB35"},
        {"deviceDescription": "PXB35 STENT",  # short + contains model
         "versionModelNumber": "PXB35"},
    )
    assert per_field["deviceDescription"]["status"] == "sku_label_skip"
    assert per_field["deviceDescription"]["similarity"] is None


def test_deviceDescription_prose_both_sides_scores_match():
    per_field, _ = compare_records(
        {"deviceDescription": "A peripheral stent for arterial disease treatment.",
         "versionModelNumber": "X"},
        {"deviceDescription": "Peripheral vascular stent for treating arterial disease.",
         "versionModelNumber": "X"},
    )
    assert per_field["deviceDescription"]["status"] == "match"
    assert per_field["deviceDescription"]["similarity"] > 0
```

- [ ] **Step 6.2: Run tests, verify failures**

```
pytest harvester/src/validators/tests/test_description_quality.py -v
```
Expected: all FAIL — `_gudid_description_is_sku_label` doesn't exist.

- [ ] **Step 6.3: Implement classifier**

In `harvester/src/validators/comparison_validator.py`, add near other helpers:

```python
_SKU_PATTERN_RE = re.compile(r"^[A-Z0-9\-_ ]+$")


def _gudid_description_is_sku_label(
    gudid_value: str | None,
    model_number: str | None,
    catalog_number: str | None,
) -> bool:
    """Detect whether a GUDID deviceDescription value is a SKU label rather
    than prose. Returns True if ANY of four heuristics trigger:
      - length < 40 chars
      - contains the device's model_number or catalog_number (case-insensitive)
      - ≥70% uppercase letter ratio (ignoring digits/punctuation)
      - matches SKU-like pattern [A-Z0-9\\-_ ]+ end-to-end
    """
    if not gudid_value or not isinstance(gudid_value, str):
        return False
    stripped = gudid_value.strip()
    if not stripped:
        return False
    if len(stripped) < 40:
        return True
    lowered = stripped.lower()
    for ident in (model_number, catalog_number):
        if ident and isinstance(ident, str) and ident.lower() in lowered:
            return True
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) >= 3:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio >= 0.70:
            return True
    if _SKU_PATTERN_RE.fullmatch(stripped):
        return True
    return False
```

- [ ] **Step 6.4: Wire classifier into `deviceDescription` block**

Replace the deviceDescription block in `compare_records()`:

```python
h_desc = harvested.get("deviceDescription"); g_desc = gudid.get("deviceDescription")
model_no = harvested.get("versionModelNumber")
catalog_no = harvested.get("catalogNumber")
if _is_null(h_desc) and _is_null(g_desc):
    results["deviceDescription"] = {
        "harvested": h_desc, "gudid": g_desc,
        "status": FieldStatus.BOTH_NULL,
        "similarity": None,
    }
elif _gudid_description_is_sku_label(g_desc, model_no, catalog_no):
    results["deviceDescription"] = {
        "harvested": h_desc, "gudid": g_desc,
        "status": FieldStatus.SKU_LABEL_SKIP,
        "similarity": None,
    }
else:
    sim = _jaccard(h_desc, g_desc)
    results["deviceDescription"] = {
        "harvested": h_desc, "gudid": g_desc,
        "status": FieldStatus.MATCH,
        "similarity": sim,
    }
```

Note: `_build_summary` handles `SKU_LABEL_SKIP` correctly because it only adds weight for `MATCH`/`MISMATCH` on deviceDescription (see Task 1). SKU-label-skip contributes neither to numerator nor denominator.

- [ ] **Step 6.5: Run tests**

```
pytest harvester/src/validators/tests/ -v
```
Expected: all pass.

- [ ] **Step 6.6: Commit**

```bash
git add harvester/src/validators/comparison_validator.py \
        harvester/src/validators/tests/test_description_quality.py \
        harvester/src/validators/tests/test_comparison_validator.py
git commit -m "$(cat <<'EOF'
feat(validators): GUDID description quality classifier

Detect when GUDID deviceDescription is a SKU label rather than prose
via four heuristics (short, contains model/catalog, ≥70% uppercase,
SKU-pattern-only). On hit: status=sku_label_skip, similarity=None,
excluded from scoring. Avoids noise percentages when GUDID holds a
SKU in the description field.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Extend `clean_brand_name` + wire into brand comparison

**Files:**
- Modify: `harvester/src/normalizers/text.py`
- Modify: `harvester/src/validators/comparison_validator.py`
- Modify: `harvester/src/normalizers/tests/test_text.py` (create if missing)

- [ ] **Step 7.1: Check/create normalizers test file**

```
ls harvester/src/normalizers/tests/
```
If `test_text.py` doesn't exist, this task creates it.

- [ ] **Step 7.2: Write failing tests**

Add to or create `harvester/src/normalizers/tests/test_text.py`:

```python
import pytest
from normalizers.text import clean_brand_name


class TestCleanBrandNameSymbols:
    @pytest.mark.parametrize("raw,expected", [
        ("Visi-Pro™", "Visi-Pro"),
        ("IN.PACT®", "IN.PACT"),
        ("Zilver PTX©", "Zilver PTX"),
        ("Visi-ProTM", "Visi-Pro"),          # TM ligature
        ("Eluvia℠", "Eluvia"),              # Service-mark symbol
    ])
    def test_strips_trademark_symbols(self, raw, expected):
        assert clean_brand_name(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("‘Supera’", "Supera"),      # smart single quotes
        ("“Xience”", "Xience"),      # smart double quotes
    ])
    def test_strips_smart_quotes(self, raw, expected):
        assert clean_brand_name(raw) == expected

    def test_strips_nbsp_and_zero_width(self):
        # U+00A0 NBSP + U+200B zero-width-space
        raw = "Zilver PTX​"
        assert clean_brand_name(raw) == "Zilver PTX"
```

- [ ] **Step 7.3: Run test, verify failures**

```
pytest harvester/src/normalizers/tests/test_text.py -v
```
Expected: FAIL on `℠` (not in `_TM_SYMBOLS_RE` today) and smart quotes (not in `INVISIBLE_CHARS` today — those handle invisible chars only).

- [ ] **Step 7.4: Extend `_TM_SYMBOLS_RE` and add smart-quote stripping**

In `harvester/src/normalizers/text.py`, update `_TM_SYMBOLS_RE` to also include `℠`:

```python
_TM_SYMBOLS_RE = re.compile(r"[™®©℠]|(?<=\w)TM(?=\s|$|\b)")
```

Add a new regex for smart quotes and update `clean_brand_name` to apply it:

```python
_SMART_QUOTES_RE = re.compile(r"[‘’“”]")


def clean_brand_name(raw: str) -> str | None:
    """Clean a brand name for GUDID alignment.

    Strips ™/®/©/℠/TM ligature, smart quotes, invisible characters, and
    trailing descriptive text (e.g. 'drug-eluting stent', 'directional
    atherectomy system').
    """
    if not raw or not isinstance(raw, str):
        return None
    text = normalize_text(raw)
    if not text:
        return None
    text = _TM_SYMBOLS_RE.sub("", text)
    text = _SMART_QUOTES_RE.sub("", text)
    text = _BRAND_SUFFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text else None
```

- [ ] **Step 7.5: Wire `clean_brand_name` into brandName compare**

In `harvester/src/validators/comparison_validator.py`, at the top:

```python
from normalizers.text import clean_brand_name
```

Replace `_norm_brand()`:

```python
def _norm_brand(value):
    cleaned = clean_brand_name(value) if value else None
    return (cleaned or "").lower()
```

- [ ] **Step 7.6: Run full suite**

```
pytest
```
Expected: all pass. Existing brandName tests still green (they used simpler examples). New text normalization tests pass.

- [ ] **Step 7.7: Commit**

```bash
git add harvester/src/normalizers/text.py \
        harvester/src/normalizers/tests/test_text.py \
        harvester/src/validators/comparison_validator.py
git commit -m "$(cat <<'EOF'
feat(normalizers): extend clean_brand_name for ℠ + smart quotes

Trademark regex now covers U+2120 service-mark symbol. New smart-quotes
regex strips U+2018/2019/201C/201D. Invisible char + NBSP + soft hyphen
handling already existed via INVISIBLE_CHARS. comparison_validator's
_norm_brand now delegates to clean_brand_name instead of its own
limited [™®†°] strip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Review route + template — status-keyed rendering

**Files:**
- Modify: `app/routes/review.py`
- Modify: `app/templates/review.html`
- Modify: `app/static/css/styles.css`

- [ ] **Step 8.1: Update `_field_status` helper + extend `fields` dict with alias_group**

In `app/routes/review.py`, the helper added in Task 1 stays. Update the `review_page` function's `fields.append(...)` block:

```python
for field_key, field_label in COMPARED_FIELDS:
    comp = comparison.get(field_key, {})
    comp_h = comp.get("harvested")
    harvested_val = comp_h if comp_h is not None else device.get(field_key, "N/A")
    comp_g = comp.get("gudid")
    gudid_val = comp_g if comp_g is not None else gudid_record.get(field_key, "N/A")

    status = _field_status(comp)
    similarity = comp.get("similarity") if field_key == "deviceDescription" else None

    fields.append({
        "key": field_key,
        "label": field_label,
        "harvested": harvested_val,
        "gudid": gudid_val,
        "status": status,
        "alias_group": comp.get("alias_group"),
        "similarity": similarity,
    })
```

Remove the now-unused `match_status` intermediate variable.

- [ ] **Step 8.2: Add CSS tokens and badge classes**

In `app/static/css/styles.css`, locate the existing CSS variables block (typically near the top). Add new tokens alongside the existing `--success`, `--warning`, `--danger`, `--muted`:

```css
:root {
    /* ...existing tokens... */
    --info: #1d4ed8;
    --info-bg: #eff6ff;
    /* --muted-bg and --warning-bg already exist per April 20 frontend-filtering work */
}
```

At the end of the file, add the match-status badge classes:

```css
.match-status {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
}
.match-status.match    { background: rgba(34, 197, 94, 0.1); color: var(--success); }
.match-status.mismatch { background: rgba(239, 68, 68, 0.1); color: var(--danger);  }
.match-status.alias    { background: var(--info-bg);         color: var(--info);    }
.match-status.both-null{ background: var(--muted-bg);        color: var(--muted);   }
.match-status.sku-skip { background: var(--warning-bg);      color: var(--warning); }
.match-status.not-compared { background: var(--muted-bg);    color: var(--muted);   }

.review-field-row.informational {
    opacity: 0.7;
}
```

Note: if `--muted-bg` or `--warning-bg` aren't yet defined (verify by grepping), add them to `:root`:
```css
    --muted-bg: #f3f4f6;
    --warning-bg: #fef3c7;
```

- [ ] **Step 8.3: Replace the per-row badge block in `review.html`**

In `app/templates/review.html`, locate lines 97–107 (the existing badge logic inside the `{% for f in fields %}` loop in review mode). Replace with a status-keyed chain:

```html
<div class="review-field-row
    {% if f.status == 'match' %}matched{% endif %}
    {% if f.status in ['both_null', 'sku_label_skip'] %}informational{% endif %}">
    <div class="review-field-name">
        {{ f.label }}
        <br>
        {% if f.status == 'match' %}
            <span class="match-status match">Match</span>
            {% if f.similarity is not none %}
                <span style="font-size: 11px; color: var(--muted); margin-left: 6px;">{{ "%.0f"|format((f.similarity or 0) * 100) }}% similar</span>
            {% endif %}
        {% elif f.status == 'mismatch' %}
            <span class="match-status mismatch">Mismatch</span>
        {% elif f.status == 'corporate_alias' %}
            <span class="match-status alias">Alias &rarr; {{ f.alias_group }}</span>
        {% elif f.status == 'both_null' %}
            <span class="match-status both-null">No Data</span>
        {% elif f.status == 'sku_label_skip' %}
            <span class="match-status sku-skip">GUDID is SKU label</span>
        {% elif f.status == 'not_compared' %}
            <span class="match-status not-compared">Not Compared</span>
        {% endif %}
    </div>
    <div class="review-value harvested">
        {% if f.harvested is none %}N/A{% else %}{{ f.harvested }}{% endif %}
    </div>
    <div class="review-value gudid">
        {% if f.gudid is none %}N/A{% else %}{{ f.gudid }}{% endif %}
    </div>
    <div class="review-pick">
        {% if f.status in ['mismatch', 'not_compared'] %}
            <label><input type="radio" name="choice_{{ f.key }}" value="harvested" checked> Keep Harvested</label>
            <label><input type="radio" name="choice_{{ f.key }}" value="gudid"> Use GUDID</label>
        {% elif f.status in ['match', 'corporate_alias'] %}
            <input type="hidden" name="choice_{{ f.key }}" value="harvested">
            <span style="color: var(--success); font-size: 13px;">
                {% if f.status == 'corporate_alias' %}Matched via alias{% else %}Matched{% endif %}
            </span>
        {% else %}
            <span style="color: var(--muted); font-size: 13px;">&ndash;</span>
        {% endif %}
    </div>
</div>
```

- [ ] **Step 8.4: Smoke-test the review page locally**

```bash
UVICORN_RELOAD=true python run.py &
```
Open http://localhost:8500, log in, navigate to `/` and click into any discrepancy. Confirm:
- `match` rows show green "Match" pill and "Matched" in the pick column
- `mismatch` rows show red "Mismatch" pill and the radio picker
- Existing validationResults documents (pre-migration) fall through the legacy `_field_status` helper and still render (all rows as match/mismatch/not_compared)

Stop the server (Ctrl-C or `pkill -f run.py`).

- [ ] **Step 8.5: Commit**

```bash
git add app/routes/review.py \
        app/templates/review.html \
        app/static/css/styles.css
git commit -m "$(cat <<'EOF'
feat(review): status-keyed badge rendering + informational rows

Per-field comparison rows now render one of six status badges (match /
mismatch / corporate_alias / both_null / sku_label_skip / not_compared)
with distinct colors. Informational rows (both_null, sku_label_skip)
render at 0.7 opacity and suppress the radio picker. Corporate-alias
rows display the canonical parent company name. New --info CSS token
for the alias badge.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Dashboard weighted-score column (no default sort change)

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/routes/dashboard.py` (if table data comes from a specific serialization path)

- [ ] **Step 9.1: Verify dashboard template table structure**

```
grep -n "match_percent\|match %\|match percent" app/templates/dashboard.html
```
Locate the column header row and the per-row td rendering for `match_percent`.

- [ ] **Step 9.2: Add `weighted_percent` column to dashboard.html**

Find the table header row (typically `<thead><tr>...`) that includes the current "Match %" column. Add a new `<th>` right after "Match %":

```html
<th>Weighted %</th>
```

In the table body row rendering (`{% for row in all_results %}` or similar), add right after the match_percent cell:

```html
<td>
    {% if row.weighted_percent is not none %}{{ row.weighted_percent }}%{% else %}&mdash;{% endif %}
</td>
```

Default sort is unchanged — whatever column currently drives the ordering stays.

- [ ] **Step 9.3: Verify dashboard route passes `weighted_percent`**

Dashboard route likely pulls all validationResults docs and passes them to the template. If the route uses a projection (`.find({}, {"fields": 1, ...})`), confirm `weighted_percent` is included or the projection is removed for simplicity.

```
grep -n "weighted_percent\|find(" app/routes/dashboard.py harvester/src/orchestrator.py | head -20
```

If needed, add `weighted_percent` to any projection. Otherwise no route change needed since Mongo returns all fields by default.

- [ ] **Step 9.4: Smoke-test**

Restart server, open dashboard. Confirm the "Weighted %" column appears. For rows created before PR1 (pre-weighted_percent field), the column shows `—`.

- [ ] **Step 9.5: Commit**

```bash
git add app/templates/dashboard.html app/routes/dashboard.py
git commit -m "$(cat <<'EOF'
feat(dashboard): add Weighted % column alongside Match %

Non-sortable display column reading validation.weighted_percent. Default
sort order stays on unweighted match_percent — changing the default
right before the capstone demo is deferred. Em-dash for rows predating
the Task 2 field addition.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Docs — `validators/CLAUDE.md` scoring update

**Files:**
- Modify: `harvester/src/validators/CLAUDE.md`

- [ ] **Step 10.1: Rewrite the Comparison Scoring section**

Open `harvester/src/validators/CLAUDE.md`. Replace the "Comparison Scoring" section with:

```markdown
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
- Identifier-level (high weight 3): `versionModelNumber`, `catalogNumber`, `brandName`, `companyName`
- Enum/regulatory (medium weight 2): `MRISafetyStatus`, `singleUse`, `rx`
- Description (low weight 1): `deviceDescription` (quality-gated; see below)

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
```

- [ ] **Step 10.2: Commit**

```bash
git add harvester/src/validators/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(validators): scoring section rewrite for PR1 status enum

Six-state status model, FIELD_WEIGHTS, corporate alias resolution,
description quality classifier, and the scoring-eligibility dependency
call-out. Reflects comparison_validator.py as of PR1 completion.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Post-PR1 checklist

Before merging PR1 to `main`:

- [ ] Full `pytest` green
- [ ] Manual: log in, navigate to a discrepancy from an old validation run (pre-migration doc) — renders correctly via legacy fallback
- [ ] Manual: run a fresh validation on 1–2 URLs. Verify new validationResults documents have `status` + `weighted_percent` fields
- [ ] Manual: discrepancy with known corporate-alias pair (Medtronic vs Covidien) renders with blue "Alias → Medtronic" badge and no radio picker
- [ ] Manual: discrepancy with known short GUDID description renders with amber "GUDID is SKU label" badge
- [ ] CSP still functional (no inline JS added; only template + CSS)
- [ ] CSRF still enforced on `/review/<id>/save`
- [ ] PR2 plan reviewed before beginning next batch
