# GUDID Field Expansion & Fallback Merge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract 7 new fields from manufacturer pages and fill null harvested fields with GUDID values during validation.

**Architecture:** Regex patterns added to `regulatory_parser.py` for 4 boolean fields; 3 semantic fields added to LLM schema/prompt; `runner.py` gets a passthrough set for non-string LLM fields; `emitter.py` passes new fields through; `gudid_client.py` returns the full merge field set; `orchestrator.py` merges GUDID values into null device fields after comparison.

**Tech Stack:** Python 3.13, pymongo, requests, pytest

---

## File Map

| File | Change |
|------|--------|
| `harvester/src/pipeline/regulatory_parser.py` | Add 4 regex pattern sets + parse logic |
| `harvester/src/pipeline/tests/test_regulatory_parser.py` | Add tests for new patterns |
| `harvester/src/pipeline/llm_extractor.py` | Expand PAGE_FIELDS_SCHEMA, PAGE_FIELDS_PROMPT, extract_all_fields |
| `harvester/src/pipeline/runner.py` | Add PASSTHROUGH_FIELDS to normalize_record |
| `harvester/src/pipeline/emitter.py` | Add new fields to package_gudid_record loop |
| `harvester/src/pipeline/tests/test_emitter.py` | Add tests for new fields passthrough |
| `harvester/src/validators/gudid_client.py` | Expand fetch_gudid_record return dict |
| `harvester/src/orchestrator.py` | Add MERGE_FIELDS + _merge_gudid_into_device, call in run_validation |

---

## Task 1: Extend regulatory_parser with 4 new boolean patterns

**Files:**
- Modify: `harvester/src/pipeline/regulatory_parser.py`
- Modify: `harvester/src/pipeline/tests/test_regulatory_parser.py`

- [ ] **Step 1: Write the failing tests**

Add to `harvester/src/pipeline/tests/test_regulatory_parser.py`:

```python
class TestLabeledContainsNRL:
    def test_contains_natural_rubber_latex(self):
        result = parse_regulatory_from_text("This device contains natural rubber latex.")
        assert result["labeledContainsNRL"] is True

    def test_made_with_natural_rubber_latex(self):
        result = parse_regulatory_from_text("Made with natural rubber latex.")
        assert result["labeledContainsNRL"] is True

    def test_contains_latex(self):
        result = parse_regulatory_from_text("Warning: contains latex components.")
        assert result["labeledContainsNRL"] is True

    def test_no_nrl_text_does_not_set_field(self):
        result = parse_regulatory_from_text("Single use only. Rx only.")
        assert "labeledContainsNRL" not in result


class TestLabeledNoNRL:
    def test_latex_free(self):
        result = parse_regulatory_from_text("This device is latex-free.")
        assert result["labeledNoNRL"] is True

    def test_latex_free_no_hyphen(self):
        result = parse_regulatory_from_text("Latex free packaging.")
        assert result["labeledNoNRL"] is True

    def test_does_not_contain_nrl(self):
        result = parse_regulatory_from_text("Does not contain natural rubber latex.")
        assert result["labeledNoNRL"] is True

    def test_not_made_with_nrl(self):
        result = parse_regulatory_from_text("Not made with natural rubber latex.")
        assert result["labeledNoNRL"] is True


class TestSterilizationPriorToUse:
    def test_sterilize_before_use(self):
        result = parse_regulatory_from_text("Sterilize before use.")
        assert result["sterilizationPriorToUse"] is True

    def test_must_be_sterilized(self):
        result = parse_regulatory_from_text("Must be sterilized before implantation.")
        assert result["sterilizationPriorToUse"] is True

    def test_requires_sterilization(self):
        result = parse_regulatory_from_text("Requires sterilization prior to use.")
        assert result["sterilizationPriorToUse"] is True

    def test_no_sterilization_text_does_not_set_field(self):
        result = parse_regulatory_from_text("Supplied sterile.")
        assert "sterilizationPriorToUse" not in result


class TestOTC:
    def test_over_the_counter(self):
        result = parse_regulatory_from_text("Available over the counter without a prescription.")
        assert result["otc"] is True

    def test_over_the_counter_hyphenated(self):
        result = parse_regulatory_from_text("This is an over-the-counter device.")
        assert result["otc"] is True

    def test_otc_abbreviation(self):
        result = parse_regulatory_from_text("OTC use only.")
        assert result["otc"] is True

    def test_without_a_prescription(self):
        result = parse_regulatory_from_text("Available without a prescription.")
        assert result["otc"] is True

    def test_rx_only_does_not_set_otc(self):
        result = parse_regulatory_from_text("Rx only.")
        assert "otc" not in result
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /mnt/c/Users/Jason/workspace/Fivos_Senior_Project
pytest harvester/src/pipeline/tests/test_regulatory_parser.py::TestLabeledContainsNRL harvester/src/pipeline/tests/test_regulatory_parser.py::TestLabeledNoNRL harvester/src/pipeline/tests/test_regulatory_parser.py::TestSterilizationPriorToUse harvester/src/pipeline/tests/test_regulatory_parser.py::TestOTC -v
```

