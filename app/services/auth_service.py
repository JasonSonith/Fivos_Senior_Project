from typing import Optional

DEMO_USERS = {
    "admin@fivos.local": {
        "password": "admin123",
        "name": "System Admin",
        "role": "admin",
    },
    "reviewer@fivos.local": {
        "password": "review123",
        "name": "Review Analyst",
        "role": "reviewer",
    },
}


def authenticate_user(email: str, password: str) -> Optional[dict]:
    if not email or not password:
        return None

    user = DEMO_USERS.get(email.strip().lower())
    if not user:
        return None

    if user["password"] != password:
        return None

    return {
        "email": email.strip().lower(),
        "name": user["name"],
        "role": user["role"],
    }


def get_current_user(request):
    return request.session.get("user")
