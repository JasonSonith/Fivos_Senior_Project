# Matched-Row Info View + Styled File Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "More Information" button for matched rows on the dashboard that opens a read-only device detail view (reusing the existing `/review/{id}` route), and restyle the batch-upload file picker so it matches the site's `.btn` design language.

**Architecture:** Both tasks are template-layer changes. Task 1 threads a `mode` flag through the existing review route and forks rendering inside `review.html` between "review" (existing behavior) and "info" (new read-only mode). Task 2 hides the native `<input type="file">`, promotes a `<label>` styled as `.btn-secondary` as the visible trigger, and wires a small JS listener to display the chosen filename. No new routes, no new templates, no new Python logic.

**Tech Stack:** FastAPI + Jinja2 templates, existing `.btn` classes in `app/static/css/styles.css`, vanilla JS.

**Testing note:** Pure UI/template changes — no meaningful unit tests exist for this layer in the codebase. Verification is manual smoke-testing via `docker compose up` and a browser.

**Spec:** `docs/superpowers/specs/2026-04-21-matched-info-view-and-file-picker-design.md`

---

## Task 1: Matched-Row Info View

**Files:**
- Modify: `app/routes/review.py:23-73` (`review_page` function)
- Modify: `app/templates/review.html` (whole file — adds `{% if mode %}` forks)
- Modify: `app/templates/dashboard.html:107-113` (Action `<td>` in the results table)

---

- [ ] **Step 1: Add `mode` flag to the review route**

File: `app/routes/review.py`

Inside `review_page()`, after the `validation = detail["validation"]` line (around line 34), derive `mode` from the validation status. Pass it into the template context.

Replace lines 34-73 (`validation = detail["validation"]` through the `return templates.TemplateResponse(...)` block) with:

```python
    validation = detail["validation"]
    device = detail["device"]
    comparison = validation.get("comparison_result") or {}
    gudid_record = validation.get("gudid_record") or {}

    mode = "info" if validation.get("status") == "matched" else "review"

    fields = []
    for field_key, field_label in COMPARED_FIELDS:
        comp = comparison.get(field_key, {})
        comp_h = comp.get("harvested")
        harvested_val = comp_h if comp_h is not None else device.get(field_key, "N/A")
        comp_g = comp.get("gudid")
        gudid_val = comp_g if comp_g is not None else gudid_record.get(field_key, "N/A")

        if field_key == "deviceDescription":
            match_status = None
            similarity = comp.get("description_similarity", 0)
        else:
            match_status = comp.get("match")
            similarity = None

        fields.append({
            "key": field_key,
            "label": field_label,
            "harvested": harvested_val,
            "gudid": gudid_val,
            "match": match_status,
            "similarity": similarity,
        })

    return templates.TemplateResponse(
        request,
        "review.html",
        context={
            "validation_id": validation_id,
            "validation": validation,
            "device": device,
            "fields": fields,
            "mode": mode,
            "current_user": user,
        },
    )
```

Only two lines are new: the `mode = ...` assignment and the `"mode": mode,` context entry. Everything else is unchanged.

---

- [ ] **Step 2: Fork `review.html` into info vs review modes**

File: `app/templates/review.html`

Replace the entire `{% block content %}`…`{% endblock %}` body with two forked branches. Concretely, overwrite lines 3-108 with:

