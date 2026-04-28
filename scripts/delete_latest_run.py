"""Delete the most recent harvest run from devices, validationResults, and verified_devices."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "harvester", "src"))

from database.db_connection import get_db
from orchestrator import get_latest_run_id


def main():
    run_id = get_latest_run_id()
    if not run_id:
        print("No runs found.")
        return

    db = get_db()
    devices = list(db["devices"].find({"_harvest.harvest_run_id": run_id}, {"_id": 1, "brandName": 1}))
    device_ids = [d["_id"] for d in devices]

    val_count = db["validationResults"].count_documents({"device_id": {"$in": device_ids}})
    ver_count = db["verified_devices"].count_documents({"source_device_id": {"$in": device_ids}})

    print(f"Latest run_id: {run_id}")
    print(f"  devices:           {len(devices)}")
    print(f"  validationResults: {val_count}")
    print(f"  verified_devices:  {ver_count}")
    for d in devices:
        print(f"    - {d.get('brandName')} ({d['_id']})")

    if input("\nDelete these? [y/N]: ").strip().lower() != "y":
        print("Aborted.")
        return

    v = db["validationResults"].delete_many({"device_id": {"$in": device_ids}})
    vd = db["verified_devices"].delete_many({"source_device_id": {"$in": device_ids}})
    dv = db["devices"].delete_many({"_harvest.harvest_run_id": run_id})
    print(f"Deleted: devices={dv.deleted_count}, validationResults={v.deleted_count}, verified_devices={vd.deleted_count}")


if __name__ == "__main__":
    main()
