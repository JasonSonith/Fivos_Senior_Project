# Frontend Overhaul Plan

## What's Changing and Why

The backend now uses Ollama-first extraction (no adapter picker needed). The frontend still shows an HTML file picker and adapter-centric workflow. This overhaul aligns the UI to the new pipeline, adds discrepancy review, and moves navigation to a top bar.

---

## New Page Structure

| Page | Route | Purpose |
|------|-------|---------|
| Dashboard | `/` | Stats from MongoDB + discrepancy review queue |
| Harvester | `/harvester` | Run pipeline (scrape + extract + append to DB) |
| Validator | `/validate` | Run GUDID validation, show field-level discrepancies |
| GUDID Lookup | `/gudid` | Direct FDA lookup (unchanged) |
| Discrepancy Review | `/review/<device_id>` | Pick harvested vs GUDID value per field |

**Removed pages:** Results (`/results`), Normalize redirect (`/normalize`)

---

## 1. Layout: Sidebar to Top Nav

### Current (`base.html`)
- 290px fixed sidebar with nav links + system status
- Top bar with title + chips

### New (`base.html`)
- **No sidebar.** Single top navigation bar spanning full width.
- Left: Fivos logo + brand name
- Center/Right: Nav links (Dashboard, Harvester, Validator, GUDID Lookup) as horizontal pills
- Content fills full viewport width below the nav bar
- Keep the dark theme, existing color variables, and glass-morphism aesthetic

### CSS Changes (`styles.css`)
- Remove `.sidebar`, `.sidebar-section`, `.sidebar-footer`, `.sidebar-label`, `.brand-wrap` (vertical layout)
- Replace `.app-shell` flex layout (side-by-side) with a vertical stack
- Add `.topnav` — full-width bar, `display: flex`, `align-items: center`, horizontal nav links
- Add `.topnav-brand` — logo + "Fivos" inline
- Add `.topnav-links` — horizontal flex row of nav pills
- `.main-area` becomes full-width, no sidebar offset
- Remove old `.topbar` (redundant with new top nav)
- Keep all existing component styles (`.panel`, `.metric-card`, `.data-table`, `.btn`, `.hero`, `.form-grid-modern`, etc.)

### Files Changed
- `app/templates/base.html` — rewrite shell structure
- `app/static/css/styles.css` — replace sidebar styles with top nav styles

---

## 2. Dashboard (`/`)

### Current
- 4 metric cards: HTML Files, Harvested Devices, Validation Results, Last Run
- Platform Summary (static feature list)
- Quick Actions (links to harvester, GUDID, validation)

