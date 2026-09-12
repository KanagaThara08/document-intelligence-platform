FROM python:3.11-slim

# Tesseract (OCR) + Poppler (pdf2image's pdftoppm/pdftocairo) are required
# by backend/app/services/ocr_service.py and are NOT present in the base
# image or Render's native Python runtime — hence Docker deployment.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY frontend ./frontend

WORKDIR /app/backend

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
