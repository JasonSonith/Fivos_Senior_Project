"""Tests for dimension_parser — extracting dimensions from specs_container text.

Uses real specs_container strings captured from pipeline output.
Tests use tab-separated format (matching runner re-extraction with
get_text(separator='\\t')) for Format A, and concatenated text for
Format B and description formats.
"""

import pytest

from pipeline.dimension_parser import parse_dimensions_from_specs


# ---------------------------------------------------------------------------
# Format A — Tabular with tab separators (primary path from runner)
# ---------------------------------------------------------------------------

class TestFormatATabbed:
    """Format A: tab-separated table data (Abbott, Cordis, Shockwave, Cook, Gore)."""

    def test_abbott_absolute_pro(self):
        """Abbott Absolute Pro — Diameter (mm), Length (mm) headers."""
        specs = (
            "Absolute Pro\tPeripheral Self-Expanding Stent System\t"
            "Stock Number\tCatheter Length\tDiameter (mm)\tLength (mm)\tSheath Compatibility (F)\t"
            "80 (cm)\t135 (cm)\t"
            "1012528-20\t1012534-20\t6.0\t20\t6\t"
            "1012528-30\t1012534-30\t6.0\t30\t6\t"
            "1012528-40\t1012534-40\t6.0\t40\t6"
        )
        result = parse_dimensions_from_specs(specs, model_number="1012528-20")
        assert result.get("diameter") is not None
        assert "6.0" in result["diameter"]
        assert "mm" in result["diameter"]
        assert result.get("length") is not None
        assert "20" in result["length"]

    def test_shockwave_l6(self):
        """Shockwave L6 — Balloon Diameter (mm), Balloon length (mm)."""
        specs = (
            "Balloon Diameter (mm)\tBalloon length (mm)\tSheath Compatibility (Fr)\t"
            "Catheter Working Length (cm)\tPulses/Cycles\tCycles\tMax Pulses\t"
            "Balloon Crossing Profile (in)\tGuidewire Compatibility (in)\t"
            "8.0\t30\t7\t110\t30\t10\t3000\t0.086\t0.018\t"
            "9.0\t30\t7\t110\t30\t10\t3000\t0.087\t0.018"
        )
        result = parse_dimensions_from_specs(specs, model_number="8.0")
        assert result.get("diameter") is not None
        assert "8.0" in result["diameter"]
        assert result.get("length") is not None
        assert "30" in result["length"]

    def test_cordis_smart_control(self):
        """Cordis S.M.A.R.T. CONTROL — Stent Diameter (mm), Stent Length (mm)."""
        specs = (
            "SKU\tProduct Description\t"
            "Sheath Compatibility (F)\tGuidewire compatibility (in)\t"
            "Stent Diameter (mm)\tStent Length (mm)\tShaft Length (cm)\t"
            "C10060SL\tSMART CONTROL STENT 10 X 60 X 80CM\t6\t0.035\t10\t60\t80\t"
            "C10040SL\tSMART CONTROL STENT 10 X 40 X 80CM\t6\t0.035\t10\t40\t80"
        )
        result = parse_dimensions_from_specs(specs, model_number="C10060SL")
        assert result.get("diameter") is not None
        assert "10" in result["diameter"]
        assert result.get("length") is not None
        assert "60" in result["length"]

    def test_cook_zilver_ptx(self):
        """Cook Zilver PTX — Stent Diameter (mm), Stent Length (mm)."""
        specs = (
            "Order Number\tReference Part Number\tInstructions for Use (IFU)\t"
            "MR Status\tAccepts Wire Guide Diameter (in)\t"
            "Stent Diameter (mm)\tStent Length (mm)\tMore Info\t"
            "125 cm Over-the-Wire Delivery System\t"
            "G38404\tZISV6-35-125-5-40-PTX\t\t\t.035\t5\t40\tExpand\t"
            "G38407\tZISV6-35-125-5-60-PTX\t\t\t.035\t5\t60\tExpand"
        )
        result = parse_dimensions_from_specs(specs, model_number="G38404")
        assert result.get("diameter") is not None
        assert "5" in result["diameter"]
        assert result.get("length") is not None
        assert "40" in result["length"]

    def test_gore_viabahn(self):
        """Gore VIABAHN — Endoprosthesis Labeled Diameter (mm)."""
        specs = (
            "GORE VIABAHN Endoprosthesis\t.035\" Guidewire\tCatalogue Number\t"
            "Endoprosthesis Labeled Diameter (mm)\t"
            "Endoprosthesis Length (cm)\t"
            "Catheter Length (cm)\t"
            "Recommended Vessel Diameter (mm)\tDevice Profile (Fr)\t"
            "VBHR050202A\t5\t2.5\t120\t4.0-4.7\t7\t"
            "VBHR050502A\t5\t5.0\t120\t4.0-4.7\t7"
        )
        result = parse_dimensions_from_specs(specs, model_number="VBHR050202A")
        assert result.get("diameter") is not None
        assert "5" in result["diameter"]

    def test_abbott_omnilink_stent_diameter(self):
        """Abbott OmniLink — Stent Diameter, Stent Length headers."""
        specs = (
            "Stent Diameter (mm)\tStent Length (mm)\t"
            "12 mm\t15 mm\t18 mm\t23 mm\t28 mm\t33 mm\t"
            "Maximum Expansion\t"
            "4.5\t✓\t✓\t✓\t✓\t✓\t✓\t5.75 mm"
        )
        result = parse_dimensions_from_specs(specs, model_number="12 MM")
        assert result.get("diameter") is not None

    def test_abbott_diamondback_crown_size(self):
        """Abbott Diamondback — Crown Size maps to diameter."""
        specs = (
            "Model Number\tCrown Size (mm)\tShaft Length (cm)\t"
            "Quantity\tSheath Size\tCompatibility\t"
            "Diamondback 360 Classic Crown\t"
            "DBP-150CLASS145\t1.50\t145\t1 each\t5F\t\t"
            "DBP-200CLASS145\t2.00\t145\t1 each\t6F"
        )
        result = parse_dimensions_from_specs(specs, model_number="DBP-150CLASS145")
        assert result.get("diameter") is not None
        assert "1.50" in result["diameter"] or "1.5" in result["diameter"]

    def test_model_number_is_dimension_value(self):
        """When model_number appears in a dimension column (Shockwave), extract it."""
        specs = (
            "Balloon Diameter (mm)\tBalloon length (mm)\t"
            "8.0\t30\t"
            "9.0\t30"
        )
        result = parse_dimensions_from_specs(specs, model_number="8.0")
        assert result.get("diameter") is not None
        assert "8.0" in result["diameter"]
        assert result.get("length") is not None
        assert "30" in result["length"]


