"""
Application entrypoint.

Wires up the FastAPI app: DB init on startup, global exception
handling (so nothing leaks stack traces/secrets to clients), static
files + page routes for the frontend, and the versioned JSON API
routes.
"""
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError

from app.core.database import init_db
from app.core.logging import get_logger
from app.api.routes import documents, frontend

logger = get_logger(__name__)

app = FastAPI(
    title="Document Intelligence Platform",
    description="AI-powered document extraction, validation & API platform.",
    version="1.0.0",
)

BASE_DIR = Path(__file__).resolve().parents[2]  # project-root
STATIC_DIR = BASE_DIR / "frontend" / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def on_startup():
    logger.info("Starting Document Intelligence Platform")
    init_db()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("Request validation error on %s: %s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "INVALID_REQUEST", "message": "The request could not be validated. Check required fields (file, document_type)."}},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Routes raise HTTPException(detail={"error": {...}}) directly for
    # domain errors — pass that shape through unchanged. For any
    # HTTPException raised elsewhere (framework-level), wrap it into
    # the same consistent error envelope.
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        content = exc.detail
    else:
        content = {"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}}
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred while processing the request."}},
    )


app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
app.include_router(frontend.router, tags=["frontend"])
