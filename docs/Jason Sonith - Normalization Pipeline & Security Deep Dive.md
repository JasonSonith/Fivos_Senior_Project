# Jason Sonith — Normalization Pipeline & Security Deep Dive
## Fivos Harvester Agent | Data Pipeline & Security Lead

---

## 1. Role Summary

As the Data Pipeline & Security lead for the Fivos Harvester Agent, Jason sits at the critical junction between raw web data and clean, storage-ready records. Every piece of HTML that Wyatt's browser automation retrieves and that Ryan's site adapters target flows through Jason's extraction and normalization layer before reaching Ralph's MongoDB data lake. Jason is also responsible for all security considerations across the Harvester Agent, including credential management, input sanitization, and data integrity enforcement.

---

## 2. The Normalization Pipeline

### 2.1 Pipeline Architecture Overview

The normalization pipeline is a multi-stage process that transforms messy, inconsistent HTML from manufacturer websites into clean, structured device records that conform to a unified internal schema. The pipeline operates as a series of discrete, composable stages so that each step can be tested, debugged, and extended independently.

```
Raw Document (HTML / JSON / XML — from Wyatt)
       │
       ▼
┌─────────────────────┐
│  Stage 1: Parsing   │  ← parse_document(raw, fmt)
│  (Doc → Parsed Obj) │    BeautifulSoup / json / ElementTree
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stage 2: Extraction│  ← Uses Ryan's adapter selectors
│  (Raw Fields → Dict)│
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stage 3: Normalize │  ← Unit conversion, name standardization
│  (Dict → Clean Dict)│
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stage 4: Validate  │  ← Type checks, range checks, completeness
│  (Clean Dict → ✓/✗) │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stage 5: Emit      │  ← Pass to Ralph's storage layer
│  (✓ Dict → MongoDB) │
└─────────────────────┘
```

### 2.2 Stage 1 — Document Parsing

**Goal**: Convert raw input (HTML, JSON, or XML) into a structured, navigable object for targeted data extraction.

**Tools**: BeautifulSoup4 + lxml (HTML); `json` stdlib (JSON); `xml.etree.ElementTree` stdlib (XML). No new dependencies beyond what the project already uses.

**Format is explicit**: The caller (the adapter config) declares `format: html | json | xml`. There is no magic content-sniffing — this avoids silent misclassification bugs.

**Key Considerations**:
- Manufacturer pages often have malformed or inconsistent HTML. BeautifulSoup's lenient parser handles broken tags gracefully.
- Some pages use JavaScript-rendered content. By the time HTML reaches this stage, Wyatt's Playwright automation has already waited for JS execution.
- JSON responses from manufacturer REST APIs are parsed as plain dicts; top-level arrays or primitives return `{}` (not useful as a record root).
- XML legacy feeds are parsed with the stdlib `ElementTree`; malformed XML returns `None`.
- Every parser logs errors and returns a safe empty/`None` value rather than raising, consistent with the "never crash the run" philosophy.

**Implementation Details**:
```python
from bs4 import BeautifulSoup
import json
import xml.etree.ElementTree as ElementTree

def parse_html(raw: str) -> BeautifulSoup:
    """Parse raw HTML. Uses lxml; falls back to html.parser."""
    try:
        return BeautifulSoup(raw, "lxml")
    except Exception:
        return BeautifulSoup(raw, "html.parser")

def parse_json(raw: str) -> dict:
    """Parse a JSON string. Returns {} on any error."""
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}

def parse_xml(raw: str) -> ElementTree.Element | None:
    """Parse an XML string. Returns None on any error."""
    try:
        return ElementTree.fromstring(raw)
    except Exception:
        return None

def parse_document(raw: str, fmt: str):
    """Route raw content to the correct parser.

    fmt: "html" | "json" | "xml"
    Raises ValueError for unknown formats.
    """
    if fmt == "html":
        return parse_html(raw)
    if fmt == "json":
        return parse_json(raw)
    if fmt == "xml":
        return parse_xml(raw)
    raise ValueError(f"Unknown format '{fmt}'.")
```

### 2.3 Stage 2 — Field Extraction

