# The events service's image. Built from the repository root so it can reach
# common/, but it copies only common/ and its own folder: nothing from the other
# two services, and nothing from the web interface.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/event_registration.sqlite3

WORKDIR /workspace

# The layout under /workspace mirrors the repository, so the relative -r in the
# service's requirements file resolves and 'services.events.main' imports.
COPY common/requirements.txt ./common/requirements.txt
COPY services/events/requirements.txt ./services/events/requirements.txt
RUN pip install --no-cache-dir -r services/events/requirements.txt \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

COPY common/ ./common/
COPY services/events/ ./services/events/

USER appuser

EXPOSE 8000

CMD ["uvicorn", "services.events.main:app", "--host", "0.0.0.0", "--port", "8000"]
