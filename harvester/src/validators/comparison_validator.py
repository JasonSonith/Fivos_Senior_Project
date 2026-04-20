import re

from normalizers.booleans import normalize_boolean, normalize_mri_status


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
    """Normalize both sides then exact-compare.

    Returns (match, h_norm, g_norm). match is None if either side
    normalizes to None (skipped from score denominator).
    """
    h_norm = normalizer(harvested) if harvested is not None else None
    g_norm = normalizer(gudid) if gudid is not None else None
    if h_norm is None or g_norm is None:
        return None, h_norm, g_norm
    return h_norm == g_norm, h_norm, g_norm


def compare_records(harvested, gudid):
    results = {}

    # Model number fields — normalize (uppercase, strip spaces/hyphens/dots)
    # match=None means "not compared" (harvested value missing)
    for field in ("versionModelNumber", "catalogNumber"):
        h = harvested.get(field)
        g = gudid.get(field)
        if not h:
            results[field] = {"harvested": h, "gudid": g, "match": None}
        else:
            results[field] = {
                "harvested": h,
                "gudid": g,
                "match": bool(g and _norm_model(h) == _norm_model(g)),
            }

    # Brand name — case-insensitive, strip trademark symbols
    h_brand = harvested.get("brandName")
    g_brand = gudid.get("brandName")
    if not h_brand:
        results["brandName"] = {"harvested": h_brand, "gudid": g_brand, "match": None}
    else:
        results["brandName"] = {
            "harvested": h_brand,
            "gudid": g_brand,
            "match": bool(g_brand and _norm_brand(h_brand) == _norm_brand(g_brand)),
        }

    # Company name — uppercase, strip punctuation
    h_company = harvested.get("companyName")
    g_company = gudid.get("companyName")
    if not h_company:
        results["companyName"] = {"harvested": h_company, "gudid": g_company, "match": None}
    else:
        results["companyName"] = {
            "harvested": h_company,
            "gudid": g_company,
            "match": bool(g_company and _norm_company(h_company) == _norm_company(g_company)),
        }

    # Device description — Jaccard similarity score, not a boolean match
    h_desc = harvested.get("deviceDescription")
    g_desc = gudid.get("deviceDescription")
    results["deviceDescription"] = {
        "harvested": h_desc,
        "gudid": g_desc,
        "description_similarity": _jaccard(h_desc, g_desc),
    }

    # MRI safety status — enum; normalize both sides. Skip if either normalizes to None.
    h_mri = harvested.get("MRISafetyStatus")
    g_mri = gudid.get("MRISafetyStatus")
    match, _, _ = _compare_normalized(h_mri, g_mri, normalize_mri_status)
    results["MRISafetyStatus"] = {"harvested": h_mri, "gudid": g_mri, "match": match}

    # Single use — boolean; normalize both sides. Skip if either normalizes to None.
    h_su = harvested.get("singleUse")
    g_su = gudid.get("singleUse")
    match, _, _ = _compare_normalized(h_su, g_su, normalize_boolean)
    results["singleUse"] = {"harvested": h_su, "gudid": g_su, "match": match}

    # Prescription (Rx) — boolean; same strategy as singleUse.
    h_rx = harvested.get("rx")
    g_rx = gudid.get("rx")
    match, _, _ = _compare_normalized(h_rx, g_rx, normalize_boolean)
    results["rx"] = {"harvested": h_rx, "gudid": g_rx, "match": match}

    return results
