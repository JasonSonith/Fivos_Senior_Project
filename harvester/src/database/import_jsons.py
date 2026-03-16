import os
import json
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "fivos"
COLLECTION_NAME = "devices"
JSON_FOLDER = r"harvester\output"

def main():
    client = MongoClient(MONGO_URI)
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