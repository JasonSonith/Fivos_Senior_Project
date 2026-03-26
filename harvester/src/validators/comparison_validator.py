def compare_records(harvested, gudid):
    results = {}

    fields = [
        "brandName",
        "versionModelNumber",
        "catalogNumber",
        "companyName",
        "deviceDescription",
    ]

    for field in fields:
        harvested_value = harvested.get(field)
        gudid_value = gudid.get(field)

        results[field] = {
            "harvested": harvested_value,
            "gudid": gudid_value,
            "match": harvested_value == gudid_value,
        }

    return results