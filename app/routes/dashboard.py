from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard(request: Request):
    from orchestrator import get_dashboard_stats, get_discrepancies
    stats = get_dashboard_stats()
    discrepancies = get_discrepancies(limit=100)

    return templates.TemplateResponse(
        request, "dashboard.html",
        context={"stats": stats, "discrepancies": discrepancies},
    )
