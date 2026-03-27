# Security

Input sanitization and credential management.

## Modules

| File | Role | Key Functions |
|------|------|---------------|
| `sanitizer.py` | HTML sanitization before parsing | `sanitize_html(raw_html)` |
| `credentials.py` | Env-based credential management | `CredentialManager.get_credential()`, `CredentialManager.get_db_uri()` |

## Sanitization

Strips: `<script>`, `<iframe>`, `<object>`, `<embed>`, `<form>` tags and all `on*` event attributes.

## Credentials

- Pattern: `FIVOS_{MANUFACTURER}_{FIELD}` env vars
- DB URI: `FIVOS_MONGO_URI` (fallback: `mongodb://localhost:27017/fivos`)
