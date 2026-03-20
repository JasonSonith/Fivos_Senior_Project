import json
from pathlib import Path

RAW_PATH = Path("data/raw/raw_records.json")
NORMALIZED_PATH = Path("data/normalized/normalized_records.json")

def save_raw_records(records: list[dict]):
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RAW_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

def load_raw_records() -> list[dict]:
    if not RAW_PATH.exists():
        return []
    with open(RAW_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_normalized_records(records: list[dict]):
    NORMALIZED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(NORMALIZED_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

def load_normalized_records() -> list[dict]:
    if not NORMALIZED_PATH.exists():
        return []
    with open(NORMALIZED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)