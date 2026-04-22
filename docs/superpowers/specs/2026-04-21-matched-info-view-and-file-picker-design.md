# Design: Matched-Row Info View + Styled File Picker

**Date:** 2026-04-21
**Author:** Jason
**Status:** Approved

## Problem

Two unrelated UI gaps on the dashboard and harvester pages:

1. **Matched rows have no action.** When the dashboard's Matches filter is active, the Action column is empty for matched rows. Reviewers have no way to drill into a matched record to verify the match or inspect the harvested data.
2. **The batch-upload file picker is unstyled.** `<input type="file">` in `harvester.html` renders as the browser-default button, visually inconsistent with the rest of the light-mode design system (Fira Sans body, teal accent, rounded `.btn` classes).

## Goals

1. Add a "More Information" button in the Action column for matched rows that opens a read-only detail view of the device.
2. Style the batch-upload file picker to match the site's existing `.btn` components.

---

## Task 1: Matched-Row Info View

### Approach

Reuse the existing `/review/{validation_id}` route. The route already fetches the device, validation, and comparison data it needs. Add a `mode` branch: when `validation.status == "matched"`, render the existing `review.html` template in an "info" mode that strips the GUDID column and the discrepancy-resolution UI.

No new routes. No new templates. Conditional rendering inside `review.html`.

### Changes

#### `app/templates/dashboard.html` — Action column

Add a branch for `matched` in the Action `<td>`:

```jinja
{% if d.status in ["partial_match", "mismatch"] %}
<a href="/review/{{ d._id }}" class="btn btn-primary btn-sm">Review</a>
{% elif d.status == "matched" %}
<a href="/review/{{ d._id }}" class="btn btn-secondary btn-sm">More Information</a>
{% elif d.status == "resolved" %}
<span style="color: var(--accent-3); font-size: 13px;">Resolved</span>
{% endif %}
```

Using `btn-secondary` to visually distinguish the informational action from the actionable `btn-primary` "Review".

#### `app/routes/review.py` — `review_page()`

After fetching the validation doc, derive a `mode` flag and pass it to the template:

```python
mode = "info" if validation.get("status") == "matched" else "review"
# ... existing field-building loop stays unchanged ...
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

No signature change, no new route. Partial/mismatch URLs still hit `mode == "review"` and behave identically.

#### `app/templates/review.html` — conditional rendering on `mode`

Wrap the existing structure in `{% if mode == "review" %}` / `{% else %}` branches:

- **Hero section:**
  - `mode == "info"`: eyebrow "Device Details"; description "All tracked fields match GUDID. Below is the harvested record."
  - `mode == "review"`: existing text unchanged.

- **Stats grid:** unchanged for both modes (Status, Match ratio, Match %, GUDID DI are still useful).

- **Field comparison panel:**
  - `mode == "info"`:
    - Two-column header: **Field** | **Value**
    - Each field row shows `f.harvested` in the value column. Match badge and the `deviceDescription` similarity label are both hidden. Pick column removed.
    - No `<form>` wrapper, no radio inputs, no hidden `choice_` inputs.
  - `mode == "review"`: existing 4-column layout unchanged.

- **Bottom action row:**
  - `mode == "info"`: hidden entirely (hero's "Back to Dashboard" is sufficient).
  - `mode == "review"`: existing "Save Corrections" / "Cancel" buttons unchanged.

### What's preserved from the existing template

Hero "Back to Dashboard" button, top stats grid, layout, typography. Only the comparison table and bottom form actions fork on `mode`.

### Data flow

Review route already resolves the device doc and builds `fields` with `harvested`, `gudid`, `match`, and `similarity`. In info mode we just ignore the `gudid` and `match` keys in the template — no route-layer change to the field list needed.

---

## Task 2: Styled File Picker

### Approach

Hide the native `<input type="file">` but keep it fully functional. Promote a `<label>` styled as a `.btn` to be the visible trigger. Add a sibling `<span>` that shows the chosen filename, updated by a small inline JS listener.

Standard HTML pattern. No framework, no dependency. Works in every browser that matters.

### Changes

#### `app/templates/harvester.html` — batch tab form

Replace:

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

- The first `<label>` keeps the field description (no `for=` since it's now a container label).
- The second `<label for="file">` is the clickable button; HTML's implicit behavior opens the file dialog.
- `hidden` on the input hides it without removing it from form submission or `required` validation.
- `<span id="file-name">` shows the selected filename.

#### `app/templates/harvester.html` — JS listener

Extend the existing `<script>` block (same one that has `switchTab`):

```javascript
document.getElementById('file').addEventListener('change', function(e) {
    const name = e.target.files[0]?.name || 'No file chosen';
    document.getElementById('file-name').textContent = name;
});
```

#### Minimal CSS (add to the existing stylesheet)

```css
.file-picker {
    display: flex;
    align-items: center;
    gap: 12px;
}

.file-name {
    color: var(--muted);
    font-size: 13px;
}
```

If an equivalent `.file-picker` utility already exists in the stylesheet, reuse it.

### Submit button

Untouched. `Upload & Harvest` stays `btn-primary`, making the two form actions visually distinct: picker = secondary, submit = primary.

---

## Out of Scope

- Styling file pickers anywhere else in the app (there aren't any other `<input type="file">` elements today; if one appears later, this pattern can be lifted).
- Drag-and-drop file drop zone — not requested.
- Device detail view for un-validated devices (devices without a `validationResults` doc have no `validation_id` to route to; they'd need a different page).
- Changing the "Review" label for partial/mismatch rows.

## Testing

- **Manual**: filter dashboard by Matches, click "More Information", verify the info-mode layout renders correctly (no GUDID column, no Pick column, no Save button), then do the same on a partial/mismatch row and verify the existing review flow is unchanged.
- **Manual**: open the harvester page, switch to the Batch Upload tab, click "Choose File", select a .txt, verify the filename appears in the span and "Upload & Harvest" submits as before.
- No new unit tests; these are template-layer conditionals with no business logic to cover.
