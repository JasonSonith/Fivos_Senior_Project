import os
import sys
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

# Add harvester/src to sys.path so orchestrator and its imports resolve
_HARVESTER_SRC = os.path.join(os.path.dirname(__file__), "..", "harvester", "src")
if os.path.abspath(_HARVESTER_SRC) not in sys.path:
    sys.path.insert(0, os.path.abspath(_HARVESTER_SRC))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.routes import dashboard, harvester
from app.routes import api as api_routes
from app.routes import gudid as gudid_routes
from app.routes import validate as validate_routes
from app.routes import review as review_routes
from app.routes import auth as auth_routes
from app.routes import admin as admin_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.user_service import seed_demo_users
    seed_demo_users()
    yield


app = FastAPI(title="Fivos Device Data Interface", lifespan=lifespan)

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
