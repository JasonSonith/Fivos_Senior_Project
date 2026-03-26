from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import dashboard, harvester, normalize, results

app = FastAPI(title="Fivos Device Data Interface")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router)
app.include_router(harvester.router)
app.include_router(normalize.router)
app.include_router(results.router)