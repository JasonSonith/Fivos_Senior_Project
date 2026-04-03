from fastapi.responses import RedirectResponse, JSONResponse


def require_login(request):
    user = request.session.get("user")
    if not user:
        return None, RedirectResponse(url="/auth/login", status_code=302)
    return user, None


def require_roles(request, allowed_roles):
    user = request.session.get("user")
    if not user:
        return None, RedirectResponse(url="/auth/login", status_code=302)

    if user.get("role") not in allowed_roles:
        return None, RedirectResponse(url="/", status_code=302)

    return user, None


def require_api_login(request):
    user = request.session.get("user")
    if not user:
        return None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    return user, None