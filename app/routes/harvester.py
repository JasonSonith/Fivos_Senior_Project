import uuid

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/harvester", tags=["Harvester"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def harvester_page(request: Request):
    adapters = request.app.state.adapter_choices
    return templates.TemplateResponse(
        request, "harvester.html",
        context={"result": None, "adapters": adapters, "job_id": None},
    )


@router.post("/run")
async def run_harvester(
    request: Request,
    background_tasks: BackgroundTasks,
    adapter_path: str = Form(...),
    url: str = Form(...),
):
    job_id = str(uuid.uuid4())
    request.app.state.jobs[job_id] = {"status": "running", "result": None}

    background_tasks.add_task(_do_harvest, request.app, job_id, url, adapter_path)

    adapters = request.app.state.adapter_choices
    return templates.TemplateResponse(
        request, "harvester.html",
        context={"result": None, "adapters": adapters, "job_id": job_id},
    )


async def _do_harvest(app, job_id: str, url: str, adapter_path: str):
    from orchestrator import run_harvest
    try:
        result = await run_harvest(url=url, adapter_path=adapter_path)
        app.state.jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        app.state.jobs[job_id] = {"status": "failed", "result": {"success": False, "error": str(e)}}
