from normalizers.unit_conversions import normalize_measurement, normalize_manufacturer
import pytest


class TestLengthConversions:

    def test_cm_to_mm(self):
        result = normalize_measurement('10 cm')
        assert result['value'] == 100.0
        assert result['unit'] == 'mm'

    def test_inches_to_mm(self):
        result = normalize_measurement('2.5 in')
        assert result['value'] == 63.5
        assert result['unit'] == 'mm'

    def test_already_mm(self):
        result = normalize_measurement('45 mm')
        assert result['value'] == 45.0
        assert result['unit'] == 'mm'

    def test_ft_to_mm(self):
        result = normalize_measurement('1 ft')
        assert result['value'] == 304.8
        assert result['unit'] == 'mm'

    def test_inch_symbol(self):
        result = normalize_measurement('6"')
        assert result['value'] == pytest.approx(152.4)
        assert result['unit'] == 'mm'

    def test_m_to_mm(self):
        result = normalize_measurement('2 m')
        assert result['value'] == 2000.0
        assert result['unit'] == 'mm'

    def test_inches_long(self):
        result = normalize_measurement('3 inches')
        assert result['value'] == pytest.approx(76.2)
        assert result['unit'] == 'mm'

    def test_feet_long(self):
        result = normalize_measurement('2 feet')
        assert result['value'] == pytest.approx(609.6)
        assert result['unit'] == 'mm'


class TestWeightConversions:

    def test_kg_to_g(self):
        result = normalize_measurement('0.5 kg')
        assert result['value'] == 500.0
        assert result['unit'] == 'g'

    def test_already_g(self):
        result = normalize_measurement('100 g')
        assert result['value'] == 100.0
        assert result['unit'] == 'g'

    def test_lbs_to_g(self):
        result = normalize_measurement('1 lbs')
        assert result['value'] == pytest.approx(453.592)
        assert result['unit'] == 'g'

    def test_lb_to_g(self):
        result = normalize_measurement('1 lb')
        assert result['value'] == pytest.approx(453.592)
        assert result['unit'] == 'g'

    def test_oz_to_g(self):
        result = normalize_measurement('2 oz')
        assert result['value'] == pytest.approx(56.699)
        assert result['unit'] == 'g'

    def test_ounces_to_g(self):
        result = normalize_measurement('2 ounces')
        assert result['value'] == pytest.approx(56.699)
        assert result['unit'] == 'g'

    def test_grams_long(self):
        result = normalize_measurement('50 grams')
        assert result['value'] == 50.0
        assert result['unit'] == 'g'


class TestVolumeConversions:

    def test_already_ml(self):
        result = normalize_measurement('100 ml')
        assert result['value'] == 100.0
        assert result['unit'] == 'mL'

    def test_l_to_ml(self):
        result = normalize_measurement('1 l')
        assert result['value'] == 1000.0
        assert result['unit'] == 'mL'

    def test_liters_to_ml(self):
        result = normalize_measurement('2 liters')
        assert result['value'] == 2000.0
        assert result['unit'] == 'mL'

    def test_cc_to_ml(self):
        result = normalize_measurement('5 cc')
        assert result['value'] == 5.0
        assert result['unit'] == 'mL'

    def test_fl_oz_to_ml(self):
        result = normalize_measurement('1 fl oz')
        assert result['value'] == pytest.approx(29.5735)
        assert result['unit'] == 'mL'


class TestPressureConversions:

    def test_already_mmhg(self):
        result = normalize_measurement('120 mmhg')
        assert result['value'] == 120.0
        assert result['unit'] == 'mmHg'

    def test_kpa_to_mmhg(self):
        result = normalize_measurement('10 kpa')
        assert result['value'] == pytest.approx(75.0062)
        assert result['unit'] == 'mmHg'

    def test_psi_to_mmhg(self):
        result = normalize_measurement('1 psi')
        assert result['value'] == pytest.approx(51.7149)
        assert result['unit'] == 'mmHg'

    def test_atm_to_mmhg(self):
        result = normalize_measurement('1 atm')
        assert result['value'] == 760.0
        assert result['unit'] == 'mmHg'

    def test_bar_to_mmhg(self):
        result = normalize_measurement('1 bar')
        assert result['value'] == pytest.approx(750.062)
        assert result['unit'] == 'mmHg'


class TestRangeValues:

    def test_range_mm(self):
        result = normalize_measurement('10-20 mm')
        assert result['is_range'] is True
        assert result['range_low'] == 10.0
        assert result['range_high'] == 20.0
        assert result['value'] == 15.0

    def test_range_cm(self):
        result = normalize_measurement('5-10 cm')
        assert result['is_range'] is True
        assert result['range_low'] == pytest.approx(50.0)
        assert result['range_high'] == pytest.approx(100.0)
        assert result['value'] == pytest.approx(75.0)

    def test_range_with_en_dash(self):
        result = normalize_measurement('10\u201315 mm')
        assert result['is_range'] is True
        assert result['range_low'] == 10.0
        assert result['range_high'] == 15.0
        assert result['value'] == 12.5


