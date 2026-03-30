import json
import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/chat"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
OLLAMA_MODEL = "mistral"

_OLLAMA_WARNED = False
_GROQ_WARNED = False

# ---------------------------------------------------------------------------
# Schemas for structured output
# ---------------------------------------------------------------------------

DESCRIPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "deviceDescription": {"type": ["string", "null"]},
    },
    "required": ["deviceDescription"],
}

PAGE_FIELDS_SCHEMA = {
    "type": "object",
    "properties": {
        "device_name": {"type": ["string", "null"]},
        "manufacturer": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "warning_text": {"type": ["string", "null"]},
        "MRISafetyStatus": {"type": ["string", "null"]},
    },
    "required": ["device_name", "manufacturer", "description"],
}

PRODUCT_ROWS_SCHEMA = {
    "type": "object",
    "properties": {
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "model_number": {"type": ["string", "null"]},
                    "catalog_number": {"type": ["string", "null"]},
                    "diameter": {"type": ["string", "null"]},
                    "length": {"type": ["string", "null"]},
                    "width": {"type": ["string", "null"]},
                    "height": {"type": ["string", "null"]},
                    "weight": {"type": ["string", "null"]},
                    "volume": {"type": ["string", "null"]},
                    "pressure": {"type": ["string", "null"]},
                },
                "required": ["model_number"],
            },
        },
    },
    "required": ["products"],
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

DESCRIPTION_PROMPT = """\
You are extracting a clinical device description for a medical device regulatory database (FDA GUDID).

Device: {device_name} by {manufacturer}, model {model_number}

Write a factual, clinical description of this device based on the page text below.
- Focus on: what the device IS, what it DOES, what anatomy/condition it treats
- Ignore: marketing claims, clinical trial results, ordering info, testimonials
- Style: one sentence, clinical terminology, no brand superlatives
- If the page does not contain enough info to write a clinical description, return null

Page text:
{visible_text}"""

PAGE_FIELDS_PROMPT = """\
You are extracting medical device data from a manufacturer's product page for the FDA GUDID database.

Extract these fields from the page text below. Return valid JSON.

Rules:
- device_name: The commercial product name / brand name (e.g., "IN.PACT ADMIRAL", "ZILVER PTX"). \
NOT the manufacturer name. NOT a description or tagline.
- manufacturer: The company that makes this device. Use the legal entity name if visible \
(e.g., "Medtronic, Inc." not just "Medtronic").
- description: One factual, clinical sentence describing what this device IS and what it DOES. \
Focus on: device type, anatomy/condition treated, mechanism of action. \
Ignore: marketing claims, clinical trial results, testimonials.
- warning_text: Copy any warning, caution, or regulatory text verbatim from the page. \
Include text about single-use, Rx only, sterility, contraindications. null if none found.
- MRISafetyStatus: One of "MR Safe", "MR Conditional", "MR Unsafe", or null if not stated on the page.

Page text:
{visible_text}"""

PRODUCT_ROWS_PROMPT = """\
You are extracting individual product SKUs from a medical device ordering/specifications table.

The device is: {device_name}

For EACH distinct product row in the table below, extract:
- model_number: The SKU, part number, catalog number, or model identifier \
(e.g., "IPU04004013P", "1012528-20", "G38404"). This is an alphanumeric code, NOT a dimension.
- catalog_number: A separate catalog/reference number if present and different from model_number. null otherwise.
- diameter: Diameter with unit as a string (e.g., "8.0 mm"). null if not listed.
- length: Length with unit as a string (e.g., "40.0 mm"). null if not listed.
- width: Width with unit. null if not listed.
- height: Height with unit. null if not listed.
- weight: Weight with unit. null if not listed.
- volume: Volume with unit. null if not listed.
- pressure: Pressure with unit. null if not listed.

Return a JSON object with a "products" array. Each element is one product row.
If there is only one product (not a table), return an array with one element.
Do NOT include rows where model_number is null or clearly a header/footer.

Table/specs text:
{table_text}"""

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _get_groq_key() -> str | None:
    return os.environ.get("GROQ_API_KEY")


