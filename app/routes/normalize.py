from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/normalize", tags=["Normalize"])


@router.get("/")
def normalize_redirect():
    """Normalization is now built into the pipeline. Redirect to validation page."""
    return RedirectResponse(url="/validate/", status_code=302)
