"""
Repository layer: the only place that talks to the database directly.
Keeps SQLAlchemy specifics out of the service/API layers.
"""
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.document import ProcessedDocument


def save_result(db: Session, record: ProcessedDocument) -> ProcessedDocument:
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_latest_by_name(db: Session, document_name: str) -> ProcessedDocument | None:
    return (
        db.query(ProcessedDocument)
        .filter(ProcessedDocument.document_name == document_name)
        .order_by(desc(ProcessedDocument.created_at))
        .first()
    )


def list_all(db: Session, limit: int = 200) -> list[ProcessedDocument]:
    return (
        db.query(ProcessedDocument)
        .order_by(desc(ProcessedDocument.created_at))
        .limit(limit)
        .all()
    )
