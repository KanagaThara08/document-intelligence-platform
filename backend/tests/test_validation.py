import io
import pytest
from PIL import Image

from app.services.document_validation_service import validate_file, DocumentValidationError


def _make_png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color="white").save(buf, format="PNG")
    return buf.getvalue()


def test_valid_png_passes():
    result = validate_file(_make_png_bytes(), "image/png", "sample.png")
    assert result.status == "PASS"
    assert result.page_count == 1


def test_empty_file_rejected():
    with pytest.raises(DocumentValidationError) as exc_info:
        validate_file(b"", "application/pdf", "empty.pdf")
    assert exc_info.value.code == "EMPTY_FILE"


def test_unsupported_content_type_rejected():
    with pytest.raises(DocumentValidationError) as exc_info:
        validate_file(b"some bytes", "application/zip", "archive.zip")
    assert exc_info.value.code == "UNSUPPORTED_FILE_TYPE"


def test_corrupted_pdf_rejected():
    with pytest.raises(DocumentValidationError) as exc_info:
        validate_file(b"%PDF-1.4 not a real pdf structure", "application/pdf", "broken.pdf")
    assert exc_info.value.code == "CORRUPTED_FILE"


def test_corrupted_image_rejected():
    with pytest.raises(DocumentValidationError) as exc_info:
        validate_file(b"not an image at all", "image/png", "broken.png")
    assert exc_info.value.code == "CORRUPTED_FILE"


from app.services import financial_validation_service as fv


def test_invoice_total_check_passes():
    data = {
        "subtotal": {"value": 12500.00},
        "tax_amount": {"value": 625.00},
        "discount": {"value": 0.00},
        "total_amount": {"value": 13125.00},
    }
    result = fv.validate("invoice", data)
    check = next(c for c in result["checks"] if c["name"] == "invoice_total_check")
    assert check["status"] == "PASS"
    assert result["overall_status"] == "PASS"


def test_invoice_total_check_fails_on_mismatch():
    data = {
        "subtotal": {"value": 100.00},
        "tax_amount": {"value": 10.00},
        "discount": {"value": 0.00},
        "total_amount": {"value": 500.00},  # deliberately wrong
    }
    result = fv.validate("invoice", data)
    check = next(c for c in result["checks"] if c["name"] == "invoice_total_check")
    assert check["status"] == "FAIL"
    assert result["overall_status"] == "FAIL"


def test_invoice_missing_fields_not_applicable():
    data = {"vendor_name": {"value": "ABC Corp"}}
    result = fv.validate("invoice", data)
    check = next(c for c in result["checks"] if c["name"] == "invoice_total_check")
    assert check["status"] == "NOT_APPLICABLE"


def test_balance_sheet_check():
    data = {
        "total_assets": {"value": 1000},
        "total_liabilities": {"value": 600},
        "total_equity": {"value": 400},
    }
    result = fv.validate("balance_sheet", data)
    assert result["overall_status"] == "PASS"


def test_parenthesized_negative_value_parsing():
    assert fv._to_number("(1,234.50)") == -1234.50
    assert fv._to_number("1,234.50") == 1234.50
    assert fv._to_number(None) is None
    assert fv._to_number("N/A") is None


def test_cash_flow_check():
    data = {
        "operating_cash_flow": {"value": 500},
        "investing_cash_flow": {"value": -200},
        "financing_cash_flow": {"value": -100},
        "net_change_in_cash": {"value": 200},
        "opening_cash": {"value": 1000},
        "closing_cash": {"value": 1200},
    }
    result = fv.validate("cash_flow_statement", data)
    assert result["overall_status"] == "PASS"


def test_invoice_line_items_reconcile_to_total_when_no_subtotal():
    # Spec 4.4: "Candidates must handle cases where GST/tax is already
    # included in the displayed total" — no separate subtotal reported.
    data = {
        "total_amount": {"value": 20.0},
        "line_items": [
            {"description": "A", "quantity": 1, "unit_price": 12.0, "amount": 12.0},
            {"description": "B", "quantity": 1, "unit_price": 8.0, "amount": 8.0},
        ],
    }
    result = fv.validate("invoice", data)
    check = next(c for c in result["checks"] if c["name"] == "line_items_sum_to_total")
    assert check["status"] == "PASS"


def test_balance_sheet_component_reconciliation():
    data = {
        "total_assets": {"value": 1000},
        "total_liabilities": {"value": 600},
        "total_equity": {"value": 400},
        "asset_components": [{"label": "Cash", "value": 300}, {"label": "Investments", "value": 700}],
        "liability_equity_components": [
            {"label": "Deposits", "value": 600}, {"label": "Capital", "value": 400},
        ],
    }
    result = fv.validate("balance_sheet", data)
    asset_check = next(c for c in result["checks"] if c["name"] == "asset_components_reconcile_to_total_assets")
    liab_check = next(c for c in result["checks"] if c["name"] == "liability_equity_components_reconcile_to_total")
    assert asset_check["status"] == "PASS"
    assert liab_check["status"] == "PASS"


def test_balance_sheet_component_check_not_applicable_when_missing():
    data = {"total_assets": {"value": 1000}, "total_liabilities": {"value": 600}, "total_equity": {"value": 400}}
    result = fv.validate("balance_sheet", data)
    asset_check = next(c for c in result["checks"] if c["name"] == "asset_components_reconcile_to_total_assets")
    assert asset_check["status"] == "NOT_APPLICABLE"


def test_comparative_period_validated_independently():
    # Current year fails, prior year (comparative) passes — each period
    # must be validated independently per spec 4.4.
    data = {
        "total_assets": {"value": 1000},
        "total_liabilities": {"value": 600},
        "total_equity": {"value": 300},  # deliberately wrong -> current period FAILs
        "comparative_periods": [
            {
                "period_label": "Prior Year",
                "data": {"total_assets": 900, "total_liabilities": 500, "total_equity": 400},  # reconciles -> PASS
            }
        ],
    }
    result = fv.validate("balance_sheet", data)
    current_check = next(
        c for c in result["checks"]
        if c["name"] == "total_capital_liabilities_equals_assets" and c["period"] == "current"
    )
    prior_check = next(
        c for c in result["checks"]
        if c["name"] == "total_capital_liabilities_equals_assets" and c["period"] == "Prior Year"
    )
    assert current_check["status"] == "FAIL"
    assert prior_check["status"] == "PASS"
    assert result["overall_status"] == "FAIL"  # any period failing fails the overall result
