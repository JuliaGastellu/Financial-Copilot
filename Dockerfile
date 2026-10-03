FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY app/ ./app/
COPY scripts/ ./scripts/
COPY alembic.ini ./alembic.ini
COPY migrations/ ./migrations/

RUN mkdir -p /app/data

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Uso un solo proceso: el índice Chroma local no admite varios procesos escribiendo a la vez.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
