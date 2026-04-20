# Frontend Filtering — Design Spec

**Date:** 2026-04-20
**Scope:** Dashboard + Harvester pages
**Stack:** Jinja2 templates, vanilla JS, existing CSS design system (slate + teal)

---

## Summary

Add client-side filtering to two pages:
1. **Dashboard** — Metric cards (Matches, Partial, Mismatches) become clickable single-select filters for the table below.
2. **Harvester** — Domain dropdown filters the results table by manufacturer hostname after a harvest job completes.

---

## 1. Dashboard — Clickable Metric Cards

### Interaction

- Three cards are filterable: **Matches**, **Partial Matches**, **Mismatches**.
- The **Harvested Devices** card is NOT clickable (it represents the total count).
- **Click a card** → activates that filter. Table shows only rows matching that status.
- **Click the same card again** → deselects, returns to showing all rows.
- **Single-select** — only one filter active at a time.

### Visual States

| State | Card Appearance |
|-------|----------------|
| Default (no filter) | All cards normal (current look) |
| Active | Colored left border (status color), light tinted background, elevated shadow |
| Inactive (sibling) | Reduced opacity (0.5), no pointer cursor change |

Filterable cards get `cursor: pointer` at all times.

### Table Changes

- Each `<tr>` in the discrepancy table gets a `data-status` attribute: `"matched"`, `"partial_match"`, or `"mismatch"`.
- When a filter is active, JS sets `display: none` on non-matching rows.
- A filter indicator appears between the panel header and the table: "Showing N [status] results" with a "Show All" link to clear the filter.
- When filter is cleared, all rows visible again and indicator hides.

### Backend Change

The dashboard route currently queries only discrepancies (partial_match + mismatch). To support filtering by "matched," the route must also return matched validation results.

**Change in `app/routes/dashboard.py`:**
- Add `all_validation_results` to the template context (query all statuses from `validationResults` collection, limited to most recent run or a reasonable cap like 200).
- The discrepancy review queue table renders ALL results (not just discrepancies), with `data-status` on each row.

**Updated table columns:**
- Brand Name, Company, Model Number, Status (badge), Match score, Action
- "Action" column shows "Review" button only for partial_match/mismatch rows.

### CSS Additions

```css
.metric-card.filterable { cursor: pointer; transition: opacity 0.2s, box-shadow 0.2s, background 0.2s; }
.metric-card.filterable:hover { box-shadow: var(--shadow-md); }
.metric-card.active-filter { background: var(--filter-tint); border-left: 3px solid var(--filter-color); box-shadow: var(--shadow-md); }
.metric-card.dimmed { opacity: 0.5; }
.filter-indicator { padding: 8px 16px; font-size: 13px; color: var(--text-2); display: none; }
.filter-indicator.visible { display: flex; align-items: center; justify-content: space-between; }
.filter-indicator a { color: var(--teal); text-decoration: none; font-weight: 500; }
```

Each status has its own tint color:
- Matches: `--filter-tint: #f0fdf4; --filter-color: var(--success);`
- Partial: `--filter-tint: #fffbeb; --filter-color: var(--warning);`
- Mismatches: `--filter-tint: #fef2f2; --filter-color: var(--danger);`

### JS (inline in template)

```
- querySelectorAll('.metric-card.filterable') → click listeners
- On click: toggle active state, apply/remove data-status filter, update indicator
- ~30 lines of vanilla JS, no dependencies
```

---

## 2. Harvester — Domain Filter Dropdown

### Interaction

- After a batch harvest job completes and the results table is populated (via existing JS polling logic), a filter dropdown appears above the table.
- Dropdown label: "Filter by domain:"
- Options: "All" + one entry per unique hostname extracted from the URL column.
- Selecting a domain hides rows whose URL doesn't match. "All" shows everything.
- Only rendered when 2+ unique domains exist in results. Hidden for single-URL harvests.

### Implementation

- **No backend changes.** Filtering is client-side only.
- After the existing JS renders rows into `#results-body`, a function extracts hostnames from each row's URL cell, deduplicates, and populates a `<select>` element.
- Each `<tr>` gets a `data-domain` attribute set to its parsed hostname.
- On `<select>` change, JS toggles row visibility by `data-domain`.

### Visual

- Dropdown uses existing form input styling (`.field select` or a standalone styled `<select>`).
- Positioned inside `#results-panel` between the summary stats grid and the table.
- Hidden by default, shown only after results render with 2+ domains.

### CSS Additions

```css
.domain-filter { display: none; padding: 0 0 16px; }
.domain-filter.visible { display: flex; align-items: center; gap: 8px; }
.domain-filter label { font-size: 13px; color: var(--text-2); white-space: nowrap; }
.domain-filter select { padding: 6px 12px; border: 1px solid var(--border); border-radius: var(--radius); font-size: 13px; background: var(--surface); }
```

---

## Files to Modify

| File | Change |
|------|--------|
| `app/routes/dashboard.py` | Query all validation results (not just discrepancies) for template |
| `app/templates/dashboard.html` | Add `data-status` to rows, filterable classes to cards, filter indicator, inline JS |
| `app/templates/harvester.html` | Add domain filter dropdown markup, extend existing JS to populate and wire it |
| `app/static/css/styles.css` | Add filter-related CSS classes (~20 lines) |

---

## Out of Scope

- Validator page (no changes)
- Server-side filtering / pagination
- URL query params for filter state persistence
- Multi-select filters
