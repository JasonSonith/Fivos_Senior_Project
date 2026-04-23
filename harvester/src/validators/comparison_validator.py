import re

from normalizers.booleans import normalize_boolean, normalize_mri_status
from normalizers.text import clean_brand_name
from normalizers.unit_conversions import normalize_measurement
from validators.company_aliases import canonical_company


class FieldStatus:
    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_COMPARED = "not_compared"
    BOTH_NULL = "both_null"
    CORPORATE_ALIAS = "corporate_alias"
    SKU_LABEL_SKIP = "sku_label_skip"


FIELD_WEIGHTS = {
    "versionModelNumber": 3, "catalogNumber": 3,
    "brandName": 3,          "companyName": 3,
    "MRISafetyStatus": 2, "singleUse": 2, "rx": 2,
    "deviceDescription": 1,
    # Layer-2 additions
    "gmdnPTName": 3, "gmdnCode": 2, "productCodes": 3,
    "deviceCountInBase": 2, "issuingAgency": 2,
    "lotBatch": 1, "serialNumber": 1,
    "manufacturingDate": 1, "expirationDate": 1,
    "premarketSubmissions": 2,
}

_SCORED_STATUSES = {FieldStatus.MATCH, FieldStatus.CORPORATE_ALIAS, FieldStatus.MISMATCH}
_NUMERATOR_STATUSES = {FieldStatus.MATCH, FieldStatus.CORPORATE_ALIAS}


def _norm_model(value):
    if not value:
        return ""
    return re.sub(r"[\s\-\.]", "", str(value)).upper()


def _norm_brand(value):
    cleaned = clean_brand_name(value) if value else None
    return (cleaned or "").lower()


def _norm_company(value):
    if not value:
        return ""
    cleaned = re.sub(r"[,\.&']", "", str(value))
    return re.sub(r"\s+", " ", cleaned).strip().upper()


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    s1 = set(str(a).lower().split())
    s2 = set(str(b).lower().split())
    union = s1 | s2
    if not union:
        return 0.0
    return round(len(s1 & s2) / len(union), 4)


def _compare_normalized(harvested, gudid, normalizer):
    h_norm = normalizer(harvested) if harvested is not None else None
    g_norm = normalizer(gudid) if gudid is not None else None
    if h_norm is None or g_norm is None:
        return None, h_norm, g_norm
    return h_norm == g_norm, h_norm, g_norm


# GUDID long-form unit → short code recognized by normalize_measurement.
_GUDID_UNIT_SHORT = {
    "Millimeter": "mm",
    "Centimeter": "cm",
    "Meter": "m",
    "Inch": "in",
    "French": "Fr",
    "Gram": "g",
    "Kilogram": "kg",
    "Milliliter": "mL",
    "Millimeter Mercury": "mmHg",
}


def _canonicalize_size_entry(entry: dict) -> dict | None:
    """Convert a GUDID-shaped size entry to {sizeType, value, canonical_unit}.

    Returns None when the entry lacks a numeric size, has an unknown unit,
    or has an unparseable value.
    """
    if not isinstance(entry, dict):
        return None
    size_type = entry.get("sizeType")
    size = entry.get("size")
    if not size_type or not isinstance(size, dict):
        return None
    raw_unit = size.get("unit")
    raw_value = size.get("value")
    if raw_unit is None or raw_value is None:
        return None
    short_unit = _GUDID_UNIT_SHORT.get(raw_unit)
    if short_unit is None:
        return None
    normalized = normalize_measurement(f"{raw_value} {short_unit}")
    value = normalized.get("value")
    canonical_unit = normalized.get("unit")
    if value is None or canonical_unit is None:
        return None
    return {
        "sizeType": size_type,
        "value": value,
        "canonical_unit": canonical_unit,
    }


_SKU_PATTERN_RE = re.compile(r"^[A-Z0-9\-_ ]+$")


def _gudid_description_is_sku_label(
    gudid_value: str | None,
    model_number: str | None,
    catalog_number: str | None,
) -> bool:
    if not gudid_value or not isinstance(gudid_value, str):
        return False
    stripped = gudid_value.strip()
    if not stripped:
        return False
    if len(stripped) < 40:
        return True
    lowered = stripped.lower()
    for ident in (model_number, catalog_number):
        if ident and isinstance(ident, str) and ident.lower() in lowered:
            return True
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) >= 3:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio >= 0.70:
            return True
    if _SKU_PATTERN_RE.fullmatch(stripped):
        return True
    return False


def _is_null(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, tuple)) and len(value) == 0:
        return True
    return False


