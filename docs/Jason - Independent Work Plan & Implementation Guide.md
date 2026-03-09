## What You Can Build Right Now (No Teammates Needed)

---

## Overview

Your role as Data Pipeline & Security Lead sits at the center of the Harvester Agent, but the actual code you write is highly modular. Most of your pipeline stages operate on pure data transformations — strings in, structured dicts out — with no dependency on a running browser, a live database, or anyone else's code. This document breaks down exactly what you can build, test, and have production-ready before any teammate delivers their piece.

---

## 1. Unit Conversion Engine

**Why it's independent**: Unit conversion is pure math. You take a string like `"10 cm"` and return `{"value": 100.0, "unit": "mm"}`. No HTML, no database, no adapters needed.

**What to build**:

```python
# normalizers/units.py

import re

UNIT_CONVERSIONS = {
    # Length → millimeters
    "mm": ("mm", lambda x: x),
    "cm": ("mm", lambda x: x * 10),
    "m": ("mm", lambda x: x * 1000),
    "in": ("mm", lambda x: x * 25.4),
    "inches": ("mm", lambda x: x * 25.4),
    "inch": ("mm", lambda x: x * 25.4),
    '"': ("mm", lambda x: x * 25.4),
    "ft": ("mm", lambda x: x * 304.8),
    "feet": ("mm", lambda x: x * 304.8),
    "foot": ("mm", lambda x: x * 304.8),
    
    # Weight → grams
    "g": ("g", lambda x: x),
    "grams": ("g", lambda x: x),
    "kg": ("g", lambda x: x * 1000),
    "lbs": ("g", lambda x: x * 453.592),
    "lb": ("g", lambda x: x * 453.592),
    "oz": ("g", lambda x: x * 28.3495),
    "ounces": ("g", lambda x: x * 28.3495),
    
    # Volume → milliliters
    "ml": ("mL", lambda x: x),
    "l": ("mL", lambda x: x * 1000),
    "liters": ("mL", lambda x: x * 1000),
    "cc": ("mL", lambda x: x),  # 1 cc = 1 mL
    "fl oz": ("mL", lambda x: x * 29.5735),
    
    # Pressure → mmHg
    "mmhg": ("mmHg", lambda x: x),
    "kpa": ("mmHg", lambda x: x * 7.50062),
    "psi": ("mmHg", lambda x: x * 51.7149),
    "atm": ("mmHg", lambda x: x * 760),
    "bar": ("mmHg", lambda x: x * 750.062),
}

def normalize_measurement(raw_value: str) -> dict:
    """Parse a measurement string and convert to canonical units.
    
    Examples:
        '10 cm'     → {'value': 100.0, 'unit': 'mm'}
        '2.5 inches' → {'value': 63.5, 'unit': 'mm'}
        '0.5 kg'    → {'value': 500.0, 'unit': 'g'}
    """
    if not raw_value or not isinstance(raw_value, str):
        return {"value": None, "unit": None, "raw": raw_value}
    
    raw_value = raw_value.strip()
    
    # Handle range values like "10-15 mm" — take first value for now, flag it
    range_match = re.match(r"([\d.]+)\s*[-–—to]+\s*([\d.]+)\s*([a-zA-Z°\"]+)", raw_value)
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        unit = range_match.group(3).lower().strip(".")
        midpoint = round((low + high) / 2, 4)
        if unit in UNIT_CONVERSIONS:
            canonical_unit, converter = UNIT_CONVERSIONS[unit]
            return {
                "value": round(converter(midpoint), 4),
                "unit": canonical_unit,
                "is_range": True,
                "range_low": round(converter(low), 4),
                "range_high": round(converter(high), 4),
            }
    
    # Standard single-value match
    match = re.match(r"([\d.]+)\s*([a-zA-Z°\"]+)", raw_value)
    if not match:
        return {"value": None, "unit": None, "raw": raw_value}
    
    value = float(match.group(1))
    unit = match.group(2).lower().strip(".")
    
    if unit in UNIT_CONVERSIONS:
        canonical_unit, converter = UNIT_CONVERSIONS[unit]
        return {"value": round(converter(value), 4), "unit": canonical_unit}
    
    # Unknown unit — keep as-is, don't crash
    return {"value": value, "unit": unit, "raw": raw_value}
```

**Tests you can write immediately** (`tests/test_units.py`):

