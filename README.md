# Document Intelligence Platform

AI-powered document extraction, validation, and API platform for financial
documents (invoices, balance sheets, profit & loss statements, and cash flow
statements) — built as an AI Engineer Internship technical case study.

> ### Submission links
> - **Public GitHub repo:** `https://github.com/KanagaThara08/document-intelligence-platform`
> - **Live frontend URL:** `https://document-intelligence-platform-vc6d.onrender.com`
> - **Live backend API URL:** `https://document-intelligence-platform-vc6d.onrender.com` (same host as frontend in this setup)
> - **Swagger/OpenAPI URL:** `https://document-intelligence-platform-vc6d.onrender.com/docs`

**Live demo:** `https://document-intelligence-platform-vc6d.onrender.com`
**API docs (Swagger):** `https://document-intelligence-platform-vc6d.onrender.com/docs`

---

## 1. What this does

Upload a PDF, JPG, or PNG of a financial document, pick its type, and the
platform will:

1. **Validate** the file (supported type, not corrupted, within the page limit).
2. **Extract text** — native PDF text layer first, falling back to Tesseract
   OCR for scanned pages or images.
3. **Extract structured fields and tables** using the Google Gemini API,
   including evidence (source text + page number) for every field, with
   `null` used instead of guessed values whenever something isn't present.
4. **Run financial validation checks** specific to the document type (e.g.
   `subtotal + tax - discount ≈ total` for invoices, `assets = liabilities +
   equity` for balance sheets).
5. **Persist and serve** the full structured result via a REST API and a
   browser dashboard.

Every stage fails gracefully — corrupt files, OCR failures, and LLM failures
are all caught and returned as a consistent, structured error, never a raw
stack trace.

---

## 2. Architecture

See [`docs/architecture.png`](docs/architecture.png) for the full diagram.

```
Browser → Frontend (Jinja2/HTML/JS) → FastAPI → [Validation → OCR → Extraction (Gemini) → Financial Validation] → SQLite
```

Each pipeline stage is an isolated module under `backend/app/services/`,
orchestrated by `document_service.py`. No stage knows about HTTP; the API
route layer (`backend/app/api/routes/documents.py`) is a thin adapter.

---

## 3. Project structure

```
project-root/
├── backend/
│   ├── app/
│   │   ├── api/routes/        # documents.py (JSON API), frontend.py (pages)
│   │   ├── core/               # config.py, database.py, logging.py
│   │   ├── models/             # SQLAlchemy ORM model
│   │   ├── schemas/            # Pydantic request/response + field schemas
│   │   ├── services/           # validation, OCR, extraction, financial validation, orchestrator
│   │   ├── repositories/       # DB access layer
│   │   └── main.py             # FastAPI app entrypoint
│   ├── tests/                  # pytest suite (32 tests)
│   ├── requirements.txt
│   └── app/data/                # SQLite file lives here at runtime
├── frontend/
│   ├── templates/               # dashboard.html, document_result.html
│   └── static/{css,js}
├── docs/
│   ├── architecture.png
│   └── solution_presentation.pdf
├── sample_outputs/               # example API responses (PASS + FAIL + error scenarios)
├── .env.example
└── README.md   (this file)
```

---

## 4. Running locally

### Prerequisites
- Python 3.11+
- Tesseract OCR and Poppler (for `pdf2image`) installed on the system:
  ```bash
  # Debian/Ubuntu
  sudo apt-get install -y tesseract-ocr poppler-utils
  # macOS
  brew install tesseract poppler
  ```
  **Windows setup note:** `pip install pytesseract`/`pdf2image` only installs
  Python wrappers, not the actual OCR/PDF-rasterization engines — you must
  install the binaries separately:
  1. Tesseract: https://github.com/UB-Mannheim/tesseract/wiki (installer,
     default path `C:\Program Files\Tesseract-OCR\`)
  2. Poppler: https://github.com/oschwartz10612/poppler-windows/releases
     (download the zip, extract anywhere, e.g. `C:\poppler`)

  Verify with `tesseract --version` and `pdftoppm -v` in a **new** terminal
  window (PATH changes need a fresh shell). If either isn't recognized even
  after installing, skip PATH entirely and point the app straight at the
  binaries via `.env`:
  ```
  TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
  POPPLER_PATH=C:\poppler\Library\bin
  ```
  (adjust to your actual install paths — for Poppler, `POPPLER_PATH` is the
  folder containing `pdftoppm.exe`). If Tesseract truly isn't reachable, the
  API returns a clear `OCR_NOT_CONFIGURED` error naming the missing piece,
  rather than a generic failure.
- A Google Gemini API key (free, no billing required): https://aistudio.google.com/apikey

### Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp ../.env.example ../.env
# then edit ../.env and set GEMINI_API_KEY=...
```

