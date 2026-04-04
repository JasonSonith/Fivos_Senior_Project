from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import user_service
from app.services.auth_guard import require_roles

router = APIRouter(prefix="/admin", tags=["Admin"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/users")
def admin_users_page(request: Request):
    current_user, redirect = require_roles(request, ["admin"])
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "admin_users.html", {
        "current_user": current_user,
        "users": user_service.list_users(),
        "new_account": None,
        "error": None,
    })


@router.post("/users/create")
def admin_create_user(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
):
    current_user, redirect = require_roles(request, ["admin"])
    if redirect:
        return redirect

    email = email.strip().lower()

    if user_service.get_user_by_email(email):
        return templates.TemplateResponse(request, "admin_users.html", {
            "current_user": current_user,
            "users": user_service.list_users(),
            "new_account": None,
            "error": f"An account with email \"{email}\" already exists.",
        })

    if role not in ("admin", "reviewer"):
        role = "reviewer"

    _, temp_pwd = user_service.create_user(
        name=name,
        email=email,
        role=role,
        created_by=current_user["email"],
    )

    return templates.TemplateResponse(request, "admin_users.html", {
        "current_user": current_user,
        "users": user_service.list_users(),
        "new_account": {"email": email, "name": name, "temp_password": temp_pwd},
        "error": None,
    })


@router.post("/users/{user_id}/toggle")
def admin_toggle_user(request: Request, user_id: str):
    current_user, redirect = require_roles(request, ["admin"])
    if redirect:
        return redirect

    if user_id == current_user.get("_id"):
        return RedirectResponse(url="/admin/users", status_code=302)

    user_service.toggle_active(user_id)
    return RedirectResponse(url="/admin/users", status_code=302)
