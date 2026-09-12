"""
Frontend page routes.

Serves the HTML dashboard and document-result pages via Jinja2
templates. Kept separate from the JSON API routes (documents.py) so
API concerns and page-rendering concerns don't mix.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

FRONTEND_DIR = Path(__file__).resolve().parents[4] / "frontend"
templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))

router = APIRouter()


@router.get("/")
def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/document/{document_name}")
def document_result_page(request: Request, document_name: str):
    return templates.TemplateResponse(
        "document_result.html", {"request": request, "document_name": document_name}
    )