```python
import pytest
from normalizers.units import normalize_measurement

class TestLengthConversions:
    def test_cm_to_mm(self):
        result = normalize_measurement("10 cm")
        assert result["value"] == 100.0
        assert result["unit"] == "mm"
    
    def test_inches_to_mm(self):
        result = normalize_measurement("2.5 inches")
        assert result["value"] == 63.5
        assert result["unit"] == "mm"
    
    def test_already_mm(self):
        result = normalize_measurement("45 mm")
        assert result["value"] == 45.0
        assert result["unit"] == "mm"
    
    def test_feet_to_mm(self):
        result = normalize_measurement("1 ft")
        assert result["value"] == 304.8
        assert result["unit"] == "mm"

    def test_inch_symbol(self):
        result = normalize_measurement('6"')
        assert result["value"] == pytest.approx(152.4)
        assert result["unit"] == "mm"

class TestWeightConversions:
    def test_kg_to_g(self):
        result = normalize_measurement("0.5 kg")
        assert result["value"] == 500.0
        assert result["unit"] == "g"
    
    def test_lbs_to_g(self):
        result = normalize_measurement("1 lbs")
        assert result["value"] == pytest.approx(453.592)
        assert result["unit"] == "g"

class TestEdgeCases:
    def test_empty_string(self):
        result = normalize_measurement("")
        assert result["value"] is None
    
    def test_none_input(self):
        result = normalize_measurement(None)
        assert result["value"] is None
    
    def test_no_unit(self):
        result = normalize_measurement("42")
        assert result["value"] is None  # Can't normalize without a unit
    
    def test_unknown_unit(self):
        result = normalize_measurement("5 fathoms")
        assert result["value"] == 5.0
        assert result["unit"] == "fathoms"
        assert "raw" in result
    
    def test_range_value(self):
        result = normalize_measurement("10-15 mm")
        assert result["is_range"] is True
        assert result["range_low"] == 10.0
        assert result["range_high"] == 15.0
    
    def test_extra_whitespace(self):
        result = normalize_measurement("  10   cm  ")
        assert result["value"] == 100.0

    def test_decimal_precision(self):
        result = normalize_measurement("3.175 in")
        assert result["value"] == pytest.approx(80.645)
```

---

## 2. Manufacturer Name Aliasing

**Why it's independent**: This is a pure string lookup. No web scraping, no database. You're building a dictionary that maps messy real-world names to canonical forms.

**What to build — using the actual Target Brands from the project**:

The Target_Brands.xlsx file from Fivos lists these manufacturers for Batch-01:

| Manufacturer (from spreadsheet) | Brands |
|---|---|
| Medtronic | IN.PACT ADMIRAL, PROTEGE EVERFLEX, HAWKONE, EVERFLEX, IN.PACT, VISI-PRO, PROTEGE GPS, IN.PACT AV, RESOLUTE ONYX, SILVERHAWK, TURBOHAWK |
| Boston Scientific | RANGER, ELUVIA, INNOVA VASCULAR, EXPRESS LD BILIARY, JETSTREAM XC, EPIC VASCULAR, SYNERGY XD, FLEXTOME |
| Abbott Vascular | DIAMONDBACK PERIPHERAL, OMNILINK ELITE, ABSOLUTE PRO, DIAMONDBACK 360, SUPERA, SUPERA VERITAS, ESPRIT, XIENCE SKYPOINT |
| W L Gore & Associates | VIABAHN VBX, VIABAHN, TIGRIS VASCULAR STENT |
| Cook | ZILVER PTX, ZILVER 635, ZILVER 518, ZILVER FLEX 35 |
| Shockwave Medical | SHOCKWAVE M5, SHOCKWAVE E8, SHOCKWAVE S4, LITHOPLASTY, SHOCKWAVE L6 |
| Cordis | S.M.A.R.T. CONTROL, PALMAZ GENESIS |
| Terumo | R2P MISAGO |

Your alias map needs to handle all the ways these names appear in the wild:

