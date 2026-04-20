# GUDID Not Found as Mismatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store `"mismatch"` instead of `"gudid_not_found"` for devices where GUDID lookup returns nothing, so they appear in the dashboard Mismatches count and table automatically.

**Architecture:** Two changes to `harvester/src/orchestrator.py`: (1) change the status written by `run_validation()` on the not-found path; (2) add a `migrate_gudid_not_found()` helper to fix existing DB records, called from the validate route's `_do_validation` so it self-heals on the next validation run.

**Tech Stack:** Python 3.13, pymongo, pytest, unittest.mock

---

## File Map

| File | Change |
|------|--------|
| `harvester/src/orchestrator.py` | Change `status: "gudid_not_found"` → `"mismatch"` in `run_validation()`; move counter to `mismatches`; add `migrate_gudid_not_found()` |
| `app/routes/validate.py` | Call `migrate_gudid_not_found()` inside `_do_validation()` |
| `harvester/src/tests/test_orchestrator.py` | New file — tests for both changes |

---

## Task 1: Test and fix `run_validation()` not-found path

**Files:**
- Create: `harvester/src/tests/test_orchestrator.py`
- Modify: `harvester/src/orchestrator.py:366-381`

- [ ] **Step 1: Create the test file**

Create `harvester/src/tests/test_orchestrator.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
from datetime import datetime, timezone


def _make_db(inserted_docs):
    """Return a mock db whose validationResults.insert_one records the doc."""
    mock_col = MagicMock()
    mock_col.insert_one.side_effect = lambda doc: inserted_docs.append(doc)
    mock_db = MagicMock()
    mock_db.__getitem__ = lambda self, key: mock_col
    return mock_db, mock_col


class TestRunValidationNotFound:
    def test_not_found_stores_mismatch_status(self):
        inserted = []
        mock_col = MagicMock()
        mock_col.insert_one.side_effect = lambda doc: inserted.append(doc)
        mock_col.find.return_value = [
            {"_id": "dev1", "catalogNumber": "CAT-001", "versionModelNumber": "M-1"}
        ]

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_col)

        with patch("database.db_connection.get_db", return_value=mock_db), \
             patch("validators.gudid_client.fetch_gudid_record", return_value=(None, None)):
            from orchestrator import run_validation
            result = run_validation()

        assert result["mismatches"] == 1
        assert result["not_found"] == 0
        status_stored = inserted[0]["status"]
        assert status_stored == "mismatch", f"Expected 'mismatch', got '{status_stored}'"

    def test_not_found_increments_mismatches_not_not_found(self):
        inserted = []
        mock_col = MagicMock()
        mock_col.insert_one.side_effect = lambda doc: inserted.append(doc)
        mock_col.find.return_value = [
            {"_id": "dev1", "catalogNumber": "CAT-001", "versionModelNumber": "M-1"},
            {"_id": "dev2", "catalogNumber": "CAT-002", "versionModelNumber": "M-2"},
        ]

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_col)

        with patch("database.db_connection.get_db", return_value=mock_db), \
             patch("validators.gudid_client.fetch_gudid_record", return_value=(None, None)):
            from orchestrator import run_validation
            result = run_validation()

        assert result["mismatches"] == 2
        assert result["not_found"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/c/Users/sonit/Github/Fivos_Senior_Project
pytest harvester/src/tests/test_orchestrator.py -v
```

Expected: FAIL — `AssertionError: Expected 'mismatch', got 'gudid_not_found'`

- [ ] **Step 3: Update `run_validation()` in orchestrator.py**

In `harvester/src/orchestrator.py`, find the not-found block (around line 366). Replace:

```python
        if not gudid_record:
            result["not_found"] += 1
            validation_col.insert_one({
                "device_id": device.get("_id"),
                "brandName": device.get("brandName"),
                "status": "gudid_not_found",
                "matched_fields": 0,
                "total_fields": 0,
                "match_percent": 0.0,
                "comparison_result": None,
                "gudid_record": None,
                "gudid_di": di,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            })
            continue
```

With:

```python
        if not gudid_record:
            result["mismatches"] += 1
            validation_col.insert_one({
                "device_id": device.get("_id"),
                "brandName": device.get("brandName"),
                "status": "mismatch",
                "matched_fields": 0,
                "total_fields": 0,
                "match_percent": 0.0,
                "comparison_result": None,
                "gudid_record": None,
                "gudid_di": di,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            })
            continue
```

