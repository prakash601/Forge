# Forge API image
#
# Builds a slim image that runs the FastAPI application.
#
# This Dockerfile uses `uv` (https://docs.astral.sh/uv/) for fast and
# reproducible Python dependency installation.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

RUN pip install --no-cache-dir uv==0.4.18 \
    && groupadd --system --gid 1000 forge \
    && useradd --system --uid 1000 --gid forge --home /app forge

WORKDIR /app

# Copy API project metadata and source
COPY --chown=forge:forge apps/api/ /app/apps/api/
COPY --chown=forge:forge db/ /app/db/

USER forge
RUN uv sync --project /app/apps/api --no-dev

WORKDIR /app/apps/api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