class TestEdgeCases:

    def test_empty_string(self):
        result = normalize_measurement('')
        assert result['value'] is None
        assert result['unit'] is None

    def test_none_input(self):
        result = normalize_measurement(None)
        assert result['value'] is None
        assert result['unit'] is None

    def test_no_unit(self):
        result = normalize_measurement('42')
        assert result['value'] is None

    def test_unknown_unit(self):
        result = normalize_measurement('5 xyz')
        assert result['value'] == 5.0
        assert result['unit'] == 'xyz'

    def test_extra_whitespace(self):
        result = normalize_measurement('  10  cm  ')
        assert result['value'] == 100.0
        assert result['unit'] == 'mm'

    def test_decimal_precision(self):
        result = normalize_measurement('1.5 cm')
        assert result['value'] == 15.0
        assert result['unit'] == 'mm'


class TestManufacturerNormalization:

    # Canonical name pass-through
    def test_canonical_medtronic(self):
        assert normalize_manufacturer('Medtronic') == 'Medtronic'

    def test_canonical_abbott_vascular(self):
        assert normalize_manufacturer('Abbott Vascular') == 'Abbott Vascular'

    def test_canonical_boston_scientific(self):
        assert normalize_manufacturer('Boston Scientific') == 'Boston Scientific'

    def test_canonical_shockwave_medical(self):
        assert normalize_manufacturer('Shockwave Medical') == 'Shockwave Medical'

    def test_canonical_cook(self):
        assert normalize_manufacturer('Cook') == 'Cook'

    def test_canonical_wl_gore(self):
        assert normalize_manufacturer('W L Gore & Associates') == 'W L Gore & Associates'

    def test_canonical_cordis(self):
        assert normalize_manufacturer('Cordis') == 'Cordis'

    def test_canonical_terumo(self):
        assert normalize_manufacturer('Terumo') == 'Terumo'

    # Common aliases — Medtronic
    def test_medtronic_inc(self):
        assert normalize_manufacturer('Medtronic Inc.') == 'Medtronic'

    def test_medtronic_plc(self):
        assert normalize_manufacturer('Medtronic plc') == 'Medtronic'

    # Common aliases — Abbott Vascular
    def test_abbott(self):
        assert normalize_manufacturer('Abbott') == 'Abbott Vascular'

    def test_st_jude_medical(self):
        assert normalize_manufacturer('St. Jude Medical') == 'Abbott Vascular'

    # Common aliases — Boston Scientific
    def test_boston_scientific_corporation(self):
        assert normalize_manufacturer('Boston Scientific Corporation') == 'Boston Scientific'

    def test_bsc(self):
        assert normalize_manufacturer('BSC') == 'Boston Scientific'

    # Common aliases — Shockwave Medical
    def test_shockwave(self):
        assert normalize_manufacturer('Shockwave') == 'Shockwave Medical'

    def test_shockwave_medical_inc(self):
        assert normalize_manufacturer('Shockwave Medical Inc') == 'Shockwave Medical'

    # Common aliases — Cook
    def test_cook_medical(self):
        assert normalize_manufacturer('Cook Medical') == 'Cook'

    def test_cook_medical_llc(self):
        assert normalize_manufacturer('Cook Medical LLC') == 'Cook'

    # Common aliases — W L Gore & Associates
    def test_gore(self):
        assert normalize_manufacturer('Gore') == 'W L Gore & Associates'

    def test_wl_gore_dotted(self):
        assert normalize_manufacturer('W.L. Gore & Associates') == 'W L Gore & Associates'

    # Common aliases — Cordis
    def test_cordis_corporation(self):
        assert normalize_manufacturer('Cordis Corporation') == 'Cordis'

    def test_cordis_corp(self):
        assert normalize_manufacturer('Cordis Corp') == 'Cordis'

    # Common aliases — Terumo
    def test_terumo_corporation(self):
        assert normalize_manufacturer('Terumo Corporation') == 'Terumo'

    def test_terumo_medical(self):
        assert normalize_manufacturer('Terumo Medical') == 'Terumo'

    # Case insensitivity
    def test_all_caps_medtronic(self):
        assert normalize_manufacturer('MEDTRONIC') == 'Medtronic'

    def test_all_caps_boston_scientific(self):
        assert normalize_manufacturer('BOSTON SCIENTIFIC') == 'Boston Scientific'

    def test_mixed_case_cook(self):
        assert normalize_manufacturer('cOoK mEdIcAl') == 'Cook'

    # Whitespace normalization
    def test_leading_trailing_spaces(self):
        assert normalize_manufacturer('  Medtronic  ') == 'Medtronic'

    def test_internal_double_spaces(self):
        assert normalize_manufacturer('Boston  Scientific') == 'Boston Scientific'

    def test_leading_trailing_with_alias(self):
        assert normalize_manufacturer('  Cook Medical  ') == 'Cook'

    # Unknown manufacturer
    def test_unknown_returns_none(self):
        assert normalize_manufacturer('Acme Medical Devices') is None

    def test_partial_match_returns_none(self):
        assert normalize_manufacturer('Medtronic Extra') is None

    # None / empty string
    def test_none_input(self):
        assert normalize_manufacturer(None) is None

    def test_empty_string(self):
        assert normalize_manufacturer('') is None

    def test_non_string_input(self):
        assert normalize_manufacturer(42) is None
