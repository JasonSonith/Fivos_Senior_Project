from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.auth_guard import require_login

router = APIRouter(prefix="/gudid", tags=["GUDID"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def gudid_page(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        request,
        "gudid.html",
        context={
            "result": None,
            "current_user": user,
        },
    )

@router.post("/lookup")
def gudid_lookup(
    request: Request,
    query: str = Form(...),
    query_type: str = Form("model"),
):
    user, redirect = require_login(request)
    if redirect:
        return redirect

    from orchestrator import lookup_gudid_device

    try:
        if query_type == "di":
            result = lookup_gudid_device(di=query)
        else:
            result = lookup_gudid_device(model_number=query)
    except Exception as e:
        result = {
            "success": False,
            "record": None,
            "di": None,
            "error": f"GUDID lookup failed: {str(e)}"
        }

    return templates.TemplateResponse(
        request,
        "gudid.html",
        context={
            "result": result,
            "current_user": user,
        },
    )