import json
import logging

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/chat"
_OLLAMA_WARNED = False

# ---------------------------------------------------------------------------
# Schemas for Ollama structured output
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
# Shared HTTP helper
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Original description-only extraction (kept for backward compatibility)
# ---------------------------------------------------------------------------


def extract_description(visible_text, device_name="", model_number="", manufacturer="", model="mistral"):
    if not visible_text or not visible_text.strip():
        return None

    prompt = DESCRIPTION_PROMPT.format(
        device_name=device_name,
        manufacturer=manufacturer,
        model_number=model_number,
        visible_text=visible_text[:4000],
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Extract only the requested field. Return valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": DESCRIPTION_SCHEMA,
    }

    parsed = _ollama_request(payload, timeout=120)
    if parsed is None:
        return None

    desc = parsed.get("deviceDescription")
    return desc if desc else None


# ---------------------------------------------------------------------------
# Full extraction: page-level fields + product rows
# ---------------------------------------------------------------------------


def extract_page_fields(visible_text: str, model: str = "mistral") -> dict | None:
    if not visible_text or not visible_text.strip():
        return None

    prompt = PAGE_FIELDS_PROMPT.format(visible_text=visible_text[:6000])

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Extract medical device fields from the page. Return valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": PAGE_FIELDS_SCHEMA,
    }

    parsed = _ollama_request(payload, timeout=300)
    if parsed is None:
        return None

    # Must have at least device_name to be useful
    if not parsed.get("device_name"):
        logger.warning("Ollama returned no device_name, skipping page")
        return None

    return parsed


def extract_product_rows(table_text: str, device_name: str = "", model: str = "mistral") -> list[dict]:
    if not table_text or not table_text.strip():
        return []

    prompt = PRODUCT_ROWS_PROMPT.format(
        device_name=device_name,
        table_text=table_text[:8000],
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Extract product rows from the table. Return valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": PRODUCT_ROWS_SCHEMA,
    }

    parsed = _ollama_request(payload, timeout=300)
    if parsed is None:
        return []

    products = parsed.get("products", [])
    # Filter out rows without a model_number
    return [p for p in products if p.get("model_number")]


def extract_all_fields(visible_text: str, table_text: str | None = None, model: str = "mistral") -> list[dict]:
    # Pass 1: page-level fields
    page_fields = extract_page_fields(visible_text, model)
    if page_fields is None:
        return []

    # Pass 2: product rows from table
    products = extract_product_rows(table_text or visible_text, page_fields.get("device_name", ""), model)

    if not products:
        # Single record with page-level data only
        page_fields["_description_source"] = "ollama"
        return [page_fields]

    # Merge each product row with page-level fields
    records = []
    for product in products:
        merged = {
            "device_name": page_fields.get("device_name"),
            "manufacturer": page_fields.get("manufacturer"),
            "description": page_fields.get("description"),
            "warning_text": page_fields.get("warning_text"),
            "MRISafetyStatus": page_fields.get("MRISafetyStatus"),
            "_description_source": "ollama",
        }
        # Product-level fields (model_number, dimensions)
        merged["model_number"] = product.get("model_number")
        merged["catalog_number"] = product.get("catalog_number")
        for dim in ("diameter", "length", "width", "height", "weight", "volume", "pressure"):
            val = product.get(dim)
            if val:
                merged[dim] = val
        records.append(merged)

    return records