```python
# normalizers/manufacturers.py

MANUFACTURER_ALIASES = {
    # Medtronic
    "medtronic": "Medtronic plc",
    "medtronic plc": "Medtronic plc",
    "medtronic inc": "Medtronic plc",
    "medtronic, inc": "Medtronic plc",
    "medtronic, inc.": "Medtronic plc",
    "medtronic usa": "Medtronic plc",
    "covidien": "Medtronic plc",  # Medtronic acquired Covidien in 2015
    
    # Boston Scientific
    "boston scientific": "Boston Scientific Corporation",
    "boston scientific corp": "Boston Scientific Corporation",
    "boston scientific corp.": "Boston Scientific Corporation",
    "boston scientific corporation": "Boston Scientific Corporation",
    "bsc": "Boston Scientific Corporation",
    
    # Abbott / Abbott Vascular
    "abbott": "Abbott Laboratories",
    "abbott laboratories": "Abbott Laboratories",
    "abbott labs": "Abbott Laboratories",
    "abbott vascular": "Abbott Laboratories",
    "abbott vascular inc": "Abbott Laboratories",
    "abbott vascular inc.": "Abbott Laboratories",
    
    # W. L. Gore & Associates
    "w l gore & associates": "W. L. Gore & Associates, Inc.",
    "w.l. gore": "W. L. Gore & Associates, Inc.",
    "w. l. gore": "W. L. Gore & Associates, Inc.",
    "wl gore": "W. L. Gore & Associates, Inc.",
    "gore": "W. L. Gore & Associates, Inc.",
    "gore & associates": "W. L. Gore & Associates, Inc.",
    "gore medical": "W. L. Gore & Associates, Inc.",
    
    # Cook
    "cook": "Cook Medical LLC",
    "cook medical": "Cook Medical LLC",
    "cook medical llc": "Cook Medical LLC",
    "cook inc": "Cook Medical LLC",
    "cook incorporated": "Cook Medical LLC",
    
    # Shockwave Medical
    "shockwave medical": "Shockwave Medical, Inc.",
    "shockwave medical inc": "Shockwave Medical, Inc.",
    "shockwave medical, inc.": "Shockwave Medical, Inc.",
    "shockwave": "Shockwave Medical, Inc.",
    
    # Cordis
    "cordis": "Cordis Corporation",
    "cordis corporation": "Cordis Corporation",
    "cordis corp": "Cordis Corporation",
    
    # Terumo
    "terumo": "Terumo Corporation",
    "terumo corporation": "Terumo Corporation",
    "terumo medical": "Terumo Corporation",
    "terumo interventional systems": "Terumo Corporation",
}

def normalize_manufacturer(raw_name: str) -> str:
    """Normalize a manufacturer name to its canonical form.
    
    Falls back to stripped original if no alias is found.
    """
    if not raw_name or not isinstance(raw_name, str):
        return raw_name
    key = raw_name.strip().lower().rstrip(".,")
    return MANUFACTURER_ALIASES.get(key, raw_name.strip())
```

**Tests** (`tests/test_manufacturers.py`):

```python
from normalizers.manufacturers import normalize_manufacturer

class TestManufacturerNormalization:
    def test_medtronic_variants(self):
        assert normalize_manufacturer("Medtronic") == "Medtronic plc"
        assert normalize_manufacturer("medtronic inc") == "Medtronic plc"
        assert normalize_manufacturer("MEDTRONIC") == "Medtronic plc"
        assert normalize_manufacturer("Medtronic, Inc.") == "Medtronic plc"
    
    def test_abbott_variants(self):
        assert normalize_manufacturer("Abbott Vascular") == "Abbott Laboratories"
        assert normalize_manufacturer("abbott labs") == "Abbott Laboratories"
    
    def test_gore_variants(self):
        assert normalize_manufacturer("W L Gore & Associates") == "W. L. Gore & Associates, Inc."
        assert normalize_manufacturer("Gore") == "W. L. Gore & Associates, Inc."
        assert normalize_manufacturer("W.L. Gore") == "W. L. Gore & Associates, Inc."
    
    def test_boston_scientific_variants(self):
        assert normalize_manufacturer("Boston Scientific") == "Boston Scientific Corporation"
        assert normalize_manufacturer("BSC") == "Boston Scientific Corporation"
    
    def test_cook_variants(self):
        assert normalize_manufacturer("Cook") == "Cook Medical LLC"
        assert normalize_manufacturer("Cook Medical") == "Cook Medical LLC"
    
    def test_shockwave_variants(self):
        assert normalize_manufacturer("Shockwave Medical") == "Shockwave Medical, Inc."
        assert normalize_manufacturer("Shockwave") == "Shockwave Medical, Inc."
    
    def test_unknown_manufacturer(self):
        assert normalize_manufacturer("Some New Company") == "Some New Company"
    
    def test_empty_input(self):
        assert normalize_manufacturer("") == ""
        assert normalize_manufacturer(None) is None
    
    def test_whitespace_handling(self):
        assert normalize_manufacturer("  Medtronic  ") == "Medtronic plc"
    
    def test_case_insensitive(self):
        assert normalize_manufacturer("BOSTON SCIENTIFIC") == "Boston Scientific Corporation"
        assert normalize_manufacturer("boston scientific") == "Boston Scientific Corporation"
```

