from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services.storage_service import load_raw_records, load_normalized_records

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
def dashboard(request: Request):
    raw_records = load_raw_records()
    normalized_records = load_normalized_records()

    stats = {
        "raw_records": len(raw_records),
        "normalized_records": len(normalized_records),
        "last_run": "Ready" if raw_records else "No runs yet",
    }

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "stats": stats}
    )