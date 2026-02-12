from normalizers.unit_conversions import normalize_measurement
import pytest

class test_length_conversions:
    
    def test_cm_to_mm(self):
        result = normalize_measurement('10 cm')
        assert result['value'] == 100.0
        assert result['unit'] == 'mm'
    
    def test_inches_to_mm(self):
        result = normalize_measurement('2.5 in')