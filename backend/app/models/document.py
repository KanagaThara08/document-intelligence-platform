"""
ORM model for a processed document record.

We store the full structured result (extracted_data, validation,
file_validation, processing_metadata) as JSON columns rather than
normalizing into many tables. For a 3-day prototype this keeps the
schema simple while still supporting "get by document name" and
"list all documents" cleanly. See README "Database/persistence
approach" for the production-scale alternative.
"""
import datetime
import uuid

from sqlalchemy import Column, String, DateTime, JSON, Float
from app.core.database import Base


class ProcessedDocument(Base):
    __tablename__ = "processed_documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_name = Column(String, index=True, nullable=False)
    document_type = Column(String, nullable=False)
    processing_status = Column(String, nullable=False)  # PASS | FAILED
    overall_confidence = Column(Float, nullable=True)

    file_validation = Column(JSON, nullable=False)
    extracted_data = Column(JSON, nullable=True)
    validation = Column(JSON, nullable=True)
    processing_metadata = Column(JSON, nullable=True)
    error = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    def to_response_dict(self) -> dict:
        """
        Shape this row back into the mandatory API response schema.

        Branches on whether extraction actually produced data, NOT on
        processing_status — those are different things. processing_status
        can legitimately be FAILED because financial validation found a
        genuine mismatch (spec 4.5: PASS requires validations to pass
        too), while extraction itself succeeded perfectly. In that case
        the evaluator still needs to see extracted_data + validation to
        understand *why* it failed — hiding it behind "error" (which is
        for actual processing failures: corrupt file, OCR failure, LLM
        failure) would make the failure undiagnosable.
        """
        body = {
            "document_name": self.document_name,
            "document_type": self.document_type,
            "processing_status": self.processing_status,
            "file_validation": self.file_validation,
            "processing_metadata": self.processing_metadata or {},
        }
        if self.overall_confidence is not None:
            body["overall_confidence"] = self.overall_confidence
        if self.extracted_data is not None:
            body["extracted_data"] = self.extracted_data
            body["validation"] = self.validation
        if self.error is not None:
            body["error"] = self.error
        return body

    def to_list_item(self) -> dict:
        """Compact representation used by the dashboard list endpoint."""
        return {
            "document_name": self.document_name,
            "document_type": self.document_type,
            "processing_status": self.processing_status,
            "overall_confidence": self.overall_confidence,
            "processed_at": (self.processing_metadata or {}).get("processed_at"),
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }
