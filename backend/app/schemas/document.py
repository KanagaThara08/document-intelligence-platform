"""
Pydantic schemas for API-level request/response shapes.

Field-level extraction schemas (per document type) live in
schemas/extraction.py — this file covers the envelope: file
validation, the overall process response, list items, and errors.
"""
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    invoice = "invoice"
    balance_sheet = "balance_sheet"
    profit_and_loss = "profit_and_loss"
    cash_flow_statement = "cash_flow_statement"


class ProcessingStatus(str, Enum):
    PASS = "PASS"
    FAILED = "FAILED"


class FileValidationResult(BaseModel):
    file_type: str
    is_supported: bool
    is_readable: bool
    page_count: Optional[int] = None
    status: str  # PASS | FAILED
    reason: Optional[str] = None


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ProcessingMetadata(BaseModel):
    ocr_used: bool
    processed_at: str
    processing_time_ms: int
    llm_model: Optional[str] = None


class ExtractedField(BaseModel):
    """
    Shape of every scalar extracted field. confidence is sourced from
    the OCR engine's own per-page word confidence (see ocr_service.py),
    never from the LLM — kept meaningful/explainable per spec 4.3, and
    is null whenever value is null (nothing to be confident about).
    """
    value: Optional[Any] = None
    page_number: Optional[int] = None
    source_text: Optional[str] = None
    confidence: Optional[float] = None


class DocumentProcessResponse(BaseModel):
    document_name: str
    document_type: DocumentType
    processing_status: ProcessingStatus
    overall_confidence: Optional[float] = None
    file_validation: FileValidationResult
    extracted_data: Optional[dict[str, Any]] = None
    validation: Optional[dict[str, Any]] = None
    processing_metadata: Optional[dict[str, Any]] = None
    error: Optional[ErrorDetail] = None


class DocumentListItem(BaseModel):
    document_name: str
    document_type: str
    processing_status: str
    overall_confidence: Optional[float] = None
    processed_at: Optional[str] = None
    created_at: Optional[str] = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentListItem]
    count: int


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
