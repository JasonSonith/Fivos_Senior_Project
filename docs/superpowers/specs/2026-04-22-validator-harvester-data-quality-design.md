# Validator & Harvester Data-Quality Expansion — Design Spec

**Date:** 2026-04-22
**Author:** Jason Sonith
**Status:** Approved (pending user review)

---

## Goal

Eliminate systemic data-quality noise in the validator and harvester layers that was surfaced while reviewing the `PXB35-09-17-080` record. Three coordinated layers of work, shipped under one plan:

1. **Validator-layer fixes** — replace the tri-state match/mismatch/skip model with a richer status enum, add a corporate-alias map, a GUDID-description quality classifier, trademark/punctuation normalization, both-null handling, and weighted scoring.
2. **New GUDID fields** — extend the GUDID client to fetch eight additional fields; add eight new MERGE targets and nine new compared fields (null-asymmetric, following the pattern of the April 20 MRI/singleUse/rx expansion).
3. **New harvester extractions** — extract `indicationsForUse`, `contraindications`, `deviceClass` via LLM, and move `premarketSubmissions` out of the LLM schema and into regex in `regulatory_parser.py`.

Everything in Layers 1 and 2 counts toward per-field scoring with a separate weighted aggregate. Layer 3 fields are harvest-only except `premarketSubmissions`, which is compared as a subset relation.

---

## Current State

`harvester/src/validators/comparison_validator.py` returns `{"match": True | False | None}` per field. The scoring loop in `harvester/src/orchestrator.py:run_validation()` counts `match is True` as the numerator and `match is not None` as the denominator, producing `match_percent`. Status thresholds (`matched` / `partial_match` / `mismatch`) are purely unweighted and purely per-field equality.

Known limitations that motivate this spec:
- `companyName` mismatches on parent/subsidiary pairs (e.g., Medtronic vs Covidien LP) score as `mismatch` even though they're the same corporate entity.
- GUDID sometimes stores a SKU label in `deviceDescription` instead of prose — Jaccard similarity against the manufacturer's clinical description produces noise percentages (3–8%) that look like catastrophic mismatches but are artifacts of GUDID data quality.
- Trademark symbols (`™®©℠`), smart quotes, zero-width chars, and the literal `TM` ligature aren't consistently stripped in the compare path. `text.py:clean_brand_name()` covers most of this but isn't wired into `comparison_validator._norm_brand()`.
- Both-sides-null fields render as "N/A vs N/A" with a mandatory radio picker — no-action rows that reviewers still have to click through.
- All seven identifier + enum fields score equally; a model-number mismatch weighs the same as a single-use label mismatch.
- GUDID's `deviceRecordStatus = "Deactivated"` is not detected; stale GUDID data gets merged into live device fields via `_merge_gudid_into_device()`.

---

## Design

### 1. Status-code model

The `match: True|False|None` tri-state is replaced with a string enum on every per-field result.

```python
# harvester/src/validators/comparison_validator.py
class FieldStatus:
    MATCH = "match"                      # values agree after normalization
    MISMATCH = "mismatch"                # values disagree
    NOT_COMPARED = "not_compared"        # harvested side is null (asymmetric)
    BOTH_NULL = "both_null"              # neither side has the value
    CORPORATE_ALIAS = "corporate_alias"  # companyName only; parent/subsidiary match
    SKU_LABEL_SKIP = "sku_label_skip"    # deviceDescription only; GUDID value is a SKU
```

Per-field return shape:
```python
{
    "harvested": <value>,
    "gudid": <value>,
    "status": FieldStatus,                   # replaces `match`
    "similarity": 0.0-1.0 | None,            # deviceDescription only, when status == match
    "alias_group": "Medtronic" | None,       # corporate_alias only; canonical parent name
}
```

**Record-level `status` on `validationResults` documents:**
- Existing: `matched`, `partial_match`, `mismatch`, `gudid_not_found`
- New: `gudid_deactivated` — short-circuit case; set in `run_validation()` before `compare_records()` is called.

**Scoring math** (in `orchestrator.run_validation()`, per field):
| `FieldStatus` | Numerator | Denominator |
|---|---|---|
| `MATCH`, `CORPORATE_ALIAS` | +1 | +1 |
| `MISMATCH` | 0 | +1 |
| `NOT_COMPARED`, `BOTH_NULL`, `SKU_LABEL_SKIP` | 0 | 0 |