---

## 3. Date Normalization

**Why it's independent**: Pure string parsing. Manufacturer websites use every date format imaginable, and you need them all in ISO 8601.

```python
# normalizers/dates.py

from datetime import datetime
import re

DATE_FORMATS = [
    "%m/%d/%Y",       # 01/15/2026
    "%m-%d-%Y",       # 01-15-2026
    "%Y-%m-%d",       # 2026-01-15 (already ISO)
    "%Y/%m/%d",       # 2026/01/15
    "%B %d, %Y",      # January 15, 2026
    "%b %d, %Y",      # Jan 15, 2026
    "%d %B %Y",       # 15 January 2026
    "%d %b %Y",       # 15 Jan 2026
    "%d-%b-%Y",       # 15-Jan-2026
    "%m/%d/%y",       # 01/15/26
    "%Y%m%d",         # 20260115
]

def normalize_date(raw_date: str) -> str | None:
    """Convert a date string to ISO 8601 format (YYYY-MM-DD).
    
    Tries multiple common formats. Returns None if unparseable.
    
    Examples:
        '01/15/2026'       → '2026-01-15'
        'January 15, 2026' → '2026-01-15'
        '15-Jan-2026'      → '2026-01-15'
    """
    if not raw_date or not isinstance(raw_date, str):
        return None
    
    cleaned = raw_date.strip()
    
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    return None
```

**Tests** (`tests/test_dates.py`):

```python
from normalizers.dates import normalize_date

class TestDateNormalization:
    def test_us_format(self):
        assert normalize_date("01/15/2026") == "2026-01-15"
    
    def test_iso_format_passthrough(self):
        assert normalize_date("2026-01-15") == "2026-01-15"
    
    def test_long_month_name(self):
        assert normalize_date("January 15, 2026") == "2026-01-15"
    
    def test_short_month_name(self):
        assert normalize_date("Jan 15, 2026") == "2026-01-15"
    
    def test_dashed_month(self):
        assert normalize_date("15-Jan-2026") == "2026-01-15"
    
    def test_european_day_first(self):
        assert normalize_date("15 January 2026") == "2026-01-15"
    
    def test_compact_format(self):
        assert normalize_date("20260115") == "2026-01-15"
    
    def test_unparseable(self):
        assert normalize_date("not a date") is None
    
    def test_empty(self):
        assert normalize_date("") is None
        assert normalize_date(None) is None
    
    def test_whitespace(self):
        assert normalize_date("  01/15/2026  ") == "2026-01-15"
```

---

## 4. Model Number Cleaning

**Why it's independent**: Another pure string operation. Strip prefixes, normalize whitespace, uppercase.

```python
# normalizers/model_numbers.py

import re

MODEL_PREFIXES = [
    r"model\s*[:.\-#]?\s*",
    r"cat\.?\s*no\.?\s*[:.\-#]?\s*",
    r"catalog\s*(?:number|no\.?|#)?\s*[:.\-#]?\s*",
    r"ref\.?\s*[:.\-#]?\s*",
    r"sku\s*[:.\-#]?\s*",
    r"part\s*(?:number|no\.?|#)?\s*[:.\-#]?\s*",
    r"item\s*(?:number|no\.?|#)?\s*[:.\-#]?\s*",
    r"p/?n\s*[:.\-#]?\s*",
]

def clean_model_number(raw_model: str) -> str | None:
    """Clean and normalize a model number string.
    
    Removes common prefixes, normalizes whitespace, uppercases.
    
    Examples:
        'Model: CS-2000X'  → 'CS-2000X'
        'REF 12345-AB'     → '12345-AB'
        'Cat. No. 9876'    → '9876'
        '  abc 123  '      → 'ABC 123'
    """
    if not raw_model or not isinstance(raw_model, str):
        return None
    
    cleaned = raw_model.strip()
    
    # Remove known prefixes (case-insensitive)
    for prefix_pattern in MODEL_PREFIXES:
        cleaned = re.sub(f"^{prefix_pattern}", "", cleaned, flags=re.IGNORECASE).strip()
    
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    
    # Uppercase
    cleaned = cleaned.upper()
    
    return cleaned if cleaned else None
```

