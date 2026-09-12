import pytest

from app.services.extraction_service import _parse_json_response, ExtractionError
from app.services.document_service import _reshape_extracted_data, _compute_overall_confidence


def test_parse_clean_json():
    raw = '{"invoice_number": {"value": "INV-1", "page_number": 1}}'
    parsed = _parse_json_response(raw)
    assert parsed["invoice_number"]["value"] == "INV-1"


def test_parse_json_wrapped_in_markdown_fences():
    raw = '```json\n{"total_amount": {"value": 100}}\n```'
    parsed = _parse_json_response(raw)
    assert parsed["total_amount"]["value"] == 100


def test_parse_json_with_surrounding_prose_falls_back_to_extraction():
    raw = 'Here is the result:\n{"vendor_name": {"value": "ACME"}}\nHope that helps!'
    parsed = _parse_json_response(raw)
    assert parsed["vendor_name"]["value"] == "ACME"


def test_parse_invalid_json_raises_extraction_error():
    with pytest.raises(ExtractionError):
        _parse_json_response("this is not json at all")


def test_reshape_extracted_data_normalizes_field_entries():
    raw = {
        "invoice_number": {"value": "INV-1", "source_text": "Invoice # INV-1", "page_number": 1},
        "line_items": [{"description": "A", "quantity": 1, "unit_price": 10, "amount": 10}],
    }
    shaped = _reshape_extracted_data(raw, page_confidence=[0.92])
    assert shaped["invoice_number"] == {
        "value": "INV-1", "page_number": 1, "source_text": "Invoice # INV-1", "confidence": 0.92,
    }
    assert shaped["line_items"] == raw["line_items"]


def test_reshape_extracted_data_null_value_has_no_confidence():
    raw = {"missing_field": {"value": None, "source_text": None, "page_number": None}}
    shaped = _reshape_extracted_data(raw, page_confidence=[1.0])
    assert shaped["missing_field"]["confidence"] is None


def test_reshape_extracted_data_falls_back_to_average_confidence_for_unresolved_page():
    raw = {"field_a": {"value": "x", "source_text": "x", "page_number": None}}
    shaped = _reshape_extracted_data(raw, page_confidence=[1.0, 0.5])
    assert shaped["field_a"]["confidence"] == 0.75


def test_compute_overall_confidence_averages_field_scores():
    extracted = {
        "a": {"value": 1, "confidence": 0.9},
        "b": {"value": 2, "confidence": 0.7},
        "c": {"value": None, "confidence": None},
        "line_items": [{"description": "x"}],
    }
    assert _compute_overall_confidence(extracted) == 0.8
