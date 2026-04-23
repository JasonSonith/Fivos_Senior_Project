import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
from datetime import datetime, timezone


class TestRunValidationNotFound:
    def test_not_found_stores_mismatch_status(self):
        inserted = []

        devices_col = MagicMock()
        devices_col.find.return_value = [
            {"_id": "dev1", "catalogNumber": "CAT-001", "versionModelNumber": "M-1"}
        ]

        validation_col = MagicMock()
        validation_col.insert_one.side_effect = lambda doc: inserted.append(doc)

        verified_col = MagicMock()

        collections = {
            "devices": devices_col,
            "validationResults": validation_col,
            "verified_devices": verified_col,
        }
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=lambda key: collections.get(key, MagicMock()))

        with patch("database.db_connection.get_db", return_value=mock_db), \
             patch("orchestrator.fetch_gudid_record", return_value=(None, None)):
            from orchestrator import run_validation
            result = run_validation()

        assert result["mismatches"] == 1
        assert result["not_found"] == 0
        status_stored = inserted[0]["status"]
        assert status_stored == "mismatch", f"Expected 'mismatch', got '{status_stored}'"

    def test_mixed_run_not_found_and_full_match(self):
        inserted = []

        devices_col = MagicMock()
        devices_col.find.return_value = [
            {"_id": "dev1", "catalogNumber": "CAT-001", "versionModelNumber": "M-1"},
            {"_id": "dev2", "catalogNumber": "CAT-002", "versionModelNumber": "M-2",
             "brandName": "Acme", "companyName": "ACME INC"},
        ]

        validation_col = MagicMock()
        validation_col.insert_one.side_effect = lambda doc: inserted.append(doc)

        verified_col = MagicMock()

        collections = {
            "devices": devices_col,
            "validationResults": validation_col,
            "verified_devices": verified_col,
        }
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=lambda key: collections.get(key, MagicMock()))

        full_match_comparison = {
            "versionModelNumber": {"harvested": "M-2", "gudid": "M-2", "status": "match"},
            "catalogNumber": {"harvested": "CAT-002", "gudid": "CAT-002", "status": "match"},
            "brandName": {"harvested": "Acme", "gudid": "Acme", "status": "match"},
            "companyName": {"harvested": "ACME INC", "gudid": "ACME INC", "status": "match"},
            "deviceDescription": {"harvested": "desc", "gudid": "desc", "status": "match", "similarity": 1.0},
            "MRISafetyStatus": {"harvested": None, "gudid": None, "status": "not_compared"},
            "singleUse": {"harvested": None, "gudid": None, "status": "not_compared"},
            "rx": {"harvested": None, "gudid": None, "status": "not_compared"},
        }
        full_match_summary = {
            "numerator": 12, "denominator": 12,
            "unweighted_numerator": 4, "unweighted_denominator": 4,
        }

        gudid_record = {"versionModelNumber": "M-2", "catalogNumber": "CAT-002",
                        "brandName": "Acme", "companyName": "ACME INC"}

        with patch("database.db_connection.get_db", return_value=mock_db), \
             patch("orchestrator.fetch_gudid_record",
                   side_effect=[(None, None), ("DI-123", gudid_record)]), \
             patch("orchestrator.compare_records",
                   return_value=(full_match_comparison, full_match_summary)):
            from orchestrator import run_validation
            result = run_validation()

        assert result["mismatches"] == 1
        assert result["full_matches"] == 1
        assert result["not_found"] == 0


class TestMigrateGudidNotFound:
    def test_updates_gudid_not_found_to_mismatch(self):
        mock_result = MagicMock()
        mock_result.matched_count = 3
        mock_result.modified_count = 3

        mock_col = MagicMock()
        mock_col.update_many.return_value = mock_result

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=lambda key: mock_col)

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
        mock_db.__getitem__ = MagicMock(side_effect=lambda key: mock_col)

        with patch("database.db_connection.get_db", return_value=mock_db):
            from orchestrator import migrate_gudid_not_found
            result = migrate_gudid_not_found()

        assert result == {"matched": 0, "modified": 0}

    def test_returns_zero_on_db_error(self):
        with patch("database.db_connection.get_db", side_effect=Exception("DB down")):
            from orchestrator import migrate_gudid_not_found
            result = migrate_gudid_not_found()
        assert result == {"matched": 0, "modified": 0}


class TestRunValidationErrorIsolation:
    """One flaky GUDID call must not kill the whole batch."""

    def test_timeout_on_one_device_does_not_kill_run(self, monkeypatch):
        import requests
        from orchestrator import run_validation

        devices = [
            {"_id": "dev1", "catalogNumber": "A1", "versionModelNumber": "M1", "brandName": "B1"},
            {"_id": "dev2", "catalogNumber": "A2", "versionModelNumber": "M2", "brandName": "B2"},
            {"_id": "dev3", "catalogNumber": "A3", "versionModelNumber": "M3", "brandName": "B3"},
        ]

        class FakeCollection:
            def __init__(self):
                self.docs = []
            def drop(self): self.docs.clear()
            def find(self, query=None): return iter(devices)
            def insert_one(self, doc): self.docs.append(doc)
            def update_one(self, *a, **kw): pass

        class FakeDb(dict):
            def __init__(self):
                self["devices"] = FakeCollection()
                self["validationResults"] = FakeCollection()
                self["verified_devices"] = FakeCollection()

        fake_db = FakeDb()
        monkeypatch.setattr("database.db_connection.get_db", lambda: fake_db)

        # Device 2 times out; devices 1 and 3 return a simple matched record.
        def fake_fetch(catalog_number=None, version_model_number=None):
            if catalog_number == "A2":
                raise requests.Timeout("simulated timeout")
            return (f"DI-{catalog_number}", {
                "brandName": f"B{catalog_number[-1]}",
                "versionModelNumber": version_model_number,
                "catalogNumber": catalog_number,
            })

        monkeypatch.setattr("orchestrator.fetch_gudid_record", fake_fetch)
        monkeypatch.setattr(
            "orchestrator.compare_records",
            lambda h, g: ({}, {"numerator": 1, "denominator": 1,
                               "unweighted_numerator": 1, "unweighted_denominator": 1}),
        )

        result = run_validation(overwrite=True)

        assert result["success"] is True
        assert result["total"] == 3
        assert result["errors"] == 1

        val_docs = fake_db["validationResults"].docs
        assert len(val_docs) == 3
        statuses = sorted(d["status"] for d in val_docs)
        assert "fetch_error" in statuses
        fetch_err_doc = next(d for d in val_docs if d["status"] == "fetch_error")
        assert fetch_err_doc["error_type"] == "Timeout"
        assert "simulated timeout" in fetch_err_doc["error_message"]
