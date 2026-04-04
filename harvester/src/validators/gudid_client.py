import requests
from bs4 import BeautifulSoup


SEARCH_URL = "https://accessgudid.nlm.nih.gov/devices/search"
LOOKUP_URL = "https://accessgudid.nlm.nih.gov/api/v3/devices/lookup.json"


def search_gudid_di(catalog_number=None, version_model_number=None):
    """Search the GUDID HTML search page to find a Device Identifier (DI).

    This is the only way to find a DI by model/catalog number since the
    JSON API only accepts DI or UDI as parameters.
    """
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


def _extract_storage_conditions(device: dict) -> dict | None:
    """Extract storage/handling conditions from GUDID device dict.

    Returns {"conditions": [...text strings...]} or None if empty.
    """
    handling = device.get("environmentalConditions", {}).get("storageHandling") or []
    texts = [
        item.get("specialConditionText", "").strip()
        for item in handling
        if item.get("specialConditionText", "").strip()
    ]
    return {"conditions": texts} if texts else None


def fetch_gudid_record(catalog_number=None, version_model_number=None):
    """Search for DI, then fetch structured device record from GUDID API.

    Returns (di, record_dict) where record_dict contains all MERGE_FIELDS,
    or (di, None) if device not found, or (None, None) if search fails.
    """
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

    sterilization = device.get("sterilization") or {}
    submissions = (
        device.get("premarketSubmissions", {}).get("premarketSubmission") or []
    )
    submission_numbers = [
        s["submissionNumber"] for s in submissions if s.get("submissionNumber")
    ]

    return di, {
        "brandName": device.get("brandName"),
        "versionModelNumber": device.get("versionModelNumber"),
        "catalogNumber": device.get("catalogNumber"),
        "companyName": device.get("companyName"),
        "deviceDescription": device.get("deviceDescription"),
        "MRISafetyStatus": device.get("MRISafetyStatus"),
        "singleUse": device.get("singleUse"),
        "rx": device.get("rx"),
        "otc": device.get("otc"),
        "labeledContainsNRL": device.get("labeledContainsNRL"),
        "labeledNoNRL": device.get("labeledNoNRL"),
        "sterilizationPriorToUse": sterilization.get("sterilizationPriorToUse"),
        "deviceKit": device.get("deviceKit"),
        "premarketSubmissions": submission_numbers or None,
        "environmentalConditions": _extract_storage_conditions(device),
    }


def lookup_by_di(di):
    """Direct lookup by Device Identifier. Returns full device dict or None."""
    if not di:
        return None

    response = requests.get(LOOKUP_URL, params={"di": di}, timeout=15)
    response.raise_for_status()

    data = response.json()
    return data.get("gudid", {}).get("device")
