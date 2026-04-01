import logging
import xml.etree.ElementTree as ElementTree

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _json_dot_get(data: dict, path: str):
    """Walk a nested dict using dot-notation path.

    Example: "product.dimensions.length" → data["product"]["dimensions"]["length"]
    Returns None if any key is missing or data is not a dict at any level.
    """
    parts = path.split(".")
    current = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def extract_fields(parsed_data, adapter: dict, fmt: str) -> dict:
    """Extract device fields from parsed content using adapter-defined selectors.

    Args:
        parsed_data: BeautifulSoup (html), dict (json), or ElementTree.Element (xml).
        adapter: Adapter config dict with an "extraction" block mapping field names to selectors.
        fmt: "html" | "json" | "xml"

    Returns:
        Dict of field_name -> raw string value (or None if not found).
    """
    raw_fields = {}
    selectors = adapter.get("extraction", {})

    for field_name, selector in selectors.items():
        value = None

        if not selector or not str(selector).strip():
            logger.warning("Field '%s' has empty selector, skipping", field_name)
            raw_fields[field_name] = None
            continue

        try:
            if fmt == "html":
                if not isinstance(parsed_data, BeautifulSoup):
                    logger.warning("extract_fields: expected BeautifulSoup for html, got %s", type(parsed_data).__name__)
                else:
                    element = parsed_data.select_one(selector)
                    if element is not None:
                        value = element.get_text(strip=True)

            elif fmt == "json":
                if not isinstance(parsed_data, dict):
                    logger.warning("extract_fields: expected dict for json, got %s", type(parsed_data).__name__)
                else:
                    value = _json_dot_get(parsed_data, selector)
                    if value is not None:
                        value = str(value)

            elif fmt == "xml":
                if not isinstance(parsed_data, ElementTree.Element):
                    logger.warning("extract_fields: expected Element for xml, got %s", type(parsed_data).__name__)
                else:
                    value = parsed_data.findtext(selector)

            else:
                logger.error("extract_fields: unknown format '%s'", fmt)

        except Exception as exc:
            logger.error("extract_fields: error extracting field '%s' with selector '%s': %s", field_name, selector, exc)

        if value is None:
            logger.warning("Field '%s' not found with selector '%s' (fmt=%s)", field_name, selector, fmt)

        raw_fields[field_name] = value

    return raw_fields