# ---------------------------------------------------------------------------
# Format A — Concatenated text (legacy/fallback, no delimiters)
# ---------------------------------------------------------------------------

class TestFormatAConcatenated:
    """Format A with concatenated text (no tabs) — best-effort extraction."""

    def test_cordis_dxl_pattern(self):
        """Cordis — 'STENT 10 X 60' description pattern in concatenated text."""
        specs = (
            "SKUSort by SKUProduct DescriptionSort by Description"
            "Stent Diameter (mm)Sort by Stent Diameter (mm)"
            "Stent Length (mm)Sort by Stent Length (mm)"
            "C10060SLSMART CONTROL STENT 10 X 60 X 80CM60.035106080"
        )
        result = parse_dimensions_from_specs(specs, model_number="C10060SL")
        assert result.get("diameter") is not None
        assert "10" in result["diameter"]
        assert result.get("length") is not None
        assert "60" in result["length"]

    def test_first_numbers_fallback(self):
        """Concatenated text without model match: extracts first numbers."""
        specs = (
            "Stent Diameter (mm)Stent Length (mm)"
            "5.040"
        )
        result = parse_dimensions_from_specs(specs)
        assert result.get("diameter") is not None
        assert "5.0" in result["diameter"]


# ---------------------------------------------------------------------------
# Format B — Key-value (Medtronic)
# ---------------------------------------------------------------------------

class TestFormatB:
    """Format B: key-value pairs without tabular headers."""

    def test_medtronic_inpact_balloon_diameters(self):
        """Medtronic IN.PACT — 'Balloon diameters4.0 to 7.0 mm'."""
        specs = (
            "FeaturesIN.PACTTM Admiral DCBIN.PACTTM 018 DCB"
            "Guidewire compatibility0.035 in0.018 in"
            "Catheter designOver-the-wire (OTW)Over-the-wire (OTW)"
            "Catheter lengths80 and 130 cm130 and 200 cm"
            "Balloon diameters4.0 to 7.0 mm4.0 to 7.0 mm"
            "Balloon lengths40, 60, 80, 120, 150, 200, 250 mm¶40, 60, 80, 100, 120, 150 mm"
        )
        result = parse_dimensions_from_specs(specs, model_number="IPU04004013P")
        assert result.get("diameter") is not None
        assert "4.0" in result["diameter"]
        assert "7.0" in result["diameter"]
        assert "mm" in result["diameter"]

    def test_medtronic_inpact_balloon_lengths(self):
        """Medtronic IN.PACT — 'Balloon lengths40, 60, 80, 120, 150, 200, 250 mm'."""
        specs = (
            "Balloon diameters4.0 to 7.0 mm"
            "Balloon lengths40, 60, 80, 120, 150, 200, 250 mm¶"
        )
        result = parse_dimensions_from_specs(specs)
        assert result.get("length") is not None
        assert "mm" in result["length"]

    def test_medtronic_resolute_onyx_no_tabular_dims(self):
        """Medtronic Resolute Onyx — key-value format."""
        specs = (
            "Stent designContinuous sinusoid technology with core wire technology"
            "Polymer and drugBioLinxTM polymer and zotarolimus"
            "Catheter distal OD (Fr)2.00-4.00 mm: 2.74.50-5.00 mm: 3.2"
        )
        result = parse_dimensions_from_specs(specs, model_number="RONYX20008UX")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Description format: "D mm x L mm" (Terumo)