Expected: All FAIL with `KeyError` or `AssertionError`.

- [ ] **Step 3: Add patterns and parse logic to regulatory_parser.py**

Replace the contents of `harvester/src/pipeline/regulatory_parser.py` with:

```python
"""Parse regulatory boolean fields from warning/precaution text.

Extracts GUDID-compatible fields from free-text warnings and precautions
found on manufacturer pages. Only produces results when patterns are matched.
"""

import re

_SINGLE_USE_PATTERNS = [
    re.compile(r"single[\s-]?use", re.IGNORECASE),
    re.compile(r"single\s+patient\s+use", re.IGNORECASE),
    re.compile(r"\bdisposable\b", re.IGNORECASE),
    re.compile(r"do\s+not\s+reuse", re.IGNORECASE),
    re.compile(r"not\s+(?:be\s+)?reused", re.IGNORECASE),
]

_RX_PATTERNS = [
    re.compile(r"federal\s+(?:\(usa\)\s+)?law.*?restricts.*?(?:physician|practitioner)", re.IGNORECASE),
    re.compile(r"\bprescription\s+(?:use\s+)?only\b", re.IGNORECASE),
    re.compile(r"\bRx\s+only\b", re.IGNORECASE),
]

_STERILE_PATTERNS = [
    re.compile(r"supplied\s+sterile", re.IGNORECASE),
    re.compile(r"contents\s+are\s*.*?\bsterile\b", re.IGNORECASE),
    re.compile(r"sterile[\s-]*packag", re.IGNORECASE),
    re.compile(r"provided\s+sterile", re.IGNORECASE),
]

_NRL_PRESENT_PATTERNS = [
    re.compile(r"contains\s+natural\s+rubber\s+latex", re.IGNORECASE),
    re.compile(r"made\s+with\s+natural\s+rubber\s+latex", re.IGNORECASE),
    re.compile(r"contains\s+latex", re.IGNORECASE),
]

_NRL_ABSENT_PATTERNS = [
    re.compile(r"latex[\s-]free", re.IGNORECASE),
    re.compile(r"does\s+not\s+contain\s+natural\s+rubber\s+latex", re.IGNORECASE),
    re.compile(r"not\s+made\s+with\s+natural\s+rubber\s+latex", re.IGNORECASE),
]

_STERILE_BEFORE_USE_PATTERNS = [
    re.compile(r"sterilize\s+before\s+use", re.IGNORECASE),
    re.compile(r"must\s+be\s+sterilized", re.IGNORECASE),
    re.compile(r"requires?\s+sterilization", re.IGNORECASE),
]

_OTC_PATTERNS = [
    re.compile(r"over[\s-]the[\s-]counter", re.IGNORECASE),
    re.compile(r"\bOTC\b"),
    re.compile(r"without\s+a\s+prescription", re.IGNORECASE),
]


def parse_regulatory_from_text(warning_text: str | None) -> dict:
    """Extract boolean GUDID fields from warning/precaution text.

    Returns dict like {"singleUse": True, "rx": True, ...}.
    Only includes fields actually found. Returns {} if nothing found.
    """
    if not warning_text or not warning_text.strip():
        return {}

    result = {}

    for pattern in _SINGLE_USE_PATTERNS:
        if pattern.search(warning_text):
            result["singleUse"] = True
            break

    for pattern in _RX_PATTERNS:
        if pattern.search(warning_text):
            result["rx"] = True
            break

    for pattern in _STERILE_PATTERNS:
        if pattern.search(warning_text):
            result["deviceSterile"] = True
            break

    for pattern in _NRL_PRESENT_PATTERNS:
        if pattern.search(warning_text):
            result["labeledContainsNRL"] = True
            break

    for pattern in _NRL_ABSENT_PATTERNS:
        if pattern.search(warning_text):
            result["labeledNoNRL"] = True
            break

    for pattern in _STERILE_BEFORE_USE_PATTERNS:
        if pattern.search(warning_text):
            result["sterilizationPriorToUse"] = True
            break

    for pattern in _OTC_PATTERNS:
        if pattern.search(warning_text):
            result["otc"] = True
            break

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest harvester/src/pipeline/tests/test_regulatory_parser.py -v
```

