"""
OCR / text extraction service.

Strategy:
  - Native PDF: try direct text-layer extraction (pypdf) first, page
    by page. Cheap and perfectly accurate when it works.
  - If a PDF page has no extractable text (scanned page), rasterize
    that page and run Tesseract OCR on it.
  - JPG/PNG: rasterize directly and run Tesseract OCR.

Returns a list of per-page text strings (1-indexed conceptually, but
stored 0-indexed in the list) so downstream extraction can attach an
evidence page_number to each field. Also returns a per-page confidence
score (0.0-1.0): 1.0 for pages read straight from a native PDF text
layer (no OCR uncertainty involved), or Tesseract's own average
word-level confidence for OCR'd pages. This is what powers the
optional field-level confidence in extraction_service.py — a real,
explainable number sourced from the OCR engine itself, per the case
study's requirement that confidence (if implemented) must be
meaningful rather than an arbitrary LLM-generated value.
"""
import io
from dataclasses import dataclass, field

import pytesseract
from PIL import Image
from pypdf import PdfReader
from pdf2image import convert_from_bytes

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

# On Windows, Tesseract/Poppler installers often don't add themselves
# to PATH, so we point pytesseract/pdf2image at explicit binary paths
# when the person has set them in .env (see README "Windows setup
# note"). No-op on Linux/macOS/Docker where PATH already works.
if settings.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

# Tesseract reports -1 for non-text regions (e.g. layout blocks); those
# are excluded from the confidence average.
_NON_TEXT_CONF = -1


@dataclass
class OcrResult:
    pages_text: list[str]
    ocr_used: bool
    page_confidence: list[float] = field(default_factory=list)


class OcrConfigurationError(Exception):
    """
    Raised when Tesseract itself can't be found/run — this is an
    environment setup problem, not "this document has no text," so it
    gets its own exception and a much more actionable message than a
    generic OCR failure (see document_service.py's handling of it).
    """
    pass


def _confidence_from_tesseract_data(ocr_data: dict) -> float:
    """
    Pure helper (easy to unit test) that reduces pytesseract's raw
    per-word output into a single 0.0-1.0 page confidence score.
    Returns 1.0 (benefit of the doubt) if no words were detected at
    all, since that's a text-extraction problem, not a confidence one.
    """
    confidences = [
        int(c) for c in ocr_data.get("conf", [])
        if str(c).lstrip("-").isdigit() and int(c) != _NON_TEXT_CONF
    ]
    if not confidences:
        return 1.0
    return round((sum(confidences) / len(confidences)) / 100, 4)


def extract_text(file_bytes: bytes, content_type: str) -> OcrResult:
    if content_type == "application/pdf":
        return _extract_from_pdf(file_bytes)
    return _extract_from_image(file_bytes)


def _extract_from_pdf(file_bytes: bytes) -> OcrResult:
    reader = PdfReader(io.BytesIO(file_bytes))
    pages_text: list[str] = []
    page_confidence: list[float] = []
    needs_ocr_pages: list[int] = []

    for idx, page in enumerate(reader.pages):
        try:
            text = (page.extract_text() or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Native text extraction failed on page %d: %s", idx + 1, exc)
            text = ""
        pages_text.append(text)
        page_confidence.append(1.0)  # native text layer: no OCR uncertainty
        if len(text) < 20:  # heuristic: near-empty => likely a scanned page
            needs_ocr_pages.append(idx)

    ocr_used = False
    if needs_ocr_pages:
        logger.info("Falling back to OCR for %d page(s)", len(needs_ocr_pages))
        try:
            images = convert_from_bytes(
                file_bytes, dpi=250,
                poppler_path=settings.POPPLER_PATH or None,
            )
            for idx in needs_ocr_pages:
                if idx < len(images):
                    pages_text[idx] = pytesseract.image_to_string(images[idx]).strip()
                    ocr_data = pytesseract.image_to_data(images[idx], output_type=pytesseract.Output.DICT)
                    page_confidence[idx] = _confidence_from_tesseract_data(ocr_data)
                    ocr_used = True
        except pytesseract.pytesseract.TesseractNotFoundError as exc:
            logger.error("Tesseract binary not found: %s", exc)
            raise OcrConfigurationError(
                "Tesseract OCR is not installed or not on PATH on this server. "
                "Install it, or set TESSERACT_CMD (and POPPLER_PATH if needed) "
                "in .env — see README 'Windows setup note'."
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.error("OCR rasterization/processing failed: %s", exc)

    return OcrResult(pages_text=pages_text, ocr_used=ocr_used, page_confidence=page_confidence)


def _extract_from_image(file_bytes: bytes) -> OcrResult:
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img = img.convert("RGB")
        text = pytesseract.image_to_string(img).strip()
        ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        confidence = _confidence_from_tesseract_data(ocr_data)
        return OcrResult(pages_text=[text], ocr_used=True, page_confidence=[confidence])
    except pytesseract.pytesseract.TesseractNotFoundError as exc:
        logger.error("Tesseract binary not found: %s", exc)
        raise OcrConfigurationError(
            "Tesseract OCR is not installed or not on PATH on this server. "
            "Install it, or set TESSERACT_CMD (and POPPLER_PATH if needed) "
            "in .env — see README 'Windows setup note'."
        ) from exc
    except pytesseract.TesseractError as exc:
        # Tesseract binary WAS found and ran, but errored internally —
        # most commonly missing/misconfigured tessdata (language files)
        # on Windows. Surface Tesseract's own error text directly rather
        # than swallowing it, since it names the actual problem.
        logger.error("Tesseract execution error: %s", exc)
        raise OcrConfigurationError(f"Tesseract OCR ran but failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("Image OCR failed: %s", exc)
        raise OcrConfigurationError(f"Unexpected OCR error: {exc}") from exc