Weighted variant applies `FIELD_WEIGHTS[field]` instead of +1/+0. Both unweighted and weighted are recorded on the validationResults document; only unweighted drives `status` (matched/partial_match/mismatch).

**Migration:** existing `validationResults` documents keep their old shape until revalidated. The review route reads defensively — if `comp.get("status")` is absent, derive it from the legacy `match` field:
- `match is True → "match"`
- `match is False → "mismatch"`
- `match is None → "not_compared"`

**Migration is forward-only.** New code writes only `status`, never `match`. There is no rollback path — if the Layer-1 rewrite ships and is later reverted, any newly-written `validationResults` documents (with `status` but no `match`) would appear as universal `not_compared` to old code reading them. The forward-only posture is intentional (we want the new semantics) and the risk is contained: `validationResults` is regenerable by re-running validation.

### 2. `comparison_validator.py` changes

Seven behavioral changes, all concentrated in this module plus one new sibling (`company_aliases.py`).

**(a) New module `harvester/src/validators/company_aliases.py`:**
```python
COMPANY_ALIASES = {
    "Medtronic":         ["Medtronic", "Covidien LP", "Covidien"],
    "Boston Scientific": ["Boston Scientific", "BTG"],
    "BD":                ["BD", "Bard", "C R Bard", "Becton Dickinson"],
    "Abbott":            ["Abbott", "St Jude Medical"],
    "Johnson & Johnson": ["Johnson & Johnson", "J&J", "Synthes", "DePuy", "Ethicon"],
    "Stryker":           ["Stryker", "Wright Medical"],
}

def canonical_company(raw: str) -> str | None:
    """Strip Inc./LP/LLC/Ltd./Corp./Corporation/Company/Co., case-fold,
    collapse whitespace, strip commas/periods/ampersands/apostrophes,
    then look up against COMPANY_ALIASES. Returns the canonical parent
    name or None."""
```

Implementation builds an O(1) reverse index at import time: `{normalized_variant: canonical_parent}`. Suffix-strip regex: `\b(Inc\.?|LP|LLC|Ltd\.?|Corp\.?|Corporation|Company|Co\.?)\b` applied case-insensitively.

**(b) Wire `clean_brand_name()` from `normalizers/text.py` into brand comparison** — replaces the local `_norm_brand()` helper. Extend `clean_brand_name()` to also strip `℠` and smart quotes `‘’“”`. The existing `_TM_SYMBOLS_RE` and `INVISIBLE_CHARS` (zero-width chars, NBSP, soft hyphens) come along for free.

**(c) Company alias check** in the `companyName` compare block: if normalized exact-compare fails, run `canonical_company()` on both sides. If both resolve and agree → `status: "corporate_alias"`, `alias_group: <canonical>`.

**(d) `both_null` detection** runs first on every field: if both sides are null/empty after normalization → `status: "both_null"`, skip remaining compare logic.

**(e) `deviceDescription` quality classifier:**
```python
def _gudid_description_is_sku_label(gudid_value, model_number, catalog_number) -> bool:
    """Returns True if the GUDID description looks like a SKU label rather
    than prose. Any ONE of the four heuristics triggers True."""
    if not gudid_value:
        return False
    stripped = gudid_value.strip()
    if len(stripped) < 40:
        return True
    for ident in (model_number, catalog_number):
        if ident and ident.lower() in stripped.lower():
            return True
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) >= 3:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio >= 0.70:
            return True
    if re.fullmatch(r"[A-Z0-9\-_ ]+", stripped):
        return True
    return False
```
When True: `status: "sku_label_skip"`, `similarity: None`, and no Jaccard runs. When False: Jaccard runs as today, `status: "match"`, `similarity: <float>`. `deviceDescription` stays out of the unweighted scoring denominator regardless (same as today).

