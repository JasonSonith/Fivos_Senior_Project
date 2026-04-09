import hashlib
import json
import os
import re

from pipeline.emitter import (
    package_record, package_gudid_record, _build_device_sizes,
    write_record_json, write_batch_json, _sanitize_filename,
    NORMALIZATION_VERSION, GUDID_UNIT_MAP,
)


SAMPLE_RECORD = {
    "device_name": "IN.PACT Admiral",
    "manufacturer": "Medtronic",
    "model_number": "ABC123",
}

SAMPLE_HTML = "<html><body><h1>Test Device</h1></body></html>"
SAMPLE_URL = "https://www.medtronic.com/us-en/products/inpact-admiral.html"
SAMPLE_ADAPTER_VERSION = "medtronic-v1.0"
SAMPLE_RUN_ID = "HR-10011"


class TestPackageRecord:
    def test_basic_packaging(self):
        result = package_record(
            SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL,
            SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
            validation_issues=["STRING_LENGTH: device_name too short"],
        )
        assert result["device_name"] == "IN.PACT Admiral"
        assert result["manufacturer"] == "Medtronic"
        assert result["model_number"] == "ABC123"
        assert result["harvest_run_id"] == SAMPLE_RUN_ID
        assert result["source_url"] == SAMPLE_URL
        assert result["adapter_version"] == SAMPLE_ADAPTER_VERSION
        assert result["normalization_version"] == NORMALIZATION_VERSION
        assert result["validation_issues"] == ["STRING_LENGTH: device_name too short"]
        assert "harvested_at" in result
        assert "raw_html_sha256" in result

    def test_sha256_correctness(self):
        expected = hashlib.sha256(SAMPLE_HTML.encode("utf-8")).hexdigest()
        result = package_record(
            SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION,
        )
        assert result["raw_html_sha256"] == expected

    def test_utc_timestamp_format(self):
        result = package_record(
            SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION,
        )
        # Should match ISO 8601 UTC format: YYYY-MM-DDTHH:MM:SSZ
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", result["harvested_at"])

    def test_default_harvest_run_id(self):
        result = package_record(
            SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION,
            harvest_run_id=None,
        )
        assert result["harvest_run_id"].startswith("HR-LOCAL-")

    def test_empty_validation_issues(self):
        result = package_record(
            SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION,
            validation_issues=[],
        )
        assert result["validation_issues"] == []

    def test_none_validation_issues_defaults_to_empty_list(self):
        result = package_record(
            SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION,
            validation_issues=None,
        )
        assert result["validation_issues"] == []

    def test_original_record_not_mutated(self):
        original = {"device_name": "Test", "manufacturer": "TestCo", "model_number": "X1"}
        original_copy = dict(original)
        package_record(original, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION)
        assert original == original_copy


GUDID_SAMPLE_RECORD = {
    "device_name": "IN.PACT Admiral",
    "manufacturer": "Medtronic",
    "model_number": "ABC123",
    "diameter": {"value": 6.0, "unit": "mm", "is_range": False},
    "length": {"value": 120.0, "unit": "mm", "is_range": False},
}


class TestBuildDeviceSizes:
    def test_basic_sizes(self):
        sizes = _build_device_sizes(GUDID_SAMPLE_RECORD)
        assert sizes is not None
        assert len(sizes) == 2
        assert sizes[0]["sizeType"] == "Diameter"
        assert sizes[0]["size"]["unit"] == "Millimeter"
        assert sizes[0]["size"]["value"] == "6.0"
        assert sizes[0]["sizeText"] is None
        assert sizes[1]["sizeType"] == "Length"
        assert sizes[1]["size"]["unit"] == "Millimeter"
        assert sizes[1]["size"]["value"] == "120.0"

    def test_no_measurements(self):
        record = {"device_name": "Test", "manufacturer": "TestCo"}
        assert _build_device_sizes(record) is None

    def test_none_measurements(self):
        record = {"diameter": None, "length": None}
        assert _build_device_sizes(record) is None

    def test_raw_string_measurement(self):
        record = {"diameter": "6.0 mm"}
        sizes = _build_device_sizes(record)
        assert sizes is not None
        assert sizes[0]["sizeType"] == "Diameter"
        assert sizes[0]["size"] is None
        assert sizes[0]["sizeText"] == "6.0 mm"

    def test_unit_mapping(self):
        record = {"weight": {"value": 500, "unit": "g", "is_range": False}}
        sizes = _build_device_sizes(record)
        assert sizes[0]["size"]["unit"] == "Gram"


