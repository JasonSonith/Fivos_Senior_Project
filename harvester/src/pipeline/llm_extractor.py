import json
import logging
import os
import re
import time

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
OLLAMA_URL = "http://localhost:11434/api/chat"

MODEL_CHAIN = [
    {"provider": "groq",   "model": "llama-3.3-70b-versatile",     "env_key": "GROQ_API_KEY"},
    {"provider": "groq",   "model": "llama-3.1-8b-instant",        "env_key": "GROQ_API_KEY"},
    {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "env_key": "NVIDIA_API_KEY"},
    {"provider": "nvidia", "model": "mistralai/mistral-large",     "env_key": "NVIDIA_API_KEY"},
    {"provider": "nvidia", "model": "google/gemma-2-27b-it",       "env_key": "NVIDIA_API_KEY"},
    {"provider": "ollama", "model": "qwen2.5:7b"},
    {"provider": "ollama", "model": "mistral"},
]

# Track which models have been confirmed unavailable this session
_disabled_models: set[str] = set()

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


def _openai_request(url: str, api_key: str, model: str, messages: list[dict],
                    timeout: int = 60, _retry: bool = False) -> dict | None:
    """Send a request to an OpenAI-compatible API (Groq, NVIDIA NIM)."""
    payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }

    try:
        response = requests.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            detail = exc.response.json().get("error", {}).get("message", str(exc))
        except Exception:
            detail = str(exc)

        if "rate limit" in detail.lower() and not _retry:
            match = re.search(r"try again in (\d+\.?\d*)s", detail)
            if match and float(match.group(1)) < 60:
                wait = float(match.group(1))
                logger.info("%s rate limited, retrying in %.1fs", model, wait)
                time.sleep(wait)
                return _openai_request(url, api_key, model, messages, timeout, _retry=True)
            # Daily limit or long wait — skip this model
            logger.warning("%s rate limited (long wait), moving to next model: %s", model, detail)
            _disabled_models.add(model)
            return None

        logger.warning("%s request failed: %s", model, detail)
        return None
    except Exception as exc:
        logger.warning("%s request failed: %s", model, exc)
        return None

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            return content
        return json.loads(content)
    except Exception as exc:
        logger.warning("Failed to parse %s response: %s", model, exc)
        return None


def _ollama_request(model: str, messages: list[dict], schema: dict,
                    timeout: int = 60) -> dict | None:
    """Send a request to local Ollama."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": schema,
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.ConnectionError:
        logger.warning("Ollama not available at %s", OLLAMA_URL)
        _disabled_models.add("ollama")
        return None
    except Exception as exc:
        logger.warning("Ollama %s request failed: %s", model, exc)
        return None

    try:
        data = response.json()
        content = data["message"]["content"]
        if isinstance(content, dict):
            return content
        return json.loads(content)
    except Exception as exc:
        logger.warning("Failed to parse Ollama %s response: %s", model, exc)
        return None


# Track which model answered the last request
_last_model_used: str | None = None


def get_last_model() -> str | None:
    return _last_model_used


def get_first_available_model() -> str:
    """Return the name of the first model in the chain that has credentials configured."""
    for entry in MODEL_CHAIN:
        env_key = entry.get("env_key")
        if env_key and not os.environ.get(env_key):
            continue
        return entry["model"]
    return "none"


def _llm_request(system_msg: str, user_msg: str, schema: dict, timeout: int = 60) -> dict | None:
    """Try each model in MODEL_CHAIN until one succeeds."""
    global _last_model_used

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    provider_urls = {"groq": GROQ_URL, "nvidia": NVIDIA_URL}

    for entry in MODEL_CHAIN:
        model = entry["model"]
        provider = entry["provider"]

        if model in _disabled_models:
            continue
        if provider == "ollama" and "ollama" in _disabled_models:
            continue

        env_key = entry.get("env_key")
        if env_key:
            api_key = os.environ.get(env_key)
            if not api_key:
                continue

        if provider in ("groq", "nvidia"):
            result = _openai_request(provider_urls[provider], api_key, model, messages, timeout)
        else:
            result = _ollama_request(model, messages, schema, timeout)

        if result is not None:
            _last_model_used = model
            logger.info("Extraction succeeded with %s (%s)", model, provider)
            return result

        logger.info("Model %s failed, trying next in chain", model)

    logger.error("All models in chain exhausted, extraction failed")
    return None


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

    source = get_last_model() or "unknown"

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
