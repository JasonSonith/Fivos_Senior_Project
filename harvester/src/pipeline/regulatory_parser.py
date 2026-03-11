"""Parse regulatory boolean fields from warning/precaution text.

Extracts GUDID-compatible fields (singleUse, rx, deviceSterile) from
free-text warnings and precautions found on manufacturer pages.
Only produces results when patterns are actually matched.
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


def parse_regulatory_from_text(warning_text: str | None) -> dict:
    """Extract boolean GUDID fields from warning/precaution text.

    Returns dict like {"singleUse": True, "rx": True, "deviceSterile": True}.
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

    return result
