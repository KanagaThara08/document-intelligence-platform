"""
Document validation service.

This is the input-control layer: it checks that an uploaded file is a
readable PDF/JPG/PNG within the page limit, BEFORE any OCR or AI
extraction is attempted. It never inspects document *content type*
(invoice vs statement) — that is supplied by the caller as metadata.
"""
import io

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.document import FileValidationResult

logger = get_logger(__name__)
settings = get_settings()


class DocumentValidationError(Exception):
    """Raised when a file fails validation. Carries an API error code."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def validate_file(file_bytes: bytes, content_type: str, filename: str) -> FileValidationResult:
    """
    Validate a raw uploaded file.

    Returns a FileValidationResult with status PASS if the file is a
    readable PDF/JPG/PNG within the page limit. Raises
    DocumentValidationError (caught by the route layer and turned into
    a 4xx JSON error response) for every failure case, so validation
    logic and HTTP concerns stay decoupled.
    """
    if not file_bytes:
        logger.warning("Rejected empty upload: %s", filename)
        raise DocumentValidationError("EMPTY_FILE", "The uploaded file is empty.")

    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > settings.MAX_FILE_SIZE_MB:
        logger.warning("Rejected oversized upload: %s (%.2f MB)", filename, size_mb)
        raise DocumentValidationError(
            "FILE_TOO_LARGE",
            f"File exceeds the {settings.MAX_FILE_SIZE_MB}MB size limit.",
        )

    normalized_type = settings.SUPPORTED_CONTENT_TYPES.get(content_type)
    if normalized_type is None:
        logger.warning("Rejected unsupported content type: %s for %s", content_type, filename)
        raise DocumentValidationError(
            "UNSUPPORTED_FILE_TYPE",
            "Only PDF / JPG / PNG documents are supported.",
        )

    if normalized_type == "pdf":
        page_count = _validate_pdf(file_bytes, filename)
    else:
        page_count = _validate_image(file_bytes, filename)

    if page_count > settings.MAX_PAGES:
        logger.warning("Rejected document exceeding page limit: %s (%d pages)", filename, page_count)
        raise DocumentValidationError(
            "PAGE_LIMIT_EXCEEDED",
            f"Document exceeds the {settings.MAX_PAGES}-page limit.",
        )

    logger.info("File validation PASS: %s (%s, %d page(s))", filename, content_type, page_count)
    return FileValidationResult(
        file_type=content_type,
        is_supported=True,
        is_readable=True,
        page_count=page_count,
        status="PASS",
    )


def _validate_pdf(file_bytes: bytes, filename: str) -> int:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise DocumentValidationError(
                    "CORRUPTED_FILE", "The PDF is password-protected and cannot be read."
                )
        page_count = len(reader.pages)
        if page_count == 0:
            raise DocumentValidationError("CORRUPTED_FILE", "The PDF contains no pages.")
        return page_count
    except DocumentValidationError:
        raise
    except (PdfReadError, Exception) as exc:  # noqa: BLE001 - convert any parse failure
        logger.error("PDF parse failure for %s: %s", filename, exc)
        raise DocumentValidationError("CORRUPTED_FILE", "The PDF file could not be read or is corrupted.")


def _validate_image(file_bytes: bytes, filename: str) -> int:
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.verify()
        return 1
    except (UnidentifiedImageError, Exception) as exc:  # noqa: BLE001
        logger.error("Image parse failure for %s: %s", filename, exc)
        raise DocumentValidationError("CORRUPTED_FILE", "The image file could not be read or is corrupted.")
