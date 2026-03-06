import re
from datetime import datetime


def normalize_date(raw) -> str | None:
    if not isinstance(raw, str):
        return None

    s = re.sub(r'\s+', ' ', raw.strip())
    if not s:
        return None

    # Formats tried in order
    simple_formats = [
        '%Y-%m-%d',
        '%Y/%m/%d',
        '%Y%m%d',
        '%m/%d/%Y',
        '%m-%d-%Y',
        '%d.%m.%Y',
        '%B %d, %Y',
        '%d %B %Y',
        '%b %d, %Y',
        '%d %b %Y',
        '%d-%b-%Y',
    ]

    for fmt in simple_formats:
        # European ambiguity: skip %m/%d/%Y if first token > 12, try %d/%m/%Y instead
        if fmt == '%m/%d/%Y':
            m = re.match(r'^(\d{1,2})/', s)
            if m and int(m.group(1)) > 12:
                try:
                    return datetime.strptime(s, '%d/%m/%Y').strftime('%Y-%m-%d')
                except ValueError:
                    pass
                continue
        if fmt == '%m-%d-%Y':
            m = re.match(r'^(\d{1,2})-', s)
            if m and int(m.group(1)) > 12:
                try:
                    return datetime.strptime(s, '%d-%m-%Y').strftime('%Y-%m-%d')
                except ValueError:
                    pass
                continue
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue

    return None
