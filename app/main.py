import os
import re
import secrets
import sys
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

from dotenv import load_dotenv

load_dotenv()

# Add harvester/src to sys.path so orchestrator and its imports resolve
_HARVESTER_SRC = os.path.join(os.path.dirname(__file__), "..", "harvester", "src")
if os.path.abspath(_HARVESTER_SRC) not in sys.path:
    sys.path.insert(0, os.path.abspath(_HARVESTER_SRC))

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from app.routes import dashboard, harvester
from app.routes import api as api_routes
from app.routes import gudid as gudid_routes
from app.routes import validate as validate_routes
from app.routes import review as review_routes
from app.routes import auth as auth_routes
from app.routes import admin as admin_routes

# Routes exempt from CSRF validation (stateless API endpoints polled by JS)
_CSRF_EXEMPT = ("/api/jobs",)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Embedder-Policy"] = "credentialless"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response


class CSRFMiddleware:
    """Pure ASGI middleware — reads body, validates token, replays body downstream."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        session = scope.get("session", {})

        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)

        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if not any(request.url.path.startswith(p) for p in _CSRF_EXEMPT):
                body = await request.body()
                content_type = request.headers.get("content-type", "")
                submitted = ""

                if "application/x-www-form-urlencoded" in content_type:
                    params = parse_qs(body.decode("latin-1"))
                    submitted = (params.get("csrf_token") or [""])[0]
                elif "multipart/form-data" in content_type:
                    match = re.search(
                        rb'name="csrf_token"\r\n\r\n([a-f0-9]+)\r\n', body
                    )
                    if match:
                        submitted = match.group(1).decode()

                expected = session.get("csrf_token", "")
                if not submitted or not secrets.compare_digest(submitted, expected):
                    resp = Response(
                        "<h1>403 Forbidden</h1><p>CSRF token missing or invalid.</p>",
                        status_code=403,
                        media_type="text/html",
                    )
                    await resp(scope, receive, send)
                    return

                # Replay body so route handlers can read it
                async def replay_receive():
                    return {"type": "http.request", "body": body, "more_body": False}

                await self.app(scope, replay_receive, send)
                return

        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.user_service import seed_demo_users
    from orchestrator import migrate_gudid_not_found
    seed_demo_users()
    migrate_gudid_not_found()
    yield


app = FastAPI(title="Fivos Device Data Interface", lifespan=lifespan)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("AUTH_SECRET_KEY", "change-me-in-env"),
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.state.jobs = {}

app.include_router(dashboard.router)
app.include_router(harvester.router)
app.include_router(api_routes.router)
app.include_router(gudid_routes.router)
app.include_router(validate_routes.router)
app.include_router(review_routes.router)
app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
