import os
import sys
import io

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_api.db")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db

# TestClient only triggers FastAPI startup events when used as a context
# manager; call init_db() directly here so tables exist regardless.
init_db()

client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_list_documents_endpoint_shape():
    resp = client.get("/api/v1/documents")
    assert resp.status_code == 200
    body = resp.json()
    assert "documents" in body
    assert "count" in body


def test_get_unknown_document_returns_404():
    resp = client.get("/api/v1/documents/does-not-exist.pdf")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_process_unsupported_file_type_rejected():
    files = {"file": ("archive.zip", io.BytesIO(b"fake zip bytes"), "application/zip")}
    data = {"document_type": "invoice"}
    resp = client.post("/api/v1/documents/process", files=files, data=data)
    assert resp.status_code == 422
    body = resp.json()
    assert body["processing_status"] == "FAILED"
    assert body["file_validation"]["status"] == "FAILED"


def test_process_empty_file_rejected():
    files = {"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    data = {"document_type": "invoice"}
    resp = client.post("/api/v1/documents/process", files=files, data=data)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "EMPTY_FILE"


def test_response_shows_extracted_data_even_when_validation_fails():
    """
    Regression test: a document can have processing_status FAILED purely
    because a financial check didn't reconcile (spec 4.5), even though
    extraction itself succeeded. The response must still include
    extracted_data + validation in that case — hiding them behind
    "error" (found live in production) makes the failure undiagnosable.
    """
    from app.models.document import ProcessedDocument

    record = ProcessedDocument(
        document_name="test.pdf",
        document_type="invoice",
        processing_status="FAILED",  # financial check FAILed, not a crash
        file_validation={"file_type": "application/pdf", "is_supported": True, "is_readable": True, "page_count": 1, "status": "PASS"},
        extracted_data={"total_amount": {"value": 100, "confidence": 0.9}},
        validation={"checks": [{"name": "x", "status": "FAIL", "period": "current"}], "overall_status": "FAIL", "issues": ["x"]},
        error=None,
    )
    body = record.to_response_dict()
    assert "extracted_data" in body
    assert body["extracted_data"]["total_amount"]["value"] == 100
    assert "validation" in body
    assert "error" not in body  # no error object when it's a genuine validation FAIL, not a crash


def teardown_module(module):
    try:
        os.remove("test_api.db")
    except OSError:
        pass
