import uuid

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/validate", tags=["Validate"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def validate_page(request: Request):
    from orchestrator import get_validation_results
    results = get_validation_results(limit=100)
    return templates.TemplateResponse(
        request, "validate.html",
        context={"results": results, "job_id": None, "run_result": None},
    )


@router.post("/run")
async def run_validation_route(request: Request, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    request.app.state.jobs[job_id] = {"status": "running", "result": None}
    background_tasks.add_task(_do_validation, request.app, job_id)
    return templates.TemplateResponse(
        request, "validate.html",
        context={"results": [], "job_id": job_id, "run_result": None},
    )


def _do_validation(app, job_id: str):
    from orchestrator import run_validation
    try:
        result = run_validation()
        app.state.jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        app.state.jobs[job_id] = {"status": "failed", "result": {"success": False, "error": str(e)}}
