import os
import sys
from collections import defaultdict
from datetime import datetime

from pymongo import MongoClient

# Ensure harvester/src is on sys.path
_SRC_DIR = os.path.join(os.path.dirname(__file__), os.pardir)
if os.path.abspath(_SRC_DIR) not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC_DIR))

from security.credentials import CredentialManager

DB_NAME = "fivos-shared"
DEVICES_COLLECTION = "devices"
RUNS_COLLECTION = "runs"


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    client = MongoClient(CredentialManager.get_db_uri())
    db = client[DB_NAME]
    devices = db[DEVICES_COLLECTION]
    runs = db[RUNS_COLLECTION]

    grouped = defaultdict(lambda: {
        "type": "harvest",
        "status": "completed",
        "harvested_times": [],
        "source_urls": set(),
        "adapter_versions": set(),
        "device_count": 0
    })

    for doc in devices.find():
        harvest = doc.get("_harvest", {})
        run_id = harvest.get("harvest_run_id")

        if not run_id:
            continue

        harvested_at = harvest.get("harvested_at")
        source_url = harvest.get("source_url")
        adapter_version = harvest.get("adapter_version")

        grouped[run_id]["device_count"] += 1

        dt = parse_dt(harvested_at)
        if dt:
            grouped[run_id]["harvested_times"].append(dt)

        if source_url:
            grouped[run_id]["source_urls"].add(source_url)

        if adapter_version:
            grouped[run_id]["adapter_versions"].add(adapter_version)

    runs.delete_many({})

    run_docs = []
    for run_id, info in grouped.items():
        times = info["harvested_times"]
        started_at = min(times).isoformat() if times else None
        ended_at = max(times).isoformat() if times else None

        run_doc = {
            "runId": run_id,
            "type": info["type"],
            "status": info["status"],
            "startedAt": started_at,
            "endedAt": ended_at,
            "deviceCount": info["device_count"],
            "sourceUrls": sorted(info["source_urls"]),
            "adapterVersions": sorted(info["adapter_versions"]),
            "notes": "Generated from devices collection using _harvest.harvest_run_id"
        }

        run_docs.append(run_doc)

    if run_docs:
        runs.insert_many(run_docs)

    print(f"Created {len(run_docs)} run documents in '{RUNS_COLLECTION}' collection.")

if __name__ == "__main__":
    main()
