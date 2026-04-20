from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    from orchestrator import get_dashboard_stats, get_all_validations_with_devices
    stats = get_dashboard_stats()
    all_results = get_all_validations_with_devices()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context={
            "stats": stats,
            "all_results": all_results,
            "current_user": user,
        },
    )
