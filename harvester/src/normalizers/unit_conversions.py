from bs4 import BeautifulSoup
import re

unit_conversions = {
    #convert to length and distacne to millimeters
    'mm': ('mm', lambda x: x),
    'cm': ('mm', lambda x: x* 10),
    'm': ('mm', lambda x: x * 1000),
    'in': ('mm', lambda x: x * 25.4),
    'inches': ('mm', lambda x: x* 25.4),
    'inch': ('mm', lambda x: x* 25.4),
    '"': ('mm', lambda x: x*25.4),
    'ft': ('mm', lambda x: x* 304.8),
    'feet': ('mm', lambda x: x* 304.8),
    'foot': ('mm', lambda x: x* 304.8),
    
    #converting weighted measurements to grams
    'g': ('g', lambda x: x),
    'grams': ('g', lambda x: x),
    'kg': ('g', lambda x: x* 1000),
    'lbs': ('g', lambda x: x*453.592),
    'lb': ('g', lambda x: x * 453.592),
    'ounces': ('g', lambda x: x * 28.3495),
    'oz': ('g', lambda x: x * 28.3495),
    
    #converting volume to ml
    'ml': ('mL', lambda x: x),
    'l': ('mL', lambda x: x*1000),
    'liters': ('mL', lambda x: x*1000),
    'cc': ('mL', lambda x: x),
    'fl oz': ('mL', lambda x: x * 29.5735),
    
    #converting pressure to mmHg (millimeters of mecury)
    'mmhg': ('mmHg', lambda x: x),
    'kpa': ('mmHg', lambda x: x * 7.50062),
    'psi': ('mmHg', lambda x: x * 51.7149),
    'atm': ('mmHg', lambda x: x* 760),
    'bar': ('mmHg', lambda x: x* 750.062)
}


manufacturer_aliases = {
    # Medtronic
    'medtronic': 'Medtronic',
    'medtronic inc': 'Medtronic',
    'medtronic inc.': 'Medtronic',
    'medtronic plc': 'Medtronic',
    'medtronic, inc.': 'Medtronic',

    # Abbott Vascular
    'abbott vascular': 'Abbott Vascular',
    'abbott': 'Abbott Vascular',
    'abbott laboratories': 'Abbott Vascular',
    'abbott labs': 'Abbott Vascular',
    'abbott vascular devices': 'Abbott Vascular',
    'st. jude medical': 'Abbott Vascular',
    'st jude medical': 'Abbott Vascular',

    # Boston Scientific
    'boston scientific': 'Boston Scientific',
    'boston scientific corporation': 'Boston Scientific',
    'boston scientific corp': 'Boston Scientific',
    'boston sci': 'Boston Scientific',
    'bsc': 'Boston Scientific',

    # Shockwave Medical
    'shockwave medical': 'Shockwave Medical',
    'shockwave': 'Shockwave Medical',
    'shockwave medical inc': 'Shockwave Medical',
    'shockwave medical, inc.': 'Shockwave Medical',

    # Cook
    'cook': 'Cook',
    'cook medical': 'Cook',
    'cook medical inc': 'Cook',
    'cook medical llc': 'Cook',
    'cook group': 'Cook',
    'cook medical incorporated': 'Cook',

    # W L Gore & Associates
    'w l gore & associates': 'W L Gore & Associates',
    'w. l. gore & associates': 'W L Gore & Associates',
    'w.l. gore & associates': 'W L Gore & Associates',
    'w.l. gore': 'W L Gore & Associates',
    'wl gore': 'W L Gore & Associates',
    'gore': 'W L Gore & Associates',
    'gore medical': 'W L Gore & Associates',

    # Cordis
    'cordis': 'Cordis',
    'cordis corporation': 'Cordis',
    'cordis corp': 'Cordis',
    'cordis corp.': 'Cordis',

    # Terumo
    'terumo': 'Terumo',
    'terumo corporation': 'Terumo',
    'terumo corp': 'Terumo',
    'terumo corp.': 'Terumo',
    'terumo medical': 'Terumo',
    'terumo bct': 'Terumo',
}

def normalize_manufacturer(raw: str):
    if not raw or not isinstance(raw, str):
        return None
    cleaned = re.sub(r'\s+', ' ', raw.strip()).lower()
    return manufacturer_aliases.get(cleaned, None)


def normalize_measurement(raw_value: str):
    if not raw_value or not isinstance(raw_value, str):
        return {"value": None, "unit": None, "raw": raw_value}
    
    raw_value = raw_value.strip()
    range_match = re.match(r"([\d.]+)\s*[-–—to]+\s*([\d.]+)\s*(fl oz|[a-zA-Z°\"]+)", raw_value)

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

    match = re.match(r"([\d.]+)\s*(fl oz|[a-zA-Z°\"]+)", raw_value)
    
    if not match:
        return {
            'value': None,
            'unit': None,
            'raw': raw_value
        }
    
    value = float(match.group(1))
    unit = match.group(2).lower().strip(".")
    
    if unit in unit_conversions:
        canonical_unit, converter = unit_conversions[unit]
        
        return {
            'value': round(converter(value), 4),
            'unit': canonical_unit
        }
    
    #for unknown units
    return {
        'value': value,
        'unit': unit,
        'raw_value': raw_value
    }