FROM python:3.14-slim AS base

WORKDIR /app

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY config.yml ./config.yml
COPY app ./app
COPY models ./models
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

RUN useradd --create-home --uid 1000 appuser \
 && chown -R appuser:appuser /app
USER appuser

FROM base AS api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM base AS worker
CMD ["python", "-m", "app.worker"]

FROM base AS migration
CMD ["alembic", "upgrade", "head"]
