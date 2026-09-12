"""
Per-document-type field definitions.

These are NOT rigid schemas that reject extra fields — the case study
explicitly requires extracting ALL meaningful fields present, not just
a fixed minimum list. Instead, each entry lists the *minimum required*
fields (used to build the extraction prompt and to sanity-check the
LLM's output) while the LLM is explicitly instructed to add any other
fields/line items it finds beyond this list.
"""

MINIMUM_FIELDS: dict[str, list[str]] = {
    "invoice": [
        "invoice_number",
        "invoice_date",
        "vendor_name",
        "customer_name",
        "currency",
        "subtotal",
        "tax_amount",
        "discount",
        "total_amount",
    ],
    "balance_sheet": [
        "statement_date",
        "currency",
        "total_assets",
        "total_liabilities",
        "total_equity",
    ],
    "profit_and_loss": [
        "period",
        "currency",
        "revenue",
        "cost_of_sales",
        "gross_profit",
        "operating_expenses",
        "operating_profit",
        "tax",
        "net_profit",
    ],
    "cash_flow_statement": [
        "period",
        "currency",
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "opening_cash",
        "net_change_in_cash",
        "closing_cash",
    ],
}

# Human-readable description of expected tables/line items per type,
# used inside the extraction prompt.
LINE_ITEM_HINTS: dict[str, str] = {
    "invoice": (
        "an array field 'line_items', each item having description, "
        "quantity, unit_price and amount where a line-item table is present"
    ),
    "balance_sheet": (
        "nested breakdowns of assets/liabilities/equity components as they "
        "appear in the statement (e.g. current_assets, non_current_assets, "
        "individual line items). ALSO include two plain arrays for "
        "validation purposes: 'asset_components' and "
        "'liability_equity_components', each a list of "
        "{\"label\": <line item name>, \"value\": <number>} covering every "
        "individual line item on that side of the balance sheet (excluding "
        "the grand total itself), so the sum of components can be "
        "reconciled to the reported total"
    ),
    "profit_and_loss": (
        "every individual income and expense line item visible"
    ),
    "cash_flow_statement": (
        "every individual cash flow line item under operating/investing/"
        "financing activities"
    ),
}

# Document types where a comparative (prior-year) column is common and the
# spec requires validating each period independently. Invoices normally
# don't carry a comparative period, so they're excluded.
SUPPORTS_COMPARATIVE_PERIOD: set[str] = {"balance_sheet", "profit_and_loss", "cash_flow_statement"}

COMPARATIVE_PERIOD_HINT = (
    "If the document shows a comparative/prior-period column (e.g. "
    "\"Year ended March 31, 2023\" next to the current year), ALSO return "
    "a top-level array field 'comparative_periods'. Each element must be: "
    "{\"period_label\": <string, e.g. \"Year ended March 31, 2023\">, "
    "\"data\": { <same minimum-required field names as above, but as "
    "plain numbers/strings, NOT wrapped in value/page_number/source_text> "
    "}}. Omit 'comparative_periods' entirely if no comparative period is "
    "shown."
)
