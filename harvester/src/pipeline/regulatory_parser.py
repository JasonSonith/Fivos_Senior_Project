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

_PREMARKET_RE = re.compile(r"\b(K\d{6,7}|P\d{6}|DEN\d{6})\b")
_REG_KEYWORDS = re.compile(
    r"510\s*\(\s*k\s*\)|premarket|\bPMA\b|FDA\s+clearance|K[- ]number|cleared\s+by\s+FDA",
    re.IGNORECASE,
)


def extract_premarket_submissions(text: str | None) -> list[str] | None:
    if not text:
        return None
    found = set()
    for match in _PREMARKET_RE.finditer(text):
        start, end = match.span()
        window = text[max(0, start - 40):min(len(text), end + 40)]
        if _REG_KEYWORDS.search(window):
            found.add(match.group(1))
    return sorted(found) or None


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
