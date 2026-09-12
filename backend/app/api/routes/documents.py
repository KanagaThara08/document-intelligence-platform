"""
Document API routes.

Thin HTTP layer: parses the request, delegates to document_service /
document_repository, and maps results to HTTP responses. No business
logic lives here.
"""
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import get_logger
from app.repositories import document_repository
from app.schemas.document import DocumentType, DocumentListResponse, HealthResponse
from app.services import document_service

logger = get_logger(__name__)
router = APIRouter()


@router.post("/documents/process")
async def process_document(
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    db: Session = Depends(get_db),
):
    try:
        file_bytes = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail={"error": {"code": "UPLOAD_READ_FAILURE", "message": "Could not read the uploaded file."}})

    content_type = file.content_type or "application/octet-stream"
    filename = file.filename or "uploaded_file"

    status_code, body = document_service.process_document(
        db=db,
        file_bytes=file_bytes,
        content_type=content_type,
        filename=filename,
        document_type=document_type.value,
    )
    return JSONResponse(status_code=status_code, content=body)


@router.get("/documents/{document_name}")
def get_document(document_name: str, db: Session = Depends(get_db)):
    record = document_repository.get_latest_by_name(db, document_name)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "DOCUMENT_NOT_FOUND", "message": f"No processed result found for '{document_name}'."}},
        )
    return record.to_response_dict()


@router.get("/documents", response_model=DocumentListResponse)
def list_documents(db: Session = Depends(get_db)):
    records = document_repository.list_all(db)
    items = [r.to_list_item() for r in records]
    return {"documents": items, "count": len(items)}


@router.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "service": "document-intelligence-api", "version": "1.0.0"}
