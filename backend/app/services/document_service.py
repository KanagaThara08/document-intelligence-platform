"""
Document processing orchestrator.

This is the single entry point the API route calls. It wires together,
in order: file validation -> OCR/text extraction -> AI field/table
extraction -> financial validation -> persistence, and always returns
a (http_status_code, response_dict) pair so the route layer stays a
thin HTTP adapter with no business logic of its own.

Every failure mode (bad file, OCR failure, LLM failure, unexpected
error) is caught here and converted into a controlled, structured
response — nothing escapes as a raw stack trace.
"""
import time
import datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.document import ProcessedDocument
from app.repositories import document_repository
from app.services import ocr_service, extraction_service
from app.services import financial_validation_service as fin_validation
from app.services.document_validation_service import validate_file, DocumentValidationError

logger = get_logger(__name__)


def _reshape_extracted_data(raw: dict, page_confidence: list[float]) -> dict:
    """
    Normalize the LLM's per-field {value, source_text, page_number}
    objects into the API's documented shape, and pass array/table
    fields (e.g. line_items) through unchanged.

    Attaches a "confidence" to each scalar field, sourced from the OCR
    engine's own confidence for the page that field's evidence points
    to (1.0 for pages read from a native PDF text layer). This keeps
    confidence "meaningful and explainable" per the spec, rather than
    an arbitrary number invented by the LLM — the LLM is never asked
    for a confidence value at all (see extraction_service._SYSTEM_PROMPT).
    Fields with no value (null, not found) get confidence=None: there
    is nothing to be confident about.
    """
    fallback_confidence = round(sum(page_confidence) / len(page_confidence), 4) if page_confidence else None
    shaped = {}
    for key, entry in raw.items():
        if isinstance(entry, dict) and "value" in entry:
            value = entry.get("value")
            page_number = entry.get("page_number")
            confidence = None
            if value is not None:
                if isinstance(page_number, int) and 1 <= page_number <= len(page_confidence):
                    confidence = page_confidence[page_number - 1]
                else:
                    confidence = fallback_confidence
            shaped[key] = {
                "value": value,
                "page_number": page_number,
                "source_text": entry.get("source_text"),
                "confidence": confidence,
            }
        else:
            # arrays (line_items, nested breakdowns) or already-plain values
            shaped[key] = entry
    return shaped


def _compute_overall_confidence(extracted_data: dict) -> float | None:
    scores = [
        entry["confidence"]
        for entry in extracted_data.values()
        if isinstance(entry, dict) and entry.get("confidence") is not None
    ]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def process_document(
    db: Session,
    file_bytes: bytes,
    content_type: str,
    filename: str,
    document_type: str,
) -> tuple[int, dict]:
    start = time.perf_counter()

    # --- Stage 1: file validation ---
    try:
        file_validation = validate_file(file_bytes, content_type, filename)
    except DocumentValidationError as exc:
        logger.warning("Validation failed for %s: %s", filename, exc.message)
        failed_record = ProcessedDocument(
            document_name=filename,
            document_type=document_type,
            processing_status="FAILED",
            file_validation={
                "file_type": content_type,
                "is_supported": exc.code != "UNSUPPORTED_FILE_TYPE",
                "is_readable": exc.code not in ("CORRUPTED_FILE", "EMPTY_FILE"),
                "page_count": None,
                "status": "FAILED",
                "reason": exc.message,
            },
            error={"code": exc.code, "message": exc.message},
        )
        document_repository.save_result(db, failed_record)
        return 422, failed_record.to_response_dict()

    # --- Stage 2: OCR / text extraction ---
    try:
        ocr_result = ocr_service.extract_text(file_bytes, content_type)
    except ocr_service.OcrConfigurationError as exc:
        # Tesseract/Poppler missing or misconfigured on this server —
        # surface the actionable message instead of a generic failure,
        # since this is a setup problem, not a bad document.
        logger.error("OCR configuration error for %s: %s", filename, exc)
        return _fail(db, filename, document_type, file_validation, "OCR_NOT_CONFIGURED", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("OCR stage failed for %s", filename)
        return _fail(db, filename, document_type, file_validation, "OCR_FAILURE", "Text extraction/OCR failed for this document.")

    if not any(p.strip() for p in ocr_result.pages_text):
        return _fail(
            db, filename, document_type, file_validation,
            "NO_TEXT_EXTRACTED", "No readable text could be extracted from this document.",
        )

    # --- Stage 3: AI field & table extraction ---
    try:
        raw_extracted = extraction_service.extract_fields(ocr_result.pages_text, document_type)
    except extraction_service.ExtractionError as exc:
        logger.error("Extraction stage failed for %s: %s", filename, exc)
        return _fail(db, filename, document_type, file_validation, "EXTRACTION_FAILURE", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected extraction failure for %s", filename)
        return _fail(db, filename, document_type, file_validation, "EXTRACTION_FAILURE", "AI extraction failed unexpectedly.")

    extracted_data = _reshape_extracted_data(raw_extracted, ocr_result.page_confidence)
    overall_confidence = _compute_overall_confidence(extracted_data)

    # --- Stage 4: financial validation ---
    try:
        validation_result = fin_validation.validate(document_type, extracted_data)
    except Exception:  # noqa: BLE001
        logger.exception("Financial validation stage failed for %s", filename)
        validation_result = {"checks": [], "overall_status": "NOT_APPLICABLE", "issues": ["validation_engine_error"]}

    processing_status = "PASS" if validation_result["overall_status"] in ("PASS", "NOT_APPLICABLE") else "FAILED"

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    metadata = {
        "ocr_used": ocr_result.ocr_used,
        "processed_at": datetime.datetime.utcnow().isoformat() + "Z",
        "processing_time_ms": elapsed_ms,
        "llm_model": extraction_service.settings.GEMINI_MODEL,
    }

    record = ProcessedDocument(
        document_name=filename,
        document_type=document_type,
        processing_status=processing_status,
        overall_confidence=overall_confidence,
        file_validation=file_validation.model_dump(),
        extracted_data=extracted_data,
        validation=validation_result,
        processing_metadata=metadata,
    )
    document_repository.save_result(db, record)
    logger.info("Processed %s as %s -> %s", filename, document_type, processing_status)
    return 200, record.to_response_dict()


def _fail(db, filename, document_type, file_validation, code, message):
    record = ProcessedDocument(
        document_name=filename,
        document_type=document_type,
        processing_status="FAILED",
        file_validation=file_validation.model_dump(),
        error={"code": code, "message": message},
    )
    document_repository.save_result(db, record)
    return 422, record.to_response_dict()
