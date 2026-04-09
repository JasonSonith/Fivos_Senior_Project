import hashlib
import logging
import re
import secrets
import string
from datetime import datetime, timezone

import bcrypt
import requests

from database.db_connection import get_db

logger = logging.getLogger(__name__)

# ── Complexity rules ──────────────────────────────────────────────────────────

_SPECIAL_RE = re.compile(r'[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]')


def check_complexity(password: str) -> list[str]:
    """Returns list of unmet rule descriptions. Empty list = all rules pass."""
    errors = []
    if len(password) < 12:
        errors.append("At least 12 characters required")
    if not re.search(r'[A-Z]', password):
        errors.append("At least one uppercase letter required")
    if not re.search(r'[a-z]', password):
        errors.append("At least one lowercase letter required")
    if not re.search(r'[0-9]', password):
        errors.append("At least one number required")
    if not _SPECIAL_RE.search(password):
        errors.append("At least one special character required (!@#$%^&*...)")
    return errors


def check_hibp(password: str) -> int:
    """
    Checks password against HIBP k-anonymity API.
    Returns breach count. 0 = safe (or API unreachable — fail-open).
    Only the first 5 chars of the SHA1 hash are sent over the network.
    """
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    try:
        resp = requests.get(
            f"https://api.pwnedpasswords.com/range/{prefix}",
            timeout=5,
            headers={"Add-Padding": "true"},
        )
        resp.raise_for_status()
        for line in resp.text.splitlines():
            parts = line.split(":")
            if len(parts) == 2 and parts[0].strip() == suffix:
                return int(parts[1].strip())
        return 0
    except Exception:
        logger.warning("HIBP check failed (network error) — allowing password (fail-open)")
        return 0


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── Temp password generation ──────────────────────────────────────────────────

def _generate_temp_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(16))
        if not check_complexity(pwd):
            return pwd


# ── DB helpers ────────────────────────────────────────────────────────────────

def _col():
    return get_db()["users"]


def _serialize(doc: dict) -> dict:
    if doc and "_id" in doc:
        doc = dict(doc)
        doc["_id"] = str(doc["_id"])
    return doc


# ── User CRUD ─────────────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> dict | None:
    doc = _col().find_one({"email": email.strip().lower()})
    return _serialize(doc) if doc else None


def list_users() -> list[dict]:
    docs = _col().find({}, {"password_hash": 0}).sort("created_at", 1)
    return [_serialize(dict(d)) for d in docs]


def create_user(name: str, email: str, role: str, created_by: str) -> tuple[str, str]:
    temp_pwd = _generate_temp_password()
    doc = {
        "email": email.strip().lower(),
        "name": name.strip(),
        "role": role,
        "password_hash": hash_password(temp_pwd),
        "force_password_change": True,
        "active": True,
        "created_at": datetime.now(timezone.utc),
        "created_by": created_by,
        "last_login": None,
    }
    result = _col().insert_one(doc)
    return str(result.inserted_id), temp_pwd


def update_password(user_id: str, new_hash: str) -> None:
    from bson import ObjectId
    _col().update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"password_hash": new_hash, "force_password_change": False}},
    )


def update_last_login(user_id: str) -> None:
    from bson import ObjectId
    _col().update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"last_login": datetime.now(timezone.utc)}},
    )


def toggle_active(user_id: str) -> bool:
    from bson import ObjectId
    doc = _col().find_one({"_id": ObjectId(user_id)}, {"active": 1})
    if not doc:
        return False
    new_state = not doc.get("active", True)
    _col().update_one({"_id": ObjectId(user_id)}, {"$set": {"active": new_state}})
    return new_state


# ── Startup seeding ───────────────────────────────────────────────────────────

def seed_demo_users() -> None:
    """
    Idempotent — checks by email before inserting.
    Seeds the two demo accounts with force_password_change=True so they
    are immediately prompted to set a strong password on first login.
    """
    col = _col()
    col.create_index("email", unique=True)

    demos = [
        {"email": "admin@fivos.local",    "name": "System Admin",   "role": "admin",    "password": "admin123"},
        {"email": "reviewer@fivos.local", "name": "Review Analyst", "role": "reviewer", "password": "review123"},
    ]
    now = datetime.now(timezone.utc)
    for d in demos:
        if col.find_one({"email": d["email"]}):
            continue
        col.insert_one({
            "email": d["email"],
            "name": d["name"],
            "role": d["role"],
            "password_hash": hash_password(d["password"]),
            "force_password_change": True,
            "active": True,
            "created_at": now,
            "created_by": "system",
            "last_login": None,
        })
        logger.info("Seeded demo user: %s", d["email"])
