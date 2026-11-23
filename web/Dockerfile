# The web interface's image. It holds no backend code and no database driver:
# the UI reaches the API only over HTTP through the gateway, so it needs neither
# common/ nor any service folder.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

COPY web/requirements.txt ./web/requirements.txt
RUN pip install --no-cache-dir -r web/requirements.txt \
    && useradd --create-home --uid 10001 appuser

COPY web/ ./web/

USER appuser

EXPOSE 5000

CMD ["waitress-serve", "--listen=0.0.0.0:5000", "web.app:app"]
