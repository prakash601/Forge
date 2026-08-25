# Forge execution worker image
#
# Builds a slim image that runs the worker skeleton. Phase 0 only starts,
# logs, and shuts down; the image intentionally does NOT include
# docker-in-docker or any sandbox capabilities.

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

COPY --chown=forge:forge workers/execution/ /app/workers/execution/

USER forge
RUN uv sync --project /app/workers/execution --no-dev

WORKDIR /app/workers/execution
CMD ["python", "-m", "forge_worker"]