Expected: All PASS (including existing tests for singleUse, rx, deviceSterile).

- [ ] **Step 5: Commit**

```bash
git add harvester/src/pipeline/regulatory_parser.py harvester/src/pipeline/tests/test_regulatory_parser.py
git commit -m "feat: add NRL, sterilizationPriorToUse, OTC patterns to regulatory_parser"
```

---

## Task 2: Extend llm_extractor schema, prompt, and field propagation

**Files:**
- Modify: `harvester/src/pipeline/llm_extractor.py`

- [ ] **Step 1: Update PAGE_FIELDS_SCHEMA**

In `llm_extractor.py`, find the `PAGE_FIELDS_SCHEMA` dict and add 3 new properties inside `"properties"`:

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
        "premarketSubmissions": {
            "type": ["array", "null"],
            "items": {"type": "string"},
        },
        "environmentalConditions": {
            "type": ["object", "null"],
            "properties": {
                "storageTemperature": {"type": ["string", "null"]},
                "storageHumidity": {"type": ["string", "null"]},
            },
        },
    },
    "required": ["device_name", "manufacturer", "description"],
}
```

- [ ] **Step 2: Update PAGE_FIELDS_PROMPT**

Find `PAGE_FIELDS_PROMPT` and append 3 new field instructions after the `MRISafetyStatus` line:

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
- premarketSubmissions: A JSON array of FDA premarket submission numbers found on the page \
(e.g. ["K123456", "P210034"]). These start with K (510k) or P (PMA) followed by digits. \
null if none found.
- environmentalConditions: An object with storageTemperature and storageHumidity as strings \
including units (e.g. {{"storageTemperature": "15-30°C", "storageHumidity": "< 85% RH"}}). \
null if storage conditions are not stated on the page.

Page text:
{visible_text}"""
```

- [ ] **Step 3: Propagate new page-level fields through extract_all_fields**

In `extract_all_fields`, the current multi-product merge only copies 5 page-level fields. Add the 3 new ones. Find the `for product in products:` loop and update the `merged` dict construction:

```python
_PAGE_LEVEL_FIELDS = (
    "device_name", "manufacturer", "description", "warning_text",
    "MRISafetyStatus", "deviceKit", "premarketSubmissions", "environmentalConditions",
)

def extract_all_fields(visible_text: str, table_text: str | None = None, model: str | None = None) -> list[dict]:
    # Pass 1: page-level fields
    page_fields = extract_page_fields(visible_text)
    if page_fields is None:
        return []

    # Pass 2: product rows from table
    products = extract_product_rows(table_text or visible_text, page_fields.get("device_name", ""))

    source = get_last_model() or "unknown"

    if not products:
        page_fields["_description_source"] = source
        return [page_fields]

    records = []
    for product in products:
        merged = {field: page_fields.get(field) for field in _PAGE_LEVEL_FIELDS}
        merged["_description_source"] = source
        merged["model_number"] = product.get("model_number")
        merged["catalog_number"] = product.get("catalog_number")
        for dim in ("diameter", "length", "width", "height", "weight", "volume", "pressure"):
            val = product.get(dim)
            if val:
                merged[dim] = val
        records.append(merged)

    return records
```

- [ ] **Step 4: Run existing tests to confirm nothing is broken**

