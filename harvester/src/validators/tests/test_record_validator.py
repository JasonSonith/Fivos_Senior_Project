from validators.record_validator import validate_record

VALID_RECORD = {
    "device_name": "IN.PACT Admiral Drug Coated Balloon",
    "manufacturer": "Medtronic",
    "model_number": "ADMIRAL-35-40-130",
    "source_url": "https://www.medtronic.com/product/123",
}


class TestRequiredFields:

    def test_missing_device_name(self):
        record = {**VALID_RECORD, "device_name": None}
        valid, issues = validate_record(record)
        assert not valid
        assert any("REQUIRED_MISSING: device_name" in i for i in issues)

    def test_empty_device_name(self):
        record = {**VALID_RECORD, "device_name": "   "}
        valid, issues = validate_record(record)
        assert not valid
        assert any("REQUIRED_MISSING: device_name" in i for i in issues)

    def test_missing_manufacturer(self):
        record = {**VALID_RECORD, "manufacturer": None}
        valid, issues = validate_record(record)
        assert not valid
        assert any("REQUIRED_MISSING: manufacturer" in i for i in issues)

    def test_empty_manufacturer(self):
        record = {**VALID_RECORD, "manufacturer": ""}
        valid, issues = validate_record(record)
        assert not valid
        assert any("REQUIRED_MISSING: manufacturer" in i for i in issues)

    def test_missing_model_number(self):
        record = {**VALID_RECORD, "model_number": None}
        valid, issues = validate_record(record)
        assert not valid
        assert any("REQUIRED_MISSING: model_number" in i for i in issues)

    def test_all_required_missing(self):
        record = {"source_url": "https://example.com"}
        valid, issues = validate_record(record)
        assert not valid
        assert len([i for i in issues if i.startswith("REQUIRED_MISSING:")]) == 3


class TestDimensionRanges:

    def test_zero_length_mm(self):
        record = {**VALID_RECORD, "dimensions": {"length_mm": 0}}
        valid, issues = validate_record(record)
        assert valid  # non-blocking
        assert any("INVALID_RANGE: dimensions.length_mm" in i for i in issues)

    def test_negative_length_mm(self):
        record = {**VALID_RECORD, "dimensions": {"length_mm": -5.0}}
        valid, issues = validate_record(record)
        assert valid
        assert any("INVALID_RANGE: dimensions.length_mm" in i for i in issues)

    def test_zero_width_mm(self):
        record = {**VALID_RECORD, "dimensions": {"width_mm": 0}}
        valid, issues = validate_record(record)
        assert valid
        assert any("INVALID_RANGE: dimensions.width_mm" in i for i in issues)

    def test_negative_height_mm(self):
        record = {**VALID_RECORD, "dimensions": {"height_mm": -1}}
        valid, issues = validate_record(record)
        assert valid
        assert any("INVALID_RANGE: dimensions.height_mm" in i for i in issues)

    def test_valid_dimensions_no_issues(self):
        record = {**VALID_RECORD, "dimensions": {"length_mm": 130.0, "width_mm": 3.5, "height_mm": 3.5}}
        valid, issues = validate_record(record)
        assert valid
        assert not any("dimensions" in i for i in issues)


class TestWeightRange:

    def test_zero_weight(self):
        record = {**VALID_RECORD, "weight_g": 0}
        valid, issues = validate_record(record)
        assert valid  # non-blocking
        assert any("INVALID_RANGE: weight_g" in i for i in issues)

    def test_negative_weight(self):
        record = {**VALID_RECORD, "weight_g": -10.5}
        valid, issues = validate_record(record)
        assert valid
        assert any("INVALID_RANGE: weight_g" in i for i in issues)

    def test_valid_weight_no_issues(self):
        record = {**VALID_RECORD, "weight_g": 25.0}
        valid, issues = validate_record(record)
        assert valid
        assert not any("weight_g" in i for i in issues)


