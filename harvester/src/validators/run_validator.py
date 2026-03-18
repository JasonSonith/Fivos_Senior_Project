import json
from pathlib import Path
from typing import Any, Dict, List

from comparison_validator import ComparisonValidator


def extract_dimensions(device_sizes: Any) -> str | None:
    if not device_sizes or not isinstance(device_sizes, list):
        return None

    parts: List[str] = []

    for item in device_sizes:
        if not isinstance(item, dict):
            continue

        size_type = item.get("sizeType")
        size_data = item.get("size", {})
        size_value = size_data.get("value") if isinstance(size_data, dict) else None
        size_unit = size_data.get("unit") if isinstance(size_data, dict) else None

        if size_value in (None, "", "None"):
            continue

        piece = ""

        if size_type:
            piece += f"{size_type}:"

        piece += str(size_value)

        if size_unit not in (None, "", "None"):
            piece += str(size_unit)

        parts.append(piece)

    return " | ".join(parts) if parts else None


def map_harvested_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "device_name": record.get("brandName"),
        "manufacturer": record.get("companyName"),
        "model_number": record.get("versionModelNumber"),
        "catalog_number": record.get("catalogNumber"),
        "device_description": record.get("deviceDescription"),
        "dimensions": extract_dimensions(record.get("deviceSizes")),
    }


def build_placeholder_gudid_record(harvested_record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "device_name": harvested_record.get("device_name"),
        "manufacturer": harvested_record.get("manufacturer"),
        "model_number": harvested_record.get("model_number"),
        "catalog_number": harvested_record.get("catalog_number"),
        "device_description": harvested_record.get("device_description"),
        "dimensions": harvested_record.get("dimensions"),
    }


def validate_records(input_file: str) -> List[Dict[str, Any]]:
    validator = ComparisonValidator()

    with open(input_file, "r", encoding="utf-8") as file:
        records = json.load(file)

    all_results: List[Dict[str, Any]] = []

    for index, raw_record in enumerate(records, start=1):
        harvested_record = map_harvested_record(raw_record)
        gudid_record = build_placeholder_gudid_record(harvested_record)

        comparison_result = validator.compare_records(harvested_record, gudid_record)

        all_results.append(
            {
                "record_number": index,
                "source_file": raw_record.get("_source_file"),
                "source_url": raw_record.get("_harvest", {}).get("source_url"),
                "harvested_record": harvested_record,
                "comparison_result": comparison_result,
            }
        )

    return all_results


def main() -> None:
    input_file = "C:/Users/tucke/Downloads/fivos.devices.json"
    output_file = "validator_results.json"

    if not Path(input_file).exists():
        print(f"Input file not found: {input_file}")
        return

    results = validate_records(input_file)

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(results, file, indent=4)

    print(f"Validated {len(results)} records.")
    print(f"Results written to {output_file}")

    if results:
        print("\nFirst record preview:")
        print(json.dumps(results[0], indent=4))


if __name__ == "__main__":
    main()