```jinja
{% block content %}
<section class="hero">
    <div>
        {% if mode == "info" %}
        <p class="eyebrow">Device Details</p>
        <h1 class="page-title">{{ device.brandName or "Device" }} &mdash; <span class="mono">{{ device.versionModelNumber or "N/A" }}</span></h1>
        <p class="page-description">
            All tracked fields match GUDID. Below is the harvested record.
        </p>
        {% else %}
        <p class="eyebrow">Discrepancy Review</p>
        <h1 class="page-title">{{ device.brandName or "Device" }} &mdash; <span class="mono">{{ device.versionModelNumber or "N/A" }}</span></h1>
        <p class="page-description">
            Compare harvested values against GUDID and pick the correct value for each field.
            Your choices will update the device record in the database.
        </p>
        {% endif %}
    </div>
    <div class="hero-actions">
        <a href="/" class="btn btn-secondary">Back to Dashboard</a>
    </div>
</section>

<section class="stats-grid">
    <div class="metric-card small">
        <p class="metric-label">Status</p>
        <h3 class="metric-value">
            {% if validation.status == "matched" %}
            <span style="color: var(--success);">Matched</span>
            {% elif validation.status == "partial_match" %}
            <span style="color: var(--warning);">Partial Match</span>
            {% elif validation.status == "mismatch" %}
            <span style="color: var(--danger);">Mismatch</span>
            {% else %}
            {{ validation.status }}
            {% endif %}
        </h3>
    </div>
    <div class="metric-card small">
        <p class="metric-label">Match</p>
        <h3 class="metric-value">{{ validation.matched_fields or 0 }}/{{ validation.total_fields or 0 }}</h3>
    </div>
    <div class="metric-card small">
        <p class="metric-label">Match %</p>
        <h3 class="metric-value">{{ validation.match_percent or 0 }}%</h3>
    </div>
    <div class="metric-card small">
        <p class="metric-label">GUDID DI</p>
        <h3 class="metric-value mono" style="font-size: 17px;">{{ validation.gudid_di or "N/A" }}</h3>
    </div>
</section>

{% if mode == "info" %}
<section class="panel">
    <div class="panel-header">
        <div>
            <h3>Harvested Values</h3>
            <p>Fields collected from the manufacturer website. All values match the corresponding GUDID record.</p>
        </div>
    </div>

    <div class="review-field-row" style="border-bottom: 2px solid var(--border); padding-bottom: 10px; grid-template-columns: 1fr 2fr;">
        <div class="review-field-name" style="padding-top:0;">Field</div>
        <div style="font-weight: 700; color: var(--accent-2); font-size: 11px; text-transform: uppercase; letter-spacing: .07em;">Value</div>
    </div>

    {% for f in fields %}
    <div class="review-field-row" style="grid-template-columns: 1fr 2fr;">
        <div class="review-field-name">{{ f.label }}</div>
        <div class="review-value harvested">
            {% if f.harvested is none %}N/A{% else %}{{ f.harvested }}{% endif %}
        </div>
    </div>
    {% endfor %}
</section>
{% else %}
<form method="post" action="/review/{{ validation_id }}/save">
    <input type="hidden" name="csrf_token" value="{{ request.session.csrf_token }}">
    <section class="panel">
        <div class="panel-header">
            <div>
                <h3>Field Comparison</h3>
                <p>For each mismatched field, choose whether to keep the harvested value or use the GUDID value</p>
            </div>
        </div>

        <div class="review-field-row" style="border-bottom: 2px solid var(--border); padding-bottom: 10px;">
            <div class="review-field-name" style="padding-top:0;">Field</div>
            <div style="font-weight: 700; color: var(--accent-2); font-size: 11px; text-transform: uppercase; letter-spacing: .07em;">Harvested Value</div>
            <div style="font-weight: 700; color: var(--accent-3); font-size: 11px; text-transform: uppercase; letter-spacing: .07em;">GUDID Value</div>
            <div style="font-weight: 700; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .07em;">Pick</div>
        </div>

        {% for f in fields %}
        <div class="review-field-row {% if f.match is true %}matched{% endif %}">
            <div class="review-field-name">
                {{ f.label }}
                {% if f.match is true %}
                <br><span class="match-yes" style="font-size: 11px;">MATCH</span>
                {% elif f.match is false %}
                <br><span class="match-no" style="font-size: 11px;">MISMATCH</span>
                {% elif f.similarity is not none %}
                <br><span style="font-size: 11px; color: var(--muted);">{{ "%.0f"|format((f.similarity or 0) * 100) }}% similar</span>
                {% endif %}
            </div>

            <div class="review-value harvested">
                {% if f.harvested is none %}N/A{% else %}{{ f.harvested }}{% endif %}
            </div>

            <div class="review-value gudid">
                {% if f.gudid is none %}N/A{% else %}{{ f.gudid }}{% endif %}
            </div>

            <div class="review-pick">
                {% if f.match is true %}
                <input type="hidden" name="choice_{{ f.key }}" value="harvested">
                <span style="color: var(--success); font-size: 13px;">Matched</span>
                {% else %}
                <label>
                    <input type="radio" name="choice_{{ f.key }}" value="harvested" checked>
                    Keep Harvested
                </label>
                <label>
                    <input type="radio" name="choice_{{ f.key }}" value="gudid">
                    Use GUDID
                </label>
                {% endif %}
            </div>
        </div>
        {% endfor %}
    </section>

    <div class="form-actions" style="margin-bottom: 40px;">
        <button type="submit" class="btn btn-primary">Save Corrections</button>
        <a href="/" class="btn btn-secondary">Cancel</a>
    </div>
</form>
{% endif %}
{% endblock %}
```