```bash
pytest harvester/src/pipeline/tests/ -v
```

Expected: All existing tests PASS. (No unit tests exist yet for llm_extractor directly — the schema/prompt changes are integration-level.)

- [ ] **Step 5: Commit**

```bash
git add harvester/src/pipeline/llm_extractor.py
git commit -m "feat: add deviceKit, premarketSubmissions, environmentalConditions to LLM extractor"
```

---

## Task 3: Add PASSTHROUGH_FIELDS to runner.py normalize_record

**Files:**
- Modify: `harvester/src/pipeline/runner.py`

**Why:** `normalize_record` has a fallback `else: normalize_text(value)`. Boolean, list, and dict fields from the LLM (deviceKit, premarketSubmissions, environmentalConditions) would be mangled by `normalize_text`. They need to pass through unchanged.

- [ ] **Step 1: Add PASSTHROUGH_FIELDS constant and update normalize_record**

In `runner.py`, after the existing field-type constants (TEXT_FIELDS, MODEL_FIELDS, etc.), add:

```python
PASSTHROUGH_FIELDS = {"deviceKit", "premarketSubmissions", "environmentalConditions", "_description_source"}
```

Then in `normalize_record`, add a branch before the final `else`:

```python
def normalize_record(raw_fields: dict, adapter: dict) -> dict:
    normalized = {}

    for field, value in raw_fields.items():
        if value is None:
            normalized[field] = None
            continue

        try:
            if field == "manufacturer":
                normalized[field] = _resolve_manufacturer(value, adapter)

            elif field in MODEL_FIELDS:
                normalized[field] = clean_model_number(value)

            elif field in DATE_FIELDS:
                normalized[field] = normalize_date(value)

            elif field in MEASUREMENT_FIELDS:
                normalized[field] = normalize_measurement(value)

            elif field == "device_name":
                normalized[field] = clean_brand_name(value)

            elif field in TEXT_FIELDS:
                normalized[field] = normalize_text(value)

            elif field in PASSTHROUGH_FIELDS:
                normalized[field] = value

            else:
                normalized[field] = normalize_text(value)

        except Exception as exc:
            logger.warning("normalize_record: failed on field '%s': %s", field, exc)
            normalized[field] = value
            normalized[f"raw_{field}"] = value

    return normalized
```

- [ ] **Step 2: Run pipeline tests**

```bash
pytest harvester/src/pipeline/tests/ -v
```

Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add harvester/src/pipeline/runner.py
git commit -m "feat: passthrough non-string LLM fields in normalize_record"
```

---

## Task 4: Update emitter.py to pass new fields through package_gudid_record

**Files:**
- Modify: `harvester/src/pipeline/emitter.py`
- Modify: `harvester/src/pipeline/tests/test_emitter.py`

- [ ] **Step 1: Write failing tests**

Add to `TestPackageGudidRecord` class in `harvester/src/pipeline/tests/test_emitter.py`:

```python
def test_labeled_contains_nrl_passed_through(self):
    record = {**SAMPLE_RECORD, "labeledContainsNRL": True}
    result = package_gudid_record(
        record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
    )
    assert result["labeledContainsNRL"] is True

def test_labeled_no_nrl_passed_through(self):
    record = {**SAMPLE_RECORD, "labeledNoNRL": True}
    result = package_gudid_record(
        record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
    )
    assert result["labeledNoNRL"] is True

def test_sterilization_prior_to_use_passed_through(self):
    record = {**SAMPLE_RECORD, "sterilizationPriorToUse": True}
    result = package_gudid_record(
        record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
    )
    assert result["sterilizationPriorToUse"] is True

def test_device_kit_passed_through(self):
    record = {**SAMPLE_RECORD, "deviceKit": True}
    result = package_gudid_record(
        record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
    )
    assert result["deviceKit"] is True

def test_premarket_submissions_passed_through(self):
    record = {**SAMPLE_RECORD, "premarketSubmissions": ["K123456", "P210034"]}
    result = package_gudid_record(
        record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
    )
    assert result["premarketSubmissions"] == ["K123456", "P210034"]

