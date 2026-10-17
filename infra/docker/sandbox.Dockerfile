# Sandbox image for Forge command execution (Phase 4, Issue #017).
#
# Build from the repo root so the fixture requirements are in context:
#   docker build -f infra/docker/sandbox.Dockerfile -t forge-sandbox:0.1.0 .
#
# The image carries the pinned test runtime (pytest + fixture deps) and
# runs as non-root `forge`. Containers start with `--network none`,
# a read-only rootfs, and the run workspace mounted at /workspace, so
# the image itself needs no credentials, secrets, or network access.
# Pinned by digest (supply chain, #017); refresh deliberately, not by rebuild.
FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

COPY fixtures/todo-app/requirements.txt /opt/forge/requirements.txt
RUN pip install --no-cache-dir -r /opt/forge/requirements.txt \
    && rm -rf /root/.cache/pip \
    && useradd --create-home --uid 1000 forge

# Writable HOME for caches (mounted as tmpfs at runtime); bytecode off
# (read-only rootfs) and unbuffered output for faithful log capture.
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 1000:1000
WORKDIR /workspace
