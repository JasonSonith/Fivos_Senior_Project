from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

DANGEROUS_TAGS = ["script", "iframe", "object", "embed", "form"]


def sanitize_html(raw_html: str) -> str:
    try:
        soup = BeautifulSoup(raw_html, "lxml")
    except Exception:
        soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all(DANGEROUS_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on"):
                del tag[attr]
    return str(soup)