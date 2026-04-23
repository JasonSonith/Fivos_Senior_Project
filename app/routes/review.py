from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.auth_guard import require_roles

def _field_status(comp_entry: dict) -> str:
    if "status" in comp_entry:
        return comp_entry["status"]
    legacy = comp_entry.get("match")
    if legacy is True:
        return "match"
    if legacy is False:
        return "mismatch"
    return "not_compared"


router = APIRouter(prefix="/review", tags=["Review"])
templates = Jinja2Templates(directory="app/templates")

COMPARED_FIELDS = [
    ("versionModelNumber", "Version / Model Number"),
    ("catalogNumber", "Catalog Number"),
    ("brandName", "Brand Name"),
    ("companyName", "Company Name"),
    ("deviceDescription", "Device Description"),
    ("MRISafetyStatus", "MRI Safety Status"),
    ("singleUse", "Single Use"),
    ("rx", "Prescription (Rx)"),
    ("gmdnPTName", "GMDN Term"),
    ("gmdnCode", "GMDN Code"),
    ("productCodes", "FDA Product Codes"),
    ("deviceCountInBase", "Pack Quantity"),
    ("issuingAgency", "Issuing Agency"),
    ("lotBatch", "Labeled: Lot / Batch"),
    ("serialNumber", "Labeled: Serial Number"),
    ("manufacturingDate", "Labeled: Manufacturing Date"),
    ("expirationDate", "Labeled: Expiration Date"),
    ("premarketSubmissions", "Premarket Submissions"),
    ("deviceSizes", "Device Sizes"),
]


@router.get("/{validation_id}")
def review_page(request: Request, validation_id: str):
    user, redirect = require_roles(request, ["admin", "reviewer"])
    if redirect:
        return redirect

    from orchestrator import get_discrepancy_detail
    detail = get_discrepancy_detail(validation_id)

    if not detail:
        return RedirectResponse(url="/", status_code=302)

    validation = detail["validation"]
    device = detail["device"]
    comparison = validation.get("comparison_result") or {}
    gudid_record = validation.get("gudid_record") or {}

    mode = "info" if validation.get("status") in ("matched", "gudid_deactivated", "fetch_error") else "review"

    fields = []
    for field_key, field_label in COMPARED_FIELDS:
        comp = comparison.get(field_key, {})

        if comp:
            # Trust the comparison snapshot. The device doc may have been backfilled
            # from GUDID after validation ran (gudid_sourced_fields), so falling back
            # to it would falsely show GUDID values on the harvested side.
            comp_h = comp.get("harvested")
            comp_g = comp.get("gudid")
            harvested_val = comp_h if comp_h not in (None, "", []) else "N/A"
            gudid_val = comp_g if comp_g not in (None, "", []) else "N/A"
        else:
            # No comparison ran (e.g., gudid_deactivated). Fall back to source docs.
            harvested_val = device.get(field_key, "N/A")
            gudid_val = gudid_record.get(field_key, "N/A")

        status = _field_status(comp)
        similarity = None
        if field_key == "deviceDescription":
            similarity = comp.get("similarity") if comp.get("similarity") is not None else comp.get("description_similarity", 0)

        fields.append({
            "key": field_key,
            "label": field_label,
            "harvested": harvested_val,
            "gudid": gudid_val,
            "status": status,
            "alias_group": comp.get("alias_group"),
            "similarity": similarity,
            "per_type": comp.get("per_type") if field_key == "deviceSizes" else None,
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


@router.post("/{validation_id}/save")
async def save_review(request: Request, validation_id: str):
    user, redirect = require_roles(request, ["admin", "reviewer"])
    if redirect:
        return redirect

    from orchestrator import resolve_discrepancy

    form = await request.form()
    field_choices = {}
    for field_key, _ in COMPARED_FIELDS:
        choice = form.get(f"choice_{field_key}")
        if choice in ("harvested", "gudid"):
            field_choices[field_key] = choice

    resolve_discrepancy(validation_id, field_choices)
    return RedirectResponse(url="/", status_code=302)