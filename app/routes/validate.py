#admin only
import uuid

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.templating import Jinja2Templates

from app.services.auth_guard import require_roles

router = APIRouter(prefix="/validate", tags=["Validate"])
templates = Jinja2Templates(directory="app/templates")


def _normalize_comparison_result(cr: dict) -> dict:
    """Ensure comparison_result entries expose keys the template expects.

    New shape uses 'status' + 'similarity'; legacy shape uses 'match' +
    'description_similarity'. This bridge makes both render correctly.
    """
    if not cr:
        return cr
    normalized = {}
    for field, entry in cr.items():
        if not isinstance(entry, dict):
            normalized[field] = entry
            continue
        e = dict(entry)
        # Derive 'match' from 'status' when absent (new shape)
        if "match" not in e:
            status = e.get("status")
            if status == "match":
                e["match"] = True
            elif status == "mismatch":
                e["match"] = False
            else:
                e["match"] = None
        # Derive 'description_similarity' from 'similarity' when absent (new shape)
        if field == "deviceDescription" and "description_similarity" not in e:
            e["description_similarity"] = e.get("similarity", 0)
        normalized[field] = e
    return normalized


@router.get("/")
def validate_page(request: Request):
    user, redirect = require_roles(request, ["admin"])
    if redirect:
        return redirect

    from orchestrator import get_validation_results
    results = get_validation_results(limit=100)
    for r in results:
        if "comparison_result" in r:
            r["comparison_result"] = _normalize_comparison_result(r["comparison_result"])

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
    from orchestrator import (
        run_validation,
        backfill_verified_devices,
        migrate_gudid_not_found,
        get_latest_run_id,
    )
    try:
        migrate_gudid_not_found()
        latest_run_id = get_latest_run_id()
        result = run_validation(run_id=latest_run_id)
        result["run_id"] = latest_run_id
        backfill = backfill_verified_devices()
        result["verified_count"] = backfill.get("verified_count", 0)
        app.state.jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        app.state.jobs[job_id] = {
            "status": "failed",
            "result": {"success": False, "error": str(e)},
        }