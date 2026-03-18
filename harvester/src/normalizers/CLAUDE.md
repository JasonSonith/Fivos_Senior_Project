# normalizers/

Cleans and standardizes raw scraped field values before they enter the pipeline.

## Modules

| File | Key Function(s) | Output |
|------|----------------|--------|
| `booleans.py` | `normalize_boolean`, `normalize_mri_status` | `bool\|None`, MRI enum string |
| `dates.py` | `normalize_date` | ISO `YYYY-MM-DD` or `None` |
| `model_numbers.py` | `clean_model_number` | Uppercase stripped string or `None` |
| `text.py` | `normalize_text`, `clean_brand_name` | Cleaned UTF-8 string or `None` |
| `unit_conversions.py` | `normalize_measurement`, `normalize_manufacturer` | `dict` with `value`/`unit`; canonical name |

All functions return `None` on empty or invalid input. Tests in `tests/`.
