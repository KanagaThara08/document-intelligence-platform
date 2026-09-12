"""
Application configuration.

All secrets and environment-specific values are read from environment
variables. Nothing sensitive is hardcoded here — see .env.example for
the list of variables this application expects.
"""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load project-root/.env explicitly (works regardless of which
# directory uvicorn is started from — local dev, Docker, or Render).
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)


class Settings:
    # --- General ---
    APP_NAME: str = "Document Intelligence Platform"
    ENV: str = os.getenv("ENV", "development")

    # --- Database ---
    # Defaults to a local SQLite file, relative to the working directory
    # the app is started from (project-root/backend — see README "Running
    # locally" and the Dockerfile's WORKDIR). Swapping to Postgres/MySQL
    # only requires changing DATABASE_URL — no code changes elsewhere.
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite:///./app/data/documents.db"
    )

    # --- LLM (Google Gemini) ---
    # Gemini was chosen for the free-tier API key (no billing/credit card
    # required at aistudio.google.com/apikey) — see extraction_service.py.
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    # --- OCR ---
    # "tesseract" (local, free, default) is the only backend wired up
    # out of the box. Kept as a setting so a hosted OCR provider could
    # be swapped in later without touching calling code.
    OCR_BACKEND: str = os.getenv("OCR_BACKEND", "tesseract")

    # Explicit binary paths for Tesseract/Poppler. Leave blank to rely
    # on PATH (the default on Linux/Docker, where both are pre-installed
    # by the Dockerfile). On Windows, pip installing pytesseract/pdf2image
    # does NOT install the actual OCR/PDF-rasterization engines — set
    # these to your local install locations if `tesseract --version` /
    # `pdftoppm -v` aren't recognized in your terminal. Example Windows
    # values (adjust to your actual install path):
    #   TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
    #   POPPLER_PATH=C:\poppler\Library\bin
    TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "")
    POPPLER_PATH: str = os.getenv("POPPLER_PATH", "")

    # --- Upload constraints ---
    MAX_PAGES: int = int(os.getenv("MAX_PAGES", "3"))
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "15"))
    SUPPORTED_CONTENT_TYPES = {
        "application/pdf": "pdf",
        "image/jpeg": "image",
        "image/jpg": "image",
        "image/png": "image",
    }

    # --- Financial validation tolerance ---
    # Allowed absolute variance (in currency units) before a check is
    # marked FAIL rather than PASS, to absorb rounding differences.
    VALIDATION_TOLERANCE: float = float(os.getenv("VALIDATION_TOLERANCE", "1.0"))

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()
