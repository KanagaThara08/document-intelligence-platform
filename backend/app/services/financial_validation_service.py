"""
Financial calculation validation service.

For each document type, runs the minimum required reconciliation
checks described in the case study. Every check follows a consistent
shape: {name, formula, operands, calculated_value, reported_value,
variance, status, period}. status is one of PASS / FAIL / NOT_APPLICABLE
— NOT_APPLICABLE (never an invented value) is used whenever an input
field required for a check is missing/null.

Numbers wrapped in parentheses are treated as negative values, per
standard accounting notation (handled in _to_number).

Per the spec's "validate each period independently where comparative
data is available" requirement, balance_sheet / profit_and_loss /
cash_flow_statement also re-run their full check set against every
entry in extracted_data["comparative_periods"] (if the LLM found a
prior-year column), tagging each resulting check with its period label.
"""
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

CURRENT_PERIOD_LABEL = "current"


def _to_number(raw):
    """Coerce an extracted field's raw value into a float, or None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        s = raw.strip().replace(",", "").replace("$", "").replace("₹", "").replace("€", "")
        negative = s.startswith("(") and s.endswith(")")
        s = s.strip("()").strip()
        if s in ("", "-", "—", "N/A", "n/a"):
            return None
        try:
            value = float(s)
            return -value if negative else value
        except ValueError:
            return None
    return None


def _field_value(data: dict, field: str):
    """
    Read a field's numeric value. Handles both the evidence-wrapped
    shape used for the current period ({"value": ..., ...}) and the
    plain shape used for comparative_periods entries (per the
    extraction prompt, comparative data is plain numbers/strings).
    """
    entry = data.get(field)
    if isinstance(entry, dict):
        return _to_number(entry.get("value"))
    return _to_number(entry)


def _make_check(name, formula, operands, calculated, reported, period=CURRENT_PERIOD_LABEL):
    if calculated is None or reported is None:
        return {
            "name": name,
            "formula": formula,
            "operands": operands,
            "calculated_value": calculated,
            "reported_value": reported,
            "variance": None,
            "status": "NOT_APPLICABLE",
            "period": period,
        }
    variance = round(calculated - reported, 2)
    status = "PASS" if abs(variance) <= settings.VALIDATION_TOLERANCE else "FAIL"
    return {
        "name": name,
        "formula": formula,
        "operands": operands,
        "calculated_value": round(calculated, 2),
        "reported_value": round(reported, 2),
        "variance": variance,
        "status": status,
        "period": period,
    }


_VALIDATORS = {}  # populated below, keyed by document_type


def validate(document_type: str, extracted_data: dict) -> dict:
    validator = _VALIDATORS.get(document_type)
    checks: list[dict] = validator(extracted_data, CURRENT_PERIOD_LABEL) if validator else []

    # Per-period validation: re-run the same checks against every
    # comparative period the extraction step found, if this document
    # type supports it (invoices generally don't have one).
    comparative_periods = extracted_data.get("comparative_periods")
    if validator and isinstance(comparative_periods, list):
        for period_entry in comparative_periods:
            if not isinstance(period_entry, dict):
                continue
            period_label = period_entry.get("period_label") or "comparative"
            period_data = period_entry.get("data")
            if isinstance(period_data, dict):
                checks.extend(validator(period_data, period_label))

    statuses = {c["status"] for c in checks}
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "PASS" in statuses:
        overall = "PASS"
    else:
        overall = "NOT_APPLICABLE"

    issues = [f"{c['name']} ({c['period']})" for c in checks if c["status"] == "FAIL"]
    return {"checks": checks, "overall_status": overall, "issues": issues}


def _validate_invoice(d: dict, period: str) -> list[dict]:
    checks = []
    subtotal = _field_value(d, "subtotal")
    tax = _field_value(d, "tax_amount")
    discount = _field_value(d, "discount") or 0.0
    total = _field_value(d, "total_amount")

    if subtotal is not None and total is not None:
        calc = subtotal + (tax or 0.0) - discount
        checks.append(_make_check(
            "invoice_total_check",
            "subtotal + tax_amount - discount",
            {"subtotal": subtotal, "tax_amount": tax, "discount": discount},
            calc, total, period,
        ))
    else:
        checks.append(_make_check(
            "invoice_total_check", "subtotal + tax_amount - discount", {}, None, None, period,
        ))

    line_items = d.get("line_items")
    if isinstance(line_items, list) and line_items:
        line_sum = 0.0
        valid = True
        for item in line_items:
            qty = _to_number(item.get("quantity"))
            price = _to_number(item.get("unit_price"))
            amount = _to_number(item.get("amount"))
            if qty is not None and price is not None and amount is not None:
                checks.append(_make_check(
                    f"line_item_check::{item.get('description', '')[:30]}",
                    "quantity * unit_price ≈ amount",
                    {"quantity": qty, "unit_price": price},
                    round(qty * price, 2), amount, period,
                ))
            if amount is not None:
                line_sum += amount
            else:
                valid = False

        if valid and subtotal is not None:
            # Standard case: a separate subtotal is shown, tax added on top.
            checks.append(_make_check(
                "line_items_sum_to_subtotal",
                "sum(line_items.amount) ≈ subtotal",
                {"line_item_count": len(line_items)},
                round(line_sum, 2), subtotal, period,
            ))
        elif valid and subtotal is None and total is not None:
            # Spec 4.4: "Candidates must handle cases where GST/tax is
            # already included in the displayed total" — when there is
            # no separate subtotal, line-item amounts are tax-inclusive,
            # so they should reconcile directly to the total instead.
            checks.append(_make_check(
                "line_items_sum_to_total",
                "sum(line_items.amount) ≈ total_amount (tax-inclusive line items, no separate subtotal reported)",
                {"line_item_count": len(line_items)},
                round(line_sum, 2), total, period,
            ))

    cash_paid = _field_value(d, "cash_paid")
    change = _field_value(d, "change")
    if cash_paid is not None and total is not None and change is not None:
        checks.append(_make_check(
            "cash_change_check",
            "cash_paid - total_amount ≈ change",
            {"cash_paid": cash_paid, "total_amount": total},
            round(cash_paid - total, 2), change, period,
        ))

    return checks


def _sum_components(components) -> tuple[float | None, int]:
    """Sum a list of {"label": ..., "value": ...} component dicts.
    Returns (sum_or_None, count). Sum is None if the list is missing,
    empty, or any entry's value isn't numeric — per spec, component
    reconciliation only applies "where sufficient line items are
    available", so a partial/unparseable list yields NOT_APPLICABLE
    rather than a misleading partial sum."""
    if not isinstance(components, list) or not components:
        return None, 0
    total = 0.0
    for item in components:
        if not isinstance(item, dict):
            return None, 0
        value = _to_number(item.get("value"))
        if value is None:
            return None, 0
        total += value
    return round(total, 2), len(components)


def _validate_balance_sheet(d: dict, period: str) -> list[dict]:
    assets = _field_value(d, "total_assets")
    liabilities = _field_value(d, "total_liabilities")
    equity = _field_value(d, "total_equity")

    checks = []
    if liabilities is not None and equity is not None and assets is not None:
        calc = liabilities + equity
        checks.append(_make_check(
            "total_capital_liabilities_equals_assets",
            "total_liabilities + total_equity ≈ total_assets",
            {"total_liabilities": liabilities, "total_equity": equity},
            calc, assets, period,
        ))
    else:
        checks.append(_make_check(
            "total_capital_liabilities_equals_assets",
            "total_liabilities + total_equity ≈ total_assets", {}, None, None, period,
        ))

    # Spec 4.4: "the sum of individual Capital & Liability components
    # should reconcile to the reported Capital & Liabilities total, and
    # the sum of individual Asset components should reconcile to the
    # reported Assets total" — only runs when the LLM found enough
    # structure to populate these component arrays.
    asset_sum, asset_count = _sum_components(d.get("asset_components"))
    if asset_sum is not None and assets is not None:
        checks.append(_make_check(
            "asset_components_reconcile_to_total_assets",
            "sum(asset_components.value) ≈ total_assets",
            {"component_count": asset_count},
            asset_sum, assets, period,
        ))
    else:
        checks.append(_make_check(
            "asset_components_reconcile_to_total_assets",
            "sum(asset_components.value) ≈ total_assets", {}, None, None, period,
        ))

    liab_equity_sum, liab_equity_count = _sum_components(d.get("liability_equity_components"))
    combined_total = None
    if liabilities is not None and equity is not None:
        combined_total = liabilities + equity
    elif assets is not None:
        combined_total = assets  # balance sheets must balance, so assets is an equally valid target
    if liab_equity_sum is not None and combined_total is not None:
        checks.append(_make_check(
            "liability_equity_components_reconcile_to_total",
            "sum(liability_equity_components.value) ≈ total_liabilities + total_equity",
            {"component_count": liab_equity_count},
            liab_equity_sum, combined_total, period,
        ))
    else:
        checks.append(_make_check(
            "liability_equity_components_reconcile_to_total",
            "sum(liability_equity_components.value) ≈ total_liabilities + total_equity", {}, None, None, period,
        ))

    return checks


def _validate_profit_and_loss(d: dict, period: str) -> list[dict]:
    checks = []

    interest_earned = _field_value(d, "interest_earned")
    other_income = _field_value(d, "other_income")
    total_income = _field_value(d, "total_income")
    if interest_earned is not None and other_income is not None and total_income is not None:
        checks.append(_make_check(
            "total_income_check",
            "interest_earned + other_income ≈ total_income",
            {"interest_earned": interest_earned, "other_income": other_income},
            round(interest_earned + other_income, 2), total_income, period,
        ))
    else:
        checks.append(_make_check("total_income_check", "interest_earned + other_income ≈ total_income", {}, None, None, period))

    interest_expended = _field_value(d, "interest_expended")
    operating_expenses = _field_value(d, "operating_expenses")
    provisions = _field_value(d, "provisions_and_contingencies")
    total_expenditure = _field_value(d, "total_expenditure")
    if None not in (interest_expended, operating_expenses, provisions, total_expenditure):
        checks.append(_make_check(
            "total_expenditure_check",
            "interest_expended + operating_expenses + provisions_and_contingencies ≈ total_expenditure",
            {"interest_expended": interest_expended, "operating_expenses": operating_expenses, "provisions_and_contingencies": provisions},
            round(interest_expended + operating_expenses + provisions, 2), total_expenditure, period,
        ))
    else:
        checks.append(_make_check(
            "total_expenditure_check",
            "interest_expended + operating_expenses + provisions_and_contingencies ≈ total_expenditure",
            {}, None, None, period,
        ))

    # Simpler / more commonly-populated P&L reconciliation using the
    # minimum required fields, run alongside the bank-style checks above
    # so the check set degrades gracefully for a standard commercial P&L.
    # Always append (as NOT_APPLICABLE when inputs are missing) for
    # consistency with the bank-style checks above — a check silently
    # disappearing vs. showing NOT_APPLICABLE would be confusing given
    # some of these fields (e.g. net_profit) may still be present.
    revenue = _field_value(d, "revenue")
    cogs = _field_value(d, "cost_of_sales")
    gross_profit = _field_value(d, "gross_profit")
    if None not in (revenue, cogs, gross_profit):
        checks.append(_make_check(
            "gross_profit_check",
            "revenue - cost_of_sales ≈ gross_profit",
            {"revenue": revenue, "cost_of_sales": cogs},
            round(revenue - cogs, 2), gross_profit, period,
        ))
    else:
        checks.append(_make_check("gross_profit_check", "revenue - cost_of_sales ≈ gross_profit", {}, None, None, period))

    operating_expenses_std = _field_value(d, "operating_expenses")
    operating_profit = _field_value(d, "operating_profit")
    if None not in (gross_profit, operating_expenses_std, operating_profit):
        checks.append(_make_check(
            "operating_profit_check",
            "gross_profit - operating_expenses ≈ operating_profit",
            {"gross_profit": gross_profit, "operating_expenses": operating_expenses_std},
            round(gross_profit - operating_expenses_std, 2), operating_profit, period,
        ))
    else:
        checks.append(_make_check("operating_profit_check", "gross_profit - operating_expenses ≈ operating_profit", {}, None, None, period))

    tax = _field_value(d, "tax")
    net_profit = _field_value(d, "net_profit")
    if None not in (operating_profit, tax, net_profit):
        checks.append(_make_check(
            "net_profit_check",
            "operating_profit - tax ≈ net_profit",
            {"operating_profit": operating_profit, "tax": tax},
            round(operating_profit - tax, 2), net_profit, period,
        ))
    else:
        checks.append(_make_check("net_profit_check", "operating_profit - tax ≈ net_profit", {}, None, None, period))

    net_profit_before_minority = _field_value(d, "consolidated_net_profit_before_minority_interest")
    if total_income is not None and total_expenditure is not None and net_profit_before_minority is not None:
        checks.append(_make_check(
            "net_profit_before_minority_check",
            "total_income - total_expenditure ≈ consolidated_net_profit_before_minority_interest",
            {"total_income": total_income, "total_expenditure": total_expenditure},
            round(total_income - total_expenditure, 2), net_profit_before_minority, period,
        ))
    else:
        checks.append(_make_check("net_profit_before_minority_check", "total_income - total_expenditure ≈ consolidated_net_profit_before_minority_interest", {}, None, None, period))

    minority_interest = _field_value(d, "minority_interest")
    net_profit_group = _field_value(d, "consolidated_net_profit_attributable_to_group")
    if None not in (net_profit_before_minority, minority_interest, net_profit_group):
        checks.append(_make_check(
            "net_profit_attributable_to_group_check",
            "consolidated_net_profit_before_minority_interest - minority_interest ≈ consolidated_net_profit_attributable_to_group",
            {"consolidated_net_profit_before_minority_interest": net_profit_before_minority, "minority_interest": minority_interest},
            round(net_profit_before_minority - minority_interest, 2), net_profit_group, period,
        ))
    else:
        checks.append(_make_check("net_profit_attributable_to_group_check", "consolidated_net_profit_before_minority_interest - minority_interest ≈ consolidated_net_profit_attributable_to_group", {}, None, None, period))

    current_profit = _field_value(d, "current_profit")
    brought_forward = _field_value(d, "brought_forward_profit")
    total_available = _field_value(d, "total_available_for_appropriation")
    if None not in (current_profit, brought_forward, total_available):
        checks.append(_make_check(
            "appropriation_check",
            "current_profit + brought_forward_profit ≈ total_available_for_appropriation",
            {"current_profit": current_profit, "brought_forward_profit": brought_forward},
            round(current_profit + brought_forward, 2), total_available, period,
        ))
    else:
        checks.append(_make_check("appropriation_check", "current_profit + brought_forward_profit ≈ total_available_for_appropriation", {}, None, None, period))

    return checks


def _validate_cash_flow(d: dict, period: str) -> list[dict]:
    checks = []

    operating = _field_value(d, "operating_cash_flow")
    investing = _field_value(d, "investing_cash_flow")
    financing = _field_value(d, "financing_cash_flow")
    fx_adjustment = _field_value(d, "fx_translation_adjustment") or 0.0
    net_change = _field_value(d, "net_change_in_cash")

    if None not in (operating, investing, financing, net_change):
        checks.append(_make_check(
            "net_change_in_cash_check",
            "operating_cash_flow + investing_cash_flow + financing_cash_flow + fx_translation_adjustment ≈ net_change_in_cash",
            {"operating_cash_flow": operating, "investing_cash_flow": investing, "financing_cash_flow": financing, "fx_translation_adjustment": fx_adjustment},
            round(operating + investing + financing + fx_adjustment, 2), net_change, period,
        ))
    else:
        checks.append(_make_check(
            "net_change_in_cash_check",
            "operating_cash_flow + investing_cash_flow + financing_cash_flow + fx_translation_adjustment ≈ net_change_in_cash",
            {}, None, None, period,
        ))

    opening_cash = _field_value(d, "opening_cash")
    closing_cash = _field_value(d, "closing_cash")
    cash_acquired = _field_value(d, "cash_acquired_on_amalgamation") or 0.0

    if None not in (opening_cash, net_change, closing_cash):
        checks.append(_make_check(
            "closing_cash_check",
            "opening_cash + net_change_in_cash + cash_acquired_on_amalgamation ≈ closing_cash",
            {"opening_cash": opening_cash, "net_change_in_cash": net_change, "cash_acquired_on_amalgamation": cash_acquired},
            round(opening_cash + net_change + cash_acquired, 2), closing_cash, period,
        ))
    else:
        checks.append(_make_check(
            "closing_cash_check",
            "opening_cash + net_change_in_cash + cash_acquired_on_amalgamation ≈ closing_cash",
            {}, None, None, period,
        ))

    return checks


_VALIDATORS.update({
    "invoice": _validate_invoice,
    "balance_sheet": _validate_balance_sheet,
    "profit_and_loss": _validate_profit_and_loss,
    "cash_flow_statement": _validate_cash_flow,
})