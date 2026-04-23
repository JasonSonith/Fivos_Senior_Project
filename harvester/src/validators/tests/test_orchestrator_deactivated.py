import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from unittest.mock import MagicMock, patch


def test_deactivated_short_circuit_writes_status_and_skips_compare():
    """run_validation sees deviceRecordStatus=Deactivated → inserts
    validationResult with status=gudid_deactivated, does not call
    compare_records, does not call _merge_gudid_into_device."""
    from orchestrator import run_validation

    mock_db = MagicMock()
    mock_device = {
        "_id": "device-123",
        "brandName": "TestDevice",
        "catalogNumber": "CAT-1",
        "versionModelNumber": "MODEL-1",
    }
    mock_gudid = {
        "deviceRecordStatus": "Deactivated",
        "brandName": "TestDevice",
        "publishDate": "2020-01-01",
    }
    mock_db["devices"].find.return_value = [mock_device]
    mock_db["validationResults"].insert_one = MagicMock()
    mock_db["validationResults"].drop = MagicMock()

    with patch("database.db_connection.get_db", return_value=mock_db), \
         patch("validators.gudid_client.fetch_gudid_record",
               return_value=("DI-123", mock_gudid)), \
         patch("orchestrator._merge_gudid_into_device") as mock_merge, \
         patch("validators.comparison_validator.compare_records") as mock_compare:
        result = run_validation(overwrite=False)

    mock_compare.assert_not_called()
    mock_merge.assert_not_called()
    mock_db["verified_devices"].update_one.assert_not_called()
    assert mock_db["validationResults"].insert_one.called
    call_arg = mock_db["validationResults"].insert_one.call_args[0][0]
    assert call_arg["status"] == "gudid_deactivated"
    assert call_arg["matched_fields"] is None
    assert call_arg["total_fields"] is None
    assert result.get("gudid_deactivated") == 1


def test_harvest_gap_counters_fire():
    """When GUDID has productCodes or premarketSubmissions but device is null,
    counters increment per device."""
    from orchestrator import run_validation

    mock_db = MagicMock()
    mock_device = {
        "_id": "device-456",
        "brandName": "X",
        "catalogNumber": "Y",
        "versionModelNumber": "Z",
    }
    mock_gudid = {
        "brandName": "X",
        "versionModelNumber": "Z",
        "productCodes": ["DYB"],
        "premarketSubmissions": ["K123456"],
        "deviceRecordStatus": "Published",
    }
    mock_db["devices"].find.return_value = [mock_device]
    mock_db["validationResults"].insert_one = MagicMock()
    mock_db["validationResults"].drop = MagicMock()

    with patch("database.db_connection.get_db", return_value=mock_db), \
         patch("validators.gudid_client.fetch_gudid_record",
               return_value=("DI-456", mock_gudid)), \
         patch("orchestrator._merge_gudid_into_device"):
        result = run_validation(overwrite=False)

    assert result.get("harvest_gap_product_codes") == 1
    assert result.get("harvest_gap_premarket") == 1