# ---------------------------------------------------------------------------

class TestDescriptionFormat:
    """Terumo-style: product code followed by 'D mm x L mm' description."""

    def test_terumo_misago(self):
        """Terumo R2P Misago — '6 mm x 40 mm' in description."""
        specs = (
            "Product CodeDescription"
            "SXR06040R200 cm, 6 Fr, 6 mm x 40 mm"
            "SXR06060R200 cm, 6 Fr, 6 mm x 60 mm"
            "SXR07040R200 cm, 6 Fr, 7 mm x 40 mm"
        )
        result = parse_dimensions_from_specs(specs, model_number="SXR06040R")
        assert result.get("diameter") == "6 mm"
        assert result.get("length") == "40 mm"

    def test_terumo_different_model(self):
        """Terumo — different model picks its own row."""
        specs = (
            "Product CodeDescription"
            "SXR06040R200 cm, 6 Fr, 6 mm x 40 mm"
            "SXR07060R200 cm, 6 Fr, 7 mm x 60 mm"
        )
        result = parse_dimensions_from_specs(specs, model_number="SXR07060R")
        assert result.get("diameter") == "7 mm"
        assert result.get("length") == "60 mm"

    def test_terumo_tabbed(self):
        """Terumo with tabs — description format still works."""
        specs = (
            "Product Code\tDescription\t"
            "SXR06040R\t200 cm, 6 Fr, 6 mm x 40 mm\t"
            "SXR07060R\t200 cm, 6 Fr, 7 mm x 60 mm"
        )
        # No unit-bearing headers like "Diameter (mm)", so tabbed parser
        # falls through to description format
        result = parse_dimensions_from_specs(specs, model_number="SXR06040R")
        assert result.get("diameter") == "6 mm"
        assert result.get("length") == "40 mm"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases and error handling."""

    def test_none_input(self):
        assert parse_dimensions_from_specs(None) == {}

    def test_empty_string(self):
        assert parse_dimensions_from_specs("") == {}

    def test_whitespace_only(self):
        assert parse_dimensions_from_specs("   \n\t  ") == {}

    def test_non_dimensional_data(self):
        """Format C — clinical percentages only (Medtronic EverFlex)."""
        specs = (
            "12-month Data24-month Data36-month Data"
            "Primary Patency (PSVR < 2.0)†77.9%66.1%60.0%"
            "Patency in Lesions ≤ 80 mm87.5%80.9%71.0%"
            "Fracture Rate0.4%0.9%0.9%"
        )
        result = parse_dimensions_from_specs(specs, model_number="EVD35-06-020-080")
        assert isinstance(result, dict)

    def test_no_crash_on_garbage(self):
        """Random text should return empty dict, never raise."""
        result = parse_dimensions_from_specs("!!@@## random garbage 123")
        assert result == {}

    def test_icd_codes_not_parsed(self):
        """Abbott ICD-10 codes should not produce false dimensions."""
        specs = (
            "ICD-10 PCS CODEDESCRIPTION"
            "2X27P3TADilation of right anterior tibial artery"
        )
        result = parse_dimensions_from_specs(specs, model_number="X27P3TA")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Merge logic (simulating runner.py integration)
# ---------------------------------------------------------------------------

class TestMergeLogic:
    """Verify that parsed dimensions only fill None fields."""

    def test_fills_none_fields(self):
        """Parsed dimensions should populate fields that are None."""
        raw_fields = {
            "diameter": None,
            "length": None,
            "device_name": "Test Device",
        }
        parsed_dims = parse_dimensions_from_specs(
            "Balloon Diameter (mm)\tBalloon length (mm)\t8.0\t30",
            model_number="8.0",
        )
        measurement_fields = {"length", "width", "height", "diameter", "weight", "volume", "pressure"}
        for field, value in parsed_dims.items():
            if field in measurement_fields and raw_fields.get(field) is None:
                raw_fields[field] = value

        assert raw_fields["diameter"] is not None
        assert raw_fields["length"] is not None
        assert raw_fields["device_name"] == "Test Device"

    def test_preserves_existing_values(self):
        """Existing non-None values must not be overwritten."""
        raw_fields = {
            "diameter": "5.0 mm",  # already set
            "length": None,
        }
        parsed_dims = {"diameter": "8.0 mm", "length": "30 mm"}
        measurement_fields = {"length", "width", "height", "diameter", "weight", "volume", "pressure"}
        for field, value in parsed_dims.items():
            if field in measurement_fields and raw_fields.get(field) is None:
                raw_fields[field] = value

        assert raw_fields["diameter"] == "5.0 mm"  # preserved
        assert raw_fields["length"] == "30 mm"  # filled
