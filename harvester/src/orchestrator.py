"""Orchestration layer — single entry point for the UI to trigger harvest and validation flows.

The pipeline (runner.py) stays pure: HTML in, dict out.
This module handles persistence (MongoDB) and coordination.
"""

import asyncio
import logging
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone

# Ensure harvester/src is on sys.path
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Adapter scanning
# ---------------------------------------------------------------------------

_DEFAULT_ADAPTER_DIR = os.path.join(_SRC_DIR, "site_adapters")


def scan_adapters(adapter_dir: str | None = None) -> list[dict]:
    """Walk site_adapters/, parse each YAML, return sorted metadata list."""
    adapter_dir = adapter_dir or _DEFAULT_ADAPTER_DIR
    adapters = []
    for root, _dirs, files in os.walk(adapter_dir):
        for fname in files:
            if not fname.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                adapters.append({
                    "path": path,
                    "manufacturer": data.get("manufacturer", "unknown"),
                    "product_type": data.get("product_type", "unknown"),
                    "base_url": data.get("base_url", ""),
                    "seed_url_count": len(data.get("seed_urls", [])),
                })
            except Exception as e:
                logger.warning("scan_adapters: skipping %s: %s", path, e)
    return sorted(adapters, key=lambda a: (a["manufacturer"], a["product_type"]))


def get_adapter_choices(adapter_dir: str | None = None) -> list[dict]:
    """Return adapter list formatted for a UI dropdown.

    Each entry: {"value": "/abs/path/to.yaml", "label": "Medtronic - table wrapper layout"}
    """
    adapters = scan_adapters(adapter_dir)
    return [
        {
            "value": a["path"],
            "label": f"{a['manufacturer'].replace('_', ' ').title()} - {a['product_type'].replace('_', ' ')}",
        }
        for a in adapters
    ]


# ---------------------------------------------------------------------------
# Harvest orchestration
# ---------------------------------------------------------------------------

async def run_harvest(
    url: str,
    adapter_path: str,
    run_id: str | None = None,
) -> dict:
    """End-to-end: scrape URL -> pipeline -> MongoDB -> return result dict."""
    if run_id is None:
        run_id = f"HR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    result = {
        "success": False,
        "run_id": run_id,
        "record": None,
        "mongo_id": None,
        "error": None,
        "scrape_elapsed_ms": None,
        "pipeline_ok": False,
    }

    # 1. Load adapter
    from pipeline.runner import load_adapter
    try:
        adapter = load_adapter(adapter_path)
    except Exception as e:
        result["error"] = f"Adapter load failed: {e}"
        return result

    # 2. Scrape (async)
    from web_scraper.scraper import fetch_page_html
    try:
        fetch_result = await fetch_page_html(url)
    except Exception as e:
        result["error"] = f"Scrape failed: {e}"
        return result

    result["scrape_elapsed_ms"] = fetch_result.elapsed_ms

    if not fetch_result.ok or not fetch_result.html:
        result["error"] = f"Scrape failed: {fetch_result.error}"
        return result

    # 3. Write HTML to temp file, run pipeline
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".html", prefix="fivos_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(fetch_result.html)

        # 4. Run pipeline (synchronous) in thread pool
        from pipeline.runner import process_single
        record = await asyncio.to_thread(
            process_single,
            tmp_path,
            adapter,
            source_url=fetch_result.final_url or url,
            harvest_run_id=run_id,
        )
    except Exception as e:
        result["error"] = f"Pipeline error: {e}"
        return result
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    result["pipeline_ok"] = record is not None

    if record is None:
        result["error"] = "Pipeline rejected the record (validation failed or extraction empty)"
        return result

    # 5. Insert into MongoDB
    from database.db_connection import get_db
    try:
        db = get_db()
        insert_result = db["devices"].insert_one(record)
        result["mongo_id"] = str(insert_result.inserted_id)
    except Exception as e:
        result["error"] = f"MongoDB insert failed: {e}"
        result["record"] = _serialize_record(record)
        return result

    result["success"] = True
    result["record"] = _serialize_record(record)
    return result


# ---------------------------------------------------------------------------
# Validation orchestration
# ---------------------------------------------------------------------------

def run_validation(run_id: str | None = None) -> dict:
    """Health-check Ollama, run GUDID validation, return structured results."""
    import requests
    from database.db_connection import get_db
    from validators.gudid_client import fetch_gudid_raw_text
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
        di, raw_gudid_text = fetch_gudid_raw_text(
            catalog_number=device.get("catalogNumber"),
            version_model_number=device.get("versionModelNumber"),
        )

        if not raw_gudid_text:
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

        try:
            gudid_record = extract_gudid_fields_with_ollama(raw_gudid_text)
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

        comparison = compare_records(device, gudid_record)
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
                    "gudid_record": gudid_record,
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

        last_device = db["devices"].find_one(sort=[("_harvest.harvested_at", -1)])
        last_run = "No runs yet"
        if last_device:
            harvest = last_device.get("_harvest", {})
            last_run = harvest.get("harvested_at", "Unknown")
    except Exception as e:
        logger.warning("get_dashboard_stats: MongoDB unavailable: %s", e)
        return {"raw_records": 0, "normalized_records": 0, "last_run": "DB unavailable"}

    return {
        "raw_records": device_count,
        "normalized_records": validation_count,
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
