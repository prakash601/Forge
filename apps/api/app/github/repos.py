"""Backend git helpers for repo-backed runs (Phase 4, Issue #018).

Only backend code (API endpoints, the publisher) calls into this
module — never agent or sandbox code. The credential travels
in-memory: it is passed to exactly one ``git`` subprocess via
``-c http.extraHeader`` (never in the URL, never on disk, never in
logs). ``GIT_TERMINAL_PROMPT=0`` guards against credential-prompt
hangs.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

from app.github.errors import GitOperationError, InvalidRepoURLError

_OWNER_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+")
_TASK_SLUG_RE = re.compile(r"[^a-z0-9]+")
_GIT_TIMEOUT_SECONDS = 120.0


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    """Parse ``https://github.com/<owner>/<repo>[.git]`` → ``(owner, repo)``.

    Rejects SSH URLs, other hosts, embedded credentials (``@`` in the
    authority), and malformed paths. Raises
    :class:`InvalidRepoURLError`.
    """
    parsed = urlparse(repo_url.strip())
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise InvalidRepoURLError(f"Not a github.com HTTPS URL: {repo_url!r}.")
    if "@" in (parsed.netloc or ""):
        raise InvalidRepoURLError("Credential-embedded URLs are not accepted.")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 2:
        raise InvalidRepoURLError(f"Expected /<owner>/<repo>: {repo_url!r}.")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    # Reject dot-segments explicitly (urlparse does not normalize them).
    if (
        not owner
        or not repo
        or owner in (".", "..")
        or repo in (".", "..")
        or not _OWNER_REPO_RE.fullmatch(owner)
        or not _OWNER_REPO_RE.fullmatch(repo)
    ):
        raise InvalidRepoURLError(f"Invalid owner/repo: {repo_url!r}.")
    return owner, repo


def task_branch_name(task: str, run_id: uuid.UUID) -> str:
    """Build ``forge/<task-slug>-<run-short>`` (never the default branch)."""
    slug = _TASK_SLUG_RE.sub("-", task.lower()).strip("-")[:30].strip("-")
    return f"forge/{slug or 'task'}-{str(run_id)[:8]}"


def _auth_header(credential: str) -> str:
    """Basic auth header value for ``x-access-token`` (in-memory only)."""
    raw = f"x-access-token:{credential}".encode()
    return f"AUTHORIZATION: basic {base64.b64encode(raw).decode('ascii')}"


def _redacted(message: str) -> str:
    """Cap subprocess output for errors (never contains credentials)."""
    return message.strip()[:500]


async def _git(
    *args: str,
    cwd: Path,
    credential: str,
    timeout_seconds: float = _GIT_TIMEOUT_SECONDS,
) -> str:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            f"http.extraHeader={_auth_header(credential)}",
            *args,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        raise GitOperationError(f"git executable unavailable: {exc}") from exc
    try:
        async with asyncio.timeout(timeout_seconds):
            stdout, stderr = await proc.communicate()
    except TimeoutError:
        proc.kill()
        raise GitOperationError("git operation timed out") from None
    if proc.returncode != 0:
        detail = _redacted(stderr.decode("utf-8", errors="replace"))
        raise GitOperationError(detail or f"git exited with code {proc.returncode}")
    return stdout.decode("utf-8", errors="replace")


def _looks_like_auth_failure(detail: str) -> bool:
    lowered = detail.lower()
    return (
        "authentication failed" in lowered
        or "could not authenticate" in lowered
        or "401" in lowered
        or "403" in lowered
    )


def _prepare_dest(dest: Path) -> None:
    """Fail if occupied; otherwise create parents (blocking syscalls)."""
    if dest.exists():
        raise GitOperationError(f"destination exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)


async def clone_repo(
    *,
    repo_url: str,
    dest: Path,
    branch: str,
    default_branch: str,
    credential: str,
    timeout_seconds: float = _GIT_TIMEOUT_SECONDS,
) -> str:
    """Clone ``repo_url`` (depth 1) and check out ``branch``.

    Returns the base commit SHA. Raises :class:`GitOperationError`
    (use :func:`is_auth_failure` to distinguish credential problems).
    """
    parse_repo_url(repo_url)  # validate before touching disk
    await asyncio.to_thread(_prepare_dest, dest)
    try:
        await _git(
            "clone",
            "--depth",
            "1",
            "--branch",
            default_branch,
            "--",
            repo_url,
            str(dest),
            cwd=dest.parent,
            credential=credential,
            timeout_seconds=timeout_seconds,
        )
    except GitOperationError as exc:
        raise GitOperationError(f"clone failed: {exc}") from exc
    await _git("checkout", "-b", branch, cwd=dest, credential=credential)
    base_commit = (await _git("rev-parse", "HEAD", cwd=dest, credential=credential)).strip()
    return base_commit


async def push_branch(
    *,
    repo_dir: Path,
    branch: str,
    default_branch: str,
    credential: str,
    timeout_seconds: float = _GIT_TIMEOUT_SECONDS,
) -> None:
    """Push ``branch`` to origin (never the default branch, never ``--force``)."""
    if branch == default_branch:
        raise GitOperationError(f"refusing to push to the default branch {default_branch!r}")
    try:
        await _git(
            "push",
            "origin",
            branch,
            cwd=repo_dir,
            credential=credential,
            timeout_seconds=timeout_seconds,
        )
    except GitOperationError as exc:
        raise GitOperationError(f"push failed: {exc}") from exc


async def head_commit(*, repo_dir: Path, credential: str) -> str:
    """Current HEAD SHA of the workspace clone."""
    return (await _git("rev-parse", "HEAD", cwd=repo_dir, credential=credential)).strip()


def is_auth_failure(error: GitOperationError) -> bool:
    """Whether a git failure looks like rejected credentials."""
    return _looks_like_auth_failure(str(error))


__all__ = [
    "clone_repo",
    "head_commit",
    "is_auth_failure",
    "parse_repo_url",
    "push_branch",
    "task_branch_name",
]
