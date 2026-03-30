import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Add harvester/src to sys.path so orchestrator and its imports resolve
_HARVESTER_SRC = os.path.join(os.path.dirname(__file__), "..", "harvester", "src")
if os.path.abspath(_HARVESTER_SRC) not in sys.path:
    sys.path.insert(0, os.path.abspath(_HARVESTER_SRC))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import dashboard, harvester
from app.routes import api as api_routes
from app.routes import gudid as gudid_routes
from app.routes import validate as validate_routes
from app.routes import review as review_routes

app = FastAPI(title="Fivos Device Data Interface")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# In-memory job store for background task polling
app.state.jobs = {}

app.include_router(dashboard.router)
app.include_router(harvester.router)
app.include_router(api_routes.router)
app.include_router(gudid_routes.router)
app.include_router(validate_routes.router)
app.include_router(review_routes.router)
