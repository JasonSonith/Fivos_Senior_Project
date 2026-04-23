import requests
from bs4 import BeautifulSoup


SEARCH_URL = "https://accessgudid.nlm.nih.gov/devices/search"
LOOKUP_URL = "https://accessgudid.nlm.nih.gov/api/v3/devices/lookup.json"

REQUEST_TIMEOUT = 60  # seconds


def search_gudid_di(catalog_number=None, version_model_number=None):
    """Search the GUDID HTML search page to find a Device Identifier (DI).

    This is the only way to find a DI by model/catalog number since the
    JSON API only accepts DI or UDI as parameters.
    """
    query = catalog_number or version_model_number
    if not query:
        return None

    response = requests.get(SEARCH_URL, params={"query": query}, timeout=REQUEST_TIMEOUT)
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
    env = device.get("environmentalConditions") or {}
    handling = env.get("storageHandling") or []
    texts = [
        item.get("specialConditionText", "").strip()
        for item in handling
        if item.get("specialConditionText", "").strip()
    ]
    return {"conditions": texts} if texts else None


def _extract_device_sizes(device: dict) -> list[dict] | None:
    """Flatten GUDID deviceSizes.deviceSize[] into a list.

    Returns None when the array is missing or empty. Filters out non-dict
    entries and entries missing sizeType. Never raises.
    """
    sizes_obj = device.get("deviceSizes") or {}
    if not isinstance(sizes_obj, dict):
        return None
    size_list = sizes_obj.get("deviceSize") or []
    if not isinstance(size_list, list):
        return None
    flattened = [
        entry for entry in size_list
        if isinstance(entry, dict) and entry.get("sizeType")
    ]
    return flattened if flattened else None


def _extract_new_fields(device: dict) -> dict:
    gmdn_terms = device.get("gmdnTerms") or {}
    if not isinstance(gmdn_terms, dict):
        gmdn_terms = {}
    gmdn_list = gmdn_terms.get("gmdn") or []
    if not isinstance(gmdn_list, list):
        gmdn_list = []
    first_gmdn = gmdn_list[0] if gmdn_list and isinstance(gmdn_list[0], dict) else {}

    product_codes_obj = device.get("productCodes") or {}
    if not isinstance(product_codes_obj, dict):
        product_codes_obj = {}
    fda_codes = product_codes_obj.get("fdaProductCode") or []
    if not isinstance(fda_codes, list):
        fda_codes = []
    product_codes = [
        pc.get("productCode") for pc in fda_codes
        if isinstance(pc, dict) and pc.get("productCode")
    ] or None

    identifiers_obj = device.get("identifiers") or {}
    if not isinstance(identifiers_obj, dict):
        identifiers_obj = {}
    identifier_list = identifiers_obj.get("identifier") or []
    if not isinstance(identifier_list, list):
        identifier_list = []
    primary_ids = [
        i for i in identifier_list
        if isinstance(i, dict) and i.get("deviceIdType") == "Primary"
    ]
    if primary_ids:
        first_id = primary_ids[0]
    elif identifier_list and isinstance(identifier_list[0], dict):
        first_id = identifier_list[0]
    else:
        first_id = {}

    return {
        "gmdnPTName": first_gmdn.get("gmdnPTName"),
        "gmdnCode": first_gmdn.get("gmdnCode"),
        "productCodes": product_codes,
        "deviceCountInBase": device.get("deviceCount"),
        "publishDate": device.get("devicePublishDate"),
        "deviceRecordStatus": device.get("deviceRecordStatus"),
        "issuingAgency": first_id.get("deviceIdIssuingAgency"),
        "lotBatch": device.get("lotBatch"),
        "serialNumber": device.get("serialNumber"),
        "manufacturingDate": device.get("manufacturingDate"),
        "expirationDate": device.get("expirationDate"),
    }


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

    response = requests.get(LOOKUP_URL, params={"di": di}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    data = response.json()
    device = data.get("gudid", {}).get("device", {})

    if not device:
        return di, None

    sterilization = device.get("sterilization") or {}
    pmk = device.get("premarketSubmissions") or {}
    submissions = pmk.get("premarketSubmission") or []
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
        "deviceSterile": sterilization.get("deviceSterile"),
        "deviceKit": device.get("deviceKit"),
        "premarketSubmissions": submission_numbers or None,
        "environmentalConditions": _extract_storage_conditions(device),
        "deviceSizes": _extract_device_sizes(device),
        **_extract_new_fields(device),
    }


def lookup_by_di(di):
    """Direct lookup by Device Identifier. Returns full device dict or None."""
    if not di:
        return None

    try:
        response = requests.get(LOOKUP_URL, params={"di": di}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data.get("gudid", {}).get("device")
    except requests.RequestException as e:
        print(f"GUDID lookup_by_di failed: {e}")
        return None
    except ValueError as e:
        print(f"GUDID lookup_by_di JSON parse failed: {e}")
        return None