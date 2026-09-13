# Forge execution worker image
#
# Runs the worker skeleton (Phase 0: start, log, shut down). The image
# does NOT embed a Docker daemon: sandboxing talks to the host daemon
# over a mounted socket (deploy concern, Phase 4 #019). The `docker`
# Python client ships via uv sync; no docker-in-docker involved.

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
