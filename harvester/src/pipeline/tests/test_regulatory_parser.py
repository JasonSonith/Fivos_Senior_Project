from pipeline.regulatory_parser import parse_regulatory_from_text


class TestSingleUse:
    def test_single_use_basic(self):
        result = parse_regulatory_from_text("This device is single use only.")
        assert result["singleUse"] is True

    def test_single_use_hyphenated(self):
        result = parse_regulatory_from_text("Single-use device. Do not resterilize.")
        assert result["singleUse"] is True

    def test_single_patient_use(self):
        result = parse_regulatory_from_text("For single patient use only.")
        assert result["singleUse"] is True

    def test_disposable(self):
        result = parse_regulatory_from_text("This is a disposable catheter.")
        assert result["singleUse"] is True

    def test_do_not_reuse(self):
        result = parse_regulatory_from_text("Warning: Do not reuse this device.")
        assert result["singleUse"] is True


class TestRx:
    def test_federal_law_restricts(self):
        text = "Caution: Federal law (USA) restricts this device to sale by or on the order of a physician."
        result = parse_regulatory_from_text(text)
        assert result["rx"] is True

    def test_prescription_only(self):
        result = parse_regulatory_from_text("Prescription use only.")
        assert result["rx"] is True

    def test_rx_only(self):
        result = parse_regulatory_from_text("Rx only")
        assert result["rx"] is True


class TestDeviceSterile:
    def test_supplied_sterile(self):
        result = parse_regulatory_from_text("This device is supplied sterile.")
        assert result["deviceSterile"] is True

    def test_contents_sterile(self):
        result = parse_regulatory_from_text("Contents are sterile unless package is opened or damaged.")
        assert result["deviceSterile"] is True

    def test_sterile_packaging(self):
        result = parse_regulatory_from_text("Sterile packaging. Do not use if seal is broken.")
        assert result["deviceSterile"] is True


class TestEdgeCases:
    def test_none_input(self):
        assert parse_regulatory_from_text(None) == {}

    def test_empty_string(self):
        assert parse_regulatory_from_text("") == {}

    def test_whitespace_only(self):
        assert parse_regulatory_from_text("   ") == {}

    def test_no_regulatory_info(self):
        result = parse_regulatory_from_text("This catheter has excellent trackability.")
        assert result == {}

    def test_multiple_fields(self):
        text = (
            "Single use only. Federal law restricts this device to sale by or on "
            "the order of a physician. Contents are sterile."
        )
        result = parse_regulatory_from_text(text)
        assert result["singleUse"] is True
        assert result["rx"] is True
        assert result["deviceSterile"] is True
