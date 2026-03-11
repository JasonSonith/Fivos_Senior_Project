import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_VALID_MRI_STATUSES = {
    "MR Safe", "MR Conditional", "MR Unsafe",
    "Labeling does not contain MRI Safety Information",
}


def validate_record(record: dict) -> tuple[bool, list[str]]:
    """
    Validate a normalized device record.

    Supports both legacy field names (device_name, manufacturer, model_number)
    and GUDID-aligned names (brandName, companyName, versionModelNumber).

    Returns (is_valid, issues) where is_valid is False if any blocking
    issue (REQUIRED_MISSING or INVALID_URL) is present.
    """
    issues: list[str] = []

    # Required fields — blocking (support both old and new names)
    required_mappings = [
        ("device_name", "brandName"),
        ("manufacturer", "companyName"),
        ("model_number", "versionModelNumber"),
    ]
    for old_name, new_name in required_mappings:
        value = record.get(old_name) or record.get(new_name)
        if not value or not str(value).strip():
            issues.append(f"REQUIRED_MISSING: {old_name}")
            logger.warning("validate_record: required field missing: %s", old_name)

    # Source URL — blocking (support both flat and nested _harvest)
    harvest = record.get("_harvest", {})
    source_url = record.get("source_url") or harvest.get("source_url")
    if source_url is not None:
        parsed = urlparse(str(source_url))
        if not parsed.scheme or not parsed.netloc:
            issues.append("INVALID_URL: source_url missing scheme or netloc")
            logger.warning("validate_record: invalid source_url: %s", source_url)
    else:
        issues.append("INVALID_URL: source_url is missing")
        logger.warning("validate_record: source_url not present in record")

    # Device sizes validation — non-blocking
    device_sizes = record.get("deviceSizes") or []
    for i, size_entry in enumerate(device_sizes):
        if not isinstance(size_entry, dict):
            continue
        size = size_entry.get("size")
        if size and isinstance(size, dict):
            val = size.get("value")
            if val is not None:
                try:
                    if float(val) <= 0:
                        issues.append(f"INVALID_RANGE: deviceSizes[{i}].value must be > 0, got {val}")
                except (TypeError, ValueError):
                    issues.append(f"INVALID_RANGE: deviceSizes[{i}].value is not numeric: {val}")

    # Legacy dimension ranges — non-blocking
    dimensions = record.get("dimensions") or {}
    for dim_field in ("length_mm", "width_mm", "height_mm"):
        value = dimensions.get(dim_field)
        if value is not None:
            try:
                if float(value) <= 0:
                    issues.append(f"INVALID_RANGE: dimensions.{dim_field} must be > 0, got {value}")
                    logger.warning("validate_record: %s out of range: %s", dim_field, value)
            except (TypeError, ValueError):
                issues.append(f"INVALID_RANGE: dimensions.{dim_field} is not numeric: {value}")

    # Weight range — non-blocking
    weight = record.get("weight_g")
    if weight is not None:
        try:
            if float(weight) <= 0:
                issues.append(f"INVALID_RANGE: weight_g must be > 0, got {weight}")
                logger.warning("validate_record: weight_g out of range: %s", weight)
        except (TypeError, ValueError):
            issues.append(f"INVALID_RANGE: weight_g is not numeric: {weight}")

    # String lengths — non-blocking (support both old and new names)
    device_name = record.get("device_name") or record.get("brandName")
    if device_name and str(device_name).strip():
        name_len = len(str(device_name))
        if not (2 <= name_len <= 500):
            issues.append(f"STRING_LENGTH: device_name must be 2-500 chars, got {name_len}")

    model_number = record.get("model_number") or record.get("versionModelNumber")
    if model_number and str(model_number).strip():
        model_len = len(str(model_number))
        if not (1 <= model_len <= 100):
            issues.append(f"STRING_LENGTH: model_number must be 1-100 chars, got {model_len}")

    # Boolean field validation — non-blocking
    for field in ("singleUse", "deviceSterile", "sterilizationPriorToUse", "rx", "otc"):
        value = record.get(field)
        if value is not None and not isinstance(value, bool):
            issues.append(f"INVALID_TYPE: {field} must be bool or None, got {type(value).__name__}")

    # MRI safety status enum — non-blocking
    mri_status = record.get("MRISafetyStatus")
    if mri_status is not None and mri_status not in _VALID_MRI_STATUSES:
        issues.append(f"INVALID_ENUM: MRISafetyStatus must be one of {_VALID_MRI_STATUSES}, got '{mri_status}'")

    is_valid = not any(
        i.startswith("REQUIRED_MISSING:") or i.startswith("INVALID_URL:")
        for i in issues
    )
    return is_valid, issues
