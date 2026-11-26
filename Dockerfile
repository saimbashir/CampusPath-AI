FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# Free OCR tools: tesseract reads images, pdftoppm (poppler) turns scanned PDF pages into images.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install -r requirements.lock.txt
COPY . .
RUN useradd -m campus && mkdir -p /data && chown -R campus:campus /app /data
USER campus
# Local Docker default. Hosted deployments set DATABASE_URL to PostgreSQL instead.
ENV DATABASE_URL=sqlite:////data/campuspath.db
# Hosts such as Render inject PORT. --proxy-headers + --forwarded-allow-ips make the app
# see the real https:// address behind the host's proxy (needed by the origin check).
EXPOSE 8000
CMD ["sh", "-c", "python -m alembic upgrade head && exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --workers 1"]
