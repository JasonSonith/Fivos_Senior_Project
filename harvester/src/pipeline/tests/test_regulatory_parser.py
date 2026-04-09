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


class TestLabeledContainsNRL:
    def test_contains_natural_rubber_latex(self):
        result = parse_regulatory_from_text("This device contains natural rubber latex.")
        assert result["labeledContainsNRL"] is True

    def test_made_with_natural_rubber_latex(self):
        result = parse_regulatory_from_text("Made with natural rubber latex.")
        assert result["labeledContainsNRL"] is True

    def test_contains_latex(self):
        result = parse_regulatory_from_text("Warning: contains latex components.")
        assert result["labeledContainsNRL"] is True

    def test_no_nrl_text_does_not_set_field(self):
        result = parse_regulatory_from_text("Single use only. Rx only.")
        assert "labeledContainsNRL" not in result


class TestLabeledNoNRL:
    def test_latex_free(self):
        result = parse_regulatory_from_text("This device is latex-free.")
        assert result["labeledNoNRL"] is True

    def test_latex_free_no_hyphen(self):
        result = parse_regulatory_from_text("Latex free packaging.")
        assert result["labeledNoNRL"] is True

    def test_does_not_contain_nrl(self):
        result = parse_regulatory_from_text("Does not contain natural rubber latex.")
        assert result["labeledNoNRL"] is True

    def test_not_made_with_nrl(self):
        result = parse_regulatory_from_text("Not made with natural rubber latex.")
        assert result["labeledNoNRL"] is True

    def test_no_latex_text_does_not_set_field(self):
        result = parse_regulatory_from_text("Single use only. Rx only.")
        assert "labeledNoNRL" not in result


class TestSterilizationPriorToUse:
    def test_sterilize_before_use(self):
        result = parse_regulatory_from_text("Sterilize before use.")
        assert result["sterilizationPriorToUse"] is True

    def test_must_be_sterilized(self):
        result = parse_regulatory_from_text("Must be sterilized before implantation.")
        assert result["sterilizationPriorToUse"] is True

    def test_requires_sterilization(self):
        result = parse_regulatory_from_text("Requires sterilization prior to use.")
        assert result["sterilizationPriorToUse"] is True

    def test_no_sterilization_text_does_not_set_field(self):
        result = parse_regulatory_from_text("Supplied sterile.")
        assert "sterilizationPriorToUse" not in result


class TestOTC:
    def test_over_the_counter(self):
        result = parse_regulatory_from_text("Available over the counter without a prescription.")
        assert result["otc"] is True

    def test_over_the_counter_hyphenated(self):
        result = parse_regulatory_from_text("This is an over-the-counter device.")
        assert result["otc"] is True

    def test_otc_abbreviation(self):
        result = parse_regulatory_from_text("OTC use only.")
        assert result["otc"] is True

    def test_without_a_prescription(self):
        result = parse_regulatory_from_text("Available without a prescription.")
        assert result["otc"] is True

    def test_rx_only_does_not_set_otc(self):
        result = parse_regulatory_from_text("Rx only.")
        assert "otc" not in result