**Tests** (`tests/test_model_numbers.py`):

```python
from normalizers.model_numbers import clean_model_number

class TestModelNumberCleaning:
    def test_model_prefix(self):
        assert clean_model_number("Model: CS-2000X") == "CS-2000X"
    
    def test_ref_prefix(self):
        assert clean_model_number("REF 12345-AB") == "12345-AB"
    
    def test_catalog_number(self):
        assert clean_model_number("Cat. No. 9876") == "9876"
    
    def test_sku_prefix(self):
        assert clean_model_number("SKU: WX-100") == "WX-100"
    
    def test_part_number(self):
        assert clean_model_number("Part Number 555-A") == "555-A"
    
    def test_uppercase(self):
        assert clean_model_number("abc-123x") == "ABC-123X"
    
    def test_whitespace_collapse(self):
        assert clean_model_number("  CS   2000  X  ") == "CS 2000 X"
    
    def test_no_prefix(self):
        assert clean_model_number("ZWP-100") == "ZWP-100"
    
    def test_empty(self):
        assert clean_model_number("") is None
        assert clean_model_number(None) is None
    
    def test_prefix_only(self):
        assert clean_model_number("Model:") is None
```

---

## 5. Text Field Cleaning

**Why it's independent**: Handles HTML entities, unicode weirdness, invisible characters. Pure text processing.

```python
# normalizers/text.py

import re
import html
import unicodedata

INVISIBLE_CHARS = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f"   # Zero-width spaces/joiners
    r"\u00ad"                              # Soft hyphen
    r"\ufeff"                              # BOM / zero-width no-break
    r"\u2060\u2061\u2062\u2063\u2064"      # Word joiner, invisible operators
    r"\u00a0"                              # Non-breaking space → replaced in whitespace step
    r"]"
)

def clean_text(raw_text: str) -> str | None:
    """Clean a general text field (device name, description, etc.).
    
    Steps:
    1. HTML entity decoding (&amp; → &)
    2. Unicode normalization (NFKC)
    3. Remove invisible characters
    4. Collapse whitespace
    5. Strip leading/trailing whitespace
    
    Examples:
        'CardioSync&amp;trade;'        → 'CardioSync™'
        'Model\\u200b X'                → 'Model X'
        '  Spaced    Out  Name  '       → 'Spaced Out Name'
    """
    if not raw_text or not isinstance(raw_text, str):
        return None
    
    # HTML entity decode
    text = html.unescape(raw_text)
    
    # Unicode normalize (NFKC decomposes compatibility chars)
    text = unicodedata.normalize("NFKC", text)
    
    # Remove invisible chars
    text = INVISIBLE_CHARS.sub("", text)
    
    # Collapse whitespace (tabs, newlines, multiple spaces → single space)
    text = re.sub(r"\s+", " ", text).strip()
    
    return text if text else None
```

---

## 6. Validation Logic

**Why it's independent**: Operates on a dictionary. Doesn't care where the dict came from.

The `validate_record` function from your deep-dive doc is already self-contained. Build it out with one addition — URL validation for the source link:

