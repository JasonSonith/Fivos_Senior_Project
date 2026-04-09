# Auth Registration & Password Security — Design Spec
**Date:** 2026-04-04  
**Status:** Approved  
**Scope:** Admin-creates-accounts user management, password complexity enforcement, HIBP breach check, forced password migration for existing demo accounts.

---

## Overview

Fivos currently uses a hardcoded `DEMO_USERS` dict in `auth_service.py` with plaintext-equivalent weak passwords. This spec replaces that with MongoDB-backed user accounts, bcrypt password hashing, NIST-aligned complexity rules, and real-time Have I Been Pwned (HIBP) k-anonymity breach checking.

**Registration model:** Admin-creates-accounts only. No self-registration route exists. An admin creates an account from `/admin/users`, a temporary password is generated, shown once, and the new user must change it on first login.

---

## Architecture

### New / Modified Files

| File | Change |
|---|---|
| `app/services/user_service.py` | **New** — user CRUD, bcrypt hashing, complexity check, server-side HIBP call, `seed_demo_users()` |
| `app/services/auth_service.py` | **Modified** — query MongoDB `users` collection instead of hardcoded dict |
| `app/routes/auth.py` | **Modified** — add `GET/POST /auth/change-password` route |
| `app/routes/admin.py` | **New** — `GET /admin/users`, `POST /admin/users/create`, `POST /admin/users/<id>/toggle` |
| `app/templates/change_password.html` | **New** — forced password change form |
| `app/templates/admin_users.html` | **New** — admin user management page |
| `app/templates/base.html` | **Modified** — add "Users" nav link for admin role only |
| `app/static/js/password.js` | **New** — client-side HIBP k-anonymity check + strength meter |
| `app/main.py` | **Modified** — call `seed_demo_users()` in lifespan startup |

### Dependencies to add
- `bcrypt` — password hashing (`pip install bcrypt`)
- `requests` — already present (used in GUDID client)

---

## Data Model

MongoDB collection: `users` (in existing `fivos-shared` DB)

```json
{
  "_id": ObjectId,
  "email": "admin@fivos.local",
  "name": "Admin",
  "role": "admin",
  "password_hash": "$2b$12$...",
  "force_password_change": true,
  "active": true,
  "created_at": ISODate,
  "created_by": "system",
  "last_login": ISODate
}
```

**Indexes:** Unique index on `email`.

**Field notes:**
- `force_password_change` — set `true` on seeded demo accounts and all admin-created accounts. Cleared to `false` atomically with `password_hash` update on successful password change.
- `active` — `false` disables login without deleting the account. Preserves audit trail.
- `created_by` — `"system"` for seeded accounts; admin's email for manually created accounts.
- `last_login` — updated on every successful login.

---

## User Service (`user_service.py`)

### Functions

**`seed_demo_users()`**  
Called from `app/main.py` lifespan on startup. Idempotent — checks by email before inserting. Seeds:
- `admin@fivos.local` / `admin123` → bcrypt hash, `force_password_change: true`, `role: admin`
- `reviewer@fivos.local` / `review123` → bcrypt hash, `force_password_change: true`, `role: reviewer`

**`get_user_by_email(email) → dict | None`**  
Queries `users` collection by email. Returns full document or `None`.

**`verify_password(plain, hashed) → bool`**  
`bcrypt.checkpw(plain.encode(), hashed.encode())`

**`check_complexity(password) → list[str]`**  
Returns list of unmet rule strings. Empty list = passes. Rules:
- Minimum 12 characters
- At least 1 uppercase letter
- At least 1 lowercase letter
- At least 1 digit
- At least 1 special character (`!@#$%^&*()-_=+[]{}|;:,.<>?`)

**`check_hibp(password) → int`**  
Server-side HIBP check. Returns breach count (0 = not found = safe).
1. Compute `SHA1(password)` → uppercase hex
2. Send first 5 chars to `https://api.pwnedpasswords.com/range/{prefix}`
3. Scan response for matching suffix
4. Return count (or 0 if not found, or 0 on network error with log warning)

**`update_password(user_id, new_password_hash)`**  
Single `update_one` call: sets `password_hash` and `force_password_change: false` atomically.

**`create_user(name, email, role, created_by) → (user_id, temp_password)`**  
Generates a cryptographically random 16-char temp password (uppercase + lowercase + digits + symbols). Hashes it. Inserts document with `force_password_change: true`, `active: true`. Returns `(inserted_id, temp_password)` — temp password returned once, never stored in plaintext.

**`update_last_login(user_id)`**  
Sets `last_login` to `datetime.utcnow()` on every successful authentication.

**`toggle_active(user_id)`**  
Flips `active` field. Used by admin to disable/enable accounts.

**`list_users() → list[dict]`**  
Returns all users sorted by `created_at`. Excludes `password_hash` field.

---

## Auth Service (`auth_service.py`)

Replace `DEMO_USERS` dict and `authenticate_user()` with:

```python
def authenticate_user(email, password):
    user = user_service.get_user_by_email(email)
    if not user:
        return None
    if not user.get("active", True):
        return None  # disabled account
    if not user_service.verify_password(password, user["password_hash"]):
        return None
    user_service.update_last_login(user["_id"])
    return user
```