def test_environmental_conditions_passed_through(self):
    record = {**SAMPLE_RECORD, "environmentalConditions": {"storageTemperature": "15-30°C"}}
    result = package_gudid_record(
        record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
    )
    assert result["environmentalConditions"] == {"storageTemperature": "15-30°C"}
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest harvester/src/pipeline/tests/test_emitter.py::TestPackageGudidRecord::test_labeled_contains_nrl_passed_through harvester/src/pipeline/tests/test_emitter.py::TestPackageGudidRecord::test_device_kit_passed_through -v
```

Expected: FAIL — fields are not in the output.

- [ ] **Step 3: Update the regulatory field loop in emitter.py**

In `package_gudid_record`, find:

```python
for field in ("singleUse", "deviceSterile", "sterilizationPriorToUse", "rx", "otc"):
    if field in normalized_record:
        record[field] = normalized_record[field]
```

Replace with:

```python
for field in (
    "singleUse", "deviceSterile", "sterilizationPriorToUse", "rx", "otc",
    "labeledContainsNRL", "labeledNoNRL", "deviceKit",
    "premarketSubmissions", "environmentalConditions",
):
    if field in normalized_record:
        record[field] = normalized_record[field]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest harvester/src/pipeline/tests/test_emitter.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add harvester/src/pipeline/emitter.py harvester/src/pipeline/tests/test_emitter.py
git commit -m "feat: pass new fields through package_gudid_record in emitter"
```

---

## Task 5: Expand gudid_client.fetch_gudid_record to return full merge field set

**Files:**
- Modify: `harvester/src/validators/gudid_client.py`

- [ ] **Step 1: Add a storage conditions helper and update fetch_gudid_record**

Replace the contents of `harvester/src/validators/gudid_client.py` with:

```python
import requests
from bs4 import BeautifulSoup


SEARCH_URL = "https://accessgudid.nlm.nih.gov/devices/search"
LOOKUP_URL = "https://accessgudid.nlm.nih.gov/api/v3/devices/lookup.json"


def search_gudid_di(catalog_number=None, version_model_number=None):
    """Search the GUDID HTML search page to find a Device Identifier (DI)."""
    query = catalog_number or version_model_number
    if not query:
        return None

    response = requests.get(SEARCH_URL, params={"query": query}, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("/devices/"):
            di = href.split("/devices/")[-1].strip()
            if di.isdigit():
                return di

    return None


def _extract_storage_conditions(device: dict) -> dict | None:
    """Extract storage/handling conditions from GUDID device dict.

    Returns {"conditions": [...text strings...]} or None if empty.
    """
    handling = device.get("environmentalConditions", {}).get("storageHandling") or []
    texts = [
        item.get("specialConditionText", "").strip()
        for item in handling
        if item.get("specialConditionText", "").strip()
    ]
    return {"conditions": texts} if texts else None


def fetch_gudid_record(catalog_number=None, version_model_number=None):
    """Search for DI, then fetch structured device record from GUDID API.

    Returns (di, record_dict) where record_dict contains all MERGE_FIELDS,
    or (di, None) if device not found, or (None, None) if search fails.
    """
    di = search_gudid_di(
        catalog_number=catalog_number,
        version_model_number=version_model_number,
    )

    if not di:
        return None, None

    response = requests.get(LOOKUP_URL, params={"di": di}, timeout=15)
    response.raise_for_status()

    data = response.json()
    device = data.get("gudid", {}).get("device", {})

    if not device:
        return di, None

    sterilization = device.get("sterilization") or {}
    submissions = (
        device.get("premarketSubmissions", {}).get("premarketSubmission") or []
    )
    submission_numbers = [
        s["submissionNumber"] for s in submissions if s.get("submissionNumber")
    ]

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
        "deviceKit": device.get("deviceKit"),
        "premarketSubmissions": submission_numbers or None,
        "environmentalConditions": _extract_storage_conditions(device),
    }


def lookup_by_di(di):
    """Direct lookup by Device Identifier. Returns full device dict or None."""
    if not di:
        return None

    response = requests.get(LOOKUP_URL, params={"di": di}, timeout=15)
    response.raise_for_status()

    data = response.json()
    return data.get("gudid", {}).get("device")