**Goal**: Use format-appropriate selectors (provided by Ryan's site adapters) to pull specific data fields out of the parsed document object.

**How Adapters Feed In**: Ryan's adapter configs (YAML/JSON) declare a `format` key and an `extraction` block mapping field names to selectors appropriate for that format:

```yaml
# HTML adapter example
format: html
extraction:
  device_name: "h1.product-title"
  manufacturer: "span.manufacturer"

# JSON adapter example
format: json
extraction:
  device_name: "product.name"          # dot-notation path into nested dict
  length_mm: "product.specs.length"

# XML adapter example
format: xml
extraction:
  device_name: ".//product/name"       # XPath expression
  length_mm: ".//product/specs/length"
```

**Selector semantics by format**:
- **HTML** — CSS selector; `soup.select_one(selector).get_text(strip=True)`
- **JSON** — dot-notation path walker (e.g. `"product.dims.length"` → nested dict lookup); no extra dependencies
- **XML** — XPath expression via stdlib `ElementTree.Element.findtext(xpath)`

**Key Considerations**:
- Not every field will be present on every page. The extractor logs a warning, sets the field to `None`, and continues — consistent with "never crash the run".
- All values are returned as raw strings (or `None`); Stage 3 normalizers handle type conversion.

**Implementation Details**:
```python
def extract_fields(parsed_data, adapter: dict, fmt: str) -> dict:
    """Extract device fields using adapter-defined selectors.

    Args:
        parsed_data: BeautifulSoup (html), dict (json), or ElementTree.Element (xml).
        adapter: Adapter config with an "extraction" block.
        fmt: "html" | "json" | "xml"

    Returns a dict of field_name -> raw string value (or None if not found).
    """
    raw_fields = {}
    for field_name, selector in adapter.get("extraction", {}).items():
        value = _extract_one(parsed_data, selector, fmt)
        if value is None:
            logger.warning("Field '%s' not found with selector '%s' (fmt=%s)", field_name, selector, fmt)
        raw_fields[field_name] = value
    return raw_fields
```

### 2.4 Stage 3 — Normalization

**Goal**: Transform inconsistent raw values into a standardized, canonical format so that downstream consumers (the Validator Agent, Ralph's data lake, analytics) can compare data across manufacturers without ambiguity.

This is the most complex and important stage of the pipeline. Medical device data comes in wildly inconsistent formats across manufacturers, and the normalization layer must handle all of them.

#### 2.4.1 Unit Normalization

All physical measurements are converted to a single canonical unit per dimension:

| Dimension   | Canonical Unit | Common Variants Handled                 |
|-------------|----------------|-----------------------------------------|
| Length      | millimeters (mm) | cm, m, inches, in, ", ft              |
| Weight      | grams (g)      | kg, lbs, lb, oz, ounces                |
| Volume      | milliliters (mL)| L, liters, cc, fl oz, gallons          |
| Temperature | Celsius (°C)   | °F, Fahrenheit, Kelvin                  |
| Pressure    | mmHg           | kPa, psi, atm, bar                     |
| Electrical  | volts/amps (as-is) | mV, mA, µA (keep with prefix)      |

**Implementation Approach**:
```python
UNIT_CONVERSIONS = {
    "cm": ("mm", lambda x: x * 10),
    "m": ("mm", lambda x: x * 1000),
    "in": ("mm", lambda x: x * 25.4),
    "inches": ("mm", lambda x: x * 25.4),
    "ft": ("mm", lambda x: x * 304.8),
    "kg": ("g", lambda x: x * 1000),
    "lbs": ("g", lambda x: x * 453.592),
    "lb": ("g", lambda x: x * 453.592),
    "oz": ("g", lambda x: x * 28.3495),
    # ... etc
}

def normalize_measurement(raw_value: str) -> dict:
    """Parse a measurement string like '10 cm' into 
    {'value': 100.0, 'unit': 'mm'}."""
    match = re.match(r"([\d.]+)\s*([a-zA-Z°]+)", raw_value.strip())
    if not match:
        return {"value": None, "unit": None, "raw": raw_value}
    
    value = float(match.group(1))
    unit = match.group(2).lower().strip(".")
    
    if unit in UNIT_CONVERSIONS:
        canonical_unit, converter = UNIT_CONVERSIONS[unit]
        return {"value": round(converter(value), 4), "unit": canonical_unit}
    
    return {"value": value, "unit": unit}
```

#### 2.4.2 Manufacturer Name Standardization

Manufacturer names appear in many variants across the web. The normalizer maps all known variants to a single canonical name to ensure consistency in the data lake.

```python
MANUFACTURER_ALIASES = {
    "medtronic": "Medtronic plc",
    "medtronic plc": "Medtronic plc",
    "medtronic inc": "Medtronic plc",
    "medtronic, inc.": "Medtronic plc",
    "abbott": "Abbott Laboratories",
    "abbott laboratories": "Abbott Laboratories",
    "abbott labs": "Abbott Laboratories",
    "boston scientific": "Boston Scientific Corporation",
    "boston scientific corp": "Boston Scientific Corporation",
    "boston scientific corp.": "Boston Scientific Corporation",
    # ... expanded as new manufacturers are added
}

def normalize_manufacturer(raw_name: str) -> str:
    key = raw_name.strip().lower().rstrip(".")
    return MANUFACTURER_ALIASES.get(key, raw_name.strip())
```

#### 2.4.3 Date Normalization

Dates are converted to ISO 8601 format (`YYYY-MM-DD`) regardless of source format.

Common input formats handled: `MM/DD/YYYY`, `DD-Mon-YYYY`, `Month DD, YYYY`, `YYYY/MM/DD`, European `DD/MM/YYYY` (with heuristic detection).

#### 2.4.4 Model Number Cleaning

Model numbers are stripped of extraneous whitespace, normalized to uppercase, and common prefixes like "Model:", "Cat. No.", "REF" are removed to leave just the identifier.

#### 2.4.5 Text Field Cleaning

General text fields (device name, descriptions) go through:
- HTML entity decoding (`&amp;` → `&`)
- Unicode normalization (NFKC form)
- Whitespace collapsing (multiple spaces/tabs/newlines → single space)
- Leading/trailing whitespace removal
- Removal of invisible characters (zero-width spaces, etc.)

### 2.5 Stage 4 — Validation

**Goal**: Catch bad data before it enters the data lake. Every record must pass validation checks before being emitted to Ralph's storage layer.

**Validation Rules**:

| Check                   | Rule                                                    | On Failure         |
|-------------------------|---------------------------------------------------------|--------------------|
| Required fields present | `device_name`, `manufacturer`, `model_number` must not be None | Reject record      |
| Type correctness        | Numeric fields must parse as numbers                    | Flag for review    |
| Range plausibility      | Dimensions must be positive, weight must be positive    | Flag for review    |
| String length           | Device name between 2–500 chars, model number 1–100 chars | Flag for review  |
| Duplicate detection     | Same model_number + manufacturer combo already in batch | Merge or skip      |
| URL validity            | Source URL must be well-formed                          | Reject record      |

**Implementation Approach**:
```python
def validate_record(record: dict) -> tuple[bool, list[str]]:
    """Validate a normalized device record.
    
    Returns (is_valid, list_of_issues).
    """
    issues = []
    
    # Required fields
    for field in ["device_name", "manufacturer", "model_number"]:
        if not record.get(field):
            issues.append(f"REQUIRED_MISSING: {field}")
    
    # Numeric range checks
    dims = record.get("dimensions", {})
    for dim_key in ["length_mm", "width_mm", "height_mm"]:
        val = dims.get(dim_key)
        if val is not None and val <= 0:
            issues.append(f"INVALID_RANGE: {dim_key} = {val}")
    
    # String length checks
    name = record.get("device_name", "")
    if name and (len(name) < 2 or len(name) > 500):
        issues.append(f"STRING_LENGTH: device_name ({len(name)} chars)")
    
    is_valid = not any("REQUIRED_MISSING" in i for i in issues)
    return is_valid, issues
```

### 2.6 Stage 5 — Emit to Storage

Once a record passes validation, it is packaged with metadata and handed off to Ralph's storage functions.

**Metadata attached at this stage**:
- `harvest_run_id` (from Jonathan's run manager)
- `harvested_at` (UTC timestamp)
- `source_url` (the page URL)
- `adapter_version` (which version of Ryan's adapter was used)
- `normalization_version` (pipeline version, for traceability)
- `validation_issues` (any non-blocking warnings from Stage 4)

---

## 3. Security Responsibilities

### 3.1 Credential Management

Some manufacturer websites require authentication (e.g., professional portals, distributor-only catalogs). Jason is responsible for ensuring credentials are never exposed in code, logs, or version control.

**Approach**:
- All credentials stored in environment variables, loaded via `python-dotenv`.
- A `.env` file exists only on the deployment machine — **never committed to Git**.
- `.gitignore` explicitly includes `.env`, `.env.*`, `*.pem`, `*.key`.
- Credential access is centralized through a single `CredentialManager` class so that all credential reads go through one auditable path.

```python
import os
from dotenv import load_dotenv

load_dotenv()

class CredentialManager:
    """Centralized credential access. All secrets flow through here."""
    
    @staticmethod
    def get_credential(manufacturer: str, field: str) -> str | None:
        key = f"FIVOS_{manufacturer.upper()}_{field.upper()}"
        value = os.getenv(key)
        if value is None:
            logger.warning(f"Credential not found: {key}")
        return value
    
    @staticmethod
    def get_db_uri() -> str:
        return os.getenv("FIVOS_MONGO_URI", "mongodb://localhost:27017/fivos")
```

**Environment Variable Naming Convention**:
```
FIVOS_MEDTRONIC_USERNAME=...
FIVOS_MEDTRONIC_PASSWORD=...
FIVOS_ABBOTT_API_KEY=...
FIVOS_MONGO_URI=mongodb://...
FIVOS_SECRET_KEY=...
```

### 3.2 Input Sanitization

Raw HTML from the web is inherently untrusted. Before any processing, the pipeline applies sanitization to prevent injection attacks or corrupted data from propagating through the system.

**Sanitization Measures**:
- **Script stripping**: All `<script>`, `<iframe>`, and `<object>` tags are removed from HTML before parsing.
- **Attribute filtering**: Event handler attributes (`onclick`, `onerror`, etc.) are stripped.
- **SQL/NoSQL injection prevention**: All data passed to MongoDB uses parameterized queries via PyMongo — raw strings are never interpolated into query strings.
- **Path traversal prevention**: Any file paths derived from web data (e.g., for raw HTML storage references) are sanitized to remove `..`, `/`, and null bytes.

```python
import re
from bs4 import BeautifulSoup

def sanitize_html(raw_html: str) -> str:
    """Remove potentially dangerous HTML elements before processing."""
    soup = BeautifulSoup(raw_html, "lxml")
    
    # Remove dangerous tags entirely
    for tag in soup.find_all(["script", "iframe", "object", "embed", "form"]):
        tag.decompose()
    
    # Remove event handler attributes
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on"):
                del tag[attr]
    
    return str(soup)
```

### 3.3 Data Integrity & Audit Trail

Every record that flows through the pipeline is tagged with provenance metadata so that any data point in the data lake can be traced back to its source.

**Integrity Measures**:
- **Checksums**: A SHA-256 hash of the raw HTML is stored alongside each record, so the original source can be verified.
- **Immutable raw storage**: The original HTML is stored (by reference) in a raw storage layer. Normalized data never overwrites the raw source.
- **Pipeline versioning**: Each record carries a `normalization_version` field. If the normalization logic changes, historical records can be re-processed.
- **Audit logging**: Every extraction, normalization, and validation step logs its inputs and outputs (with sensitive fields redacted) for post-hoc debugging.

### 3.4 Rate Limiting & Anti-Ban Compliance

While Wyatt owns the browser automation, Jason enforces security-aware rate limiting at the pipeline level:
- Respecting `robots.txt` directives per manufacturer site.
- Configurable per-site delay defaults (2 seconds between requests, configurable up to 10 seconds for sensitive sites).
- User-Agent strings that honestly identify the Fivos system rather than spoofing real browsers.
- Immediate backoff on HTTP 429 (Too Many Requests) responses.

### 3.5 Dependency Security

- All Python dependencies pinned to exact versions in `requirements.txt`.
- Regular `pip audit` scans for known vulnerabilities in dependencies.
- Minimal dependency footprint — only libraries actually used are included.

### 3.6 HIPAA Awareness

Since Fivos operates in the medical device space and may eventually handle data adjacent to protected health information (PHI), the pipeline is designed with HIPAA-consciousness even though the current scope (publicly available device specs) does not involve PHI directly:
- No patient data is ever scraped or stored.
- Logging never includes credential values.
- Data at rest in MongoDB should be encrypted (coordination with Ralph).
- Network connections to manufacturer sites use HTTPS exclusively.

---

## 4. Key Interfaces with Other Team Members

| Interface                  | Direction              | Details                                              |
|----------------------------|------------------------|------------------------------------------------------|
| **Wyatt → Jason**          | HTML input             | Wyatt passes rendered page HTML to Jason's pipeline  |
| **Ryan → Jason**           | Adapter configs        | Ryan provides YAML/JSON selector configs per site    |
| **Jason → Ralph**          | Structured records     | Jason emits validated, normalized dicts to Ralph's DB layer |
| **Jonathan → Jason**       | Run context            | Jonathan provides `harvest_run_id` and logging hooks |
| **Jason → Jonathan**       | Pipeline metrics       | Jason reports extraction success/failure counts back |

---

## 5. Error Handling Strategy

The pipeline follows a "never crash the run" philosophy. Individual page failures should not halt an entire harvest run.

- **Parsing failures**: Log the error, store the raw HTML for manual review, skip to next page.
- **Extraction failures** (selector finds nothing): Log a warning per missing field, emit partial record if enough required fields are present.
- **Normalization failures** (unrecognized unit, unparseable value): Keep the raw value in a `raw_*` field alongside the normalized field (set to `None`), flag for review.
- **Validation failures**: Critical failures (missing required fields) → reject and log. Non-critical warnings → emit with `validation_issues` list attached.

---

## 6. Testing Strategy

- **Unit tests**: Each normalization function (unit conversion, name standardization, date parsing) has dedicated test cases covering edge cases.
- **Integration tests**: End-to-end tests using saved HTML snapshots from real manufacturer pages to verify the full pipeline produces expected output.
- **Regression tests**: When a manufacturer site changes and Ryan updates an adapter, the corresponding test snapshots are updated and the full pipeline is re-verified.
- **Fuzz testing**: Random/malformed HTML inputs to ensure the pipeline never crashes, only logs errors.
