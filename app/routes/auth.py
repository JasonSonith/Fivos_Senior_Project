from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import user_service
from app.services.auth_service import authenticate_user, get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None, "email": ""})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    user = authenticate_user(email, password)

    if not user:
        # Distinguish disabled vs wrong credentials for clearer error messages
        existing = user_service.get_user_by_email(email)
        if existing and not existing.get("active", True):
            error = "Your account has been disabled. Contact an administrator."
        else:
            error = "Invalid email or password."
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": error, "email": email},
            status_code=401,
        )

    request.session["user"] = {
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "force_password_change": user.get("force_password_change", False),
        "_id": user.get("_id", ""),
    }

    if user.get("force_password_change"):
        return RedirectResponse(url="/auth/change-password", status_code=302)
    return RedirectResponse(url="/", status_code=302)


@router.get("/change-password")
def change_password_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    if not user.get("force_password_change"):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "change_password.html", {"errors": {}})


@router.post("/change-password")
def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    session_user = get_current_user(request)
    if not session_user:
        return RedirectResponse(url="/auth/login", status_code=302)

    db_user = user_service.get_user_by_email(session_user["email"])
    if not db_user:
        return RedirectResponse(url="/auth/login", status_code=302)

    errors = {}

    # Verify current password
    if not user_service.verify_password(current_password, db_user["password_hash"]):
        errors["current_password"] = "Current password is incorrect."

    # Confirm match
    if new_password != confirm_password:
        errors["confirm_password"] = "Passwords do not match."

    # Complexity
    if "new_password" not in errors:
        complexity_errors = user_service.check_complexity(new_password)
        if complexity_errors:
            errors["new_password"] = complexity_errors[0]

    # Must differ from current
    if "current_password" not in errors and "new_password" not in errors:
        if user_service.verify_password(new_password, db_user["password_hash"]):
            errors["new_password"] = "New password must differ from your current password."

    # HIBP server-side check
    if "new_password" not in errors:
        count = user_service.check_hibp(new_password)
        if count > 0:
            errors["new_password"] = (
                f"This password appeared in {count:,} known data breaches. "
                "Choose a different password."
            )

    if errors:
        return templates.TemplateResponse(
            request, "change_password.html", {"errors": errors}, status_code=400
        )

    # All checks passed — update DB and session atomically
    user_service.update_password(db_user["_id"], user_service.hash_password(new_password))

    session_data = dict(request.session.get("user", {}))
    session_data["force_password_change"] = False
    request.session["user"] = session_data

    return RedirectResponse(url="/", status_code=302)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=302)
