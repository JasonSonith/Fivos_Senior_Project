import re
import html
import unicodedata

INVISIBLE_CHARS = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f"   # Zero-width spaces/joiners/marks
    r"\u00ad"                              # Soft hyphen
    r"\ufeff"                              # BOM / zero-width no-break
    r"\u2060\u2061\u2062\u2063\u2064"     # Word joiner, invisible operators
    r"\u00a0"                              # Non-breaking space
    r"]"
)

_BRAND_SUFFIX_RE = re.compile(
    r"\s+(?:drug[- ](?:coated|eluting)\s+(?:\w+\s+)*?(?:balloon|stent)(?:\s+system)?"
    r"|(?:self[- ]expanding|balloon[- ]expandable)\s+(?:\w+\s+)*?(?:stent|endoprosthesis)(?:\s+system)?"
    r"|(?:peripheral|coronary|vascular)\s+(?:IVL\s+)?(?:catheter|stent)(?:\s+system)?"
    r"|directional\s+atherectomy\s+system"
    r"|endoprosthesis(?:\s+with\s+heparin)?"
    r"|(?:vascular\s+)?stent\s+system"
    r"|(?:\(DES\)))",
    re.IGNORECASE,
)

_TM_SYMBOLS_RE = re.compile(r"[™®©]|(?<=\w)TM(?=\s|$|\b)")


def clean_brand_name(raw: str) -> str | None:
    """Clean a brand name for GUDID alignment.

    Strips ™/®/©/TM symbols and trailing descriptive text
    (e.g. 'drug-eluting stent', 'directional atherectomy system').
    """
    if not raw or not isinstance(raw, str):
        return None
    text = normalize_text(raw)
    if not text:
        return None
    # Strip TM/®/© symbols
    text = _TM_SYMBOLS_RE.sub("", text)
    # Strip trailing descriptive suffixes
    text = _BRAND_SUFFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text else None


def normalize_text(raw: str) -> str | None:
    """Clean a general text field.
    Steps: HTML decode → NFKC normalize → strip invisible chars → collapse whitespace.
    Returns None for empty/non-string input.
    """
    if not raw or not isinstance(raw, str):
        return None
    text = html.unescape(raw)
    text = unicodedata.normalize("NFKC", text)
    text = INVISIBLE_CHARS.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text else None
