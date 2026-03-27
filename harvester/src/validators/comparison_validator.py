import re


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

    return results