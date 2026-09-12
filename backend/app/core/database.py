"""
Database engine and session management (SQLAlchemy).

Uses SQLite by default (DATABASE_URL in config). Swapping to
Postgres/MySQL only requires changing DATABASE_URL — no code changes
elsewhere, since all access goes through the repository layer.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import get_settings

settings = get_settings()

# Ensure the directory for the SQLite file exists (harmless no-op for
# non-sqlite URLs).
if settings.DATABASE_URL.startswith("sqlite:///"):
    db_path = settings.DATABASE_URL.replace("sqlite:///", "", 1)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Called once on application startup."""
    from app.models import document  # noqa: F401  (registers models with Base)
    Base.metadata.create_all(bind=engine)