`get_current_user(request)` remains session-based, unchanged.

---

## Routes

### `auth.py` additions

**`GET /auth/change-password`**  
- Requires login (`require_login`)
- If `force_password_change` is `false`, redirect to `/`
- Renders `change_password.html`

**`POST /auth/change-password`**  
- Requires login
- Validates `current_password` against stored hash
- Runs `check_complexity(new_password)` — returns errors if fails
- Runs `check_hibp(new_password)` — rejects if breach count > 0
- Checks `new_password == confirm_password`
- Calls `update_password(user_id, bcrypt_hash(new_password))`
- Redirects to `/`

### Auth guard update

`require_login` in `auth_guard.py` must also check `force_password_change`:

```python
CHANGE_PWD_EXEMPT = {"/auth/change-password", "/auth/logout"}
if user.get("force_password_change") and request.url.path not in CHANGE_PWD_EXEMPT:
    return user, RedirectResponse("/auth/change-password")
```

### `admin.py` (new)

**`GET /admin/users`** — admin role required. Renders user list + create form.

**`POST /admin/users/create`** — admin role required. Calls `create_user()`. On success, re-renders the page with the temp password revealed in a one-time display block.

**`POST /admin/users/<id>/toggle`** — admin role required. Calls `toggle_active()`. Prevents admin from disabling their own account.

---

## Password Validation Flow

### Client-side (`password.js`)

Runs on both `/auth/change-password` and the admin create form.

1. On `input` event (debounced 300ms for complexity, 500ms for HIBP):
   - Run 5 complexity checks → update checklist + 4-segment strength bar
   - Strength levels: 0–1 rules = Weak (red), 2–3 = Fair (amber), 4 = Good (green), 4 + HIBP clean = Strong (green)
2. HIBP check fires only when all 5 complexity rules pass:
   - Compute `SHA1(password)` via `SubtleCrypto.digest('SHA-1', ...)`
   - `GET https://api.pwnedpasswords.com/range/{first5chars}`
   - Check if remaining 35-char suffix appears in response
   - Show breach count warning if found; show "Strong — not found in any breach ✓" if clean
3. Submit button enabled only when: all complexity rules pass AND HIBP returns clean AND (confirm field matches, if present)
4. Show/hide toggle on all password fields

### Server-side re-validation (`auth.py` POST handler)

Defense-in-depth — re-runs complexity check and HIBP check on every submit. Rejects with 400 + error message if either fails. Cannot be bypassed by disabling JS.

---

## Admin UI (`/admin/users`)

- Accessible only to `admin` role. "Users" link in top nav appears only when `current_user.role == "admin"`.
- **User table columns:** Name, Email, Role, Last Login, Status, Action
- **Status badges:** `Active` (green), `Pwd Reset ⚠` (amber — `force_password_change: true`), `Disabled` (gray, dimmed row)
- **Create form:** Name, Email, Role dropdown (reviewer/admin). On submit: creates account, reveals temp password once in a copy-able teal code block with "This is shown once" note.
- **Action column:** Disable/Enable toggle button. Admins cannot disable themselves — their own row shows no action button.

---

## Change Password Page (`/auth/change-password`)

- No top nav — user is locked to this page until completion. A "Logout" link is available so they can exit without being permanently trapped.
- Amber "Action Required" banner explains why they're here
- Fields: Current Password, New Password (with live strength meter + checklist), Confirm New Password
- All three fields have show/hide toggles (per ui-ux-pro-max `password-toggle` rule)
- Submit button disabled until all checks pass
- On success: `force_password_change` set to `false`, redirect to `/`

---

## Migration of Existing Demo Accounts

`seed_demo_users()` runs at every startup (idempotent via email check):

1. If `admin@fivos.local` not in `users` collection → insert with hashed `admin123`, `force_password_change: true`
2. If `reviewer@fivos.local` not in `users` collection → insert with hashed `review123`, `force_password_change: true`
3. Remove `DEMO_USERS` dict from `auth_service.py`

**On first login after migration:**
- Login succeeds (bcrypt matches)
- `force_password_change: true` → redirect to `/auth/change-password`
- `admin123` / `review123` both appear in HIBP with high breach counts → HIBP check blocks reuse
- User must set a new compliant password to proceed

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| HIBP API unreachable (network error) | Server logs warning, **allows** the password (fail-open). Client shows "Breach check unavailable" notice. |
| Duplicate email on create | Flash error "An account with that email already exists" |
| Inactive account login attempt | "Your account has been disabled. Contact an administrator." |
| Wrong current password on change | "Current password is incorrect" field error |
| New password same as current | "New password must differ from current password" |

---

## Security Notes

- Passwords never logged, never stored in plaintext, never returned in API responses
- HIBP k-anonymity: only 5/40 chars of the SHA1 hash leave the browser — the full hash is never transmitted
- Temp passwords generated with `secrets.token_urlsafe()` — cryptographically random
- bcrypt work factor: 12 (default — ~250ms on modern hardware, acceptable for login)
- `password_hash` field excluded from `list_users()` response