def _status_from_bool(match):
    if match is True:
        return FieldStatus.MATCH
    if match is False:
        return FieldStatus.MISMATCH
    return FieldStatus.NOT_COMPARED


def _subset_match(h_list, g_list):
    if set(h_list) <= set(g_list):
        return FieldStatus.MATCH
    return FieldStatus.MISMATCH


def _build_summary(per_field):
    numerator = 0
    denominator = 0
    unweighted_num = 0
    unweighted_den = 0
    for field, result in per_field.items():
        status = result.get("status")
        if field == "deviceDescription":
            if status == FieldStatus.MATCH:
                weight = FIELD_WEIGHTS.get(field, 1)
                numerator += weight
                denominator += weight
            elif status == FieldStatus.MISMATCH:
                denominator += FIELD_WEIGHTS.get(field, 1)
            continue
        if status in _SCORED_STATUSES:
            unweighted_den += 1
            weight = FIELD_WEIGHTS.get(field, 1)
            denominator += weight
            if status in _NUMERATOR_STATUSES:
                unweighted_num += 1
                numerator += weight
    return {
        "numerator": numerator,
        "denominator": denominator,
        "unweighted_numerator": unweighted_num,
        "unweighted_denominator": unweighted_den,
    }


def compare_records(harvested, gudid):
    results = {}

    for field in ("versionModelNumber", "catalogNumber"):
        h = harvested.get(field)
        g = gudid.get(field)
        if _is_null(h) and _is_null(g):
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.BOTH_NULL}
            continue
        if not h:
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.NOT_COMPARED}
        else:
            match = bool(g and _norm_model(h) == _norm_model(g))
            results[field] = {
                "harvested": h, "gudid": g,
                "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
            }

    h_brand = harvested.get("brandName")
    g_brand = gudid.get("brandName")
    if _is_null(h_brand) and _is_null(g_brand):
        results["brandName"] = {"harvested": h_brand, "gudid": g_brand, "status": FieldStatus.BOTH_NULL}
    elif not h_brand:
        results["brandName"] = {"harvested": h_brand, "gudid": g_brand, "status": FieldStatus.NOT_COMPARED}
    else:
        match = bool(g_brand and _norm_brand(h_brand) == _norm_brand(g_brand))
        results["brandName"] = {
            "harvested": h_brand, "gudid": g_brand,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }

    h_company = harvested.get("companyName"); g_company = gudid.get("companyName")
    if _is_null(h_company) and _is_null(g_company):
        results["companyName"] = {"harvested": h_company, "gudid": g_company, "status": FieldStatus.BOTH_NULL}
    elif _is_null(h_company):
        results["companyName"] = {"harvested": h_company, "gudid": g_company, "status": FieldStatus.NOT_COMPARED}
    else:
        if g_company and _norm_company(h_company) == _norm_company(g_company):
            results["companyName"] = {"harvested": h_company, "gudid": g_company, "status": FieldStatus.MATCH}
        else:
            h_canonical = canonical_company(h_company)
            g_canonical = canonical_company(g_company)
            if h_canonical and g_canonical and h_canonical == g_canonical:
                results["companyName"] = {
                    "harvested": h_company, "gudid": g_company,
                    "status": FieldStatus.CORPORATE_ALIAS,
                    "alias_group": h_canonical,
                }
            else:
                results["companyName"] = {
                    "harvested": h_company, "gudid": g_company,
                    "status": FieldStatus.MISMATCH,
                }

    h_desc = harvested.get("deviceDescription"); g_desc = gudid.get("deviceDescription")
    model_no = harvested.get("versionModelNumber")
    catalog_no = harvested.get("catalogNumber")
    if _is_null(h_desc) and _is_null(g_desc):
        results["deviceDescription"] = {
            "harvested": h_desc, "gudid": g_desc,
            "status": FieldStatus.BOTH_NULL,
            "similarity": None,
        }
    elif _gudid_description_is_sku_label(g_desc, model_no, catalog_no):
        results["deviceDescription"] = {
            "harvested": h_desc, "gudid": g_desc,
            "status": FieldStatus.SKU_LABEL_SKIP,
            "similarity": None,
        }
    else:
        sim = _jaccard(h_desc, g_desc)
        results["deviceDescription"] = {
            "harvested": h_desc, "gudid": g_desc,
            "status": FieldStatus.MATCH,
            "similarity": sim,
        }

    for field, normalizer in (
        ("MRISafetyStatus", normalize_mri_status),
        ("singleUse", normalize_boolean),
        ("rx", normalize_boolean),
    ):
        h = harvested.get(field)
        g = gudid.get(field)
        if _is_null(h) and _is_null(g):
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.BOTH_NULL}
            continue
        match, _, _ = _compare_normalized(h, g, normalizer)
        results[field] = {
            "harvested": h, "gudid": g,
            "status": _status_from_bool(match),
        }

    # --- Layer 2 fields ---

    # gmdnPTName — case-insensitive exact
    h = harvested.get("gmdnPTName"); g = gudid.get("gmdnPTName")
    if _is_null(h) and _is_null(g):
        results["gmdnPTName"] = {"harvested": h, "gudid": g, "status": FieldStatus.BOTH_NULL}
    elif _is_null(h):
        results["gmdnPTName"] = {"harvested": h, "gudid": g, "status": FieldStatus.NOT_COMPARED}
    else:
        match = bool(g and isinstance(h, str) and isinstance(g, str)
                     and h.strip().lower() == g.strip().lower())
        results["gmdnPTName"] = {
            "harvested": h, "gudid": g,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }

    # gmdnCode, issuingAgency — case-sensitive exact
    for field in ("gmdnCode", "issuingAgency"):
        h = harvested.get(field); g = gudid.get(field)
        if _is_null(h) and _is_null(g):
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.BOTH_NULL}
            continue
        if _is_null(h):
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.NOT_COMPARED}
            continue
        match = bool(g and str(h).strip() == str(g).strip())
        results[field] = {
            "harvested": h, "gudid": g,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }

    # productCodes — subset match (asymmetric)
    h_pc = harvested.get("productCodes"); g_pc = gudid.get("productCodes")
    if _is_null(h_pc) and _is_null(g_pc):
        results["productCodes"] = {"harvested": h_pc, "gudid": g_pc, "status": FieldStatus.BOTH_NULL}
    elif _is_null(h_pc):
        results["productCodes"] = {"harvested": h_pc, "gudid": g_pc, "status": FieldStatus.NOT_COMPARED}
    elif _is_null(g_pc):
        results["productCodes"] = {"harvested": h_pc, "gudid": g_pc, "status": FieldStatus.MISMATCH}
    else:
        results["productCodes"] = {
            "harvested": h_pc, "gudid": g_pc,
            "status": _subset_match(h_pc, g_pc),
        }

    # deviceCountInBase — integer equality
    h_count = harvested.get("deviceCountInBase"); g_count = gudid.get("deviceCountInBase")
    if _is_null(h_count) and _is_null(g_count):
        results["deviceCountInBase"] = {"harvested": h_count, "gudid": g_count, "status": FieldStatus.BOTH_NULL}
    elif _is_null(h_count):
        results["deviceCountInBase"] = {"harvested": h_count, "gudid": g_count, "status": FieldStatus.NOT_COMPARED}
    else:
        match = False
        try:
            match = int(h_count) == int(g_count) if g_count is not None else False
        except (TypeError, ValueError):
            match = False
        results["deviceCountInBase"] = {
            "harvested": h_count, "gudid": g_count,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }

    # Labeled-identifier booleans — normalize_boolean, null-asymmetric
    for field in ("lotBatch", "serialNumber", "manufacturingDate", "expirationDate"):
        h = harvested.get(field); g = gudid.get(field)
        if _is_null(h) and _is_null(g):
            results[field] = {"harvested": h, "gudid": g, "status": FieldStatus.BOTH_NULL}
            continue
        match, _, _ = _compare_normalized(h, g, normalize_boolean)
        results[field] = {
            "harvested": h, "gudid": g,
            "status": _status_from_bool(match),
        }

    # premarketSubmissions — subset match (same semantics as productCodes)
    h_pm = harvested.get("premarketSubmissions"); g_pm = gudid.get("premarketSubmissions")
    if _is_null(h_pm) and _is_null(g_pm):
        results["premarketSubmissions"] = {"harvested": h_pm, "gudid": g_pm, "status": FieldStatus.BOTH_NULL}
    elif _is_null(h_pm):
        results["premarketSubmissions"] = {"harvested": h_pm, "gudid": g_pm, "status": FieldStatus.NOT_COMPARED}
    elif _is_null(g_pm):
        results["premarketSubmissions"] = {"harvested": h_pm, "gudid": g_pm, "status": FieldStatus.MISMATCH}
    else:
        results["premarketSubmissions"] = {
            "harvested": h_pm, "gudid": g_pm,
            "status": _subset_match(h_pm, g_pm),
        }

    summary = _build_summary(results)
    return results, summary
