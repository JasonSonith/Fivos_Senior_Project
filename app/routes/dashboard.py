from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard(request: Request):
    from orchestrator import get_dashboard_stats
    stats = get_dashboard_stats()

    return templates.TemplateResponse(
        request, "dashboard.html", context={"stats": stats}
    )