class TestPackageGudidRecord:
    def test_field_mapping(self):
        result = package_gudid_record(
            GUDID_SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL,
            SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert result["brandName"] == "IN.PACT Admiral"
        assert result["versionModelNumber"] == "ABC123"
        assert result["companyName"] == "Medtronic"
        assert result["catalogNumber"] is None  # no catalog_number in input, no fallback

    def test_harvest_metadata_nested(self):
        result = package_gudid_record(
            GUDID_SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL,
            SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert "_harvest" in result
        h = result["_harvest"]
        assert h["harvest_run_id"] == SAMPLE_RUN_ID
        assert h["source_url"] == SAMPLE_URL
        assert h["adapter_version"] == SAMPLE_ADAPTER_VERSION
        assert h["normalization_version"] == NORMALIZATION_VERSION
        assert "harvested_at" in h
        assert "raw_html_sha256" in h

    def test_device_sizes_included(self):
        result = package_gudid_record(
            GUDID_SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL,
            SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert result["deviceSizes"] is not None
        assert len(result["deviceSizes"]) == 2

    def test_null_device_sizes_when_no_measurements(self):
        result = package_gudid_record(
            SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL,
            SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert result["deviceSizes"] is None

    def test_regulatory_fields_passed_through(self):
        record = {**SAMPLE_RECORD, "singleUse": True, "rx": True}
        result = package_gudid_record(
            record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert result["singleUse"] is True
        assert result["rx"] is True

    def test_mri_status_passed_through(self):
        record = {**SAMPLE_RECORD, "MRISafetyStatus": "MR Conditional"}
        result = package_gudid_record(
            record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert result["MRISafetyStatus"] == "MR Conditional"

    def test_original_record_not_mutated(self):
        original = dict(GUDID_SAMPLE_RECORD)
        package_gudid_record(GUDID_SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION)
        assert GUDID_SAMPLE_RECORD == original

    def test_default_harvest_run_id(self):
        result = package_gudid_record(
            SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION,
        )
        assert result["_harvest"]["harvest_run_id"].startswith("HR-LOCAL-")

    def test_validation_issues_default_empty(self):
        result = package_gudid_record(
            SAMPLE_RECORD, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION,
        )
        assert result["_harvest"]["validation_issues"] == []

    def test_labeled_contains_nrl_passed_through(self):
        record = {**SAMPLE_RECORD, "labeledContainsNRL": True}
        result = package_gudid_record(
            record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert result["labeledContainsNRL"] is True

    def test_labeled_no_nrl_passed_through(self):
        record = {**SAMPLE_RECORD, "labeledNoNRL": True}
        result = package_gudid_record(
            record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert result["labeledNoNRL"] is True

    def test_sterilization_prior_to_use_passed_through(self):
        record = {**SAMPLE_RECORD, "sterilizationPriorToUse": True}
        result = package_gudid_record(
            record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert result["sterilizationPriorToUse"] is True

    def test_device_kit_passed_through(self):
        record = {**SAMPLE_RECORD, "deviceKit": True}
        result = package_gudid_record(
            record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert result["deviceKit"] is True

    def test_premarket_submissions_passed_through(self):
        record = {**SAMPLE_RECORD, "premarketSubmissions": ["K123456", "P210034"]}
        result = package_gudid_record(
            record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert result["premarketSubmissions"] == ["K123456", "P210034"]

    def test_environmental_conditions_passed_through(self):
        record = {**SAMPLE_RECORD, "environmentalConditions": {"storageTemperature": "15-30°C"}}
        result = package_gudid_record(
            record, SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        assert result["environmentalConditions"] == {"storageTemperature": "15-30°C"}


class TestWriteRecordJson:
    def _make_packaged_record(self, **overrides):
        record = package_record(
            {**SAMPLE_RECORD, **overrides},
            SAMPLE_HTML, SAMPLE_URL, SAMPLE_ADAPTER_VERSION, SAMPLE_RUN_ID,
        )
        return record

    def test_write_record_json_creates_file(self, tmp_path):
        record = self._make_packaged_record()
        path = write_record_json(record, str(tmp_path))
        assert path != ""
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["device_name"] == "IN.PACT Admiral"
        assert data["manufacturer"] == "Medtronic"

    def test_write_record_json_filename_format(self, tmp_path):
        record = self._make_packaged_record()
        path = write_record_json(record, str(tmp_path))
        filename = os.path.basename(path)
        assert filename.startswith("Medtronic_ABC123_")
        assert filename.endswith(".json")

    def test_write_record_json_creates_output_dir(self, tmp_path):
        nested = str(tmp_path / "sub" / "dir")
        record = self._make_packaged_record()
        path = write_record_json(record, nested)
        assert os.path.isfile(path)
        assert os.path.isdir(nested)

    def test_write_record_json_sanitizes_filename(self, tmp_path):
        record = self._make_packaged_record(
            manufacturer="W.L. Gore & Associates",
            model_number="VIABAHN/VBX (3.0)",
        )
        path = write_record_json(record, str(tmp_path))
        filename = os.path.basename(path)
        # No special chars that break filesystems
        assert "/" not in filename
        assert "&" not in filename
        assert "(" not in filename
        assert " " not in filename

    def test_write_record_json_failure_does_not_raise(self):
        record = self._make_packaged_record()
        # Use an invalid path that can't be created
        result = write_record_json(record, "/dev/null/impossible/path")
        assert result == ""

    def test_write_batch_json(self, tmp_path):
        records = [
            self._make_packaged_record(model_number="MDT-001"),
            self._make_packaged_record(model_number="MDT-002"),
            self._make_packaged_record(model_number="MDT-003"),
        ]
        paths = write_batch_json(records, str(tmp_path))
        assert len(paths) == 3
        assert all(os.path.isfile(p) for p in paths)

    def test_write_record_json_long_model_number(self, tmp_path):
        """Filenames with very long model_number values must not exceed OS limits."""
        long_model = "A" * 500
        record = self._make_packaged_record(model_number=long_model)
        path = write_record_json(record, str(tmp_path))
        assert path != ""
        assert os.path.isfile(path)
        filename = os.path.basename(path)
        assert len(filename) <= 255  # filesystem limit


class TestSanitizeFilename:
    def test_short_name_unchanged(self):
        assert _sanitize_filename("ABC123") == "ABC123"

    def test_special_chars_replaced(self):
        result = _sanitize_filename("W.L. Gore & Associates")
        assert "&" not in result
        assert "." not in result

    def test_long_name_truncated_with_hash(self):
        long_name = "X" * 200
        result = _sanitize_filename(long_name, max_len=80)
        assert len(result) == 80
        # Last 8 chars should be a hex hash
        assert re.match(r"[0-9a-f]{8}", result[-8:])

    def test_truncated_names_differ_for_different_inputs(self):
        name_a = "A" * 200
        name_b = "B" * 200
        assert _sanitize_filename(name_a) != _sanitize_filename(name_b)

    def test_empty_name_returns_unknown(self):
        assert _sanitize_filename("") == "unknown"

    def test_only_special_chars_returns_unknown(self):
        assert _sanitize_filename("...///") == "unknown"

    def test_custom_max_len(self):
        result = _sanitize_filename("A" * 50, max_len=30)
        assert len(result) == 30