```python
# validators/record_validator.py

import re
from urllib.parse import urlparse

def validate_record(record: dict) -> tuple[bool, list[str]]:
    """Validate a normalized device record.
    
    Returns (is_valid, list_of_issues).
    is_valid is False only for critical failures (missing required fields).
    Non-critical issues are warnings that don't block storage.
    """
    issues = []
    
    # --- Critical: Required fields ---
    for field in ["device_name", "manufacturer", "model_number"]:
        if not record.get(field):
            issues.append(f"REQUIRED_MISSING: {field}")
    
    # --- Warning: Numeric range checks ---
    dims = record.get("dimensions", {})
    for dim_key in ["length_mm", "width_mm", "height_mm"]:
        val = dims.get(dim_key)
        if val is not None:
            if not isinstance(val, (int, float)):
                issues.append(f"TYPE_ERROR: {dim_key} is {type(val).__name__}, expected number")
            elif val <= 0:
                issues.append(f"INVALID_RANGE: {dim_key} = {val}")
            elif val > 10000:  # 10 meters — probably an error for medical devices
                issues.append(f"SUSPICIOUS_RANGE: {dim_key} = {val}mm (>10m)")
    
    # --- Warning: String length ---
    name = record.get("device_name", "")
    if name and (len(name) < 2 or len(name) > 500):
        issues.append(f"STRING_LENGTH: device_name ({len(name)} chars)")
    
    model = record.get("model_number", "")
    if model and (len(model) < 1 or len(model) > 100):
        issues.append(f"STRING_LENGTH: model_number ({len(model)} chars)")
    
    # --- Warning: URL validity ---
    source_url = record.get("source_url", "")
    if source_url:
        parsed = urlparse(source_url)
        if not parsed.scheme or not parsed.netloc:
            issues.append(f"INVALID_URL: {source_url}")
    
    # Record is valid if no REQUIRED fields are missing
    is_valid = not any("REQUIRED_MISSING" in i for i in issues)
    return is_valid, issues
```

---

## 7. Security Layer

### 7.1 CredentialManager

```python
# security/credentials.py

import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class CredentialManager:
    """Centralized, auditable credential access."""
    
    @staticmethod
    def get_credential(manufacturer: str, field: str) -> str | None:
        key = f"FIVOS_{manufacturer.upper()}_{field.upper()}"
        value = os.getenv(key)
        if value is None:
            logger.warning(f"Credential not found: {key}")
        else:
            logger.debug(f"Credential accessed: {key}")  # Never log the value
        return value
    
    @staticmethod
    def get_db_uri() -> str:
        return os.getenv("FIVOS_MONGO_URI", "mongodb://localhost:27017/fivos")
```

### 7.2 HTML Sanitizer

```python
# security/sanitizer.py

from bs4 import BeautifulSoup

DANGEROUS_TAGS = ["script", "iframe", "object", "embed", "form", "base", "meta"]

def sanitize_html(raw_html: str) -> str:
    """Strip dangerous HTML elements and attributes before pipeline processing."""
    soup = BeautifulSoup(raw_html, "lxml")
    
    for tag in soup.find_all(DANGEROUS_TAGS):
        tag.decompose()
    
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on"):
                del tag[attr]
    
    return str(soup)
```

### 7.3 `.env.example` (commit this — not the real `.env`)

```
# Copy this file to .env and fill in real values
# NEVER commit .env to Git

# Database
FIVOS_MONGO_URI=mongodb://localhost:27017/fivos

# Manufacturer credentials (if needed for authenticated portals)
# FIVOS_MEDTRONIC_USERNAME=
# FIVOS_MEDTRONIC_PASSWORD=
# FIVOS_ABBOTT_API_KEY=

# App
FIVOS_SECRET_KEY=change-me-to-a-random-string
```

### 7.4 `.gitignore` entries you should add now

```
.env
.env.*
*.pem
*.key
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

---

## 8. Integration Testing with Mocks

You don't need Wyatt's browser or Ryan's adapters to test your full pipeline end-to-end. Save a real HTML page from a manufacturer site and write a mock adapter:

### Step 1: Save sample HTML
Visit a Medtronic product page in your browser, right-click → "Save As" → save the HTML file to `tests/fixtures/medtronic_sample.html`.

### Step 2: Write a mock adapter config

```python
# tests/fixtures/mock_adapters.py

MEDTRONIC_MOCK_ADAPTER = {
    "manufacturer": "medtronic",
    "extraction": {
        "device_name": "h1.product-title",           # Adjust to real selectors
        "model_number": ".model-number span",
        "dimensions": "#specs-table tr:contains('Dimensions') td",
    }
}
```

### Step 3: End-to-end test

```python
# tests/test_pipeline_e2e.py

from pathlib import Path
from pipeline.parser import parse_html
from pipeline.extractor import extract_fields
from normalizers.units import normalize_measurement
from normalizers.manufacturers import normalize_manufacturer
from normalizers.text import clean_text
from normalizers.model_numbers import clean_model_number
from validators.record_validator import validate_record
from tests.fixtures.mock_adapters import MEDTRONIC_MOCK_ADAPTER

