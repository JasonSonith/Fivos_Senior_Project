from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/results", tags=["Results"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def results_page(request: Request):
    from orchestrator import get_devices, get_validation_results
    devices = get_devices(limit=100)
    validations = get_validation_results(limit=100)

    return templates.TemplateResponse(
        request, "results.html",
        context={"devices": devices, "validations": validations},
    )
