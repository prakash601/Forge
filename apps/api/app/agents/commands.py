"""Allowlisted command execution for the Tester (Issue #009).

Only pytest runs, confined to the run workspace with a scrubbed
environment and a hard timeout. Anything else is denied — the Tester
reasons about failures but never gets a general shell (TOOL_CONTRACTS
§9: Tester has run_command, not arbitrary execution).

Full output streams are capped in memory; Phase 2 has no artifact
store yet (LLD §15 arrives with the sandbox), so callers keep the
parsed summary, not the raw logs.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.errors import AgentError

_SCRUB_EXACT = frozenset({"DATABASE_URL"})
_SCRUB_PREFIXES = ("GITHUB_", "OPENAI_", "FORGE_")

_SUMMARY_RE = re.compile(r"(\d+)\s+(passed|failed|skipped|error|xfailed|xpassed)\b")
_MAX_OUTPUT_CHARS = 20_000


@dataclass
class PytestOutcome:
    """Parsed result of one pytest invocation."""

    exit_code: int
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[str] = field(default_factory=list)
    output: str = ""


def scrub_env() -> dict[str, str]:
    """Copy ``os.environ`` minus secret-bearing keys."""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in _SCRUB_EXACT and not key.startswith(_SCRUB_PREFIXES)
    }


def resolve_pytest_argv(command: str) -> list[str]:
    """Resolve a proposed command to a pytest invocation or deny it.

    Accepts ``pytest ...`` and ``python -m pytest ...`` (the latter
    pinned to this interpreter so the fixture's dependencies resolve).
    Anything else raises :class:`AgentError`.
    """
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise AgentError(f"command denied (unparseable): {command!r}") from exc
    if not argv:
        raise AgentError("command denied (empty)")
    program = Path(argv[0]).name
    if program == "pytest":
        return [sys.executable, "-m", "pytest", *argv[1:]]
    if program in {"python", "python3"} and argv[1:2] == ["-m"] and argv[2:3] == ["pytest"]:
        return [sys.executable, *argv[1:]]
    raise AgentError(f"command denied (tester runs pytest only): {command!r}")


def run_pytest(workspace: Path, command: str, timeout_seconds: float = 120.0) -> PytestOutcome:
    """Run one allowlisted pytest command in ``workspace`` and parse it.

    Exit 0 → tests passed; exit 1 → tests failed. Any other exit, a
    timeout, or a startup failure raises :class:`AgentError` (an
    infrastructure failure, not a test failure).
    """
    argv = resolve_pytest_argv(command)
    try:
        proc = subprocess.run(  # noqa: S603
            argv,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=scrub_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentError(f"pytest timed out after {timeout_seconds}s") from exc
    except OSError as exc:
        raise AgentError(f"pytest failed to start: {exc}") from exc
    output = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-_MAX_OUTPUT_CHARS:]
    if proc.returncode == 0:
        passed, failed, skipped = _parse_counts(output)
        outcome = PytestOutcome(
            exit_code=0, passed=passed, failed=failed, skipped=skipped, output=output
        )
        return outcome
    if proc.returncode == 1:
        passed, failed, skipped = _parse_counts(output)
        return PytestOutcome(
            exit_code=1,
            passed=passed,
            failed=failed,
            skipped=skipped,
            failures=_parse_failures(output),
            output=output,
        )
    raise AgentError(f"pytest exited with code {proc.returncode} (infrastructure failure)")


def _parse_counts(output: str) -> tuple[int, int, int]:
    passed = failed = skipped = 0
    for line in output.splitlines()[-8:]:
        for count, kind in _SUMMARY_RE.findall(line):
            if kind == "passed":
                passed += int(count)
            elif kind == "failed" or kind == "error":
                failed += int(count)
            elif kind == "skipped":
                skipped += int(count)
    return passed, failed, skipped


def _parse_failures(output: str) -> list[str]:
    failures: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("FAILED ") or stripped.startswith("ERROR "):
            failures.append(stripped.split(None, 1)[1][:300])
    return failures


__all__ = ["PytestOutcome", "resolve_pytest_argv", "run_pytest", "scrub_env"]