### New
- **4 metric cards:** Harvested Devices (from `devices` count), Matches, Partial Matches, Mismatches (from `validationResults` counts)
- **Quick Actions row:** Run Harvester, Run Validation, GUDID Lookup
- **Discrepancy Review Queue** — a table showing all `validationResults` where `status` is `partial_match` or `mismatch`
  - Columns: Brand Name, Company, Model Number, Status (color-coded), Match %, Action (Review button)
  - "Review" button links to `/review/<validation_id>`
  - Devices with `status: "matched"` do NOT appear here (they're fine as-is in `devices`)
  - Empty state: "All devices are fully matched. No discrepancies to review."

### Backend Changes (`orchestrator.py`)
- `get_dashboard_stats()` — replace `html_files` count with match/partial/mismatch counts from `validationResults`:
  ```python
  return {
      "device_count": db["devices"].count_documents({}),
      "matches": db["validationResults"].count_documents({"status": "matched"}),
      "partial_matches": db["validationResults"].count_documents({"status": "partial_match"}),
      "mismatches": db["validationResults"].count_documents({"status": "mismatch"}),
      "last_run": ...,
  }
  ```
- New function `get_discrepancies(limit=100)` — query `validationResults` where `status` in `["partial_match", "mismatch"]`, sorted by `updated_at` desc, join with device `brandName`/`companyName`/`versionModelNumber`

### Route Changes (`app/routes/dashboard.py`)
- Call `get_dashboard_stats()` and `get_discrepancies()`, pass both to template

### Template Changes (`app/templates/dashboard.html`)
- Replace HTML Files card with Matches/Partial/Mismatches cards
- Remove Platform Summary and Quick Actions panels
- Add Quick Actions as a simple button row under the stats
- Add Discrepancy Review Queue table

### Files Changed
- `app/routes/dashboard.py`
- `app/templates/dashboard.html`
- `harvester/src/orchestrator.py` — update `get_dashboard_stats()`, add `get_discrepancies()`

---

## 3. Harvester Console (`/harvester`)

### Current
- Lists HTML files from `out_html/` with checkboxes
- User selects files, clicks "Run Pipeline"
- Calls `run_pipeline_batch()` which uses Ollama extraction, then overwrites DB

### New
- **Two input modes** for harvesting, each processes one URL at a time through the full pipeline (scrape + Ollama extract + append to `devices`):

  **Mode A — Single URL:**
  - Text input field for one URL
  - "Harvest" button
  - Scrapes that single URL, extracts devices, appends to DB
  - Shows result inline: success/fail, how many devices extracted from that page

  **Mode B — File Upload (.txt):**
  - File upload input accepting `.txt` files (one URL per line, `#` comments ignored)
  - "Upload & Harvest" button
  - Backend processes each URL individually (one at a time, sequentially)
  - Live progress: shows which URL is being processed (e.g., "Processing 3/12: medtronic.com/...")
  - Per-URL result row appears as each completes: URL, status (success/fail), devices extracted

- **UI layout:**
  - Two-tab or two-section layout: "Single URL" and "Batch Upload"
  - Processing indicator with per-URL progress (polls `/api/jobs/<id>`)
  - Results table below showing harvest history for the current session
  - **Append mode only.** No `--overwrite` flag. Each run adds new records.

### Backend Changes (`orchestrator.py`)
- New function `run_harvest_single(url: str)`:
  ```python
  def run_harvest_single(url: str) -> dict:
      """Scrape one URL, extract with Ollama, append to devices collection."""
      # 1. Scrape the single URL
      # 2. Extract via Ollama (two-pass)
      # 3. Insert records into db["devices"] (append, no drop)
      # Return: {"url": url, "scraped": bool, "devices_extracted": N, "db_inserted": N, "run_id": "...", "error": str|None}
  ```
- New function `run_harvest_batch(urls: list[str])`:
  ```python
  def run_harvest_batch(urls: list[str]) -> dict:
      """Process a list of URLs one at a time. Updates job progress per URL."""
      # Loops over urls, calls run_harvest_single() for each
      # Updates app.state.jobs[job_id] with per-URL progress so frontend can poll
      # Return: {"total": N, "succeeded": N, "failed": N, "results": [per-url dicts], "run_id": "..."}
  ```
  These replace the current `run_pipeline_batch()` which overwrites by default.

### Important: Append-Only from the UI
- The current `run_pipeline_batch(overwrite=True)` and `run_validation(overwrite=True)` default to dropping collections. **Both defaults must change to `overwrite=False`.**
- The `--overwrite` flag remains available on the CLI (`runner.py`) for manual/developer use, but the UI never passes it.
- `run_harvest_single()` and `run_harvest_batch()` have no overwrite parameter at all — they always append.

### Route Changes (`app/routes/harvester.py`)
- GET `/harvester/` — render page (no data needed)
- POST `/harvester/run-single` — accept `url` from form input, call `run_harvest_single(url)` as background task
- POST `/harvester/run-batch` — accept uploaded `.txt` file, parse URLs, call `run_harvest_batch(urls)` as background task

### Template Changes (`app/templates/harvester.html`)
- Remove HTML file table and checkboxes
- Add two input sections:
  1. Single URL: text input + "Harvest" button
  2. Batch: file upload (`.txt`) + "Upload & Harvest" button
- Processing indicator with per-URL progress for batch mode
- Results summary: per-URL status rows (URL, success/fail, device count)

### Files Changed
- `app/routes/harvester.py`
- `app/templates/harvester.html`
- `harvester/src/orchestrator.py` — add `run_harvest_single()` and `run_harvest_batch()`, keep `run_pipeline_batch()` for CLI compatibility

---

## 4. Validator Console (`/validate`)

### Current
- "Run Validation" button
- Summary cards (total, matches, partials, mismatches, not found)
- Table with: Brand Name, Status, Match %, GUDID DI, Updated

### New
- "Run Validation" button (same behavior — compares `devices` against GUDID API)
- Summary cards (same — total, matches, partials, mismatches, not found)
- **Results table with field-level discrepancies visible:**
  - Columns: Brand Name, Status, versionModelNumber (match?), catalogNumber (match?), brandName (match?), companyName (match?), Description Similarity, GUDID DI, Action
  - Each field cell shows a color indicator: green check if match, red X if mismatch, gray dash if skipped (None)
  - Clicking a row or "Review" button on partial/mismatch rows goes to `/review/<validation_id>`
  - Matched rows have no action button (they're fine)

### Backend Changes
- `get_validation_results()` already returns `comparison_result` dict — just need to pass it through to the template. Currently it does, but the template doesn't render it.

### Route Changes (`app/routes/validate.py`)
- No route logic changes needed. The existing route already fetches validation results with comparison data.

### Template Changes (`app/templates/validate.html`)
- Expand table to show per-field match status from `v.comparison_result`
- Add color-coded indicators per field
- Add "Review" link for non-matched rows

### Files Changed
- `app/templates/validate.html`

---

## 5. Discrepancy Review Page (`/review/<validation_id>`)

### This is entirely new.

**Purpose:** For a single partial_match or mismatch device, show each compared field side-by-side (harvested value vs GUDID value) and let the user pick which is correct. The chosen value updates the `devices` collection.

### UI Layout
- **Header:** Device name, model number, company — identifying info
- **Field comparison table:**
  - Row per compared field: `versionModelNumber`, `catalogNumber`, `brandName`, `companyName`, `deviceDescription`
  - Columns: Field Name, Harvested Value, GUDID Value, Match Status, Pick (radio buttons: "Keep Harvested" / "Use GUDID")
  - Matched fields are pre-selected as "Keep Harvested" and grayed out (no action needed)
  - Mismatched fields are highlighted — user must pick one
  - Description shows Jaccard similarity score + both full texts
- **"Save Corrections" button** — POST to `/review/<validation_id>/save`

### Backend Changes (`orchestrator.py`)
- New function `get_discrepancy_detail(validation_id: str)`:
  - Fetch the `validationResults` document by `_id`
  - Fetch the linked `devices` document by `device_id`
  - Return both records + comparison_result for the template
- New function `resolve_discrepancy(validation_id: str, field_choices: dict)`:
  - `field_choices` maps field names to `"harvested"` or `"gudid"`
  - For each field where user chose `"gudid"`, update `devices` document with the GUDID value
  - Update the `validationResults` document: set `status` to `"resolved"`, record which fields were corrected and when
  - Return success/failure

### Route (`app/routes/review.py` — new file)
- GET `/review/<validation_id>` — call `get_discrepancy_detail()`, render template
- POST `/review/<validation_id>/save` — parse form (field radio buttons), call `resolve_discrepancy()`, redirect to dashboard with success message

### Template (`app/templates/review.html` — new file)
- Device identification header
- Field-by-field comparison form with radio buttons
- Description comparison with similarity score
- "Save Corrections" button

### Files Created
- `app/routes/review.py`
- `app/templates/review.html`

### Files Changed
- `app/main.py` — register the new review router
- `harvester/src/orchestrator.py` — add `get_discrepancy_detail()` and `resolve_discrepancy()`

---

## 6. GUDID Lookup (`/gudid`)

**No changes.** Keep current route, template, and functionality exactly as-is.

---

## 7. Cleanup

### Files to Delete
- `app/routes/results.py` — functionality merged into dashboard + validator
- `app/routes/normalize.py` — dead redirect, no longer needed
- `app/templates/results.html` — replaced by dashboard discrepancy table + validator detail

### Files to Update
- `app/main.py` — remove `results` and `normalize` router includes, add `review` router

---

## Implementation Order

Each step produces a working app (no broken intermediate states):

### Step 1: Layout overhaul (base.html + styles.css)
Move sidebar nav to top bar. All existing pages still render correctly with new layout.

### Step 2: Dashboard overhaul
Update stats to pull from MongoDB validation counts. Add discrepancy queue table. Remove HTML file count and static feature panels.

### Step 3: Harvester overhaul
Replace file picker with URL textarea. Wire to new `run_harvest()` function that appends to DB.

### Step 4: Validator overhaul
Expand results table to show per-field match/mismatch status. Add "Review" links.

### Step 5: Discrepancy review page (new)
Build the field-by-field comparison + pick UI. Wire save to update `devices` collection.

### Step 6: Cleanup
Remove dead routes/templates. Final pass on styling consistency.

---

## Summary of All File Changes

| File | Action | Step |
|------|--------|------|
| `app/templates/base.html` | Rewrite (sidebar to top nav) | 1 |
| `app/static/css/styles.css` | Rewrite sidebar styles, add top nav styles | 1 |
| `app/routes/dashboard.py` | Update to pass new stats + discrepancies | 2 |
| `app/templates/dashboard.html` | Rewrite (new stats, discrepancy queue) | 2 |
| `harvester/src/orchestrator.py` | Update `get_dashboard_stats()`, add `get_discrepancies()`, add `run_harvest()`, add `get_discrepancy_detail()`, add `resolve_discrepancy()` | 2-5 |
| `app/routes/harvester.py` | Rewrite (URL textarea, call `run_harvest()`) | 3 |
| `app/templates/harvester.html` | Rewrite (URL textarea, remove file picker) | 3 |
| `app/templates/validate.html` | Expand table with per-field discrepancies | 4 |
| `app/routes/review.py` | **New file** (GET + POST for discrepancy review) | 5 |
| `app/templates/review.html` | **New file** (field comparison form) | 5 |
| `app/main.py` | Remove results/normalize routers, add review router | 6 |
| `app/routes/results.py` | **Delete** | 6 |
| `app/routes/normalize.py` | **Delete** | 6 |
| `app/templates/results.html` | **Delete** | 6 |

---

## MongoDB Schema Impact

No schema changes to `devices` or `validationResults` collections. The review feature only:
- Reads existing fields from both collections
- Updates individual field values in `devices` documents
- Adds `status: "resolved"` + `resolved_at` + `resolved_fields` to `validationResults` documents

No migrations needed.
