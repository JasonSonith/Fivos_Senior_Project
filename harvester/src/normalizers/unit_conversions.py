from bs4 import BeautifulSoup
import re

unit_conversions = {
    #convert to millimeters
    'mm': ('mm', lambda x: x),
    'cm': ('mm', lambda x: x* 10),
    'm': ('mm', lambda x: 1000),
    'in': ('mm', lambda x: x * 25.4),
    'inches': ('mm', lambda x: x* 25.4),
    'inch': ('mm', lambda x: x* 25.4),
    '"': ('mm', lambda x: x*25.4),
    'ft': ('mm', lambda x: x* 304.8),
    'feet': ('mm', lambda x: x* 304.8),
    'foot': ('mm', lambda x: x* 304.8),
    
    #converting to grams
    'g': ('g', lambda x: x),
    'grams': ('g', lambda x: x * 1000),
    'kg': ('g', lambda x: x* 1000),
    'lbs': ('g', lambda x: x*453.592),
    'lb': ('g', lambda x: x * 453.592),
    'ounces': ('g', lambda x: x * 28.3495),
    'oz': ('g', lambda x: x* 29.3495),
    
    #converting volume to ml
    'ml': ('mL', lambda x: x),
    'l': ('mL', lambda x: x*1000),
    'liters': ('mL', lambda x: x*1000),
    'cc': ('mL', lambda x: x),
    'fl oz': ('mL', lambda x: x * 29.5735),
    
    #converting pressure to mmHg
    'mmhg': ('mmHg', lambda x: x),
    'kpa': ('mmHg', lambda x: x * 7.50062),
    'psi': ('mmHg', lambda x: x * 51.7149),
    'atm': ('mmHg', lambda x: x* 760),
    'bar': ('mmHg', lambda x: x* 750.062)
}

def normalize_measurement(raw_value: str):
    if not raw_value or not isinstance(raw_value, str):
        return {"value": None, "unit": None, "raw": raw_value}
    
    raw_value = raw_value.strip()
    range_match = re.match(r"([\d.]+)\s*[-–—to]+\s*([\d.]+)\s*([a-zA-Z°\"]+)", raw_value)
    
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        unit = range_match.group(3).lower().strip(".")
        midpoint = round((low + high) / 2, 4)
    
    if unit in unit_conversions:
        canonical_unit, converter = unit_conversions[unit]
        
        return {
            'value': round(converter(midpoint), 4),
            'unit': canonical_unit,
            'is_range': True,
            'range_low': round(converter(low), 4),
            'range_high': round(converter(high), 4)
        }

#fill this in for test cases
def main():
    pass

if __name__ == "__main__":
    main()