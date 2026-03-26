from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services.storage_service import load_raw_records, save_normalized_records
from app.services.normalization_service import normalize_records

router = APIRouter(prefix="/normalize", tags=["Normalize"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
def normalize_page(request: Request):
    raw_records = load_raw_records()
    normalized_records = normalize_records(raw_records)
    save_normalized_records(normalized_records)

    return templates.TemplateResponse(
        "normalize.html",
        {
            "request": request,
            "raw_count": len(raw_records),
            "normalized_count": len(normalized_records),
            "records": normalized_records,
        }
    )