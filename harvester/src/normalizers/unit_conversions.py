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
    # Medtronic — GUDID legal entity: "MEDTRONIC, INC."
    'medtronic': 'MEDTRONIC, INC.',
    'medtronic inc': 'MEDTRONIC, INC.',
    'medtronic inc.': 'MEDTRONIC, INC.',
    'medtronic plc': 'MEDTRONIC, INC.',
    'medtronic, inc.': 'MEDTRONIC, INC.',
    'medtronic, inc': 'MEDTRONIC, INC.',

    # Covidien (GUDID lists some Medtronic devices under Covidien)
    'covidien': 'Covidien LP',
    'covidien lp': 'Covidien LP',

    # Abbott Vascular — GUDID legal entity: "ABBOTT VASCULAR INC."
    'abbott vascular': 'ABBOTT VASCULAR INC.',
    'abbott': 'ABBOTT VASCULAR INC.',
    'abbott vascular inc.': 'ABBOTT VASCULAR INC.',
    'abbott vascular inc': 'ABBOTT VASCULAR INC.',
    'abbott laboratories': 'ABBOTT VASCULAR INC.',
    'abbott labs': 'ABBOTT VASCULAR INC.',
    'abbott vascular devices': 'ABBOTT VASCULAR INC.',
    'st. jude medical': 'ABBOTT VASCULAR INC.',
    'st jude medical': 'ABBOTT VASCULAR INC.',

    # Boston Scientific — GUDID legal entity: "Boston Scientific Corporation"
    'boston scientific': 'Boston Scientific Corporation',
    'boston scientific corporation': 'Boston Scientific Corporation',
    'boston scientific corp': 'Boston Scientific Corporation',
    'boston scientific corp.': 'Boston Scientific Corporation',
    'boston sci': 'Boston Scientific Corporation',
    'bsc': 'Boston Scientific Corporation',

    # Shockwave Medical — GUDID legal entity: "Shockwave Medical, Inc."
    'shockwave medical': 'Shockwave Medical, Inc.',
    'shockwave': 'Shockwave Medical, Inc.',
    'shockwave medical inc': 'Shockwave Medical, Inc.',
    'shockwave medical, inc.': 'Shockwave Medical, Inc.',
    'shockwave medical inc.': 'Shockwave Medical, Inc.',

    # Cook — GUDID legal entity: "COOK IRELAND LTD"
    'cook': 'COOK IRELAND LTD',
    'cook medical': 'COOK IRELAND LTD',
    'cook medical inc': 'COOK IRELAND LTD',
    'cook medical llc': 'COOK IRELAND LTD',
    'cook group': 'COOK IRELAND LTD',
    'cook medical incorporated': 'COOK IRELAND LTD',
    'cook ireland': 'COOK IRELAND LTD',
    'cook ireland ltd': 'COOK IRELAND LTD',

    # W L Gore & Associates — GUDID legal entity: "W. L. Gore & Associates, Inc."
    'w l gore & associates': 'W. L. Gore & Associates, Inc.',
    'w. l. gore & associates': 'W. L. Gore & Associates, Inc.',
    'w.l. gore & associates': 'W. L. Gore & Associates, Inc.',
    'w. l. gore & associates, inc.': 'W. L. Gore & Associates, Inc.',
    'w.l. gore': 'W. L. Gore & Associates, Inc.',
    'wl gore': 'W. L. Gore & Associates, Inc.',
    'gore': 'W. L. Gore & Associates, Inc.',
    'gore medical': 'W. L. Gore & Associates, Inc.',

    # Cordis — GUDID legal entity: "Cordis US Corp."
    'cordis': 'Cordis US Corp.',
    'cordis corporation': 'Cordis US Corp.',
    'cordis corp': 'Cordis US Corp.',
    'cordis corp.': 'Cordis US Corp.',
    'cordis us corp.': 'Cordis US Corp.',
    'cordis us corp': 'Cordis US Corp.',

    # Terumo — GUDID legal entity: "TERUMO CORPORATION"
    'terumo': 'TERUMO CORPORATION',
    'terumo corporation': 'TERUMO CORPORATION',
    'terumo corp': 'TERUMO CORPORATION',
    'terumo corp.': 'TERUMO CORPORATION',
    'terumo medical': 'TERUMO CORPORATION',
    'terumo bct': 'TERUMO CORPORATION',
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