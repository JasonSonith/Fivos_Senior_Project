import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
from datetime import datetime, timezone


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