**Scoring-eligibility dependency — call out loudly in `validators/CLAUDE.md`:** `deviceDescription` contributes to the *weighted* score only when the quality check passes. Two devices with identical harvested descriptions but different GUDID description quality (one SKU-labeled, one prose) will produce different weighted scores — the SKU-labeled case drops a weight-1 contribution entirely, the prose case adds it to the denominator. Correct behavior, but surprising; reviewers reading weighted percentages need to understand that the denominator itself is data-dependent, not a fixed per-device constant.

**(f) `FIELD_WEIGHTS` constant:**
```python
FIELD_WEIGHTS = {
    # Identifier-level (high)
    "versionModelNumber": 3, "catalogNumber": 3,
    "brandName": 3,          "companyName": 3,
    "gmdnPTName": 3,         "productCodes": 3,
    # Enum + classification (medium)
    "MRISafetyStatus": 2, "singleUse": 2, "rx": 2,
    "gmdnCode": 2,        "deviceCountInBase": 2, "issuingAgency": 2,
    "premarketSubmissions": 2,
    # Labeling metadata (low)
    "lotBatch": 1, "serialNumber": 1,
    "manufacturingDate": 1, "expirationDate": 1,
    # Description (low; quality-gated)
    "deviceDescription": 1,
}
```

**(g) `compare_records()` return shape** becomes `(per_field_results, summary)`:
```python
{
    "numerator": int,              # sum of FIELD_WEIGHTS for match + corporate_alias
    "denominator": int,            # sum of FIELD_WEIGHTS for match + mismatch + corporate_alias
    "unweighted_numerator": int,   # count of match + corporate_alias
    "unweighted_denominator": int, # count of match + mismatch + corporate_alias
}
```

**(h) Null-asymmetric preserved** for the four historical identifier fields (`versionModelNumber`, `catalogNumber`, `brandName`, `companyName`): harvested null → `NOT_COMPARED`, harvested present + GUDID null → `MISMATCH`. Same semantics as today, just via the new enum.

### 3. `orchestrator.py` changes

All changes in `run_validation()` plus one added counter on the result dict.

**(a) GUDID-deactivated short-circuit** — new guard before the `compare_records()` call:
```python
record_status = (gudid_record or {}).get("deviceRecordStatus")
if record_status == "Deactivated":
    validation_col.insert_one({
        "device_id": device["_id"],
        "brandName": device.get("brandName"),
        "status": "gudid_deactivated",
        "matched_fields": None, "total_fields": None,
        "match_percent": None,  "weighted_percent": None,
        "description_similarity": None,
        "comparison_result": None,
        "gudid_record": gudid_record,
        "gudid_di": di,
        "gudid_record_status": record_status,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    result["gudid_deactivated"] = result.get("gudid_deactivated", 0) + 1
    continue   # No merge — stale GUDID shouldn't overwrite live device fields.
```

Deactivated records do **not** populate `verified_devices` and do **not** trigger `_merge_gudid_into_device()`.

**Harvested data for the deactivated banner:** the review route already calls `get_discrepancy_detail(validation_id)` which fetches both the `validationResult` and the associated `device` document by `device_id`. No `device_snapshot` is stored on the validationResult — the existing fetch-by-`device_id` path provides the harvested values the §6 banner renders. Single source of truth (the `devices` collection) is preserved; no duplication in the validationResult document.

**(b) Scoring rewrite** (replacing lines ~383–403):
```python
per_field, summary = compare_records(device, gudid_record)

matched_fields = summary["unweighted_numerator"]
total_fields = summary["unweighted_denominator"]
match_percent = round((matched_fields / total_fields) * 100, 2) if total_fields else 0.0
weighted_percent = round((summary["numerator"] / summary["denominator"]) * 100, 2) if summary["denominator"] else 0.0

if total_fields == 0:
    status = "mismatch"
elif matched_fields == total_fields:
    status = "matched"
elif matched_fields > 0:
    status = "partial_match"
else:
    status = "mismatch"
```

Status still derives from unweighted. `weighted_percent` is stored alongside and drives the dashboard default sort.

**(c) `MERGE_FIELDS` extended** with Layer-2 additions (§4).

**(d) Counters on the run result** — `gudid_deactivated` added alongside `full_matches` / `partial_matches` / `mismatches` / `gudid_not_found`. Dashboard `get_dashboard_stats()` gains a "Deactivated" tile.

