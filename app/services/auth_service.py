from app.services import user_service


def authenticate_user(email: str, password: str) -> dict | None:
    if not email or not password:
        return None
    user = user_service.get_user_by_email(email)
    if not user:
        return None
    if not user.get("active", True):
        return None
    if not user_service.verify_password(password, user["password_hash"]):
        return None
    user_service.update_last_login(user["_id"])
    return user


def get_current_user(request) -> dict | None:
    return request.session.get("user")
