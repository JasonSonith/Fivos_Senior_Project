import uuid

from fastapi import APIRouter, BackgroundTasks, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/harvester", tags=["Harvester"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def harvester_page(request: Request):
    return templates.TemplateResponse(
        request, "harvester.html",
        context={"job_id": None, "single_result": None},
    )


@router.post("/run-single")
async def run_single(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    url = form.get("url", "").strip()

    if not url:
        return templates.TemplateResponse(
            request, "harvester.html",
            context={"job_id": None, "single_result": {"error": "Please enter a URL"}},
        )

    job_id = str(uuid.uuid4())
    request.app.state.jobs[job_id] = {"status": "running", "result": None}
    background_tasks.add_task(_do_harvest_single, request.app, job_id, url)

    return templates.TemplateResponse(
        request, "harvester.html",
        context={"job_id": job_id, "single_result": None, "mode": "single"},
    )


@router.post("/run-batch")
async def run_batch(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    upload = form.get("file")

    if not upload or not hasattr(upload, "read"):
        return templates.TemplateResponse(
            request, "harvester.html",
            context={"job_id": None, "single_result": {"error": "Please upload a .txt file"}},
        )

    content = (await upload.read()).decode("utf-8", errors="ignore")
    urls = [
        line.strip() for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    if not urls:
        return templates.TemplateResponse(
            request, "harvester.html",
            context={"job_id": None, "single_result": {"error": "No URLs found in uploaded file"}},
        )

    job_id = str(uuid.uuid4())
    request.app.state.jobs[job_id] = {"status": "running", "result": None}
    background_tasks.add_task(_do_harvest_batch, request.app, job_id, urls)

    return templates.TemplateResponse(
        request, "harvester.html",
        context={"job_id": job_id, "single_result": None, "mode": "batch", "url_count": len(urls)},
    )


def _do_harvest_single(app, job_id: str, url: str):
    from orchestrator import run_harvest_single
    try:
        result = run_harvest_single(url)
        app.state.jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        app.state.jobs[job_id] = {"status": "failed", "result": {"error": str(e)}}


def _do_harvest_batch(app, job_id: str, urls: list[str]):
    from orchestrator import run_harvest_batch
    try:
        result = run_harvest_batch(urls, job_store=app.state.jobs, job_id=job_id)
        app.state.jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        app.state.jobs[job_id] = {"status": "failed", "result": {"error": str(e)}}
