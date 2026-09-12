"""
Central logging configuration.

Every module gets its logger via `get_logger(__name__)` so log lines
are attributable to the stage that emitted them (validation, OCR,
extraction, financial validation, API, etc.) — this is what makes
failures diagnosable during evaluation without exposing internals to
end users.
"""
import logging
import sys
from app.core.config import get_settings

_CONFIGURED = False


def _configure_root_logger() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)
    root.handlers = [handler]
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    _configure_root_logger()
    return logging.getLogger(name)
