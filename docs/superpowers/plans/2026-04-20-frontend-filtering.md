# Frontend Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add client-side filtering to the Dashboard (clickable metric cards) and Harvester (domain dropdown) pages.

**Architecture:** Pure client-side filtering via vanilla JS `display:none` toggling on table rows. One backend change: Dashboard route returns all validation results (not just discrepancies) so "matched" rows exist in the DOM to filter to.

**Tech Stack:** FastAPI/Jinja2 templates, vanilla JavaScript, existing CSS design system (slate + teal)

---

## File Structure

| File | Role |
|------|------|
| `app/routes/dashboard.py` | Add orchestrator call that returns all validation results with device info |
| `harvester/src/orchestrator.py` | New `get_all_validations_with_devices()` function |
| `app/templates/dashboard.html` | Clickable cards, `data-status` rows, filter indicator, inline JS |
| `app/templates/harvester.html` | Domain filter dropdown, extend existing JS |
| `app/static/css/styles.css` | ~20 lines of filter CSS classes |

---

### Task 1: Backend — Add `get_all_validations_with_devices` to orchestrator

**Files:**
- Modify: `harvester/src/orchestrator.py:453-474`

- [ ] **Step 1: Add the new function after `get_discrepancies`**

Add this function at line 476 (before `get_devices`):

```python
def get_all_validations_with_devices(limit: int = 200) -> list[dict]:
    """Get all validation results with joined device info for dashboard filtering."""
    from database.db_connection import get_db
    try:
        db = get_db()
        cursor = db["validationResults"].find().sort("updated_at", -1).limit(limit)

        results = []
        for doc in cursor:
            device = db["devices"].find_one({"_id": doc.get("device_id")})
            serialized = _serialize_record(doc)
            if device:
                serialized["companyName"] = device.get("companyName", "N/A")
                serialized["versionModelNumber"] = device.get("versionModelNumber", "N/A")
            results.append(serialized)
        return results
    except Exception as e:
        logger.warning("get_all_validations_with_devices: %s", e)
        return []
```

- [ ] **Step 2: Commit**

```bash
git add harvester/src/orchestrator.py
git commit -m "feat: add get_all_validations_with_devices for dashboard filtering"
```

---

### Task 2: Dashboard route — Return all validation results

**Files:**
- Modify: `app/routes/dashboard.py`

- [ ] **Step 1: Update the route to import and call the new function**

Replace the entire file content with:

```python
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    from orchestrator import get_dashboard_stats, get_all_validations_with_devices
    stats = get_dashboard_stats()
    all_results = get_all_validations_with_devices(limit=200)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context={
            "stats": stats,
            "all_results": all_results,
            "current_user": user,
        },
    )
```

- [ ] **Step 2: Commit**

```bash
git add app/routes/dashboard.py
git commit -m "feat: dashboard route returns all validation results for filtering"
```

---

### Task 3: CSS — Add filter classes

**Files:**
- Modify: `app/static/css/styles.css`

- [ ] **Step 1: Add filter CSS at the end of the file**

Append these styles to the bottom of `styles.css`:

```css
/* ── Filtering ───────────────────────────────────── */

.metric-card.filterable {
    cursor: pointer;
    transition: opacity 0.2s, box-shadow 0.2s, background 0.2s, border-left 0.2s;
}

.metric-card.filterable:hover {
    box-shadow: var(--shadow-md);
}

.metric-card.active-filter--success {
    background: #f0fdf4;
    border-left: 3px solid var(--success);
    box-shadow: var(--shadow-md);
}

.metric-card.active-filter--warning {
    background: #fffbeb;
    border-left: 3px solid var(--warning);
    box-shadow: var(--shadow-md);
}

.metric-card.active-filter--danger {
    background: #fef2f2;
    border-left: 3px solid var(--danger);
    box-shadow: var(--shadow-md);
}

.metric-card.dimmed {
    opacity: 0.5;
    cursor: pointer;
}

.filter-indicator {
    padding: 8px 16px;
    font-size: 13px;
    color: var(--text-2);
    display: none;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border);
}

.filter-indicator.visible {
    display: flex;
}

.filter-indicator a {
    color: var(--teal);
    text-decoration: none;
    font-weight: 500;
    cursor: pointer;
}

.filter-indicator a:hover {
    text-decoration: underline;
}

.domain-filter {
    display: none;
    padding: 0 0 16px;
    align-items: center;
    gap: 8px;
}

.domain-filter.visible {
    display: flex;
}

.domain-filter label {
    font-size: 13px;
    color: var(--text-2);
    white-space: nowrap;
}

.domain-filter select {
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 13px;
    background: var(--surface);
    color: var(--text);
}
```

- [ ] **Step 2: Commit**

```bash
git add app/static/css/styles.css
git commit -m "feat: add CSS classes for filter UI (cards, indicator, domain dropdown)"
```

---

### Task 4: Dashboard template — Clickable cards + filtered table

**Files:**
- Modify: `app/templates/dashboard.html`

