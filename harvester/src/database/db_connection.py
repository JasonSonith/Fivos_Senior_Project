import logging
import os
import sys

from pymongo import MongoClient

# Ensure harvester/src is on sys.path so security.credentials resolves
_SRC_DIR = os.path.join(os.path.dirname(__file__), os.pardir)
if os.path.abspath(_SRC_DIR) not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC_DIR))

from security.credentials import CredentialManager

logger = logging.getLogger(__name__)

_client = None
_db = None


def _get_client():
    global _client
    if _client is None:
        uri = CredentialManager.get_db_uri()
        _client = MongoClient(uri)
    return _client


def get_db(db_name: str = "fivos-shared"):
    global _db
    if _db is None or _db.name != db_name:
        _db = _get_client()[db_name]
    return _db


# Backward-compatible module-level attribute access.
# Existing code like `from db_connection import devices_collection` still works.
def __getattr__(name: str):
    if name == "client":
        return _get_client()
    if name == "db":
        return get_db()
    if name == "devices_collection":
        return get_db()["devices"]
    if name == "validation_collection":
        return get_db()["validationResults"]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def test_connection():
    try:
        _get_client().admin.command("ping")
        print("Connected to MongoDB successfully!")
    except Exception as e:
        print("Connection failed:", e)


if __name__ == "__main__":
    test_connection()
