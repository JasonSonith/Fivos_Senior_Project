from harvester.src.normalizers.unit_conversions import normalize_measurement

FIELDS_TO_NORMALIZE = {"outer_diameter", "weight", "volume"}

def normalize_record(record: dict) -> dict:
    normalized = {}

    for key, value in record.items():
        if key in FIELDS_TO_NORMALIZE and isinstance(value, str):
            normalized_value = normalize_measurement(value)
            if normalized_value["value"] is not None and normalized_value["unit"] is not None:
                normalized[key] = f"{normalized_value['value']} {normalized_value['unit']}"
            else:
                normalized[key] = value
        else:
            normalized[key] = value

    return normalized

def normalize_records(records: list[dict]) -> list[dict]:
    return [normalize_record(record) for record in records]