import json
import logging
import xml.etree.ElementTree as ElementTree

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_html(raw: str) -> BeautifulSoup:
    """Parse raw HTML into a BeautifulSoup tree.

    Uses lxml for speed; falls back to html.parser if lxml is unavailable.
    Never raises — returns an empty soup on total failure.
    """
    try:
        return BeautifulSoup(raw, "lxml")
    except Exception:
        try:
            return BeautifulSoup(raw, "html.parser")
        except Exception as exc:
            logger.error("parse_html failed: %s", exc)
            return BeautifulSoup("", "html.parser")


def parse_json(raw: str) -> dict:
    """Parse a JSON string into a dict.

    Returns {} on any error so callers never have to check for None.
    """
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
        # JSON arrays or primitives are not useful as a record root
        logger.warning("parse_json: top-level value is %s, not dict; returning {}", type(result).__name__)
        return {}
    except Exception as exc:
        logger.error("parse_json failed: %s", exc)
        return {}


def parse_xml(raw: str) -> ElementTree.Element | None:
    """Parse an XML string into an ElementTree Element.

    Returns None on any error.
    """
    try:
        return ElementTree.fromstring(raw)
    except Exception as exc:
        logger.error("parse_xml failed: %s", exc)
        return None


def parse_document(raw: str, fmt: str):
    """Route raw content to the correct parser based on fmt.

    fmt must be one of: "html", "json", "xml".
    Raises ValueError for unknown formats.
    """
    if fmt == "html":
        return parse_html(raw)
    if fmt == "json":
        return parse_json(raw)
    if fmt == "xml":
        return parse_xml(raw)
    raise ValueError(f"Unknown format '{fmt}'. Expected 'html', 'json', or 'xml'.")
