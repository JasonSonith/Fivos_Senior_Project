import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

NORMALIZATION_VERSION = "1.0.0"


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

        manufacturer = _sanitize_filename(record.get("manufacturer", "unknown"))
        model_number = _sanitize_filename(record.get("model_number", "unknown"))
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
