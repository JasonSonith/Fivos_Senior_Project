import re

from normalizers.booleans import normalize_boolean, normalize_mri_status


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
}

_SCORED_STATUSES = {FieldStatus.MATCH, FieldStatus.CORPORATE_ALIAS, FieldStatus.MISMATCH}
_NUMERATOR_STATUSES = {FieldStatus.MATCH, FieldStatus.CORPORATE_ALIAS}


def _norm_model(value):
    if not value:
        return ""
    return re.sub(r"[\s\-\.]", "", str(value)).upper()


def _norm_brand(value):
    if not value:
        return ""
    cleaned = re.sub(r"[™®†°]", "", str(value))
    return re.sub(r"\s+", " ", cleaned).strip().lower()


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


def _status_from_bool(match):
    if match is True:
        return FieldStatus.MATCH
    if match is False:
        return FieldStatus.MISMATCH
    return FieldStatus.NOT_COMPARED


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
    if not h_brand:
        results["brandName"] = {"harvested": h_brand, "gudid": g_brand, "status": FieldStatus.NOT_COMPARED}
    else:
        match = bool(g_brand and _norm_brand(h_brand) == _norm_brand(g_brand))
        results["brandName"] = {
            "harvested": h_brand, "gudid": g_brand,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }

    h_company = harvested.get("companyName")
    g_company = gudid.get("companyName")
    if not h_company:
        results["companyName"] = {"harvested": h_company, "gudid": g_company, "status": FieldStatus.NOT_COMPARED}
    else:
        match = bool(g_company and _norm_company(h_company) == _norm_company(g_company))
        results["companyName"] = {
            "harvested": h_company, "gudid": g_company,
            "status": FieldStatus.MATCH if match else FieldStatus.MISMATCH,
        }

    h_desc = harvested.get("deviceDescription")
    g_desc = gudid.get("deviceDescription")
    if not h_desc and not g_desc:
        results["deviceDescription"] = {
            "harvested": h_desc, "gudid": g_desc,
            "status": FieldStatus.NOT_COMPARED,
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
        match, _, _ = _compare_normalized(h, g, normalizer)
        results[field] = {
            "harvested": h, "gudid": g,
            "status": _status_from_bool(match),
        }

    summary = _build_summary(results)
    return results, summary
