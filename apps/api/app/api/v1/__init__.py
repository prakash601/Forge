"""Versioned v1 router.

Phase 0 mounts an empty router so the URL prefix `/api/v1` is reserved and
clients can rely on the API surface existing. Application routes (projects,
repositories, tasks, runs, ...) are introduced in Phase 1+.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