Key points:
- `{% if mode == "info" %}` branch: 2-column table (Field | Value). No `<form>`, no radios, no Save/Cancel buttons. Each row overrides `grid-template-columns: 1fr 2fr` inline because `.review-field-row` CSS is defined for the 4-column layout.
- `{% else %}` branch: verbatim copy of the existing 4-column review UI. No behavioral change for partial/mismatch records.
- Hero and stats grid are shared between modes (one hero block with nested `mode` fork on copy; stats grid identical).

---

- [ ] **Step 3: Add "More Information" button to the dashboard Action column**

File: `app/templates/dashboard.html`

Replace lines 107-113 (the Action `<td>`):

```jinja
                    <td>
                        {% if d.status in ["partial_match", "mismatch"] %}
                        <a href="/review/{{ d._id }}" class="btn btn-primary btn-sm">Review</a>
                        {% elif d.status == "resolved" %}
                        <span style="color: var(--accent-3); font-size: 13px;">Resolved</span>
                        {% endif %}
                    </td>
```

with:

```jinja
                    <td>
                        {% if d.status in ["partial_match", "mismatch"] %}
                        <a href="/review/{{ d._id }}" class="btn btn-primary btn-sm">Review</a>
                        {% elif d.status == "matched" %}
                        <a href="/review/{{ d._id }}" class="btn btn-secondary btn-sm">More Information</a>
                        {% elif d.status == "resolved" %}
                        <span style="color: var(--accent-3); font-size: 13px;">Resolved</span>
                        {% endif %}
                    </td>
```

One new `{% elif %}` branch.

---

- [ ] **Step 4: Smoke test the info view**

Rebuild the container so template changes take effect:

```bash
cd /mnt/c/Users/Jason/workspace/Fivos_Senior_Project/docker
docker compose up --build -d
```

Wait for `app-1` to log `Uvicorn running on http://0.0.0.0:8500`, then:

1. Open `http://localhost:8500`, log in.
2. Click the **Matches** metric card to filter.
3. Confirm every matched row has a **More Information** button (styled as secondary — softer color than the primary Review buttons on partial/mismatch rows).
4. Click one. Expected: `/review/<id>` loads, hero says "Device Details", field table has 2 columns (Field | Value), no radio buttons, no Save Corrections button.
5. Click **Back to Dashboard**. Clear the Matches filter, click a **partial_match** row's **Review** button. Expected: the original 4-column review UI renders unchanged, with radios and Save Corrections.

If step 5 looks different from before this change, stop and re-check the `{% else %}` branch copy of the HTML in `review.html`.

---

- [ ] **Step 5: Commit Task 1**

```bash
cd /mnt/c/Users/Jason/workspace/Fivos_Senior_Project
git add app/routes/review.py app/templates/review.html app/templates/dashboard.html
git commit -m "$(cat <<'EOF'
feat(review): add read-only info view for matched devices

Dashboard's Matches filter now shows a "More Information" button
that opens /review/{id} in info mode: 2-column field table, no
GUDID comparison UI, no Save Corrections buttons. Route reuses the
existing review_page handler with a status-derived mode flag.
EOF
)"
```

---

## Task 2: Styled File Picker

**Files:**
- Modify: `app/templates/harvester.html:49-52` (batch-tab file input markup) and `app/templates/harvester.html:144-150` (existing `<script>` block)
- Modify: `app/static/css/styles.css` (append new rules at end of file)

---

- [ ] **Step 1: Append CSS rules for the file picker**

File: `app/static/css/styles.css`

Append to the end of the file (after the last existing `.domain-filter select` block, line 1138):