- [ ] **Step 1: Replace the full template content**

```html
{% extends "base.html" %}

{% block content %}
<section class="hero">
    <div>
        <p class="eyebrow">Overview</p>
        <h1 class="page-title">Dashboard</h1>
        <p class="page-description">
            Monitor harvested device records, validation results, and review discrepancies.
        </p>
    </div>
</section>

<section class="stats-grid">
    <div class="metric-card">
        <p class="metric-label">Harvested Devices</p>
        <h3 class="metric-value">{{ stats.device_count or 0 }}</h3>
        <p class="metric-foot">Total devices in the database</p>
    </div>

    <div class="metric-card filterable" data-filter="matched" data-color="success">
        <p class="metric-label">Matches</p>
        <h3 class="metric-value" style="color: var(--success);">{{ stats.matches or 0 }}</h3>
        <p class="metric-foot">Fully matched against GUDID</p>
    </div>

    <div class="metric-card filterable" data-filter="partial_match" data-color="warning">
        <p class="metric-label">Partial Matches</p>
        <h3 class="metric-value" style="color: var(--warning);">{{ stats.partial_matches or 0 }}</h3>
        <p class="metric-foot">Some fields differ from GUDID</p>
    </div>

    <div class="metric-card filterable" data-filter="mismatch" data-color="danger">
        <p class="metric-label">Mismatches</p>
        <h3 class="metric-value" style="color: var(--danger);">{{ stats.mismatches or 0 }}</h3>
        <p class="metric-foot">No fields matched GUDID</p>
    </div>
</section>

<div class="quick-actions">
    <a href="/harvester" class="action-card">
        <span class="action-title">Run Harvester</span>
        <span class="action-text">Scrape manufacturer URLs and extract device data</span>
    </a>
    <a href="/validate" class="action-card">
        <span class="action-title">Run Validation</span>
        <span class="action-text">Compare harvested devices against FDA GUDID</span>
    </a>
    <a href="/gudid" class="action-card">
        <span class="action-title">GUDID Lookup</span>
        <span class="action-text">Search the FDA GUDID database directly</span>
    </a>
</div>

<section class="panel">
    <div class="panel-header">
        <div>
            <h3>Validation Results</h3>
            <p>All validated devices — click a metric card above to filter</p>
        </div>
    </div>

    <div class="filter-indicator" id="filter-indicator">
        <span id="filter-indicator-text"></span>
        <a onclick="clearFilter()">Show All</a>
    </div>

    {% if all_results %}
    <div class="table-wrap">
        <table class="data-table">
            <thead>
                <tr>
                    <th>Brand Name</th>
                    <th>Company</th>
                    <th>Model Number</th>
                    <th>Status</th>
                    <th>Match</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody id="results-tbody">
                {% for d in all_results %}
                <tr data-status="{{ d.status }}">
                    <td>{{ d.brandName or "N/A" }}</td>
                    <td>{{ d.companyName or "N/A" }}</td>
                    <td class="mono">{{ d.versionModelNumber or "N/A" }}</td>
                    <td>
                        {% if d.status == "matched" %}
                        <span class="badge badge-success">Matched</span>
                        {% elif d.status == "partial_match" %}
                        <span class="badge badge-warning">Partial</span>
                        {% elif d.status == "mismatch" %}
                        <span class="badge badge-danger">Mismatch</span>
                        {% elif d.status == "resolved" %}
                        <span class="badge badge-resolved">Resolved</span>
                        {% else %}
                        <span class="badge badge-muted">{{ d.status or "N/A" }}</span>
                        {% endif %}
                    </td>
                    <td>{{ d.matched_fields or 0 }}/{{ d.total_fields or 0 }} ({{ d.match_percent or 0 }}%)</td>
                    <td>
                        {% if d.status in ["partial_match", "mismatch"] %}
                        <a href="/review/{{ d._id }}" class="btn btn-primary btn-sm">Review</a>
                        {% elif d.status == "resolved" %}
                        <span style="color: var(--accent-3); font-size: 13px;">Resolved</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% else %}
    <div class="empty-state">
        <p>No validation results yet. Run the harvester and validator to see results here.</p>
    </div>
    {% endif %}
</section>

<script>
(function() {
    let activeFilter = null;
    const cards = document.querySelectorAll('.metric-card.filterable');
    const rows = document.querySelectorAll('#results-tbody tr');
    const indicator = document.getElementById('filter-indicator');
    const indicatorText = document.getElementById('filter-indicator-text');

    cards.forEach(card => {
        card.addEventListener('click', () => {
            const status = card.dataset.filter;
            if (activeFilter === status) {
                clearFilter();
            } else {
                applyFilter(status, card.dataset.color);
            }
        });
    });

    function applyFilter(status, color) {
        activeFilter = status;
        let count = 0;

        rows.forEach(row => {
            if (row.dataset.status === status) {
                row.style.display = '';
                count++;
            } else {
                row.style.display = 'none';
            }
        });

        cards.forEach(c => {
            c.classList.remove('active-filter--success', 'active-filter--warning', 'active-filter--danger', 'dimmed');
            if (c.dataset.filter === status) {
                c.classList.add('active-filter--' + color);
            } else if (c.classList.contains('filterable')) {
                c.classList.add('dimmed');
            }
        });

        const label = status === 'partial_match' ? 'partial match' : status;
        indicatorText.textContent = 'Showing ' + count + ' ' + label + ' result' + (count !== 1 ? 's' : '');
        indicator.classList.add('visible');
    }

    window.clearFilter = function() {
        activeFilter = null;
        rows.forEach(row => row.style.display = '');
        cards.forEach(c => {
            c.classList.remove('active-filter--success', 'active-filter--warning', 'active-filter--danger', 'dimmed');
        });
        indicator.classList.remove('visible');
    };
})();
</script>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add app/templates/dashboard.html
git commit -m "feat: dashboard metric cards as clickable filters with JS toggle"
```

