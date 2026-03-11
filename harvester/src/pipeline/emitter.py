import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

NORMALIZATION_VERSION = "1.0.0"

GUDID_UNIT_MAP = {
    "mm": "Millimeter", "cm": "Centimeter", "m": "Meter",
    "in": "Inch", "g": "Gram", "kg": "Kilogram",
    "mL": "Milliliter", "mmHg": "Millimeter Mercury",
}

GUDID_SIZE_TYPE_MAP = {
    "diameter": "Diameter", "length": "Length", "width": "Width",
    "height": "Height", "weight": "Weight", "volume": "Volume",
    "pressure": "Pressure",
}


def _build_device_sizes(normalized: dict) -> list[dict] | None:
    """Build GUDID-format deviceSizes array from measurement fields.

    Each measurement field that has a normalized dict value (with 'value' and
    'unit' keys) is converted to {sizeType, size: {unit, value}, sizeText}.
    Returns None if no measurement fields are present.
    """
    sizes = []
    for field_key, size_type in GUDID_SIZE_TYPE_MAP.items():
        measurement = normalized.get(field_key)
        if measurement is None:
            continue
        if isinstance(measurement, dict) and "value" in measurement and "unit" in measurement:
            raw_unit = measurement["unit"]
            gudid_unit = GUDID_UNIT_MAP.get(raw_unit, raw_unit)
            sizes.append({
                "sizeType": size_type,
                "size": {
                    "unit": gudid_unit,
                    "value": str(measurement["value"]),
                },
                "sizeText": None,
            })
        elif isinstance(measurement, str):
            # Raw string that wasn't normalized — include as sizeText
            sizes.append({
                "sizeType": size_type,
                "size": None,
                "sizeText": measurement,
            })
    return sizes if sizes else None


def package_gudid_record(
    normalized_record: dict,
    raw_html: str,
    source_url: str,
    adapter_version: str,
    harvest_run_id: str | None = None,
    validation_issues: list[str] | None = None,
) -> dict:
    """Package a normalized record with GUDID-aligned field names.

    Maps internal field names to GUDID schema. Harvest metadata is nested
    under the ``_harvest`` key. Never mutates the input dict. Never raises.
    """
    try:
        record = {}

        # GUDID device identification fields
        record["brandName"] = normalized_record.get("device_name")
        record["versionModelNumber"] = normalized_record.get("model_number")
        record["catalogNumber"] = normalized_record.get("catalog_number") or normalized_record.get("model_number")
        record["companyName"] = normalized_record.get("manufacturer")
        record["deviceDescription"] = normalized_record.get("description")

        # Device sizes
        record["deviceSizes"] = _build_device_sizes(normalized_record)

        # Regulatory boolean fields
        for field in ("singleUse", "deviceSterile", "sterilizationPriorToUse", "rx", "otc"):
            if field in normalized_record:
                record[field] = normalized_record[field]

        # Enum fields
        if "MRISafetyStatus" in normalized_record:
            record["MRISafetyStatus"] = normalized_record["MRISafetyStatus"]

        # Harvest metadata
        if harvest_run_id is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            harvest_run_id = f"HR-LOCAL-{ts}"

        record["_harvest"] = {
            "harvest_run_id": harvest_run_id,
            "harvested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_url": source_url,
            "adapter_version": adapter_version,
            "normalization_version": NORMALIZATION_VERSION,
            "validation_issues": validation_issues if validation_issues is not None else [],
            "raw_html_sha256": hashlib.sha256(raw_html.encode("utf-8")).hexdigest(),
        }

        return record

    except Exception as exc:
        logger.error("package_gudid_record failed: %s", exc)
        return dict(normalized_record)


def package_record(
    normalized_record: dict,
    raw_html: str,
    source_url: str,
    adapter_version: str,
    harvest_run_id: str | None = None,
    validation_issues: list[str] | None = None,
) -> dict:
    """Package a normalized record with harvest metadata.

    Merges metadata into a copy of the normalized record. Never mutates
    the input dict. Never raises — returns a best-effort result on any
    internal error.
    """
    try:
        record = dict(normalized_record)

        if harvest_run_id is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            harvest_run_id = f"HR-LOCAL-{ts}"

        record["harvest_run_id"] = harvest_run_id
        record["harvested_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record["source_url"] = source_url
        record["adapter_version"] = adapter_version
        record["normalization_version"] = NORMALIZATION_VERSION
        record["validation_issues"] = validation_issues if validation_issues is not None else []
        record["raw_html_sha256"] = hashlib.sha256(raw_html.encode("utf-8")).hexdigest()

        return record

    except Exception as exc:
        logger.error("package_record failed: %s", exc)
        return dict(normalized_record)


def _sanitize_filename(name: str, max_len: int = 80) -> str:
    """Replace non-alphanumeric chars (except hyphens/underscores) with underscores.

    Truncates to *max_len* characters.  When truncation is needed a short hash
    of the original value is appended so that distinct long names still produce
    distinct filenames.
    """
    sanitized = re.sub(r"[^\w\-]", "_", name).strip("_")
    if len(sanitized) > max_len:
        short_hash = hashlib.sha256(name.encode()).hexdigest()[:8]
        sanitized = sanitized[: max_len - 9] + "_" + short_hash
    return sanitized or "unknown"


def write_record_json(record: dict, output_dir: str = "harvester/output") -> str:
    """Write a packaged record to a JSON file. Returns the file path.

    On any failure, logs the error and returns an empty string (never raises).
    """
    try:
        os.makedirs(output_dir, exist_ok=True)

        manufacturer = _sanitize_filename(
            record.get("companyName") or record.get("manufacturer", "unknown")
        )
        model_number = _sanitize_filename(
            record.get("versionModelNumber") or record.get("model_number", "unknown")
        )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        filename = f"{manufacturer}_{model_number}_{timestamp}.json"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)

        logger.info("Wrote record to %s", filepath)
        return filepath

    except Exception as exc:
        logger.error("write_record_json failed: %s", exc)
        return ""


def write_batch_json(records: list[dict], output_dir: str = "harvester/output") -> list[str]:
    """Write multiple packaged records to individual JSON files.

    Returns a list of file paths (empty strings for any that failed).
    """
    return [write_record_json(record, output_dir) for record in records]