def test_full_pipeline_with_saved_html():
    # Load saved HTML
    html_path = Path(__file__).parent / "fixtures" / "medtronic_sample.html"
    raw_html = html_path.read_text(encoding="utf-8")
    
    # Stage 1: Parse
    soup = parse_html(raw_html)
    assert soup is not None
    
    # Stage 2: Extract
    raw_fields = extract_fields(soup, MEDTRONIC_MOCK_ADAPTER)
    assert isinstance(raw_fields, dict)
    
    # Stage 3: Normalize (whatever fields were found)
    if raw_fields.get("device_name"):
        raw_fields["device_name"] = clean_text(raw_fields["device_name"])
    if raw_fields.get("model_number"):
        raw_fields["model_number"] = clean_model_number(raw_fields["model_number"])
    raw_fields["manufacturer"] = normalize_manufacturer("Medtronic")
    
    # Stage 4: Validate
    is_valid, issues = validate_record(raw_fields)
    
    # Should produce a record (valid or with warnings, not crash)
    assert isinstance(is_valid, bool)
    assert isinstance(issues, list)
```

---

## 9. Suggested File Structure

Set this up in your repo now so teammates see an organized codebase when they start:

```
fivos-harvester/
├── .env.example
├── .gitignore
├── .python-version
├── pyproject.toml
├── requirements.txt
├── README.md
├── normalizers/
│   ├── __init__.py
│   ├── units.py
│   ├── manufacturers.py
│   ├── dates.py
│   ├── model_numbers.py
│   └── text.py
├── validators/
│   ├── __init__.py
│   └── record_validator.py
├── security/
│   ├── __init__.py
│   ├── credentials.py
│   └── sanitizer.py
├── pipeline/
│   ├── __init__.py
│   ├── parser.py
│   └── extractor.py
├── tests/
│   ├── __init__.py
│   ├── test_units.py
│   ├── test_manufacturers.py
│   ├── test_dates.py
│   ├── test_model_numbers.py
│   ├── test_record_validator.py
│   ├── test_pipeline_e2e.py
│   └── fixtures/
│       ├── mock_adapters.py
│       └── medtronic_sample.html
└── adapters/           ← Ryan will populate this
    └── README.md
```

---

## 10. Starter `requirements.txt`

```
beautifulsoup4==4.12.3
lxml==5.3.0
python-dotenv==1.0.1
pytest==8.3.4
```

Add more as needed. Pin exact versions. Run `pip freeze > requirements.txt` after installing to capture exact versions from your environment.

---

## 11. Suggested Build Order

| Priority | Task | Estimated Time | Dependencies |
|----------|------|----------------|-------------|
| 1 | Set up repo structure, venv, requirements.txt, .gitignore | 1 hour | None |
| 2 | Unit conversion engine + tests | 2-3 hours | None |
| 3 | Manufacturer alias map + tests | 1-2 hours | None |
| 4 | Model number cleaner + tests | 1 hour | None |
| 5 | Text field cleaner + tests | 1 hour | None |
| 6 | Date normalizer + tests | 1-2 hours | None |
| 7 | Record validator + tests | 1-2 hours | Normalizers done |
| 8 | CredentialManager + .env setup | 30 min | None |
| 9 | HTML sanitizer | 30 min | BeautifulSoup |
| 10 | HTML parser (Stage 1) | 30 min | None |
| 11 | Field extractor with mock adapters (Stage 2) | 1-2 hours | Parser done |
| 12 | Wire full pipeline + E2E test | 2-3 hours | All above done |

**Total: ~14-20 hours of solo work before you need anyone else's code.**

---

## 12. When You'll Need Teammates

| Teammate | What You Need From Them | When |
|----------|------------------------|------|
| **Wyatt** | Real rendered HTML flowing into your `parse_html()` | After your pipeline is built and tested with mocks |
| **Ryan** | Real YAML/JSON adapter configs replacing your mock adapters | After he maps out at least one manufacturer site |
| **Ralph** | A `save_record(record: dict)` function to call from Stage 5 | After your emit stage is mocked and working |
| **Jonathan** | `harvest_run_id` injected into your metadata packaging | After his run manager generates IDs |

Until then, mock all of these interfaces. Your pipeline doesn't care if the HTML came from Playwright or a saved file — it processes the same way.
