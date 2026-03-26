from datetime import datetime, UTC
from harvester.src.database.db_connection import devices_collection, validation_collection
from harvester.src.validators.comparison_validator import compare_records
from harvester.src.validators.gudid_client import fetch_gudid_raw_text
from harvester.src.validators.ollama_client import extract_gudid_fields_with_ollama


def run_validator(query: dict | None = None) -> dict:
    devices = list(devices_collection.find(query or {}))
    print(f"Found {len(devices)} devices")

    total_devices = 0
    full_matches = 0
    partial_matches = 0
    mismatches = 0
    not_found = 0

    for device in devices:
        total_devices += 1

        di, raw_gudid_text = fetch_gudid_raw_text(
            catalog_number=device.get("catalogNumber"),
            version_model_number=device.get("versionModelNumber"),
        )

        if not raw_gudid_text:
            not_found += 1

            validation_collection.update_one(
                {"device_id": device.get("_id")},
                {
                    "$set": {
                        "device_id": device.get("_id"),
                        "brandName": device.get("brandName"),
                        "status": "gudid_not_found",
                        "matched_fields": 0,
                        "total_fields": 5,
                        "match_percent": 0.0,
                        "comparison_result": None,
                        "gudid_record": None,
                        "gudid_di": di,
                        "updated_at": datetime.now(UTC),
                    },
                    "$setOnInsert": {
                        "created_at": datetime.now(UTC),
                    },
                },
                upsert=True,
            )
            print(f"GUDID not found: {device.get('brandName')}")
            continue

        try:
            gudid_record = extract_gudid_fields_with_ollama(raw_gudid_text)
        except Exception as e:
            validation_collection.update_one(
                {"device_id": device.get("_id")},
                {
                    "$set": {
                        "device_id": device.get("_id"),
                        "brandName": device.get("brandName"),
                        "status": "ollama_failed",
                        "matched_fields": 0,
                        "total_fields": 5,
                        "match_percent": 0.0,
                        "comparison_result": None,
                        "gudid_record": None,
                        "gudid_di": di,
                        "error": str(e),
                        "updated_at": datetime.now(UTC),
                    },
                    "$setOnInsert": {
                        "created_at": datetime.now(UTC),
                    },
                },
                upsert=True,
            )
            print(f"Ollama failed: {device.get('brandName')}")
            continue

        result = compare_records(device, gudid_record)

        matched_fields = sum(1 for value in result.values() if value["match"])
        total_fields = len(result)
        match_percent = round((matched_fields / total_fields) * 100, 2) if total_fields > 0 else 0.0

        if matched_fields == total_fields:
            overall_status = "matched"
            full_matches += 1
        elif matched_fields > 0:
            overall_status = "partial_match"
            partial_matches += 1
        else:
            overall_status = "mismatch"
            mismatches += 1

        validation_collection.update_one(
            {"device_id": device.get("_id")},
            {
                "$set": {
                    "device_id": device.get("_id"),
                    "brandName": device.get("brandName"),
                    "status": overall_status,
                    "matched_fields": matched_fields,
                    "total_fields": total_fields,
                    "match_percent": match_percent,
                    "comparison_result": result,
                    "gudid_record": gudid_record,
                    "gudid_di": di,
                    "updated_at": datetime.now(UTC),
                },
                "$setOnInsert": {
                    "created_at": datetime.now(UTC),
                },
            },
            upsert=True,
        )

        print(f"{device.get('brandName')} → {matched_fields}/{total_fields} ({match_percent}%)")

    print("\n===== VALIDATION SUMMARY =====")
    print(f"Total Devices: {total_devices}")
    print(f"Full Matches: {full_matches}")
    print(f"Partial Matches: {partial_matches}")
    print(f"Mismatches: {mismatches}")
    print(f"GUDID Not Found: {not_found}")

    return {
        "total": total_devices,
        "full_matches": full_matches,
        "partial_matches": partial_matches,
        "mismatches": mismatches,
        "not_found": not_found,
    }


if __name__ == "__main__":
    run_validator()