```css

.file-picker {
    display: flex;
    align-items: center;
    gap: 12px;
}

.file-picker input[type="file"] {
    display: none;
}

.file-name {
    color: var(--muted);
    font-size: 13px;
    word-break: break-all;
}
```

`input[type="file"] { display: none }` is belt-and-suspenders alongside the `hidden` HTML attribute on the input — some browsers still render a small sliver with `hidden` alone on file inputs.

---

- [ ] **Step 2: Replace the batch-tab file input markup**

File: `app/templates/harvester.html`

Replace lines 49-52:

```html
            <div class="field">
                <label for="file">Upload URL List (.txt)</label>
                <input id="file" type="file" name="file" accept=".txt" required>
            </div>
```

with:

```html
            <div class="field">
                <label>Upload URL List (.txt)</label>
                <div class="file-picker">
                    <label for="file" class="btn btn-secondary">Choose File</label>
                    <input id="file" type="file" name="file" accept=".txt" required hidden>
                    <span id="file-name" class="file-name">No file chosen</span>
                </div>
            </div>
```

The outer `<label>` keeps the field description (no `for=`, acts as a heading). The inner `<label for="file">` is the clickable styled button — the browser's built-in label-to-input wiring opens the file dialog on click.

---

- [ ] **Step 3: Add JS listener for filename display**

File: `app/templates/harvester.html`

Find the existing `<script>` block that starts at line 144:

```html
<script>
function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById('tab-' + tab).classList.add('active');
    event.target.classList.add('active');
}
</script>
```

Replace with:

```html
<script>
function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById('tab-' + tab).classList.add('active');
    event.target.classList.add('active');
}

document.getElementById('file').addEventListener('change', function(e) {
    const name = e.target.files[0] ? e.target.files[0].name : 'No file chosen';
    document.getElementById('file-name').textContent = name;
});
</script>
```

Added one listener below `switchTab`. Runs immediately on page load (the input exists at that point since the batch tab is inside the main DOM, just hidden by `.tab-content:not(.active)`).

---

- [ ] **Step 4: Smoke test the file picker**

Rebuild the container if you didn't already (template edits take effect on container restart, but a CSS edit requires the browser to re-fetch — hard refresh works, or rebuild to bust any container-level cache):

```bash
cd /mnt/c/Users/Jason/workspace/Fivos_Senior_Project/docker
docker compose up --build -d
```

Then:

1. Open `http://localhost:8500/harvester`.
2. Click the **Batch Upload** tab.
3. Confirm the "Choose File" button matches the site's secondary-button style (same rounded corners, padding, hover state as the "Back to Dashboard" button on the review page). Beside it: "No file chosen" in the muted text color.
4. Click **Choose File** → file dialog opens → select any `.txt` file.
5. Confirm the filename replaces "No file chosen" next to the button.
6. Click **Upload & Harvest**. Submission should proceed as before (a job starts, processing panel appears). If the form errors out with "please select a file" even though a file is selected, the `required` + `hidden` combination is blocking validation — revert `hidden` to `style="display: none;"` on the `<input>`.

---

- [ ] **Step 5: Commit Task 2**

```bash
cd /mnt/c/Users/Jason/workspace/Fivos_Senior_Project
git add app/static/css/styles.css app/templates/harvester.html
git commit -m "$(cat <<'EOF'
feat(harvester): style batch-upload file picker to match .btn design

Native <input type="file"> hidden; clickable <label class="btn btn-secondary">
replaces it as the visible control. JS listener shows the chosen filename
beside the button.
EOF
)"
```

---

## End-of-Plan Verification

After both tasks commit, do one final end-to-end pass:

- [ ] **Step 6: Full regression pass**

1. Dashboard without any filter — partial/mismatch rows still show **Review**, matched rows (visible in the unfiltered list) now show **More Information**, resolved rows show the plain "Resolved" text. No visual regressions elsewhere.
2. Click **Matches** filter — all surviving rows show **More Information**. Click the card again to clear.
3. Click **Partial Matches** filter — all surviving rows show **Review**, behavior unchanged from before.
4. Navigate to `/harvester` → **Batch Upload** tab → verify styled picker + filename display works.
5. Navigate to `/harvester` → **Single URL** tab → verify the URL input and Harvest button still look the same (Task 2 shouldn't have touched this tab).

If every step passes, the feature is complete.