```

- [ ] **Step 2: Run all validator tests**

```bash
pytest harvester/src/validators/tests/ -v
```

Expected: All PASS (existing record_validator tests unaffected).

- [ ] **Step 3: Commit**

```bash
git add harvester/src/validators/gudid_client.py
git commit -m "feat: expand fetch_gudid_record to return all merge fields"
```

---

## Task 6: Add GUDID fallback merge to orchestrator.run_validation

**Files:**
- Modify: `harvester/src/orchestrator.py`

- [ ] **Step 1: Add MERGE_FIELDS constant and _merge_gudid_into_device helper**

In `orchestrator.py`, after the imports and before the `_serialize_record` helper, add:

```python
MERGE_FIELDS = [
    "catalogNumber",
    "labeledContainsNRL", "labeledNoNRL",
    "sterilizationPriorToUse", "otc",
    "deviceKit",
    "premarketSubmissions",
    "environmentalConditions",
    "brandName", "versionModelNumber", "companyName", "deviceDescription",
    "MRISafetyStatus", "singleUse", "rx",
]


def _merge_gudid_into_device(db, device: dict, gudid_record: dict) -> list[str]:
    """Fill null device fields with GUDID values. Returns list of fields filled."""
    updates = {}
    filled = []
    for field in MERGE_FIELDS:
        if device.get(field) is None and gudid_record.get(field) is not None:
            updates[field] = gudid_record[field]
            filled.append(field)

    if updates:
        updates["gudid_sourced_fields"] = filled
        db["devices"].update_one(
            {"_id": device["_id"]},
            {"$set": updates},
        )

    return filled
```

- [ ] **Step 2: Call _merge_gudid_into_device in run_validation**

In `run_validation`, find the block that inserts the validation record. Add the merge call AFTER `compare_records` and AFTER the `validation_col.insert_one(...)` call, so the comparison records original harvested values:

```python
        comparison = compare_records(device, gudid_record)

        compared = {
            k: v for k, v in comparison.items()
            if k != "deviceDescription" and v.get("match") is not None
        }
        matched_fields = sum(1 for v in compared.values() if v["match"])
        total_fields = len(compared)
        match_percent = round((matched_fields / total_fields) * 100, 2) if total_fields > 0 else 0.0
        description_similarity = comparison.get("deviceDescription", {}).get("description_similarity", 0.0)

        if matched_fields == total_fields:
            status = "matched"
            result["full_matches"] += 1
        elif matched_fields > 0:
            status = "partial_match"
            result["partial_matches"] += 1
        else:
            status = "mismatch"
            result["mismatches"] += 1

        validation_col.insert_one({
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
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })

        # Fill null device fields from GUDID (runs after comparison to preserve original diff)
        _merge_gudid_into_device(db, device, gudid_record)
```

- [ ] **Step 3: Run all tests**

```bash
pytest harvester/src/ -v --ignore=harvester/src/pipeline/tests/test_pipeline_e2e.py
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add harvester/src/orchestrator.py
git commit -m "feat: fill null device fields from GUDID during validation (harvested-first merge)"
```

---

## Self-Review Checklist

- [x] **regulatory_parser.py** — 4 new pattern sets + parse blocks. Tests cover positive match, negative (no false positives on adjacent patterns).
- [x] **llm_extractor.py** — Schema, prompt, and `extract_all_fields` merge all updated. `_PAGE_LEVEL_FIELDS` tuple drives propagation to avoid repetition.
- [x] **runner.py** — `PASSTHROUGH_FIELDS` prevents `normalize_text` from mangling booleans/lists/dicts from LLM.
- [x] **emitter.py** — Extended field loop covers all 10 regulatory/semantic fields.
- [x] **gudid_client.py** — `fetch_gudid_record` returns 15 fields. `sterilizationPriorToUse` correctly unnested from `sterilization`. `premarketSubmissions` returns `None` (not `[]`) when empty so the merge treats it as missing.
- [x] **orchestrator.py** — Merge runs AFTER comparison insert, so the validation record captures original harvested vs GUDID diff. `gudid_sourced_fields` provides traceability.
- [x] **Type consistency** — `premarketSubmissions` is `string[] | None` throughout (harvester LLM returns strings, GUDID client extracts `submissionNumber` strings).
