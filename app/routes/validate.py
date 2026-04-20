#admin only
import uuid

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.templating import Jinja2Templates

from app.services.auth_guard import require_roles

router = APIRouter(prefix="/validate", tags=["Validate"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def validate_page(request: Request):
    user, redirect = require_roles(request, ["admin"])
    if redirect:
        return redirect

    from orchestrator import get_validation_results
    results = get_validation_results(limit=100)

    return templates.TemplateResponse(
        request,
        "validate.html",
        context={
            "results": results,
            "job_id": None,
            "run_result": None,
            "current_user": user,
        },
    )


@router.post("/run")
async def run_validation_route(request: Request, background_tasks: BackgroundTasks):
    user, redirect = require_roles(request, ["admin"])
    if redirect:
        return redirect

    job_id = str(uuid.uuid4())
    request.app.state.jobs[job_id] = {"status": "running", "result": None}
    background_tasks.add_task(_do_validation, request.app, job_id)

    return templates.TemplateResponse(
        request,
        "validate.html",
        context={
            "results": [],
            "job_id": job_id,
            "run_result": None,
            "current_user": user,
        },
    )


@router.post("/backfill-verified")
def backfill_verified(request: Request):
    user, redirect = require_roles(request, ["admin"])
    if redirect:
        return redirect

    from orchestrator import backfill_verified_devices
    result = backfill_verified_devices()
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/validate/", status_code=302)


def _do_validation(app, job_id: str):
    from orchestrator import run_validation, backfill_verified_devices
    try:
        result = run_validation()
        # Backfill verified_devices for any matched records
        backfill = backfill_verified_devices()
        result["verified_count"] = backfill.get("verified_count", 0)
        app.state.jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        app.state.jobs[job_id] = {
            "status": "failed",
            "result": {"success": False, "error": str(e)},
        }