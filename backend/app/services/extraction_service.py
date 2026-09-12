"""
AI-based field & table extraction service.

Takes OCR'd/extracted page text and asks Google Gemini to return a
single structured JSON object containing every meaningful field and
table visible in the document for the given document_type. The model
is explicitly instructed to use null for anything not present rather
than inventing values, per the case-study's anti-hallucination
requirement.

Gemini was chosen (over Anthropic Claude) specifically because Google
AI Studio issues a genuinely free-tier API key with no billing/credit
card required, which fits this assignment's "free/free-tier" guidance
better for a quick prototype/demo. Swapping providers again later only
requires changes in this one file — nothing else in the pipeline
(document_service.py, financial_validation_service.py, etc.) depends
on which LLM is used.

Evidence page numbers are assigned by attaching, alongside each field
value, the page text used for extraction — for multi-page inputs we
ask the model to report the page number itself, since it can see
which page-labeled chunk a value came from.
"""
import json
import re

from google import genai
from google.genai import types

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.extraction import MINIMUM_FIELDS, LINE_ITEM_HINTS, SUPPORTS_COMPARATIVE_PERIOD, COMPARATIVE_PERIOD_HINT

logger = get_logger(__name__)
settings = get_settings()


class ExtractionError(Exception):
    pass


_SYSTEM_PROMPT = """You are a meticulous financial document data-extraction engine.
You will be given the OCR/text-extracted content of a financial document, split
by page. Extract ALL meaningful information visible in the document and return
ONLY a single valid JSON object — no prose, no markdown fences, no commentary.

Rules:
- Every field must be an object: {"value": <value or null>, "source_text": <short
  verbatim snippet supporting the value, or null>, "page_number": <int or null>}.
- If a value is not present or not legible, set "value" to null. NEVER invent,
  guess, or infer a value that is not supported by the document text.
- Numbers must be plain numbers (no currency symbols, no thousands separators)
  in the "value" field.
- Include every minimum required field listed below, AND any additional
  meaningful fields, headers, dates, parties, or line items visible in the
  document that are not in that minimum list.
- Represent tables / line items as an array field as described below. Each
  array element should itself contain plain key/value pairs (not the
  value/source_text/page_number wrapper) since tables are evaluated as a unit.
- Parenthesized or bracketed numbers, e.g. (1,234), represent negative values.
"""


def extract_fields(pages_text: list[str], document_type: str) -> dict:
    if not settings.GEMINI_API_KEY:
        raise ExtractionError(
            "GEMINI_API_KEY is not configured on the server. Set it as an "
            "environment variable (get a free key at https://aistudio.google.com/apikey) "
            "to enable AI extraction."
        )

    minimum_fields = MINIMUM_FIELDS[document_type]
    line_item_hint = LINE_ITEM_HINTS[document_type]
    comparative_hint = f"\n{COMPARATIVE_PERIOD_HINT}\n" if document_type in SUPPORTS_COMPARATIVE_PERIOD else ""

    document_text = "\n\n".join(
        f"--- PAGE {i + 1} ---\n{text}" for i, text in enumerate(pages_text)
    )

    user_prompt = f"""Document type: {document_type}

Minimum required fields (must appear as keys, value null if not present):
{json.dumps(minimum_fields, indent=2)}

Also extract: {line_item_hint}
{comparative_hint}
Document content:
{document_text}

Return ONLY the JSON object described in the system instructions."""

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    logger.info("Calling Gemini (%s) for %s extraction", settings.GEMINI_MODEL, document_type)
    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                max_output_tokens=8000,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Gemini API call failed: %s", exc)
        raise ExtractionError(f"LLM extraction call failed: {exc}") from exc

    raw_text = response.text or ""
    if not raw_text.strip():
        logger.error("Gemini returned an empty response for %s extraction", document_type)
        raise ExtractionError("The AI extraction response was empty.")

    return _parse_json_response(raw_text)


def _parse_json_response(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # Last resort: grab the largest {...} block in the response.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        logger.error("Failed to parse LLM JSON response: %s", exc)
        raise ExtractionError("The AI extraction response was not valid JSON.")
