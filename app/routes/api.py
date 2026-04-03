from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.auth_guard import require_api_login

router = APIRouter(prefix="/api", tags=["API"])


@router.get("/jobs/{job_id}")
def get_job_status(request: Request, job_id: str):
    user, error_response = require_api_login(request)
    if error_response:
        return error_response

    job = request.app.state.jobs.get(job_id)
    if job is None:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    return JSONResponse(job)