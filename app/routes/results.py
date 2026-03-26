from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services.storage_service import load_raw_records, load_normalized_records

router = APIRouter(prefix="/results", tags=["Results"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
def results_page(request: Request):
    raw_records = load_raw_records()
    normalized_records = load_normalized_records()

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "raw_records": raw_records,
            "normalized_records": normalized_records,
        }
    )