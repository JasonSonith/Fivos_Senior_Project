from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["API"])


@router.get("/jobs/{job_id}")
def get_job_status(request: Request, job_id: str):
    job = request.app.state.jobs.get(job_id)
    if job is None:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JSONResponse(job)
