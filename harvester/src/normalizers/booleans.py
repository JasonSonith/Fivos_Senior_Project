"""Normalize boolean and enum fields for GUDID alignment."""

_TRUE_VALUES = {"yes", "true", "1", "y", "on"}
_FALSE_VALUES = {"no", "false", "0", "n", "off"}

_MRI_STATUS_MAP = {
    "mr safe": "MR Safe",
    "mri safe": "MR Safe",
    "mr conditional": "MR Conditional",
    "mri conditional": "MR Conditional",
    "mr unsafe": "MR Unsafe",
    "mri unsafe": "MR Unsafe",
    "not safe": "MR Unsafe",
}

_MRI_NO_INFO = "Labeling does not contain MRI Safety Information"


def normalize_boolean(raw: str) -> bool | None:
    """Normalize yes/no/true/false text to Python bool.

    Returns None if the value cannot be interpreted.
    """
    if raw is None:
        return None
    cleaned = str(raw).strip().lower()
    if not cleaned:
        return None
    if cleaned in _TRUE_VALUES:
        return True
    if cleaned in _FALSE_VALUES:
        return False
    return None


def normalize_mri_status(raw: str) -> str | None:
    """Normalize MRI safety status to GUDID enum values.

    Returns one of: 'MR Safe', 'MR Conditional', 'MR Unsafe',
    'Labeling does not contain MRI Safety Information', or None.
    """
    if raw is None:
        return None
    cleaned = str(raw).strip().lower()
    if not cleaned:
        return None
    # Check "no info" pattern first (before partial match catches "mr safe" in "no mri safety info")
    if ("no" in cleaned and "info" in cleaned) or ("no" in cleaned and "safety" in cleaned and "info" in cleaned):
        return _MRI_NO_INFO
    if cleaned in _MRI_STATUS_MAP:
        return _MRI_STATUS_MAP[cleaned]
    # Partial match
    for key, value in _MRI_STATUS_MAP.items():
        if key in cleaned:
            return value
    return None