Also update the `result` dict at the top of `run_validation()` — change `"not_found": 0` to keep it present but always zero:

```python
    result = {
        "success": False,
        "total": 0,
        "full_matches": 0,
        "partial_matches": 0,
        "mismatches": 0,
        "not_found": 0,   # kept for backwards compat, always 0 now
        "error": None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest harvester/src/tests/test_orchestrator.py -v
```

Expected: PASS — both tests green

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
pytest harvester/src/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass (408 previously)

- [ ] **Step 6: Commit**

```bash
git add harvester/src/orchestrator.py harvester/src/tests/test_orchestrator.py
git commit -m "fix(validation): store mismatch instead of gudid_not_found status"
```

---

## Task 2: Add migration helper and wire into validate route

**Files:**
- Modify: `harvester/src/orchestrator.py` (add function after `backfill_verified_devices`)
- Modify: `app/routes/validate.py:68-77`
- Modify: `harvester/src/tests/test_orchestrator.py` (add test class)

- [ ] **Step 1: Add migration test to test file**

Append to `harvester/src/tests/test_orchestrator.py`:

```python
class TestMigrateGudidNotFound:
    def test_updates_gudid_not_found_to_mismatch(self):
        mock_result = MagicMock()
        mock_result.matched_count = 3
        mock_result.modified_count = 3

        mock_col = MagicMock()
        mock_col.update_many.return_value = mock_result

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_col)

        with patch("database.db_connection.get_db", return_value=mock_db):
            from orchestrator import migrate_gudid_not_found
            result = migrate_gudid_not_found()

        mock_col.update_many.assert_called_once_with(
            {"status": "gudid_not_found"},
            {"$set": {"status": "mismatch"}},
        )
        assert result == {"matched": 3, "modified": 3}

    def test_returns_zero_counts_when_nothing_to_migrate(self):
        mock_result = MagicMock()
        mock_result.matched_count = 0
        mock_result.modified_count = 0

        mock_col = MagicMock()
        mock_col.update_many.return_value = mock_result

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_col)

        with patch("database.db_connection.get_db", return_value=mock_db):
            from orchestrator import migrate_gudid_not_found
            result = migrate_gudid_not_found()

        assert result == {"matched": 0, "modified": 0}
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
pytest harvester/src/tests/test_orchestrator.py::TestMigrateGudidNotFound -v
```

Expected: FAIL — `ImportError: cannot import name 'migrate_gudid_not_found'`

- [ ] **Step 3: Add `migrate_gudid_not_found()` to orchestrator.py**

In `harvester/src/orchestrator.py`, add after the `backfill_verified_devices()` function (around line 483):

```python
def migrate_gudid_not_found() -> dict:
    """One-time migration: rename existing gudid_not_found records to mismatch."""
    from database.db_connection import get_db
    db = get_db()
    r = db["validationResults"].update_many(
        {"status": "gudid_not_found"},
        {"$set": {"status": "mismatch"}},
    )
    return {"matched": r.matched_count, "modified": r.modified_count}
```

- [ ] **Step 4: Run migration tests to verify they pass**

```bash
pytest harvester/src/tests/test_orchestrator.py::TestMigrateGudidNotFound -v
```

Expected: PASS — both tests green

- [ ] **Step 5: Wire migration into `_do_validation` in validate.py**

In `app/routes/validate.py`, update `_do_validation()`:

```python
def _do_validation(app, job_id: str):
    from orchestrator import run_validation, backfill_verified_devices, migrate_gudid_not_found
    try:
        migrate_gudid_not_found()
        result = run_validation()
        backfill = backfill_verified_devices()
        result["verified_count"] = backfill.get("verified_count", 0)
        app.state.jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        app.state.jobs[job_id] = {
            "status": "failed",
            "result": {"success": False, "error": str(e)},
        }
```

- [ ] **Step 6: Run full test suite**

```bash
pytest harvester/src/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add harvester/src/orchestrator.py harvester/src/tests/test_orchestrator.py app/routes/validate.py
git commit -m "feat(validation): migrate gudid_not_found to mismatch on next validation run"
```
