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
             patch("validators.gudid_client.fetch_gudid_record", return_value=(None, None)):
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
            "versionModelNumber": {"harvested": "M-2", "gudid": "M-2", "match": True},
            "catalogNumber": {"harvested": "CAT-002", "gudid": "CAT-002", "match": True},
            "brandName": {"harvested": "Acme", "gudid": "Acme", "match": True},
            "companyName": {"harvested": "ACME INC", "gudid": "ACME INC", "match": True},
            "deviceDescription": {"harvested": "desc", "gudid": "desc", "description_similarity": 1.0},
            "MRISafetyStatus": {"harvested": None, "gudid": None, "match": None},
            "singleUse": {"harvested": None, "gudid": None, "match": None},
            "rx": {"harvested": None, "gudid": None, "match": None},
        }

        gudid_record = {"versionModelNumber": "M-2", "catalogNumber": "CAT-002",
                        "brandName": "Acme", "companyName": "ACME INC"}

        with patch("database.db_connection.get_db", return_value=mock_db), \
             patch("validators.gudid_client.fetch_gudid_record",
                   side_effect=[(None, None), ("DI-123", gudid_record)]), \
             patch("validators.comparison_validator.compare_records",
                   return_value=full_match_comparison):
            from orchestrator import run_validation
            result = run_validation()

        assert result["mismatches"] == 1
        assert result["full_matches"] == 1
        assert result["not_found"] == 0
