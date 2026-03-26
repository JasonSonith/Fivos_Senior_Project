import uuid

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/harvester", tags=["Harvester"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def harvester_page(request: Request):
    from orchestrator import list_html_files
    files = list_html_files()
    return templates.TemplateResponse(
        request, "harvester.html",
        context={"files": files, "job_id": None},
    )


@router.post("/run")
async def run_pipeline(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    selected = form.getlist("files")
    file_paths = list(selected) if selected else None

    job_id = str(uuid.uuid4())
    request.app.state.jobs[job_id] = {"status": "running", "result": None}
    background_tasks.add_task(_do_pipeline, request.app, job_id, file_paths)

    from orchestrator import list_html_files
    files = list_html_files()
    return templates.TemplateResponse(
        request, "harvester.html",
        context={"files": files, "job_id": job_id},
    )


def _do_pipeline(app, job_id: str, file_paths: list[str] | None):
    from orchestrator import run_pipeline_batch
    try:
        result = run_pipeline_batch(file_paths=file_paths)
        app.state.jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        app.state.jobs[job_id] = {"status": "failed", "result": {"error": str(e)}}