**(e) Harvest-gap observability** — after `compare_records()` returns and before the `validationResults` insert, emit INFO-level logs when GUDID has data the harvester didn't capture:
```python
if gudid_record.get("productCodes") and not device.get("productCodes"):
    logger.info("[harvest-gap] device %s (%s): GUDID productCodes=%r, harvested=null",
                device.get("_id"), device.get("brandName"), gudid_record["productCodes"])
    result["harvest_gap_product_codes"] = result.get("harvest_gap_product_codes", 0) + 1

if gudid_record.get("premarketSubmissions") and not device.get("premarketSubmissions"):
    logger.info("[harvest-gap] device %s (%s): GUDID premarketSubmissions=%r, harvested=null",
                device.get("_id"), device.get("brandName"), gudid_record["premarketSubmissions"])
    result["harvest_gap_premarket"] = result.get("harvest_gap_premarket", 0) + 1
```

Purpose: the subset-match rules return `not_compared` when harvested is empty (per Q5/§4 semantics), which silently masks extraction misses. Counters + per-device log lines let us quantify harvester-extraction gaps in the run summary without adding UI surface yet. The counts appear on the run-result dict for inclusion in the batch result JSON.

**(e) `verified_devices` unchanged** — a device that matches on companyName via `corporate_alias` plus everything else still scores `matched` (alias counts +1/+1) and flows into `verified_devices` normally. The `comparison_result` on the `validationResults` document preserves `alias_group` for audit.

### 4. GUDID client + Layer 2 fields

Eight new GUDID fields fetched by `fetch_gudid_record()` in `gudid_client.py`, stored on the device document via `MERGE_FIELDS`, and (except where noted) compared in `compare_records()`.

**Defensive extraction pattern** — mandatory for all new paths. The April 8 validator crash was a null-intermediate bug (`device.get("environmentalConditions", {}).get("storageHandling")` crashing when the key was present but null). Every new path must use the `or`-fallback unwrap, never the two-argument `.get()` default:

```python
# CORRECT — handles missing key, null value, and wrong type
gmdn_terms = device.get("gmdnTerms") or {}
gmdn_list = gmdn_terms.get("gmdn") or []
gmdn_pt_name = gmdn_list[0].get("gmdnPTName") if gmdn_list else None

# INCORRECT — crashes when gmdnTerms key exists but is null
gmdn_pt_name = device.get("gmdnTerms", {}).get("gmdn", [{}])[0].get("gmdnPTName")
```

