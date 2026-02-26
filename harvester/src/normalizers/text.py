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