def _groq_request(messages: list[dict], schema: dict, timeout: int = 60) -> dict | None:
    global _GROQ_WARNED

    api_key = _get_groq_key()
    if not api_key:
        if not _GROQ_WARNED:
            logger.info("GROQ_API_KEY not set, falling back to Ollama")
            _GROQ_WARNED = True
        return None

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "response_format": {
            "type": "json_object",
        },
        "temperature": 0,
    }

    try:
        response = requests.post(
            GROQ_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            detail = exc.response.json().get("error", {}).get("message", str(exc))
        except Exception:
            detail = str(exc)
        logger.warning("Groq request failed: %s", detail)
        return None
    except Exception as exc:
        logger.warning("Groq request failed: %s", exc)
        return None

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            return content
        return json.loads(content)
    except Exception as exc:
        logger.warning("Failed to parse Groq response: %s", exc)
        return None


def _ollama_request(payload: dict, timeout: int = 60) -> dict | None:
    global _OLLAMA_WARNED

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.ConnectionError:
        if not _OLLAMA_WARNED:
            logger.warning("Ollama not available at %s, skipping extraction", OLLAMA_URL)
            _OLLAMA_WARNED = True
        return None
    except Exception as exc:
        logger.warning("Ollama request failed: %s", exc)
        return None

    try:
        data = response.json()
        content = data["message"]["content"]
        if isinstance(content, dict):
            return content
        return json.loads(content)
    except Exception as exc:
        logger.warning("Failed to parse Ollama response: %s", exc)
        return None


def _llm_request(system_msg: str, user_msg: str, schema: dict, timeout: int = 60) -> dict | None:
    """Try Groq first, fall back to Ollama."""
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    # Try Groq
    result = _groq_request(messages, schema, timeout=timeout)
    if result is not None:
        return result

    # Fall back to Ollama
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "format": schema,
    }
    return _ollama_request(payload, timeout=timeout)


# ---------------------------------------------------------------------------
# Original description-only extraction (kept for backward compatibility)
# ---------------------------------------------------------------------------


def extract_description(visible_text, device_name="", model_number="", manufacturer="", model=None):
    if not visible_text or not visible_text.strip():
        return None

    prompt = DESCRIPTION_PROMPT.format(
        device_name=device_name,
        manufacturer=manufacturer,
        model_number=model_number,
        visible_text=visible_text[:4000],
    )

    parsed = _llm_request(
        "Extract only the requested field. Return valid JSON.",
        prompt,
        DESCRIPTION_SCHEMA,
        timeout=120,
    )
    if parsed is None:
        return None

    desc = parsed.get("deviceDescription")
    return desc if desc else None


# ---------------------------------------------------------------------------
# Full extraction: page-level fields + product rows
# ---------------------------------------------------------------------------


def extract_page_fields(visible_text: str, model: str | None = None) -> dict | None:
    if not visible_text or not visible_text.strip():
        return None

    prompt = PAGE_FIELDS_PROMPT.format(visible_text=visible_text[:6000])

    parsed = _llm_request(
        "Extract medical device fields from the page. Return valid JSON.",
        prompt,
        PAGE_FIELDS_SCHEMA,
        timeout=300,
    )
    if parsed is None:
        return None

    if not parsed.get("device_name"):
        logger.warning("LLM returned no device_name, skipping page")
        return None

    return parsed


def extract_product_rows(table_text: str, device_name: str = "", model: str | None = None) -> list[dict]:
    if not table_text or not table_text.strip():
        return []

    prompt = PRODUCT_ROWS_PROMPT.format(
        device_name=device_name,
        table_text=table_text[:8000],
    )

    parsed = _llm_request(
        "Extract product rows from the table. Return valid JSON.",
        prompt,
        PRODUCT_ROWS_SCHEMA,
        timeout=300,
    )
    if parsed is None:
        return []

    products = parsed.get("products", [])
    return [p for p in products if p.get("model_number")]


def extract_all_fields(visible_text: str, table_text: str | None = None, model: str | None = None) -> list[dict]:
    # Pass 1: page-level fields
    page_fields = extract_page_fields(visible_text)
    if page_fields is None:
        return []

    # Pass 2: product rows from table
    products = extract_product_rows(table_text or visible_text, page_fields.get("device_name", ""))

    source = "groq" if _get_groq_key() else "ollama"

    if not products:
        page_fields["_description_source"] = source
        return [page_fields]

    records = []
    for product in products:
        merged = {
            "device_name": page_fields.get("device_name"),
            "manufacturer": page_fields.get("manufacturer"),
            "description": page_fields.get("description"),
            "warning_text": page_fields.get("warning_text"),
            "MRISafetyStatus": page_fields.get("MRISafetyStatus"),
            "_description_source": source,
        }
        merged["model_number"] = product.get("model_number")
        merged["catalog_number"] = product.get("catalog_number")
        for dim in ("diameter", "length", "width", "height", "weight", "volume", "pressure"):
            val = product.get(dim)
            if val:
                merged[dim] = val
        records.append(merged)

    return records
