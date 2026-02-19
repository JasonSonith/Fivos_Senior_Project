import re

MODEL_PREFIXES = [
    r"model\s*[-:.\\#]?\s*",
    r"cat\.?\s*no\.?\s*[-:.\\#]?\s*",
    r"catalog\s*(?:number|no\.?|#)?\s*[-:.\\#]?\s*",
    r"ref\.?\s*[-:.\\#]?\s*",
    r"sku\s*[-:.\\#]?\s*",
    r"part\s*(?:number|no\.?|#)?\s*[-:.\\#]?\s*",
    r"item\s*(?:number|no\.?|#)?\s*[-:.\\#]?\s*",
    r"p/?n\s*[-:.\\#]?\s*",
]

"""
strips common labels such as Model:, Cat. No., REF, SKU, Part Number, P/N, etc. from the front of a
string using a list of regex patterns, then collapses whitespace and uppercases the result. Returns 'None'
for a empty or non string input or if stripping leaves nothing.

Example:
- "Model: CS-2000X"  gets turned into "CS-2000X" after iterating through the MODEL_PREFIXES list
- "CS   2000  X" → "CS 2000 X" after stripping whitespaces
- "cs-2000x" → "CS-2000X" ensures everything is uppercase
- returns None if stripped string leaves nothing or empty string input
"""
def clean_model_number(raw_model: str) -> str | None:
    if not raw_model or not isinstance(raw_model, str):
        return None

    cleaned = raw_model.strip()

    for pattern in MODEL_PREFIXES:
        cleaned = re.sub(f"^{pattern}", "", cleaned, flags=re.IGNORECASE).strip()

    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.upper()

    return cleaned if cleaned else None