**Path verification before coding** — as the first task of the implementation plan, query Atlas (or pull from the validationResults collection's stored `gudid_record` snapshots) for 5–10 real GUDID responses. Print the resolved values for each of the eight paths below. Confirm the actual JSON shape matches the spec. Adjust any path that doesn't resolve, and document the real shape in the implementation plan before any new-field code is written.

**Unit tests for every path** must cover four input cases:
1. Happy path — all intermediates present, terminal value resolves
2. Missing key — `device.get("gmdnTerms") is None`
3. Null intermediate — `device.get("gmdnTerms")` returns `{"gmdn": None}` or `{"gmdn": []}`
4. Unexpected type — e.g., `gmdn` is a dict instead of a list

All four paths return `None` without crashing.

| Field | GUDID path | Storage | Compared? | Compare strategy | Weight |
|---|---|---|---|---|---|
| `gmdnPTName` | `device.gmdnTerms.gmdn[0].gmdnPTName` | string | Yes | Normalized case-fold exact | 3 |
| `gmdnCode` | `device.gmdnTerms.gmdn[0].gmdnCode` | string | Yes | Exact | 2 |
| `productCodes` | `device.productCodes.fdaProductCode[].productCode` | `list[str]` | Yes | `set(harvested) ⊆ set(gudid)` → match | 3 |
| `deviceCountInBase` | `device.deviceCountInBase` | int | Yes | Integer equality | 2 |
| `publishDate` | `device.publishDate` (fallback: `device.devicePublishDate`) | ISO date | No — metadata | — | — |
| `deviceRecordStatus` | `device.deviceRecordStatus` | string | No — drives §3 short-circuit | — | — |
| `issuingAgency` | `device.identifiers.identifier[0].issuingAgency` | string | Yes | Exact | 2 |
| `lotBatch` | `device.identifiers.identifier[0].lotBatch` | bool | Yes | `normalize_boolean`, null-asymmetric | 1 |
| `serialNumber` | `device.identifiers.identifier[0].serialNumber` | bool | Yes | `normalize_boolean`, null-asymmetric | 1 |
| `manufacturingDate` | `device.identifiers.identifier[0].manufacturingDate` | bool | Yes | `normalize_boolean`, null-asymmetric | 1 |
| `expirationDate` | `device.identifiers.identifier[0].expirationDate` | bool | Yes | `normalize_boolean`, null-asymmetric | 1 |

**Set-compare rules** for `productCodes` and (Layer 3) `premarketSubmissions`:
- Both empty → `both_null`
- Harvested empty, GUDID non-empty → `not_compared` (manufacturer doesn't have to advertise every GUDID-assigned code)
- Harvested present, GUDID empty → `mismatch`
- Both present, `set(harvested) ⊆ set(gudid)` → `match`
- Both present, harvested has elements not in GUDID → `mismatch`

Both rules flag the manufacturer claiming something GUDID doesn't confirm, while tolerating GUDID having additional codes/clearances not advertised on the page.

**`MERGE_FIELDS` additions:**
```python
MERGE_FIELDS += [
    "gmdnPTName", "gmdnCode", "productCodes",
    "deviceCountInBase",
    "publishDate", "deviceRecordStatus",
    "issuingAgency",
    "lotBatch", "serialNumber", "manufacturingDate", "expirationDate",
]
```

**`COMPARED_FIELDS` additions** (ordered by weight, in `app/routes/review.py`):
```python
COMPARED_FIELDS += [
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

**Review-page metadata** (not compared, not in `COMPARED_FIELDS`): `publishDate` renders as a new "GUDID Updated" tile in the stats grid; `deviceRecordStatus` is only shown when value is not `"Published"`.

### 5. Harvester additions — Layer 3

Four new extractions. `indicationsForUse`, `contraindications`, `deviceClass` go through the LLM; `premarketSubmissions` moves from LLM to regex.

**`PAGE_FIELDS_SCHEMA` additions** in `harvester/src/pipeline/llm_extractor.py`:
```python
"indicationsForUse":  {"type": ["string", "null"]},
"contraindications":  {"type": ["string", "null"]},
"deviceClass":        {"type": ["string", "null"], "enum": ["I", "II", "III", None]},
# REMOVED: premarketSubmissions (moved to regex in regulatory_parser.py)
```

**`PAGE_FIELDS_PROMPT` additions** (appended to existing rules, `premarketSubmissions` rule deleted):
```
- indicationsForUse: Copy the "Indications for Use" section verbatim as free text.
  Typically appears as a paragraph near the top of the page. null if not present.
- contraindications: Copy the "Contraindications" section verbatim as free text.
  null if not present.
- deviceClass: FDA device class ("I", "II", or "III") if explicitly stated on the page.
  null if not stated. Only return one of those three literal values.
```

Schema post-validation already null-strips invalid enum values.

**`regulatory_parser.py` — new function with keyword-context hardening:**

The raw pattern `\b(K\d{6,7}|P\d{6}|DEN\d{6})\b` false-positives on catalog numbers that happen to start with `K` followed by 6–7 digits (e.g., a SKU like `K1234567` on a product page). Hardening approach: require a regulatory keyword within ±30 characters of each match.

```python
_PREMARKET_RE = re.compile(r"\b(K\d{6,7}|P\d{6}|DEN\d{6})\b")
_REG_KEYWORDS = re.compile(
    r"510\s*\(\s*k\s*\)|premarket|\bPMA\b|FDA\s+clearance|K[- ]number|cleared\s+by\s+FDA",
    re.IGNORECASE,
)

def extract_premarket_submissions(text: str | None) -> list[str] | None:
    """Extract K-numbers, PMA numbers, DEN-numbers that appear within ±30 chars
    of a regulatory keyword (510(k), premarket, PMA, FDA clearance, K-number,
    cleared by FDA). Returns sorted deduplicated list, or None."""
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

**Negative-case tests required:**
- `"K1234567 STENT VISI PRO"` (catalog-like, no regulatory keyword) → extracts nothing
- `"510(k) clearance K123456"` → extracts `["K123456"]`
- `"Cleared by FDA under K123456 and K789012"` → extracts both
- `"PMA P210034"` → extracts `["P210034"]`
- `"Product code K1234567 in our catalog"` (explicitly non-regulatory context, the word "Product code" shouldn't count as a keyword) → extracts nothing
- Multiple matches near one keyword — the window check is per-match, so each match needs its own nearby keyword

**Wiring** in `llm_extractor.extract_all_fields()` (line 434 of `harvester/src/pipeline/llm_extractor.py`): after `extract_page_fields()` returns, concatenate `warning_text + " " + description + " " + indicationsForUse` and run `extract_premarket_submissions()` over the result. Attach as `premarketSubmissions` on each record before returning. The regex path owns this field end-to-end — the LLM no longer sees the field name in the schema.

**Storage:** `indicationsForUse`, `contraindications`, `deviceClass` stored on the device document, rendered on the review page in a new "Additional Information" panel beneath the comparison table. Not compared, not in `COMPARED_FIELDS`.

**`premarketSubmissions` comparison** — added to `COMPARED_FIELDS` with weight 2, using the same subset-match rules as `productCodes` (§4).

**Explicitly NOT doing in Layer 3:**
- `deviceClass` not compared against GUDID (harvest-only per constraint; GUDID also has it, but comparison is out of scope for this pass).
- No changes to `PRODUCT_ROWS_SCHEMA` or `PRODUCT_ROWS_PROMPT`.
- No changes to the parallel-batch flow, per-provider semaphores, or thread-local patterns.

### 6. Review UI state design

Status → visual mapping in `app/templates/review.html` and `app/static/css/styles.css`.

| `FieldStatus` | Badge | Color token | Picker shown? | Default selection |
|---|---|---|---|---|
| `match` | `MATCH` | `--success` | No — "Matched" text | harvested (locked) |
| `mismatch` | `MISMATCH` | `--danger` | Yes | harvested |
| `corporate_alias` | `ALIAS → {alias_group}` | `--info` (new) | No — "Matched via alias" | harvested (locked) |
| `both_null` | `NO DATA` | `--muted` | No — informational | n/a |
| `not_compared` | `NOT COMPARED` | `--muted` | Yes | harvested |
| `sku_label_skip` | `GUDID IS SKU LABEL` | `--warning` | No — informational | n/a |

**New CSS classes** in `app/static/css/styles.css`:
```css
.match-status { display: inline-block; padding: 2px 8px; border-radius: 4px;
                font-size: 10px; font-weight: 700; letter-spacing: .06em; }
.match-status.alias     { background: var(--info-bg);    color: var(--info);    }
.match-status.both-null { background: var(--muted-bg);   color: var(--muted);   }
.match-status.sku-skip  { background: var(--warning-bg); color: var(--warning); }
.review-field-row.informational { opacity: 0.7; }
```

New color token pair `--info` / `--info-bg` (blue tones). The `--muted-bg` and `--warning-bg` pairs already exist.

**Template changes in `review.html`:**
- Per-row badge block (current lines 98–107) becomes an `{% if/elif %}` chain keyed on `f.status`.
- Radio picker block (current lines 118–131) gates on `f.status in ("mismatch", "not_compared")`; other statuses render read-only.
- `deviceDescription` keeps its `% similar` display but only when `status == "match"`.

**`gudid_deactivated` banner** at top of `review.html` when `validation.status == "gudid_deactivated"`:
```html
<div class="banner banner-warning">
    <strong>GUDID record deactivated.</strong>
    The FDA has deactivated this device's GUDID entry ({{ validation.gudid_di }},
    last published {{ validation.gudid_record.publishDate }}). The harvested data
    below is the live source — no per-field comparison was run.
</div>
```

Below the banner: a read-only two-column harvested table (mirrors the existing `mode="info"` layout).

**`publishDate` row** in the existing stats grid alongside "GUDID DI":
```html
<div class="metric-card small">
    <p class="metric-label">GUDID Updated</p>
    <h3 class="metric-value mono">{{ validation.gudid_record.publishDate or "N/A" }}</h3>
</div>
```

**Dashboard (`dashboard.html`) changes:**
- New "Deactivated" metric card (non-filterable for this pass), styled with `--warning`.
- Weighted-score column added to the discrepancy table alongside the existing unweighted column. **Default sort remains unweighted** — changing the default right before the capstone demo is a user-visible behavior shift that should ship deliberately. The flip to weighted-desc is flagged as a follow-up in the changelog and deferred to a post-demo pass.

**`review.py` route changes** — `COMPARED_FIELDS` grows per §4. `fields` list-comprehension reads `f.status` and `f.alias_group` into the template context. Legacy fallback for old validationResults documents derives `status` from the legacy `match` key as described in §1.

### 7. Testing

**New + extended test files:**

| File | Scope |
|---|---|
| `harvester/src/validators/tests/test_company_aliases.py` (new) | `canonical_company()`: exact, case-fold, suffix strip, whitespace, punctuation, no-match. One parametrized test per seed group. |
| `harvester/src/validators/tests/test_description_quality.py` (new) | `_gudid_description_is_sku_label()` across 12 handcrafted fixtures: 3 real-prose → False, 3 short (<40) → True, 3 contains-model-number → True, 3 all-uppercase → True. |
| `harvester/src/validators/tests/test_comparison_validator.py` (extend) | Per-field transitions for `both_null`, `corporate_alias`, `sku_label_skip`. Weighted-score math. Subset-match rules for `productCodes` and `premarketSubmissions`. Assertions updated from `.get("match")` to `.get("status")`. |
| `harvester/src/validators/tests/test_comparison_new_fields.py` (new) | Each Layer-2 compared field: happy path + mismatch + null-asymmetric + both-null. |
| `harvester/src/validators/tests/test_orchestrator_deactivated.py` (new) | `run_validation()` short-circuit on `deviceRecordStatus == "Deactivated"`. Asserts `status == "gudid_deactivated"`, no comparison, no merge, no verified_devices. |
| `harvester/src/pipeline/tests/test_regulatory_parser.py` (extend or new) | `extract_premarket_submissions()`: K6/K7, P6, DEN6, mixed text, dedup, sort, empty → None. |
| `harvester/src/pipeline/tests/test_llm_extractor_schema.py` (extend or new) | Three new string fields accepted; `deviceClass` enum rejects non-I/II/III strings → null; `premarketSubmissions` no longer in schema. |

**Integration test** — `tests/test_pxb35_integration.py` with two fixtures in `tests/fixtures/`:
- `pxb35_harvested.json` — serialized device record
- `pxb35_gudid_response.json` — hand-built GUDID response reflecting the real record's quirks (SKU-as-description, corporate alias on companyName)

Asserts:
- `companyName.status == "corporate_alias"`, `alias_group` is the expected canonical parent
- `deviceDescription.status == "sku_label_skip"`
- `brandName.status == "match"` after trademark normalization
- Unweighted and weighted percentages come out to specific expected numbers

**Regression gate:** full pytest suite (407+ tests) passes. Existing `test_comparison_validator.py` assertions migrate from `match` to `status` as part of the status-model task.

**Manual end-to-end smoke test** at implementation close:
1. `docker compose up`, log in, change password.
2. Upload `sample_urls.txt` on Harvester, wait for completion.
3. Run validation. Confirm at least one record exhibits each new status type.
4. Open a `matched`, a `partial_match`, and a `gudid_deactivated` record (if produced). Confirm UI states render per §6.
5. Confirm CSP, CSRF, and security headers still pass.
6. Confirm `POST /review/<id>/save` still 403s without a CSRF token.

---

## Non-Goals

- No changes to the parallel-batch flow, per-provider semaphores (`OLLAMA=1`, `GROQ=3`, `NVIDIA=4`), `threading.local()` for `_last_model_used`, or locked `_disabled_models` set.
- No changes to the 5-model LLM fallback chain.
- No changes to the 3-phase orchestrator structure (scrape → extract → validate).
- No changes to Docker compose layout, port 8500, CSRF middleware, SecurityHeadersMiddleware.
- No migration of existing `validationResults` documents — old documents retain the legacy `match` shape until revalidated. Migration is **forward-only**; no rollback path.
- No `deviceClass` GUDID comparison (harvest-only).
- No `PRODUCT_ROWS_SCHEMA` / `PRODUCT_ROWS_PROMPT` changes.
- No default dashboard sort change (stays unweighted; weighted column added but non-default).
- No changes to `AUTH_SECRET_KEY` / `.env` / port-8000 doc references / API key rotation / `.env.example` drift — all four are known open items tracked separately for an operational cleanup branch.

## Deferred — flag in changelog for post-demo pass

- Default dashboard sort flip to weighted-desc.
- Any UI surface for the `harvest_gap_*` counters (currently logs-only).
- Expanded `COMPANY_ALIASES` seed list beyond the six initial groups (Medtronic, Boston Scientific, BD, Abbott, J&J, Stryker). The alias map is intentionally conservative for this pass; additions belong in a follow-up that can draw from observed mismatches in the production data.

---

## Files Changed

| File | Change |
|---|---|
| `harvester/src/validators/company_aliases.py` | **New** — alias map + `canonical_company()` |
| `harvester/src/validators/comparison_validator.py` | New `FieldStatus` enum, `FIELD_WEIGHTS`, alias check, both-null check, description quality classifier, return shape `(per_field, summary)`, weighted scoring |
| `harvester/src/validators/gudid_client.py` | Fetch 8 new GUDID fields, new `productCodes` array + identifier-booleans extraction |
| `harvester/src/normalizers/text.py` | Extend `clean_brand_name()`: add `℠`, smart quotes to stripped set |
| `harvester/src/orchestrator.py` | Deactivated short-circuit, scoring rewrite using summary dict, `MERGE_FIELDS` extended, new result counter |
| `harvester/src/pipeline/llm_extractor.py` | Three new schema fields, three new prompt rules, `premarketSubmissions` removed from schema + prompt |
| `harvester/src/pipeline/regulatory_parser.py` | New `extract_premarket_submissions()` regex function |
| `harvester/src/pipeline/llm_extractor.py` (`extract_all_fields`) | Wire `extract_premarket_submissions()` in after `extract_page_fields()` returns |
| `app/routes/review.py` | `COMPARED_FIELDS` extended (9 entries), template context reads `status` + `alias_group`, legacy `match` fallback |
| `app/routes/dashboard.py` | Expose deactivated count + weighted-score column |
| `app/templates/review.html` | Status-keyed badge chain, informational-row styling, deactivated banner, publishDate tile, "Additional Information" panel for harvest-only Layer-3 fields |
| `app/templates/dashboard.html` | "Deactivated" metric card + weighted-score column |
| `app/static/css/styles.css` | New `--info` / `--info-bg` tokens, `.match-status.*` badge classes, `.review-field-row.informational` |
| `harvester/src/validators/tests/test_company_aliases.py` | **New** |
| `harvester/src/validators/tests/test_description_quality.py` | **New** |
| `harvester/src/validators/tests/test_comparison_validator.py` | Extend — new states, weighted math, subset-match |
| `harvester/src/validators/tests/test_comparison_new_fields.py` | **New** — Layer-2 field compare logic |
| `harvester/src/validators/tests/test_orchestrator_deactivated.py` | **New** — deactivated short-circuit |
| `harvester/src/pipeline/tests/test_regulatory_parser.py` | Extend — premarket regex |
| `harvester/src/pipeline/tests/test_llm_extractor_schema.py` | Extend or new — schema field additions + removal |
| `tests/fixtures/pxb35_harvested.json` | **New** |
| `tests/fixtures/pxb35_gudid_response.json` | **New** |
| `tests/test_pxb35_integration.py` | **New** — end-to-end compare against fixtures |
| `harvester/src/validators/CLAUDE.md` | Update scoring section: 16 compared fields, new status enum, weighted scoring, alias map |
| `harvester/src/pipeline/CLAUDE.md` | Note regex-based premarket extraction, three new LLM fields |
| `CLAUDE.md` (root) | Update Validation Scoring section: new field count, weighted score, deactivated short-circuit |
| `Senior Project/Changelogs/Changelog - 2026-04-22.md` (Obsidian vault) | **New** — session writeup matching April 20/21 format |
