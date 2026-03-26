from fastapi import APIRouter, Form, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/gudid", tags=["GUDID"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def gudid_page(request: Request):
    return templates.TemplateResponse(
        request, "gudid.html", context={"result": None},
    )


@router.post("/lookup")
def gudid_lookup(
    request: Request,
    query: str = Form(...),
    query_type: str = Form("model"),
):
    from orchestrator import lookup_gudid_device
    if query_type == "di":
        result = lookup_gudid_device(di=query)
    else:
        result = lookup_gudid_device(model_number=query)
    return templates.TemplateResponse(
        request, "gudid.html", context={"result": result},
    )
