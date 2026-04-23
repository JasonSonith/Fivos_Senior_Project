import re


COMPANY_ALIASES = {
    "Medtronic":         ["Medtronic", "Covidien LP", "Covidien"],
    "Boston Scientific": ["Boston Scientific", "BTG"],
    "BD":                ["BD", "Bard", "C R Bard", "Becton Dickinson"],
    "Abbott":            ["Abbott", "St Jude Medical"],
    "Johnson & Johnson": ["Johnson & Johnson", "J&J", "Synthes", "DePuy", "Ethicon"],
    "Stryker":           ["Stryker", "Wright Medical"],
}

_SUFFIX_RE = re.compile(
    r"\b(Inc\.?|LP|LLC|Ltd\.?|Corp\.?|Corporation|Company|Co\.?)\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[,\.&']")
_WS_RE = re.compile(r"\s+")


def _normalize(raw: str) -> str:
    text = _SUFFIX_RE.sub("", raw)
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip().lower()
    return text


_REVERSE_INDEX = {}
for _canonical, _variants in COMPANY_ALIASES.items():
    for _variant in _variants:
        _REVERSE_INDEX[_normalize(_variant)] = _canonical


def canonical_company(raw: str | None) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    normalized = _normalize(raw)
    if not normalized:
        return None
    return _REVERSE_INDEX.get(normalized)
