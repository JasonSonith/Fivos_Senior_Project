from normalizers.unit_conversions import normalize_measurement
import pytest

class test_length_conversions:
    
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
    
class TestWeightConversions:
    
    def kg_to_g(self):
        result = normalize_measurement('0.5 kg')
        assert result['value'] == 500.0
        assert result['unit'] == 'g'