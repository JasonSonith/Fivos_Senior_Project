"""Parse dimension values (diameter, length, weight, etc.) from specs_container text.

This module sits between extraction and normalization in the pipeline.
It mines structured dimension data from the raw specs_container text that
the extractor captures from manufacturer specification tables.

Three data formats are handled:

- **Format A (Tabular)**: Headers like "Diameter (mm)" followed by rows of values.
  Used by Abbott, Cordis, Shockwave, Cook, Gore, Terumo.
- **Format B (Key-value)**: Labels like "Balloon diameters" followed by values.
  Used by Medtronic (IN.PACT, Resolute Onyx).
- **Format C (Non-dimensional)**: Clinical percentages or non-metric data.
  Returns empty dict.

When called from the runner, specs_text is re-extracted with tab separators
between HTML elements, making cell-boundary detection reliable.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Maps label text (lowercased) to MEASUREMENT_FIELDS keys.
DIMENSION_LABEL_MAP = {
    "diameter": "diameter",
    "stent diameter": "diameter",
    "balloon diameter": "diameter",
    "crown size": "diameter",
    "endoprosthesis labeled diameter": "diameter",
    "endoprosthesis labeleddiameter": "diameter",
    "length": "length",
    "stent length": "length",
    "balloon length": "length",
    "endoprosthesis length": "length",
    "endoprosthesislength": "length",
    "weight": "weight",
    "width": "width",
    "height": "height",
    "volume": "volume",
    "pressure": "pressure",
}

# Labels that must NOT map to a dimension (to avoid false positives).
_SKIP_LABELS = {
    "shaft length", "catheter length", "catheter working length",
    "balloon diameterfor device touch-up",
    "recommended balloon diameter", "recommended vessel diameter",
    "balloon crossing profile", "guidewire compatibility",
    "sheath compatibility", "device profile",
    "accepts wire guide diameter", "wire guide diameter",
}

# Regex to find unit-bearing headers in tab-separated cells.
_HEADER_UNIT_RE = re.compile(r"^(.*?)\s*\((\w+)\)\s*$")

# Regex to find dimension headers in concatenated text (more targeted).
_CONCAT_DIM_RE = re.compile(
    r"((?:Stent |Balloon |Endoprosthesis (?:Labeled\s*)?|Crown )?"
    r"(?:Diameter|Length|Width|Height|Weight|Volume|Pressure))"
    r"\s*\((\w+)\)",
    re.IGNORECASE,
)


def parse_dimensions_from_specs(
    specs_text: str | None,
    model_number: str | None = None,
    adapter: dict | None = None,
) -> dict[str, str | None]:
    """Extract dimension fields from specs_container text.

    Returns a dict mapping MEASUREMENT_FIELDS keys to raw string values
    suitable for ``normalize_measurement()``.  Returns ``{}`` on failure
    or when no dimensional data is found.  Never raises.
    """
    if not specs_text or not specs_text.strip():
        return {}

    try:
        if "\t" in specs_text:
            result = _parse_tabbed(specs_text, model_number)
            if result:
                return result

        result = _try_format_a(specs_text, model_number)
        if result:
            return result

        result = _try_format_b(specs_text)
        if result:
            return result

        result = _try_description_format(specs_text, model_number)
        if result:
            return result

        return {}

    except Exception as exc:
        logger.warning("parse_dimensions_from_specs: unexpected error: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_label(label: str) -> str | None:
    """Map a header/label string to a MEASUREMENT_FIELDS key, or None."""
    cleaned = re.sub(r"[†‡§‖¶*]", "", label).strip().lower()
    cleaned = re.sub(r"\s*sort by\b.*", "", cleaned)
    if not cleaned:
        return None
    if cleaned in _SKIP_LABELS:
        return None
    for skip in _SKIP_LABELS:
        if skip in cleaned:
            return None
    if cleaned in DIMENSION_LABEL_MAP:
        return DIMENSION_LABEL_MAP[cleaned]
    for key, field in DIMENSION_LABEL_MAP.items():
        if key in cleaned:
            return field
    return None


def _cell_number(val: str) -> float | None:
    """Extract numeric value from a cell that is purely a number.

    Accepts '6.0', '20', '6.0 mm' but rejects '1012528-20', 'G38404',
    'ZISV6-35-125-5-40-PTX' and other non-numeric cells.
    """
    val = val.strip()
    if not val:
        return None
    m = re.match(r"^(\d+\.?\d*)(?:\s+\w+)?$", val)
    if m:
        return float(m.group(1))
    return None


def _is_similar_cell(cell: str, model_number: str) -> bool:
    """Check if *cell* looks like another product entry similar to model_number."""
    c = cell.strip()
    mn = model_number.strip()
    if not c or c == mn or c.upper() == mn.upper():
        return False
    # Similar length (±3) and same character type at start
    if abs(len(c) - len(mn)) > 3:
        return False
    if mn[0].isalpha() != c[0].isalpha():
        return False
    # For numeric model numbers (e.g. "8.0"), check value range
    if re.match(r"^\d+\.?\d*$", mn):
        m = re.match(r"^(\d+\.?\d*)$", c)
        if m and 0.5 <= float(m.group(1)) <= 50:
            return True
        return False
    return True


# ---------------------------------------------------------------------------
# Tab-separated parsing (primary path when called from the runner)
# ---------------------------------------------------------------------------

def _parse_tabbed(specs_text: str, model_number: str | None) -> dict[str, str | None]:
    """Parse tab-separated specs text where each cell is a distinct token."""
    cells = [c.strip() for c in specs_text.split("\t")]

    # Find dimension headers: {field_key: unit}
    dim_info = _find_dim_headers_tabbed(cells)
    if not dim_info:
        return {}

    mn = model_number.strip() if model_number else None

    # Find model_number cell
    model_idx = None
    if mn:
        for i, c in enumerate(cells):
            if c == mn or c.upper() == mn.upper():
                model_idx = i
                break

    if model_idx is None:
        # No model found — try first data row
        return _extract_from_cells(cells, dim_info)

    # Scan a fixed window from model_idx and extract dimensions in order
    scan_end = min(model_idx + 15, len(cells))
    scan_cells = cells[model_idx:scan_end]
    return _extract_dims_from_row(scan_cells, dim_info)


def _find_dim_headers_tabbed(cells: list[str]) -> dict[str, str]:
    """Find dimension headers in tab-separated cells.

    Returns {field_key: unit} for recognized dimension headers.
    """
    dim_info: dict[str, str] = {}
    for cell in cells:
        cleaned = re.sub(r"\s*Sort by\b.*", "", cell, flags=re.IGNORECASE)
        m = _HEADER_UNIT_RE.match(cleaned)
        if m:
            label = m.group(1).strip()
            unit = m.group(2).strip()
            field_key = _normalize_label(label)
            if field_key is not None and field_key not in dim_info:
                dim_info[field_key] = unit
    return dim_info


def _extract_dims_from_row(
    row: list[str],
    dim_info: dict[str, str],
) -> dict[str, str | None]:
    """Extract dimension values from a row of cells using multiple strategies."""
    # Strategy 1: "D X L" pattern in text cells
    for cell in row:
        dxl = re.search(r"(\d+\.?\d*)\s*[xX×]\s*(\d+\.?\d*)", cell)
        if dxl:
            result = {}
            if "diameter" in dim_info:
                result["diameter"] = f"{dxl.group(1)} {dim_info['diameter']}"
            if "length" in dim_info:
                result["length"] = f"{dxl.group(2)} {dim_info['length']}"
            if result:
                return result

    # Strategy 2: Ordered extraction — assign numeric cells to dimensions
    # in the order the dimension headers appear.
    result = {}
    dim_fields = list(dim_info.keys())
    dim_idx = 0
    for cell in row:
        if dim_idx >= len(dim_fields):
            break
        num = _cell_number(cell)
        if num is None or num < 0.5:
            continue
        field_key = dim_fields[dim_idx]
        result[field_key] = f"{cell.strip()} {dim_info[field_key]}"
        dim_idx += 1

    return result


def _extract_from_cells(
    cells: list[str],
    dim_info: dict[str, str],
) -> dict[str, str | None]:
    """Fallback: scan all cells for the first plausible dimension values."""
    result = {}
    used: set[int] = set()
    for field_key, unit in dim_info.items():
        for i, cell in enumerate(cells):
            if i in used:
                continue
            num = _cell_number(cell)
            if num is not None and num >= 0.5:
                result[field_key] = f"{cell.strip()} {unit}"
                used.add(i)
                break
    return result


# ---------------------------------------------------------------------------
# Concatenated text parsing (fallback for data without tabs)
# ---------------------------------------------------------------------------

def _extract_dim_headers_concat(specs_text: str) -> list[tuple[str, str, int]]:
    """Find dimension headers from concatenated text using targeted regex."""
    headers = []
    for m in _CONCAT_DIM_RE.finditer(specs_text):
        label = m.group(1).strip()
        unit = m.group(2).strip()
        field_key = _normalize_label(label)
        if field_key is not None:
            headers.append((field_key, unit, m.end()))
    return headers


def _try_format_a(specs_text: str, model_number: str | None) -> dict[str, str | None]:
    """Parse Format A — tabular data with unit-bearing headers (concatenated)."""
    dim_headers = _extract_dim_headers_concat(specs_text)
    if not dim_headers:
        return {}

    last_header_end = max(h[2] for h in dim_headers)
    data_section = specs_text[last_header_end:]

    if model_number and model_number.strip():
        mn = model_number.strip()
        pos = data_section.find(mn)
        if pos < 0:
            pos = data_section.lower().find(mn.lower())
        if pos >= 0:
            window = data_section[pos + len(mn):pos + len(mn) + 400]
            # Look for "D X L" pattern
            dxl = re.search(r"(\d+\.?\d*)\s*[xX×]\s*(\d+\.?\d*)", window)
            if dxl:
                result = {}
                for fk, unit, _ in dim_headers:
                    if fk == "diameter" and "diameter" not in result:
                        result["diameter"] = f"{dxl.group(1)} {unit}"
                    elif fk == "length" and "length" not in result:
                        result["length"] = f"{dxl.group(2)} {unit}"
                if result:
                    return result

    # Fallback: first numbers from data section
    nums = re.findall(r"\d+\.?\d*", data_section[:200])
    if nums:
        result = {}
        for i, (fk, unit, _) in enumerate(dim_headers):
            if i < len(nums):
                result[fk] = f"{nums[i]} {unit}"
        return result

    return {}


def _try_format_b(specs_text: str) -> dict[str, str | None]:
    """Parse Format B — key-value pairs like 'Balloon diameters4.0 to 7.0 mm'."""
    result = {}

    kv_patterns = [
        (
            "diameter",
            re.compile(
                r"(?:balloon|stent)\s*diameters?\s*"
                r"([\d.,]+(?:\s*(?:to|–|-|,\s*and|,)\s*[\d.,]+)*\s*(?:mm|cm|in))",
                re.IGNORECASE,
            ),
        ),
        (
            "length",
            re.compile(
                r"(?:balloon|stent)\s*lengths?\s*"
                r"([\d.,]+(?:\s*(?:to|–|-|,\s*and|,|¶)\s*[\d.,]+)*\s*(?:mm|cm|in))",
                re.IGNORECASE,
            ),
        ),
        (
            "length",
            re.compile(
                r"catheter\s*lengths?\s*"
                r"([\d.,]+(?:\s*(?:to|–|-|,\s*and|,|and)\s*[\d.,]+)*\s*(?:mm|cm|in))",
                re.IGNORECASE,
            ),
        ),
    ]

    for field_key, pattern in kv_patterns:
        if field_key in result:
            continue
        m = pattern.search(specs_text)
        if m:
            result[field_key] = m.group(1).strip()

    return result


def _try_description_format(
    specs_text: str,
    model_number: str | None,
) -> dict[str, str | None]:
    """Parse Terumo-style description: '200 cm, 6 Fr, 6 mm x 40 mm'."""
    if not model_number:
        return {}

    mn = model_number.strip()
    pos = specs_text.find(mn)
    if pos < 0:
        return {}

    after = specs_text[pos + len(mn): pos + len(mn) + 200]
    m = re.search(r"(\d+\.?\d*)\s*mm\s*x\s*(\d+\.?\d*)\s*mm", after)
    if m:
        return {
            "diameter": f"{m.group(1)} mm",
            "length": f"{m.group(2)} mm",
        }

    return {}
