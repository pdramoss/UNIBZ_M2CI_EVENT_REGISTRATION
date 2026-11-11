FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/event_registration.sqlite3

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

COPY app/ ./app/
COPY scripts/ ./scripts/
COPY web/ ./web/

USER appuser

EXPOSE 5000 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