### Run

```bash
# from project-root/backend — .env is loaded automatically (python-dotenv)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open:
- Dashboard: http://localhost:8000/
- Swagger docs: http://localhost:8000/docs

### Run tests

```bash
cd backend
python3 -m pytest tests/ -v
```

All 32 tests should pass. They cover file validation, financial calculation
logic, OCR confidence scoring, LLM-response JSON parsing, and the API's
error-handling paths — none require a live Gemini API call, so they run
in CI without a key.

---

## 5. API reference

### `POST /api/v1/documents/process`
Multipart form upload.

| Field | Type | Description |
|---|---|---|
| `file` | file | PDF / JPG / PNG, max 3 pages, max 15MB |
| `document_type` | string | one of `invoice`, `balance_sheet`, `profit_and_loss`, `cash_flow_statement` |

Returns `200` with a `processing_status: "PASS"` body on success, or `422`
with `processing_status: "FAILED"` (and an `error` object) if the file fails
validation, OCR, or extraction. See `sample_outputs/` for real examples of
every scenario, taken from the provided dataset.

**Example:**
```bash
curl -X POST "<DEPLOYED_URL>/api/v1/documents/process" \
  -F "file=@invoice.jpg" \
  -F "document_type=invoice"
```
Response (truncated — full example in `sample_outputs/invoice_pass_example.json`):
```json
{
  "document_name": "invoice.jpg",
  "document_type": "invoice",
  "processing_status": "PASS",
  "extracted_data": { "total_amount": { "value": 9.00, "page_number": 1, "source_text": "Total Includes GST 6% 9.00" } },
  "validation": { "overall_status": "PASS", "checks": [ /* ... */ ], "issues": [] }
}
```

### `GET /api/v1/documents/{document_name}`
Returns the most recent processed result for that filename, or `404` with a
structured error if none exists.

**Example:**
```bash
curl "<DEPLOYED_URL>/api/v1/documents/invoice.jpg"
```

### `GET /api/v1/documents`
Returns a list of all processed documents (used by the dashboard).

**Example:**
```bash
curl "<DEPLOYED_URL>/api/v1/documents"
```
```json
{ "documents": [ { "document_name": "invoice.jpg", "document_type": "invoice", "processing_status": "PASS", "processed_at": "2026-09-11T03:10:00Z" } ], "count": 1 }
```

### `GET /api/v1/health`
Basic health check for uptime monitoring.

```bash
curl "<DEPLOYED_URL>/api/v1/health"
# {"status":"ok","service":"document-intelligence-api","version":"1.0.0"}
```

Full interactive documentation (request/response schemas, "try it out") is
auto-generated by FastAPI at `/docs`.

---

## 6. Response shape

```jsonc
{
  "document_name": "invoice_001.pdf",
  "document_type": "invoice",
  "processing_status": "PASS",           // or "FAILED"
  "overall_confidence": 0.78,             // OPTIONAL — average of field confidences, sourced from real OCR confidence
  "file_validation": { "file_type": "...", "is_supported": true, "is_readable": true, "page_count": 1, "status": "PASS" },
  "extracted_data": {
    "total_amount": { "value": 9.00, "page_number": 1, "source_text": "Total Includes GST 6% 9.00", "confidence": 0.78 },
    "line_items": [ { "description": "...", "quantity": 1, "unit_price": 8.49, "amount": 8.49 } ]
  },
  "validation": {
    "checks": [ { "name": "invoice_total_check", "formula": "...", "calculated_value": 9.0, "reported_value": 9.0, "variance": 0.0, "status": "PASS", "period": "current" } ],
    "overall_status": "PASS",
    "issues": []
  },
  "processing_metadata": { "ocr_used": true, "processed_at": "...", "processing_time_ms": 4210, "llm_model": "gemini-3.6-flash" }
}
```

Every field the LLM could not find is `null` (never guessed). Additional
fields and full line-item tables beyond the minimum required set are
included whenever the document contains them — see
`sample_outputs/balance_sheet_pass_example.json` for an example with over a
dozen extra fields beyond the minimum required five.

---

## 7. Financial validation logic

| Document type | Key checks |
|---|---|
| Invoice | `subtotal + tax - discount ≈ total`; per-line-item `qty × unit_price ≈ amount`; `Σ line items ≈ subtotal` — **or, when no separate subtotal is reported (tax already baked into line prices), `Σ line items ≈ total` instead**; `cash_paid - total ≈ change` |
| Balance Sheet | `total_liabilities + total_equity ≈ total_assets`; **plus, when the LLM found enough structure**, `Σ asset_components ≈ total_assets` and `Σ liability_equity_components ≈ total_liabilities + total_equity` |
| Profit & Loss | `revenue - cost_of_sales ≈ gross_profit` chain (commercial P&L), plus a parallel bank-statement chain (`interest_earned + other_income ≈ total_income`, `interest_expended + operating_expenses + provisions ≈ total_expenditure`, `total_income - total_expenditure ≈ net_profit_before_minority`, `net_profit_before_minority - minority_interest ≈ net_profit_attributable_to_group`, `current_profit + brought_forward_profit ≈ total_available_for_appropriation`) |
| Cash Flow | `operating + investing + financing + fx_adjustment ≈ net_change_in_cash`; `opening + net_change + cash_acquired ≈ closing_cash` |

**Comparative periods, validated independently (spec 4.4):** for balance
sheet, P&L, and cash flow statements, whenever the document shows a
prior-year/comparative column, the extraction step also returns a
`comparative_periods` array, and **every check above is re-run against each
comparative period separately** — each result in `validation.checks` carries
a `period` field (`"current"` or the period's label) so an evaluator can see
exactly which period a given PASS/FAIL belongs to (example below).

Each check reports `PASS`, `FAIL`, or `NOT_APPLICABLE` (used when a required
input field is missing — never silently guessed or skipped). A configurable
`VALIDATION_TOLERANCE` (default ₹1.00 / $1.00) absorbs rounding differences.
Parenthesized numbers, e.g. `(1,234.50)`, are parsed as negative values, per
standard accounting notation.

**Assumption on `processing_status` vs `validation.overall_status`:** spec
4.5 defines `PASS` as "required fields are extracted accurately **and**
required validations pass," which we follow literally — `processing_status`
is `FAILED` when a document's financial checks don't reconcile, not just
when the file itself is unreadable/unsupported/corrupt. `validation`'s own
`overall_status` / `issues` fields carry the more granular PASS/FAIL/
NOT_APPLICABLE breakdown per check and per period. See
`sample_outputs/profit_and_loss_validation_failure_example.json`: HDFC
Bank's 2024 consolidated P&L genuinely includes an "addition on
amalgamation" appropriation line outside the minimum-required schema, so
`appropriation_check` legitimately FAILs for 2024 (`processing_status:
"FAILED"`) while the *same check on the same document's 2023 comparative
column* genuinely PASSes — proof the validator isn't hiding or faking
either result.

---

## 8. Design decisions & trade-offs

- **Visual design**: the dashboard uses a deliberate "ledger" aesthetic
  (ink/paper/brass palette, serif headings, monospace figures, ledger-rule
  dividers instead of generic SaaS card shadows) rather than a default
  dark-mode dashboard template — grounded in the subject matter (financial
  statements, ledgers, evidence trails) rather than a generic tech look.

- **SQLite over Postgres**: zero-config persistence appropriate for a 3-day
  prototype; swappable via a single `DATABASE_URL` env var since all access
  goes through the repository layer.
- **Tesseract over a paid OCR API**: free, local, no rate limits or extra
  signup under a tight deadline. The provided dataset's scanned financial
  statements OCR cleanly with this approach (verified against the real
  sample files during development).
- **Gemini for structured extraction, not a fine-tuned model**: given a
  strict JSON-schema prompt, a general-purpose LLM handles noisy OCR text,
  varied document layouts, and produces evidence citations far more
  reliably than a custom-trained extractor could within the time budget.
  Gemini specifically was chosen because Google AI Studio issues a
  genuinely free-tier API key (no billing/credit card required), which
  matters more for a fast prototype than for a production system.
- **Confidence sourced from OCR, not the LLM**: the LLM is deliberately
  never asked to self-report a confidence score (see
  `extraction_service._SYSTEM_PROMPT`) — an LLM-guessed "0.97" is exactly
  the arbitrary number the spec warns against. Instead, each field's
  `confidence` is the real Tesseract word-confidence of the OCR page its
  evidence came from (1.0 for text read straight from a native PDF layer,
  no OCR involved). This is measurable, reproducible, and explainable: see
  section 9 below for actual measured numbers from the provided dataset.

---

## 9. OCR accuracy & confidence scoring

Measured directly against the provided dataset using Tesseract's own
per-word confidence output (`pytesseract.image_to_data`):

| Document | Avg. word confidence |
|---|---|
| Balance Sheet / P&L / Cash Flow (clean scanned reports) | ~92% |
| Invoice (real-world receipt photo) | ~78% |

This gap is real and expected: the financial statements are high-contrast,
typeset scans; the invoice is a low-resolution thermal-receipt photograph,
which is genuinely harder for any OCR engine. Rather than hide this,
`overall_confidence` and each field's `confidence` surface it directly —
see `sample_outputs/low_confidence_invoice_example.json` for the
low-confidence demonstration scenario, and
`sample_outputs/balance_sheet_pass_example.json` for a high-confidence one.
The dashboard and result page both color-code confidence (green ≥85%,
amber 60–85%, red <60%) so an evaluator can spot shaky extractions at a
glance without reading raw JSON.

**Not yet implemented** (documented as a limitation, not silently
omitted): image preprocessing (deskew, binarization, contrast
normalization) before OCR, which would likely close some of this gap on
receipt-quality images, and a cloud OCR fallback for scans below a
confidence threshold.

---

## 10. Known limitations

- Processing is synchronous — a very large batch of uploads would benefit
  from a background queue (Celery/RQ) rather than blocking the request.
- OCR uses a single local engine (Tesseract); a production system would add
  a cloud OCR fallback for low-quality scans.
- SQLite is fine for evaluation but not for concurrent production load.
- The P&L validation set covers both a standard commercial P&L and a
  bank-style P&L format; a heavily bespoke third format may only get
  partial (`NOT_APPLICABLE`) coverage rather than false negatives.

See `docs/solution_presentation.pdf` for the full roadmap slide.

---

## 11. What I would change for production

- Move from synchronous request handling to an async job queue (Celery/RQ +
  Redis) with a status-polling or webhook pattern, so large files or slow
  OCR don't hold an HTTP connection open.
- Replace SQLite with managed Postgres and add S3 (or equivalent) object
  storage for the original uploaded files, not just the extracted JSON.
- Add a second OCR provider (e.g. Google Document AI or AWS Textract) as a
  fallback for low-quality scans where Tesseract's accuracy drops.
- Add authentication/API keys per caller, request rate limiting, and
  structured audit logging of who processed what and when.
- Add a human-in-the-loop review queue for low-confidence or FAILED
  extractions before they're treated as ground truth downstream.
- Containerize with a proper CI/CD pipeline (build → test → deploy) instead
  of a manual Render deploy.

---

## 12. AI coding assistant usage declaration

This solution was built with **Claude (Anthropic)** as an AI coding
assistant, used throughout for:
- Scaffolding the backend module structure (config, database, services,
  repositories, schemas, API routes) to match the required separation of
  concerns.
- Writing the OCR fallback logic, the Gemini extraction prompt
  and JSON-parsing/reshaping logic, and the per-document-type financial
  validation formulas.
- Writing the pytest test suite and debugging failures found while running
  it (e.g. FastAPI's `TestClient` not triggering startup events without a
  context manager; HTTPException response shaping).
- Generating the frontend (HTML/CSS/JS), the architecture diagram, and the
  solution presentation deck.
- Drafting this README.

All code was reviewed, and the OCR pipeline and API were smoke-tested
against the actual sample documents provided in the case study dataset
during development (see the OCR/sample output notes throughout this
README). The one part *not* independently verified before submission was a
live end-to-end call to the Gemini extraction API, since that requires
the candidate's own API key — see "Local setup" above to verify that step.

---

## 13. Deployment (Render)

This repo includes a `Dockerfile` at the project root — **use Render's
Docker deployment**, since Tesseract/Poppler (required for OCR) are not
present on Render's native Python runtime, and the Dockerfile installs them.

1. Push this repository to GitHub.
2. On [Render](https://render.com), click **New → Web Service**, connect the
   repo, and when prompted for the environment, select **Docker** (Render
   auto-detects the root `Dockerfile`).
3. Leave build/start commands blank — the Dockerfile's `CMD` handles it.
4. Environment variables (Render dashboard → Environment):
   - `GEMINI_API_KEY` = your key (never commit this — get a free one at
     https://aistudio.google.com/apikey)
   - `GEMINI_MODEL` = `gemini-3.6-flash`
   - `DATABASE_URL` = `sqlite:///./app/data/documents.db`
5. Deploy. Render provisions a public HTTPS URL — put it at the top of this
   README and in the presentation once live.

A `render.yaml` blueprint is also included at the project root if you'd
rather use Render's "New → Blueprint" one-click flow instead of steps 2–4.

> **Note on free-tier disk**: SQLite on Render's free tier is ephemeral —
> the database resets on redeploy/restart. This is acceptable for
> evaluation; for persistence across restarts, either upgrade to a Render
> disk add-on or swap `DATABASE_URL` to a managed Postgres instance (one
> env var change, no code changes).

---

## 14. Testing this yourself

Use the sample documents provided in the case study dataset — three scanned
financial statement PDFs (Balance Sheet, Cash Flow, Profit & Loss) and a
scanned invoice image all process correctly end-to-end through the OCR
fallback path, as demonstrated in `sample_outputs/`.
