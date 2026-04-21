from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    from orchestrator import get_dashboard_stats, get_discrepancies
    stats = get_dashboard_stats()
    discrepancies = get_discrepancies(limit=100)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context={
            "stats": stats,
            "discrepancies": discrepancies,
            "current_user": user,
        },
    )


_FILTER_LABELS = {
    "all": "Harvested Devices",
    "matched": "Matches",
    "partial_match": "Partial Matches",
    "mismatch": "Mismatches",
}


@router.get("/devices")
def devices_list(request: Request, filter: str = Query(default="all")):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    if filter not in _FILTER_LABELS:
        filter = "all"

    from orchestrator import get_devices_with_filter
    devices = get_devices_with_filter(filter_status=filter)

    return templates.TemplateResponse(
        request,
        "devices.html",
        context={
            "devices": devices,
            "filter": filter,
            "filter_label": _FILTER_LABELS[filter],
            "current_user": user,
        },
    )
