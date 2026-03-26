import os
import sys
import json

from pymongo import MongoClient

# Ensure harvester/src is on sys.path
_SRC_DIR = os.path.join(os.path.dirname(__file__), os.pardir)
if os.path.abspath(_SRC_DIR) not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC_DIR))

from security.credentials import CredentialManager

DB_NAME = "fivos-shared"
COLLECTION_NAME = "devices"
JSON_FOLDER = os.path.join("harvester", "output")


def main():
    client = MongoClient(CredentialManager.get_db_uri())
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    inserted_count = 0

    for filename in os.listdir(JSON_FOLDER):
        if filename.endswith(".json"):
            path = os.path.join(JSON_FOLDER, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["_source_file"] = filename
                collection.insert_one(data)
                inserted_count += 1
                print(f"Inserted: {filename}")
            except Exception as e:
                print(f"Failed: {filename} -> {e}")

    print(f"Done. Inserted {inserted_count} files.")

if __name__ == "__main__":
    main()
