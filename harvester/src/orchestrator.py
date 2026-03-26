"""Orchestration layer — single entry point for the UI.

Two main operations:
1. run_pipeline_batch() — process existing HTML files from out_html/ through the extraction pipeline
2. run_validation() — compare harvested devices against GUDID via Ollama AI agent
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

# Ensure harvester/src is on sys.path
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_ADAPTER_DIR = os.path.join(_SRC_DIR, "site_adapters")
_DEFAULT_HTML_DIR = os.path.join(_SRC_DIR, "web-scraper", "out_html")
_DEFAULT_OUTPUT_DIR = os.path.join(_SRC_DIR, "..", "output")


# ---------------------------------------------------------------------------
# HTML file listing (for harvester page)
# ---------------------------------------------------------------------------

def list_html_files(html_dir: str | None = None) -> list[dict]:
    """List available HTML files in out_html/ for the harvester page."""
    html_dir = html_dir or _DEFAULT_HTML_DIR
    files = []
    if not os.path.isdir(html_dir):
        return files
    for fname in sorted(os.listdir(html_dir)):
        if not fname.endswith((".html", ".htm")):
            continue
        path = os.path.join(html_dir, fname)
        # Extract manufacturer domain from filename (format: host__page__hash.html)
        parts = fname.split("__")
        manufacturer = parts[0] if parts else "unknown"
        if manufacturer.startswith("www."):
            manufacturer = manufacturer[4:]
        files.append({
            "filename": fname,
            "path": path,
            "size_kb": round(os.path.getsize(path) / 1024, 1),
            "manufacturer": manufacturer,
        })
    return files


# ---------------------------------------------------------------------------
# Pipeline batch processing
# ---------------------------------------------------------------------------

def run_pipeline_batch(file_paths: list[str] | None = None) -> dict:
    """Run the extraction pipeline on HTML files in out_html/.

    Uses runner.process_batch() with auto-adapter-matching by domain.
    After pipeline writes JSON files, inserts each record into MongoDB.

    Args:
        file_paths: Specific file paths to process, or None for all in out_html/
    """
    from pipeline.runner import load_adapters, process_batch

    run_id = f"HR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # Load all adapters keyed by domain
    adapter_map = load_adapters(_DEFAULT_ADAPTER_DIR)

    # Determine input directory
    if file_paths:
        # If specific files given, use the directory of the first file
        input_dir = os.path.dirname(file_paths[0])
    else:
        input_dir = _DEFAULT_HTML_DIR

    output_dir = os.path.abspath(_DEFAULT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    # Run the pipeline batch
    summary = process_batch(
        input_dir=input_dir,
        adapter_map=adapter_map,
        output_dir=output_dir,
        harvest_run_id=run_id,
    )

    # Insert succeeded records into MongoDB
    records = []
    from database.db_connection import get_db
    try:
        db = get_db()
        for json_path in summary.get("files", []):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    record = json.load(f)
                db["devices"].insert_one(record)
                records.append(_serialize_record(record))
            except Exception as e:
                logger.warning("run_pipeline_batch: failed to import %s: %s", json_path, e)
    except Exception as e:
        logger.warning("run_pipeline_batch: MongoDB unavailable: %s", e)

    summary["records"] = records
    summary["run_id"] = run_id
    return summary


# ---------------------------------------------------------------------------
# GUDID API lookup
# ---------------------------------------------------------------------------

def lookup_gudid_device(di: str | None = None, model_number: str | None = None) -> dict:
    """Query GUDID API for a device.

    Returns: {"success": bool, "record": dict | None, "di": str | None, "error": str | None}
    """
    from validators.gudid_client import lookup_by_di, search_gudid_di

    result = {"success": False, "record": None, "di": None, "error": None}

    try:
        if di:
            device = lookup_by_di(di)
            result["di"] = di
        elif model_number:
            found_di = search_gudid_di(version_model_number=model_number)
            if not found_di:
                result["error"] = f"No GUDID device found for model number: {model_number}"
                return result
            result["di"] = found_di
            device = lookup_by_di(found_di)
        else:
            result["error"] = "Provide either a DI or model number"
            return result

        if not device:
            result["error"] = f"Device not found for DI: {result['di']}"
            return result

        result["success"] = True
        result["record"] = device
    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# Validation orchestration (with Ollama AI agent)
# ---------------------------------------------------------------------------

def run_validation(run_id: str | None = None) -> dict:
    """Validate harvested devices against GUDID via Ollama AI agent."""
    import requests
    from database.db_connection import get_db
    from validators.gudid_client import fetch_gudid_record
    from validators.ollama_client import extract_gudid_fields_with_ollama
    from validators.comparison_validator import compare_records

    result = {
        "success": False,
        "ollama_available": False,
        "total": 0,
        "full_matches": 0,
        "partial_matches": 0,
        "mismatches": 0,
        "not_found": 0,
        "ollama_failed": 0,
        "error": None,
    }

    # 1. Health-check Ollama
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        result["ollama_available"] = resp.status_code == 200
    except Exception:
        result["error"] = "Ollama is not reachable at localhost:11434. Start Ollama to enable GUDID validation."
        return result

    # 2. Query devices
    db = get_db()
    devices_col = db["devices"]
    validation_col = db["validationResults"]

    query = {}
    if run_id:
        query["_harvest.harvest_run_id"] = run_id

    devices = list(devices_col.find(query))
    result["total"] = len(devices)

    if not devices:
        result["success"] = True
        result["error"] = "No devices found to validate"
        return result

    # 3. Validate each device
    for device in devices:
        di, gudid_record = fetch_gudid_record(
            catalog_number=device.get("catalogNumber"),
            version_model_number=device.get("versionModelNumber"),
        )

        if not gudid_record:
            result["not_found"] += 1
            validation_col.update_one(
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
                        "updated_at": datetime.now(timezone.utc),
                    },
                    "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
                },
                upsert=True,
            )
            continue

        # Use Ollama AI agent to extract/verify fields
        try:
            gudid_text = json.dumps(gudid_record, indent=2)
            ollama_record = extract_gudid_fields_with_ollama(gudid_text)
        except Exception:
            result["ollama_failed"] += 1
            validation_col.update_one(
                {"device_id": device.get("_id")},
                {
                    "$set": {
                        "device_id": device.get("_id"),
                        "brandName": device.get("brandName"),
                        "status": "ollama_failed",
                        "updated_at": datetime.now(timezone.utc),
                    },
                    "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
                },
                upsert=True,
            )
            continue

        comparison = compare_records(device, ollama_record)
        matched_fields = sum(1 for v in comparison.values() if v["match"])
        total_fields = len(comparison)
        match_percent = round((matched_fields / total_fields) * 100, 2) if total_fields > 0 else 0.0

        if matched_fields == total_fields:
            status = "matched"
            result["full_matches"] += 1
        elif matched_fields > 0:
            status = "partial_match"
            result["partial_matches"] += 1
        else:
            status = "mismatch"
            result["mismatches"] += 1

        validation_col.update_one(
            {"device_id": device.get("_id")},
            {
                "$set": {
                    "device_id": device.get("_id"),
                    "brandName": device.get("brandName"),
                    "status": status,
                    "matched_fields": matched_fields,
                    "total_fields": total_fields,
                    "match_percent": match_percent,
                    "comparison_result": comparison,
                    "gudid_record": ollama_record,
                    "gudid_di": di,
                    "updated_at": datetime.now(timezone.utc),
                },
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )

    result["success"] = True
    return result


# ---------------------------------------------------------------------------
# DB query helpers (for UI routes)
# ---------------------------------------------------------------------------

def get_dashboard_stats() -> dict:
    from database.db_connection import get_db
    try:
        db = get_db()
        device_count = db["devices"].count_documents({})
        validation_count = db["validationResults"].count_documents({})
        html_count = len(list_html_files())

        last_device = db["devices"].find_one(sort=[("_harvest.harvested_at", -1)])
        last_run = "No runs yet"
        if last_device:
            harvest = last_device.get("_harvest", {})
            last_run = harvest.get("harvested_at", "Unknown")
    except Exception as e:
        logger.warning("get_dashboard_stats: MongoDB unavailable: %s", e)
        return {"raw_records": 0, "normalized_records": 0, "html_files": 0, "last_run": "DB unavailable"}

    return {
        "raw_records": device_count,
        "normalized_records": validation_count,
        "html_files": html_count,
        "last_run": last_run,
    }


def get_devices(limit: int = 100, skip: int = 0, run_id: str | None = None) -> list[dict]:
    from database.db_connection import get_db
    try:
        db = get_db()
        query = {}
        if run_id:
            query["_harvest.harvest_run_id"] = run_id
        cursor = db["devices"].find(query).sort("_harvest.harvested_at", -1).skip(skip).limit(limit)
        return [_serialize_record(doc) for doc in cursor]
    except Exception as e:
        logger.warning("get_devices: %s", e)
        return []


def get_validation_results(limit: int = 100, skip: int = 0) -> list[dict]:
    from database.db_connection import get_db
    try:
        db = get_db()
        cursor = db["validationResults"].find().sort("updated_at", -1).skip(skip).limit(limit)
        return [_serialize_record(doc) for doc in cursor]
    except Exception as e:
        logger.warning("get_validation_results: %s", e)
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_record(record: dict) -> dict:
    """Make a MongoDB document JSON-serializable (convert ObjectId, datetime, etc.)."""
    out = {}
    for k, v in record.items():
        if hasattr(v, "__str__") and type(v).__name__ == "ObjectId":
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, dict):
            out[k] = _serialize_record(v)
        elif isinstance(v, list):
            out[k] = [_serialize_record(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out