---

### Task 5: Harvester template — Domain filter dropdown

**Files:**
- Modify: `app/templates/harvester.html`

- [ ] **Step 1: Add the domain filter markup**

In `harvester.html`, find the results panel section (the `<section>` with `id="results-panel"`). Insert the domain filter div between `<div id="results-summary">...</div>` and `<div id="results-table-wrap">`:

After the closing `</div>` of `results-summary` (around line 115) and before `<div id="results-table-wrap"`, add:

```html
    <div class="domain-filter" id="domain-filter">
        <label for="domain-select">Filter by domain:</label>
        <select id="domain-select">
            <option value="all">All</option>
        </select>
    </div>
```

- [ ] **Step 2: Update the `renderRow` function to include `data-domain`**

Replace the existing `renderRow` function in the `{% if job_id %}` script block with:

```javascript
    function renderRow(r) {
        const ok = !r.error && r.devices_extracted > 0;
        let domain = '';
        try { domain = new URL(r.url).hostname; } catch(e) {}
        return `<tr data-domain="${domain}">
            <td style="max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${r.url || "N/A"}</td>
            <td>${r.scraped ? "Yes" : "No"}</td>
            <td>${r.devices_extracted || 0}</td>
            <td>${r.db_inserted || 0}</td>
            <td><span class="badge ${ok ? 'badge-success' : 'badge-danger'}">${ok ? 'OK' : 'Failed'}</span></td>
        </tr>`;
    }
```

- [ ] **Step 3: Add domain filter population logic after results render**

At the end of the batch results block (after `document.getElementById("results-body").innerHTML = rows;` around line 219), add:

```javascript
                populateDomainFilter();
```

And after the single URL result block (after `document.getElementById("results-body").innerHTML = renderRow(result);` around line 198), add:

```javascript
                populateDomainFilter();
```

- [ ] **Step 4: Add the `populateDomainFilter` function**

Add this function inside the IIFE, after the `renderRow` function:

```javascript
    function populateDomainFilter() {
        const tableRows = document.querySelectorAll('#results-body tr');
        const domains = new Set();
        tableRows.forEach(row => {
            const d = row.dataset.domain;
            if (d) domains.add(d);
        });

        if (domains.size < 2) return;

        const select = document.getElementById('domain-select');
        select.innerHTML = '<option value="all">All</option>';
        [...domains].sort().forEach(d => {
            select.innerHTML += `<option value="${d}">${d}</option>`;
        });

        document.getElementById('domain-filter').classList.add('visible');

        select.addEventListener('change', () => {
            const val = select.value;
            tableRows.forEach(row => {
                row.style.display = (val === 'all' || row.dataset.domain === val) ? '' : 'none';
            });
        });
    }
```

- [ ] **Step 5: Commit**

```bash
git add app/templates/harvester.html
git commit -m "feat: harvester domain filter dropdown for batch results"
```

---

### Task 6: Manual verification

- [ ] **Step 1: Start the dev server**

```bash
cd /mnt/c/Users/Jason/workspace/Fivos_Senior_Project
uvicorn app.main:app --port 8000 --reload
```

- [ ] **Step 2: Verify Dashboard filtering**

1. Navigate to `http://localhost:8000/`
2. Confirm metric cards show pointer cursor on hover (Matches, Partial, Mismatches — NOT Harvested Devices)
3. Click "Matches" — card highlights green, others dim, table filters to matched rows only, indicator shows "Showing N matched results"
4. Click "Matches" again — filter clears, all rows visible
5. Click "Partial Matches" — card highlights amber, table shows partial_match rows
6. Click "Show All" link — filter clears

- [ ] **Step 3: Verify Harvester filtering**

1. Navigate to `http://localhost:8000/harvester`
2. Upload a batch .txt file with URLs from 2+ different manufacturer domains
3. After harvest completes, confirm domain dropdown appears above results table
4. Select a domain — only matching rows visible
5. Select "All" — all rows visible again

- [ ] **Step 4: Run test suite**

```bash
pytest
```

Expected: All existing tests pass (no backend logic changed that would break tests).

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address any issues found during manual verification"
```
