from fastapi import APIRouter, Form, Request
from fastapi.templating import Jinja2Templates

from app.services.scraper_service import run_scraper_job

router = APIRouter(prefix="/harvester", tags=["Harvester"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
def harvester_page(request: Request):
    return templates.TemplateResponse(
        "harvester.html",
        {"request": request, "result": None}
    )

@router.post("/run")
async def run_harvester(
    request: Request,
    manufacturer: str = Form(...),
    url: str = Form(...),
):
    result = await run_scraper_job(manufacturer=manufacturer, url=url)

    return templates.TemplateResponse(
        "harvester.html",
        {"request": request, "result": result}
    )