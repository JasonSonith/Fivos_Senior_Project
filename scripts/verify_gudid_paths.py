"""One-shot script — query Atlas for 5-10 validationResults docs with
stored gudid_record snapshots, print resolved values for each planned
Layer-2 path."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "harvester" / "src"))

from database.db_connection import get_db


PATHS_TO_CHECK = [
    ("gmdnPTName", lambda d: ((d.get("gmdnTerms") or {}).get("gmdn") or [{}])[0].get("gmdnPTName") if ((d.get("gmdnTerms") or {}).get("gmdn") or []) else None),
    ("gmdnCode",   lambda d: ((d.get("gmdnTerms") or {}).get("gmdn") or [{}])[0].get("gmdnCode") if ((d.get("gmdnTerms") or {}).get("gmdn") or []) else None),
    ("productCodes", lambda d: [pc.get("productCode") for pc in ((d.get("productCodes") or {}).get("fdaProductCode") or []) if isinstance(pc, dict) and pc.get("productCode")]),
    ("deviceCountInBase",  lambda d: d.get("deviceCountInBase")),
    ("publishDate",        lambda d: d.get("publishDate") or d.get("devicePublishDate")),
    ("deviceRecordStatus", lambda d: d.get("deviceRecordStatus")),
    ("issuingAgency",      lambda d: (((d.get("identifiers") or {}).get("identifier") or [{}])[0] or {}).get("issuingAgency") if ((d.get("identifiers") or {}).get("identifier") or []) else None),
    ("lotBatch",           lambda d: (((d.get("identifiers") or {}).get("identifier") or [{}])[0] or {}).get("lotBatch") if ((d.get("identifiers") or {}).get("identifier") or []) else None),
    ("serialNumber",       lambda d: (((d.get("identifiers") or {}).get("identifier") or [{}])[0] or {}).get("serialNumber") if ((d.get("identifiers") or {}).get("identifier") or []) else None),
    ("manufacturingDate",  lambda d: (((d.get("identifiers") or {}).get("identifier") or [{}])[0] or {}).get("manufacturingDate") if ((d.get("identifiers") or {}).get("identifier") or []) else None),
    ("expirationDate",     lambda d: (((d.get("identifiers") or {}).get("identifier") or [{}])[0] or {}).get("expirationDate") if ((d.get("identifiers") or {}).get("identifier") or []) else None),
]


def main():
    db = get_db()
    samples = list(db["validationResults"].find(
        {"gudid_record": {"$ne": None}},
        {"gudid_record": 1, "gudid_di": 1, "brandName": 1},
    ).limit(10))

    if not samples:
        print("No validationResults with gudid_record found. Run a validation first.")
        return

    print(f"Checking {len(samples)} real GUDID responses:\n")
    for doc in samples:
        gudid = doc.get("gudid_record") or {}
        print(f"=== {doc.get('brandName')} (DI: {doc.get('gudid_di')}) ===")
        for path_name, resolver in PATHS_TO_CHECK:
            try:
                value = resolver(gudid)
                if isinstance(value, str) and len(value) > 80:
                    value_repr = f"{value[:77]!r}... (truncated)"
                else:
                    value_repr = repr(value)
                print(f"  {path_name:<22} = {value_repr}")
            except Exception as e:
                print(f"  {path_name:<22} = EXCEPTION: {type(e).__name__}: {e}")
        print()


if __name__ == "__main__":
    main()
