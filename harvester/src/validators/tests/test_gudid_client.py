from validators.gudid_client import _extract_new_fields


class TestDefensiveExtraction:
    def test_happy_path_all_fields_resolve(self):
        device = {
            "gmdnTerms": {"gmdn": [{"gmdnPTName": "Stent", "gmdnCode": "12345"}]},
            "productCodes": {"fdaProductCode": [{"productCode": "DYB"}, {"productCode": "OXM"}]},
            "deviceCount": 1,
            "devicePublishDate": "2023-01-15",
            "deviceRecordStatus": "Published",
            "identifiers": {"identifier": [{
                "deviceIdIssuingAgency": "GS1",
            }]},
            "lotBatch": "true",
            "serialNumber": "false",
            "manufacturingDate": "true",
            "expirationDate": "true",
        }
        result = _extract_new_fields(device)
        assert result["gmdnPTName"] == "Stent"
        assert result["gmdnCode"] == "12345"
        assert result["productCodes"] == ["DYB", "OXM"]
        assert result["deviceCountInBase"] == 1
        assert result["publishDate"] == "2023-01-15"
        assert result["deviceRecordStatus"] == "Published"
        assert result["issuingAgency"] == "GS1"
        assert result["lotBatch"] == "true"
        assert result["serialNumber"] == "false"
        assert result["manufacturingDate"] == "true"
        assert result["expirationDate"] == "true"

    def test_missing_keys_return_none(self):
        result = _extract_new_fields({})
        for key in ("gmdnPTName", "gmdnCode", "deviceCountInBase",
                    "publishDate", "deviceRecordStatus", "issuingAgency",
                    "lotBatch", "serialNumber", "manufacturingDate", "expirationDate"):
            assert result[key] is None, f"{key} should be None on empty input"
        assert result["productCodes"] is None

    def test_null_intermediate_gmdn_terms(self):
        device = {"gmdnTerms": None}
        result = _extract_new_fields(device)
        assert result["gmdnPTName"] is None
        assert result["gmdnCode"] is None

    def test_null_gmdn_list(self):
        device = {"gmdnTerms": {"gmdn": None}}
        result = _extract_new_fields(device)
        assert result["gmdnPTName"] is None

    def test_empty_gmdn_list(self):
        device = {"gmdnTerms": {"gmdn": []}}
        result = _extract_new_fields(device)
        assert result["gmdnPTName"] is None
        assert result["gmdnCode"] is None

    def test_null_identifiers(self):
        device = {"identifiers": None}
        result = _extract_new_fields(device)
        assert result["issuingAgency"] is None

    def test_empty_identifier_list(self):
        device = {"identifiers": {"identifier": []}}
        result = _extract_new_fields(device)
        assert result["issuingAgency"] is None

    def test_null_product_codes(self):
        device = {"productCodes": None}
        result = _extract_new_fields(device)
        assert result["productCodes"] is None

    def test_product_codes_with_null_entries(self):
        device = {"productCodes": {"fdaProductCode": [{"productCode": "DYB"}, {}, {"productCode": None}]}}
        result = _extract_new_fields(device)
        assert result["productCodes"] == ["DYB"]

    def test_boolean_flags_at_top_level(self):
        """Per PR2 T1 verification: lotBatch/serialNumber/manufacturingDate/expirationDate
        live at device.<field>, not inside identifiers."""
        device = {
            "lotBatch": True,
            "serialNumber": False,
            "manufacturingDate": "true",
            "expirationDate": None,
        }
        result = _extract_new_fields(device)
        assert result["lotBatch"] is True
        assert result["serialNumber"] is False
        assert result["manufacturingDate"] == "true"
        assert result["expirationDate"] is None

    def test_wrong_type_gmdn_terms_string_doesnt_crash(self):
        result = _extract_new_fields({"gmdnTerms": "not a dict"})
        assert result["gmdnPTName"] is None
        assert result["gmdnCode"] is None

    def test_wrong_type_gmdn_as_dict_doesnt_crash(self):
        result = _extract_new_fields({"gmdnTerms": {"gmdn": {"gmdnPTName": "X"}}})
        # gmdn should be a list, not a dict — resolver must not crash
        assert result["gmdnPTName"] is None

    def test_wrong_type_identifier_as_dict_doesnt_crash(self):
        result = _extract_new_fields({"identifiers": {"identifier": {"deviceIdIssuingAgency": "GS1"}}})
        assert result["issuingAgency"] is None

    def test_wrong_type_product_codes_as_string(self):
        result = _extract_new_fields({"productCodes": "not a dict"})
        assert result["productCodes"] is None

    def test_issuingAgency_prefers_Primary_over_index_zero(self):
        device = {"identifiers": {"identifier": [
            {"deviceIdType": "Package", "deviceIdIssuingAgency": "PKG-AGENCY"},
            {"deviceIdType": "Primary", "deviceIdIssuingAgency": "PRIMARY-AGENCY"},
        ]}}
        result = _extract_new_fields(device)
        assert result["issuingAgency"] == "PRIMARY-AGENCY"

    def test_issuingAgency_falls_back_to_index_zero_when_no_Primary(self):
        device = {"identifiers": {"identifier": [
            {"deviceIdIssuingAgency": "AGENCY-0"},
        ]}}
        result = _extract_new_fields(device)
        assert result["issuingAgency"] == "AGENCY-0"


class TestDeviceSizesExtraction:
    def test_flattens_deviceSizes_array(self):
        from validators.gudid_client import _extract_device_sizes
        device = {
            "deviceSizes": {
                "deviceSize": [
                    {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "3.5"}, "sizeText": None},
                    {"sizeType": "Length",   "size": {"unit": "Millimeter", "value": "20"},  "sizeText": None},
                ]
            }
        }
        sizes = _extract_device_sizes(device)
        assert sizes == [
            {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "3.5"}, "sizeText": None},
            {"sizeType": "Length",   "size": {"unit": "Millimeter", "value": "20"},  "sizeText": None},
        ]

    def test_missing_key_returns_none(self):
        from validators.gudid_client import _extract_device_sizes
        assert _extract_device_sizes({}) is None
        assert _extract_device_sizes({"deviceSizes": None}) is None
        assert _extract_device_sizes({"deviceSizes": {}}) is None
        assert _extract_device_sizes({"deviceSizes": {"deviceSize": None}}) is None
        assert _extract_device_sizes({"deviceSizes": {"deviceSize": []}}) is None

    def test_malformed_entries_filtered(self):
        from validators.gudid_client import _extract_device_sizes
        device = {"deviceSizes": {"deviceSize": [
            {"sizeType": "Diameter", "size": {"unit": "Millimeter", "value": "3.5"}, "sizeText": None},
            "not a dict",
            {"not_a_size_type": "bad"},
        ]}}
        sizes = _extract_device_sizes(device)
        assert sizes is not None
        assert len(sizes) == 1
        assert sizes[0]["sizeType"] == "Diameter"

    def test_deviceSizes_as_list_returns_none(self):
        from validators.gudid_client import _extract_device_sizes
        # GUDID API has been known to return unexpected shapes for nested objects
        assert _extract_device_sizes({"deviceSizes": [{"sizeType": "X"}]}) is None

    def test_deviceSize_as_string_returns_none(self):
        from validators.gudid_client import _extract_device_sizes
        assert _extract_device_sizes({"deviceSizes": {"deviceSize": "a string"}}) is None
