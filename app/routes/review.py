from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/review", tags=["Review"])
templates = Jinja2Templates(directory="app/templates")

COMPARED_FIELDS = [
    ("versionModelNumber", "Version / Model Number"),
    ("catalogNumber", "Catalog Number"),
    ("brandName", "Brand Name"),
    ("companyName", "Company Name"),
    ("deviceDescription", "Device Description"),
]


@router.get("/{validation_id}")
def review_page(request: Request, validation_id: str):
    from orchestrator import get_discrepancy_detail
    detail = get_discrepancy_detail(validation_id)

    if not detail:
        return RedirectResponse(url="/", status_code=302)

    validation = detail["validation"]
    device = detail["device"]
    comparison = validation.get("comparison_result") or {}
    gudid_record = validation.get("gudid_record") or {}

    fields = []
    for field_key, field_label in COMPARED_FIELDS:
        comp = comparison.get(field_key, {})
        harvested_val = comp.get("harvested") or device.get(field_key, "N/A")
        gudid_val = comp.get("gudid") or gudid_record.get(field_key, "N/A")

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
        request, "review.html",
        context={
            "validation_id": validation_id,
            "validation": validation,
            "device": device,
            "fields": fields,
        },
    )


@router.post("/{validation_id}/save")
async def save_review(request: Request, validation_id: str):
    from orchestrator import resolve_discrepancy

    form = await request.form()
    field_choices = {}
    for field_key, _ in COMPARED_FIELDS:
        choice = form.get(f"choice_{field_key}")
        if choice in ("harvested", "gudid"):
            field_choices[field_key] = choice

    resolve_discrepancy(validation_id, field_choices)
    return RedirectResponse(url="/", status_code=302)