class TestStringLengths:

    def test_device_name_too_short(self):
        record = {**VALID_RECORD, "device_name": "X"}
        valid, issues = validate_record(record)
        assert valid  # non-blocking
        assert any("STRING_LENGTH: device_name" in i for i in issues)

    def test_device_name_too_long(self):
        record = {**VALID_RECORD, "device_name": "A" * 501}
        valid, issues = validate_record(record)
        assert valid
        assert any("STRING_LENGTH: device_name" in i for i in issues)

    def test_device_name_at_min_length(self):
        record = {**VALID_RECORD, "device_name": "AB"}
        valid, issues = validate_record(record)
        assert valid
        assert not any("STRING_LENGTH: device_name" in i for i in issues)

    def test_device_name_at_max_length(self):
        record = {**VALID_RECORD, "device_name": "A" * 500}
        valid, issues = validate_record(record)
        assert valid
        assert not any("STRING_LENGTH: device_name" in i for i in issues)

    def test_model_number_too_long(self):
        record = {**VALID_RECORD, "model_number": "M" * 101}
        valid, issues = validate_record(record)
        assert valid
        assert any("STRING_LENGTH: model_number" in i for i in issues)

    def test_model_number_at_max_length(self):
        record = {**VALID_RECORD, "model_number": "M" * 100}
        valid, issues = validate_record(record)
        assert valid
        assert not any("STRING_LENGTH: model_number" in i for i in issues)


class TestUrlValidity:

    def test_missing_scheme(self):
        record = {**VALID_RECORD, "source_url": "www.medtronic.com/product/123"}
        valid, issues = validate_record(record)
        assert not valid
        assert any("INVALID_URL:" in i for i in issues)

    def test_missing_netloc(self):
        record = {**VALID_RECORD, "source_url": "https://"}
        valid, issues = validate_record(record)
        assert not valid
        assert any("INVALID_URL:" in i for i in issues)

    def test_no_source_url(self):
        record = {k: v for k, v in VALID_RECORD.items() if k != "source_url"}
        valid, issues = validate_record(record)
        assert not valid
        assert any("INVALID_URL:" in i for i in issues)

    def test_valid_https_url(self):
        record = {**VALID_RECORD, "source_url": "https://www.medtronic.com/us-en/healthcare-professionals/products/cardiac-rhythm/defibrillators/index.html"}
        valid, issues = validate_record(record)
        assert valid
        assert not any("INVALID_URL:" in i for i in issues)

    def test_valid_http_url(self):
        record = {**VALID_RECORD, "source_url": "http://example.com/device"}
        valid, issues = validate_record(record)
        assert valid
        assert not any("INVALID_URL:" in i for i in issues)


class TestCleanRecord:

    def test_fully_valid_record_returns_true_empty_issues(self):
        valid, issues = validate_record(VALID_RECORD)
        assert valid is True
        assert issues == []

    def test_valid_record_with_optional_fields(self):
        record = {
            **VALID_RECORD,
            "dimensions": {"length_mm": 130.0, "width_mm": 3.5, "height_mm": 3.5},
            "weight_g": 12.5,
        }
        valid, issues = validate_record(record)
        assert valid is True
        assert issues == []


class TestEdgeCases:

    def test_empty_record_does_not_crash(self):
        valid, issues = validate_record({})
        assert not valid
        assert len(issues) > 0

    def test_none_values_do_not_crash(self):
        record = {"device_name": None, "manufacturer": None, "model_number": None, "source_url": None}
        valid, issues = validate_record(record)
        assert not valid

    def test_missing_optional_fields_are_fine(self):
        # Record with only required fields — no dimensions, no weight
        valid, issues = validate_record(VALID_RECORD)
        assert valid is True
        assert issues == []

    def test_dimensions_none_does_not_crash(self):
        record = {**VALID_RECORD, "dimensions": None}
        valid, issues = validate_record(record)
        assert valid is True
        assert issues == []

    def test_extra_unknown_fields_are_ignored(self):
        record = {**VALID_RECORD, "unknown_field": "some value", "another": 42}
        valid, issues = validate_record(record)
        assert valid is True
        assert issues == []
