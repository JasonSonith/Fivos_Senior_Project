import requests
from bs4 import BeautifulSoup


SEARCH_URL = "https://accessgudid.nlm.nih.gov/devices/search"
LOOKUP_URL = "https://accessgudid.nlm.nih.gov/api/v3/devices/lookup.json"


def search_gudid_di(catalog_number=None, version_model_number=None):
    query = catalog_number or version_model_number
    if not query:
        return None

    response = requests.get(SEARCH_URL, params={"query": query}, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("/devices/"):
            di = href.split("/devices/")[-1].strip()
            if di.isdigit():
                return di

    return None


def fetch_gudid_raw_text(catalog_number=None, version_model_number=None):
    di = search_gudid_di(
        catalog_number=catalog_number,
        version_model_number=version_model_number,
    )

    if not di:
        return None, None

    response = requests.get(LOOKUP_URL, params={"di": di}, timeout=15)
    response.raise_for_status()

    data = response.json()
    device = data.get("gudid", {}).get("device", {})

    if not device:
        return di, None

    raw_text = f"""
DI: {di}
Brand Name: {device.get("brandName")}
Version or Model Number: {device.get("versionModelNumber")}
Catalog Number: {device.get("catalogNumber")}
Company Name: {device.get("companyName")}
Device Description: {device.get("deviceDescription")}
"""

    return di, raw_text