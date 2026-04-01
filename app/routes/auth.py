from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.auth_service import authenticate_user, get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
            "email": "",
        },
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    user = authenticate_user(email, password)

    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Invalid email or password.",
                "email": email,
            },
            status_code=401,
        )

    request.session["user"] = user
    return RedirectResponse(url="/", status_code=302)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=302)
