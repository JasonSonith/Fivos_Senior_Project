"""Orchestration layer — single entry point for the UI.

Operations:
1. run_harvest_single() / run_harvest_batch() — scrape + extract + append to DB
2. run_validation() — compare harvested devices against GUDID API
3. get_discrepancy_detail() / resolve_discrepancy() — human review of mismatches
4. lookup_gudid_device() — direct GUDID API lookup
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import requests
from bson import ObjectId

from validators.gudid_client import fetch_gudid_record
from validators.comparison_validator import compare_records

logger = logging.getLogger(__name__)

_DEFAULT_HTML_DIR = os.path.join(_SRC_DIR, "web-scraper", "out_html")
_DEFAULT_OUTPUT_DIR = os.path.join(_SRC_DIR, "..", "output")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MERGE_FIELDS = [
    "catalogNumber",
    "labeledContainsNRL", "labeledNoNRL",
    "sterilizationPriorToUse", "deviceSterile", "otc",
    "deviceKit",
    "premarketSubmissions",
    "environmentalConditions",
    "brandName", "versionModelNumber", "companyName", "deviceDescription",
    "MRISafetyStatus", "singleUse", "rx",
    # Layer-2 additions
    "gmdnPTName", "gmdnCode", "productCodes",
    "deviceCountInBase",
    "publishDate", "deviceRecordStatus",
    "issuingAgency",
    "lotBatch", "serialNumber", "manufacturingDate", "expirationDate",
]


def _is_null_list(value) -> bool:
    return value is None or (isinstance(value, list) and len(value) == 0)


def _derive_outcome(matched_fields: int, total_fields: int) -> str:
    """Translate unweighted match counts into the validationResults status string."""
    if matched_fields == total_fields:
        return "matched"
    if matched_fields > 0:
        return "partial_match"
    return "mismatch"


def _merge_gudid_into_device(db, device: dict, gudid_record: dict) -> list[str]:
    """Fill null device fields with GUDID values. Returns list of fields filled."""
    updates = {}
    filled = []
    for field in MERGE_FIELDS:
        if device.get(field) is None and gudid_record.get(field) is not None:
            updates[field] = gudid_record[field]
            filled.append(field)

    if updates:
        updates["gudid_sourced_fields"] = filled
        db["devices"].update_one(
            {"_id": device["_id"]},
            {"$set": updates},
        )

    return filled


def _serialize_record(record: dict) -> dict:
    """Make a MongoDB document JSON-serializable."""
    out = {}
    for k, v in record.items():
        if isinstance(v, ObjectId):
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


def _get_run_id() -> str:
    return f"HR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Harvest: scrape + extract + append to DB
# ---------------------------------------------------------------------------

def run_harvest_single(url: str) -> dict:
    """Scrape one URL, extract with Ollama, append to devices collection.

    Returns: {"url", "scraped", "devices_extracted", "db_inserted", "run_id", "error"}
    """
    from pipeline.runner import scrape_urls, _process_single_ollama, write_record_json
    from database.db_connection import get_db

    run_id = _get_run_id()
    result = {
        "url": url,
        "scraped": False,
        "devices_extracted": 0,
        "db_inserted": 0,
        "run_id": run_id,
        "error": None,
    }

    try:
        output_dir = os.path.abspath(_DEFAULT_OUTPUT_DIR)
        os.makedirs(output_dir, exist_ok=True)

        # 1. Scrape
        saved = scrape_urls([url], _DEFAULT_HTML_DIR)
        if not saved:
            result["error"] = f"Failed to scrape {url}"
            return result
        result["scraped"] = True

        # 2. Extract via Ollama
        records = _process_single_ollama(saved[0], source_url=url, harvest_run_id=run_id)
        result["devices_extracted"] = len(records)

        if not records:
            result["error"] = "Ollama extraction returned no records"
            return result

        # 3. Write JSON + append to DB
        try:
            db = get_db()
            for record in records:
                write_record_json(record, output_dir)
                db["devices"].insert_one(record)
                result["db_inserted"] += 1
        except Exception as e:
            logger.warning("run_harvest_single: MongoDB error: %s", e)
            result["error"] = f"DB write error: {e}"

    except Exception as e:
        logger.error("run_harvest_single: %s", e)
        result["error"] = str(e)

    return result


def run_harvest_batch(urls: list[str], job_store: dict | None = None, job_id: str | None = None) -> dict:
    """Scrape + parallel-extract + DB insert, in three phases.

    Phase 1: sequential scrape (Playwright is already internally batched).
    Phase 2: parallel LLM extraction via ThreadPoolExecutor.
    Phase 3: sequential JSON writes + MongoDB inserts on the main thread.

    Returns the shape expected by app/templates/harvester.html:
        {total, succeeded, failed, results: [...], run_id}
    Each results entry: {url, scraped, devices_extracted, db_inserted, error}
    """
    from pipeline.runner import _scrape_urls_with_meta, write_record_json
    from pipeline.parallel_batch import process_html_files_parallel
    from database.db_connection import get_db

    run_id = _get_run_id()
    output_dir = os.path.abspath(_DEFAULT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    # Phase 1: scrape (per-URL metadata preserves failures)
    meta = _scrape_urls_with_meta(urls, _DEFAULT_HTML_DIR)
    scraped = [m for m in meta if m["path"]]
    source_urls = {m["path"]: m["url"] for m in scraped}

    # Phase 2: parallel extraction
    def _progress(completed: int, total: int) -> None:
        if job_store is not None and job_id is not None:
            job_store[job_id] = {
                "status": "running",
                "result": {"progress": completed, "total": total},
            }

    file_results = process_html_files_parallel(
        [m["path"] for m in scraped],
        harvest_run_id=run_id,
        source_urls=source_urls,
        progress_callback=_progress,
    )
    file_results_by_path = {r.path: r for r in file_results}

    # Phase 3: JSON write + DB insert sequentially
    try:
        db = get_db()
    except Exception as e:
        logger.warning("run_harvest_batch: MongoDB unavailable: %s", e)
        db = None

    results: list[dict] = []
    for m in meta:
        entry = {
            "url": m["url"],
            "scraped": m["path"] is not None,
            "devices_extracted": 0,
            "db_inserted": 0,
            "error": m["error"],
        }
        fr = file_results_by_path.get(m["path"]) if m["path"] else None
        if fr is not None:
            entry["devices_extracted"] = len(fr.records)
            if fr.error:
                entry["error"] = fr.error
            for record in fr.records:
                write_record_json(record, output_dir)
                if db is not None:
                    try:
                        db["devices"].insert_one(record)
                        entry["db_inserted"] += 1
                    except Exception as e:
                        entry["error"] = f"DB error: {e}"
        results.append(entry)

    return {
        "total": len(urls),
        "succeeded": sum(
            1 for r in results
            if r["devices_extracted"] > 0 and not r["error"]
        ),
        "failed": sum(
            1 for r in results
            if r["devices_extracted"] == 0 or r["error"]
        ),
        "results": results,
        "run_id": run_id,
    }


# ---------------------------------------------------------------------------
# Legacy pipeline batch (for CLI compatibility)
# ---------------------------------------------------------------------------

def run_pipeline_batch(file_paths: list[str] | None = None, overwrite: bool = False) -> dict:
    """Run the extraction pipeline on HTML files in out_html/.

    Args:
        file_paths: Specific file paths to process, or None for all in out_html/
        overwrite: If True, drop devices collection before inserting. Default False.
    """
    from pipeline.runner import process_batch

    run_id = _get_run_id()

    if file_paths:
        input_dir = os.path.dirname(file_paths[0])
    else:
        input_dir = _DEFAULT_HTML_DIR

    output_dir = os.path.abspath(_DEFAULT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    summary = process_batch(
        input_dir=input_dir,
        output_dir=output_dir,
        harvest_run_id=run_id,
    )

    records = []
    from database.db_connection import get_db
    try:
        db = get_db()
        if overwrite:
            db["devices"].drop()
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
    """Query GUDID API for a device."""
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
# Validation
# ---------------------------------------------------------------------------

def run_validation(run_id: str | None = None, overwrite: bool = False) -> dict:
    """Validate harvested devices against GUDID. Default: append (no overwrite)."""
    from database.db_connection import get_db

    result = {
        "success": False,
        "total": 0,
        "full_matches": 0,
        "partial_matches": 0,
        "mismatches": 0,
        "not_found": 0,
        "gudid_deactivated": 0,
        "harvest_gap_product_codes": 0,
        "harvest_gap_premarket": 0,
        "errors": 0,
        "error": None,
    }

    db = get_db()
    devices_col = db["devices"]
    validation_col = db["validationResults"]

    verified_col = db["verified_devices"]

    if overwrite:
        validation_col.drop()
        verified_col.drop()

    query = {}
    if run_id:
        query["_harvest.harvest_run_id"] = run_id

    devices = list(devices_col.find(query))
    result["total"] = len(devices)

    if not devices:
        result["success"] = True
        result["error"] = "No devices found to validate"
        return result

    for device in devices:
        try:
            di, gudid_record = fetch_gudid_record(
                catalog_number=device.get("catalogNumber"),
                version_model_number=device.get("versionModelNumber"),
            )
        except requests.RequestException as exc:
            logger.warning(
                "GUDID fetch failed for catalog=%s model=%s: %s: %s",
                device.get("catalogNumber"),
                device.get("versionModelNumber"),
                type(exc).__name__,
                exc,
            )
            result["errors"] += 1
            now = datetime.now(timezone.utc)
            validation_col.insert_one({
                "device_id": device.get("_id"),
                "brandName": device.get("brandName"),
                "status": "fetch_error",
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:500],
                "matched_fields": None,
                "total_fields": None,
                "match_percent": None,
                "weighted_percent": None,
                "description_similarity": None,
                "comparison_result": None,
                "gudid_record": None,
                "gudid_di": None,
                "created_at": now,
                "updated_at": now,
            })
            continue

        if not gudid_record:
            result["mismatches"] += 1
            validation_col.insert_one({
                "device_id": device.get("_id"),
                "brandName": device.get("brandName"),
                "status": "mismatch",
                "matched_fields": 0,
                "total_fields": 0,
                "match_percent": 0.0,
                "weighted_percent": 0.0,
                "comparison_result": None,
                "gudid_record": None,
                "gudid_di": di,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            })
            continue

        record_status = (gudid_record or {}).get("deviceRecordStatus")
        if record_status == "Deactivated":
            validation_col.insert_one({
                "device_id": device["_id"],
                "brandName": device.get("brandName"),
                "status": "gudid_deactivated",
                "matched_fields": None,
                "total_fields": None,
                "match_percent": None,
                "weighted_percent": None,
                "description_similarity": None,
                "comparison_result": None,
                "gudid_record": gudid_record,
                "gudid_di": di,
                "gudid_record_status": record_status,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            })
            result["gudid_deactivated"] = result.get("gudid_deactivated", 0) + 1
            continue

        comparison, summary = compare_records(device, gudid_record)
        matched_fields = summary["unweighted_numerator"]
        total_fields = summary["unweighted_denominator"]
        match_percent = round((matched_fields / total_fields) * 100, 2) if total_fields else 0.0
        weighted_percent = round(
            (summary["numerator"] / summary["denominator"]) * 100, 2
        ) if summary["denominator"] else 0.0
        description_similarity = comparison.get("deviceDescription", {}).get("similarity") or 0.0

        status = _derive_outcome(matched_fields, total_fields)
        if status == "matched":
            result["full_matches"] += 1
        elif status == "partial_match":
            result["partial_matches"] += 1
        else:
            result["mismatches"] += 1

        if gudid_record.get("productCodes") and _is_null_list(device.get("productCodes")):
            logger.info(
                "[harvest-gap] device %s (%s): GUDID productCodes=%r, harvested=null",
                device.get("_id"), device.get("brandName"),
                gudid_record["productCodes"],
            )
            result["harvest_gap_product_codes"] += 1

        if gudid_record.get("premarketSubmissions") and _is_null_list(device.get("premarketSubmissions")):
            logger.info(
                "[harvest-gap] device %s (%s): GUDID premarketSubmissions=%r, harvested=null",
                device.get("_id"), device.get("brandName"),
                gudid_record["premarketSubmissions"],
            )
            result["harvest_gap_premarket"] += 1

        validation_col.insert_one({
            "device_id": device.get("_id"),
            "brandName": device.get("brandName"),
            "status": status,
            "matched_fields": matched_fields,
            "total_fields": total_fields,
            "match_percent": match_percent,
            "weighted_percent": weighted_percent,
            "description_similarity": description_similarity,
            "comparison_result": comparison,
            "gudid_record": gudid_record,
            "gudid_di": di,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })

        # Fully matched devices → store in verified_devices (harvested + GUDID extras)
        if status == "matched":
            verified_record = dict(device)
            verified_record.pop("_id", None)
            # Merge GUDID fields where harvested is null
            for field in MERGE_FIELDS:
                if verified_record.get(field) is None and gudid_record.get(field) is not None:
                    verified_record[field] = gudid_record[field]
            verified_record["gudid_di"] = di
            verified_record["verified_at"] = datetime.now(timezone.utc)
            verified_record["source_device_id"] = device.get("_id")
            # Upsert by model+catalog to avoid duplicates on re-validation
            verified_col.update_one(
                {"versionModelNumber": verified_record.get("versionModelNumber"),
                 "catalogNumber": verified_record.get("catalogNumber")},
                {"$set": verified_record},
                upsert=True,
            )

        # Fill null device fields from GUDID (runs after comparison to preserve original diff)
        _merge_gudid_into_device(db, device, gudid_record)

    result["success"] = True

    # Remove JSON files from output dir so next validation only sees new harvests.
    output_dir = os.path.abspath(_DEFAULT_OUTPUT_DIR)
    removed = 0
    if os.path.isdir(output_dir):
        for fname in os.listdir(output_dir):
            if fname.endswith(".json"):
                try:
                    os.remove(os.path.join(output_dir, fname))
                    removed += 1
                except OSError as e:
                    logger.warning("Could not remove %s: %s", fname, e)
    logger.info("Cleaned up %d JSON file(s) from %s", removed, output_dir)
    result["cleaned_up"] = removed

    return result


def backfill_verified_devices() -> dict:
    """Process existing validation results and populate verified_devices for matched records."""
    from database.db_connection import get_db
    try:
        db = get_db()
        verified_col = db["verified_devices"]
        matched_results = db["validationResults"].find({"status": "matched"})

        count = 0
        for vr in matched_results:
            device = db["devices"].find_one({"_id": vr.get("device_id")})
            if not device:
                continue

            gudid_record = vr.get("gudid_record") or {}
            verified_record = dict(device)
            verified_record.pop("_id", None)

            # Merge GUDID fields where harvested is null
            for field in MERGE_FIELDS:
                if verified_record.get(field) is None and gudid_record.get(field) is not None:
                    verified_record[field] = gudid_record[field]

            verified_record["gudid_di"] = vr.get("gudid_di")
            verified_record["verified_at"] = datetime.now(timezone.utc)
            verified_record["source_device_id"] = device.get("_id")

            verified_col.update_one(
                {"versionModelNumber": verified_record.get("versionModelNumber"),
                 "catalogNumber": verified_record.get("catalogNumber")},
                {"$set": verified_record},
                upsert=True,
            )
            count += 1

        return {"success": True, "verified_count": count}
    except Exception as e:
        logger.warning("backfill_verified_devices: %s", e)
        return {"success": False, "error": str(e)}


def migrate_gudid_not_found() -> dict:
    """One-time migration: rename existing gudid_not_found records to mismatch."""
    from database.db_connection import get_db
    try:
        db = get_db()
        r = db["validationResults"].update_many(
            {"status": "gudid_not_found"},
            {"$set": {"status": "mismatch"}},
        )
        return {"matched": r.matched_count, "modified": r.modified_count}
    except Exception as e:
        logger.warning("migrate_gudid_not_found: %s", e)
        return {"matched": 0, "modified": 0}


# ---------------------------------------------------------------------------
# Dashboard stats & discrepancy queries
# ---------------------------------------------------------------------------

def get_dashboard_stats() -> dict:
    from database.db_connection import get_db
    try:
        db = get_db()
        device_count = db["devices"].count_documents({})
        partial_matches = db["validationResults"].count_documents({"status": "partial_match"})
        mismatches = db["validationResults"].count_documents({"status": "mismatch"})
        matches = db["verified_devices"].count_documents({})
        deactivated_count = db["validationResults"].count_documents({"status": "gudid_deactivated"})

        last_device = db["devices"].find_one(sort=[("_harvest.harvested_at", -1)])
        last_run = "No runs yet"
        if last_device:
            harvest = last_device.get("_harvest", {})
            last_run = harvest.get("harvested_at", "Unknown")
    except Exception as e:
        logger.warning("get_dashboard_stats: MongoDB unavailable: %s", e)
        return {"device_count": 0, "matches": 0, "partial_matches": 0, "mismatches": 0, "deactivated": 0, "last_run": "DB unavailable"}

    return {
        "device_count": device_count,
        "matches": matches,
        "partial_matches": partial_matches,
        "mismatches": mismatches,
        "deactivated": deactivated_count,
        "last_run": last_run,
    }


def get_discrepancies(limit: int = 100) -> list[dict]:
    """Get validation results that need human review (partial_match or mismatch)."""
    from database.db_connection import get_db
    try:
        db = get_db()
        cursor = db["validationResults"].find(
            {"status": {"$in": ["partial_match", "mismatch"]}}
        ).sort("updated_at", -1).limit(limit)

        results = []
        for doc in cursor:
            # Join with device to get identifying info
            device = db["devices"].find_one({"_id": doc.get("device_id")})
            serialized = _serialize_record(doc)
            if device:
                serialized["companyName"] = device.get("companyName", "N/A")
                serialized["versionModelNumber"] = device.get("versionModelNumber", "N/A")
            results.append(serialized)
        return results
    except Exception as e:
        logger.warning("get_discrepancies: %s", e)
        return []


def get_all_dashboard_records() -> list[dict]:
    """Get combined verified_devices + validation discrepancies for dashboard filtering.

    'matched' = records from verified_devices collection (confirmed GUDID matches).
    'partial_match'/'mismatch' = records from validationResults with those statuses.
    """
    from database.db_connection import get_db
    try:
        db = get_db()
        results = []

        # Verified devices = "matched". Batch-fetch matching validation IDs so the
        # dashboard's More Information link resolves to /review/{validation_id}.
        verified_docs = list(db["verified_devices"].find().sort("verified_at", -1))
        source_ids = [d["source_device_id"] for d in verified_docs if d.get("source_device_id") is not None]
        matched_validations_by_device_id = {
            v["device_id"]: v["_id"]
            for v in db["validationResults"].find(
                {"device_id": {"$in": source_ids}, "status": "matched"}
            ).sort("updated_at", -1)
        }

        for doc in verified_docs:
            serialized = _serialize_record(doc)
            serialized["status"] = "matched"
            serialized["companyName"] = doc.get("companyName", "N/A")
            serialized["versionModelNumber"] = doc.get("versionModelNumber", "N/A")
            serialized["brandName"] = doc.get("brandName", "N/A")
            serialized["matched_fields"] = None
            serialized["total_fields"] = None
            serialized["match_percent"] = None
            serialized["weighted_percent"] = None
            validation_id = matched_validations_by_device_id.get(doc.get("source_device_id"))
            serialized["_id"] = str(validation_id) if validation_id else None
            results.append(serialized)

        # Partial match, mismatch, and deactivated from validation results
        discrepancy_docs = list(db["validationResults"].find(
            {"status": {"$in": ["partial_match", "mismatch", "gudid_deactivated"]}}
        ).sort("updated_at", -1))

        device_ids = [d["device_id"] for d in discrepancy_docs if d.get("device_id") is not None]
        devices_by_id = {
            dev["_id"]: dev
            for dev in db["devices"].find({"_id": {"$in": device_ids}})
        }

        for doc in discrepancy_docs:
            device = devices_by_id.get(doc.get("device_id"))
            serialized = _serialize_record(doc)
            if device:
                serialized["companyName"] = device.get("companyName", "N/A")
                serialized["versionModelNumber"] = device.get("versionModelNumber", "N/A")
            results.append(serialized)

        return results
    except Exception as e:
        logger.warning("get_all_dashboard_records: %s", e)
        return []


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


def get_latest_run_id() -> str | None:
    """Return harvest_run_id of the most recently harvested device, or None."""
    from database.db_connection import get_db
    try:
        db = get_db()
        last = db["devices"].find_one(
            {"_harvest.harvest_run_id": {"$exists": True}},
            sort=[("_harvest.harvested_at", -1)],
        )
        if not last:
            return None
        return last.get("_harvest", {}).get("harvest_run_id")
    except Exception as e:
        logger.warning("get_latest_run_id: %s", e)
        return None


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
# Discrepancy review
# ---------------------------------------------------------------------------

def get_discrepancy_detail(validation_id: str) -> dict | None:
    """Fetch a single validation result + linked device for review."""
    from database.db_connection import get_db
    try:
        db = get_db()
        doc = db["validationResults"].find_one({"_id": ObjectId(validation_id)})
        if not doc:
            return None

        device = db["devices"].find_one({"_id": doc.get("device_id")})

        return {
            "validation": _serialize_record(doc),
            "device": _serialize_record(device) if device else {},
        }
    except Exception as e:
        logger.warning("get_discrepancy_detail: %s", e)
        return None


def resolve_discrepancy(validation_id: str, field_choices: dict) -> dict:
    """Apply user's field choices to the devices collection.

    field_choices: {"fieldName": "harvested" | "gudid", ...}
    For "gudid" choices, update the device with the GUDID value.
    """
    from database.db_connection import get_db

    result = {"success": False, "error": None}

    try:
        db = get_db()
        doc = db["validationResults"].find_one({"_id": ObjectId(validation_id)})
        if not doc:
            result["error"] = "Validation result not found"
            return result

        comparison = doc.get("comparison_result") or {}
        gudid_record = doc.get("gudid_record") or {}
        device_id = doc.get("device_id")

        if not device_id:
            result["error"] = "No linked device"
            return result

        # Build update dict for fields where user chose GUDID value
        update_fields = {}
        resolved_fields = {}
        for field, choice in field_choices.items():
            resolved_fields[field] = choice
            if choice == "gudid":
                gudid_val = gudid_record.get(field)
                if gudid_val is not None:
                    update_fields[field] = gudid_val

        # Update device
        if update_fields:
            db["devices"].update_one(
                {"_id": device_id},
                {"$set": update_fields},
            )

        # Mark validation as resolved
        db["validationResults"].update_one(
            {"_id": ObjectId(validation_id)},
            {"$set": {
                "status": "resolved",
                "resolved_at": datetime.now(timezone.utc),
                "resolved_fields": resolved_fields,
                "updated_at": datetime.now(timezone.utc),
            }},
        )

        result["success"] = True

    except Exception as e:
        logger.error("resolve_discrepancy: %s", e)
        result["error"] = str(e)

    return result
