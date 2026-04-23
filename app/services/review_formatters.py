"""Render helpers for list-shaped fields on the review page.

Source-unit passthrough: values are displayed as they exist in the record
(only the long-form unit name is shortened). The per-type sub-row beneath
the deviceSizes row already carries the canonical comparison value — this
formatter intentionally does not re-run the cm→mm conversion.
"""

_UNIT_SHORT = {
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


def _format_value(raw):
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    if f.is_integer():
        return str(int(f))
    return f"{f:g}"


def format_device_sizes(value) -> str:
    if not value or not isinstance(value, list):
        return "N/A"
    rows = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        size_type = entry.get("sizeType")
        if not size_type:
            continue
        size = entry.get("size")
        if isinstance(size, dict) and size.get("value") not in (None, ""):
            raw_unit = size.get("unit")
            unit = _UNIT_SHORT.get(raw_unit, raw_unit) if raw_unit else ""
            val = _format_value(size.get("value"))
            line = f"{size_type}: {val} {unit}".rstrip()
            rows.append(line)
            continue
        size_text = entry.get("sizeText")
        if size_text:
            rows.append(f"{size_type}: {size_text}")
    if not rows:
        return "N/A"
    return "\n".join(rows)


def format_code_list(value) -> str:
    if not value or not isinstance(value, list):
        return "N/A"
    codes = [str(c).strip() for c in value if c not in (None, "")]
    if not codes:
        return "N/A"
    return ", ".join(codes)
