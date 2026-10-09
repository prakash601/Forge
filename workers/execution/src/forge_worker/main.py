"""Execution worker process.

Phase 0 responsibilities:

1. Load configuration.
2. Initialize structured logging.
3. Print `Forge worker started`.
4. Reap orphaned sandbox containers left by a crashed run (docker
   backend only; best-effort).
5. Wait for `SIGINT` / `SIGTERM`.
6. Shut down gracefully and exit 0.

The worker deliberately does NOT:

- Execute arbitrary shell commands.
- Talk to a database.
- Poll a queue.
- Run agents.

Those capabilities land in Phase 5 (Execution Worker + Docker Sandbox).
Phase 5 job-loop contract (Issue #84 — design, not implementation):

- One run per job, idempotent on `(run_id, command_counter)`: a
  retried command reuses the recorded artifact instead of re-running.
- Graceful drain on SIGTERM: finish the in-flight command (up to its
  timeout), checkpoint, then exit — never abandon mid-write.
- Retry/backoff on transient failures (image pull, daemon busy);
  permanent failures (quota, OOM, timeout) are terminal results,
  not retries.
- Orphan cleanup: containers are named `forge-<run_id>-<NNNN>` so a
  fresh worker can reap crash leftovers at startup (see
  :func:`_reap_stale_sandbox_containers`); in-flight cleanup stays on
  the timeout path.
- Budgets in `config.py` (`run_max_seconds`, `run_max_commands`) are
  enforced by the loop, not by the executors.
"""

from __future__ import annotations

import asyncio
import re
import signal
import sys
from types import FrameType

from forge_worker.config import Settings, get_settings
from forge_worker.logging import configure_logging, get_logger

log = get_logger(__name__)

# Container names minted per command (`forge-<run_id>-<NNNN>`); the
# worker's own containers never match, so reaping this pattern at
# startup cannot remove the worker itself.
_ORPHAN_CONTAINER_RE = re.compile(r"^forge-[0-9a-fA-F-]{36}-\d{4}$")


async def _reap_stale_sandbox_containers() -> int:
    """Remove crash-orphaned `forge-<run_id>-<NNNN>` containers.

    Best-effort: any failure (no daemon, no permission) is logged and
    yields 0. Returns the count removed.
    """
    try:
        import docker
    except ImportError:
        return 0
    try:
        client = await asyncio.to_thread(docker.from_env, timeout=10)
        containers = await asyncio.to_thread(client.containers.list, all=True)
        removed = 0
        for container in containers:
            if _ORPHAN_CONTAINER_RE.match(container.name or ""):
                await asyncio.to_thread(container.remove, force=True)
                removed += 1
        if removed:
            log.info("worker_orphans_reaped", count=removed)
        return removed
    except Exception as exc:
        log.warning("worker_orphan_reap_failed", error=str(exc))
        return 0


class Worker:
    """Lifecycle owner for the worker process.

    A `Worker` instance:

    - Configures logging from settings.
    - Logs the `worker_started` event.
    - Waits for a shutdown signal.
    - Logs the `worker_stopped` event.

    The actual job loop is introduced in Phase 5.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._shutdown_event = asyncio.Event()

    @property
    def settings(self) -> Settings:
        return self._settings

    def request_shutdown(self) -> None:
        """Signal the worker to begin graceful shutdown.

        Safe to call from signal handlers (sync context).
        """
        if not self._shutdown_event.is_set():
            log.info("worker_shutdown_requested")
            self._shutdown_event.set()

    def _install_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        def _loop_handler(signum: int) -> None:
            log.info("worker_signal_received", signal=signal.Signals(signum).name)
            self.request_shutdown()

        def _signal_handler(signum: int, _frame: FrameType | None) -> None:
            _loop_handler(signum)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _loop_handler, sig)
            except NotImplementedError:
                # Windows or other environments without add_signal_handler.
                signal.signal(sig, _signal_handler)

    async def run(self) -> int:
        """Run the worker until a shutdown signal is received.

        Returns the process exit code.
        """
        configure_logging(self._settings)
        # The plain-text "Forge worker started" line is the contract that
        # operators rely on when reading the container's stdout. It uses
        # a `print` so it shows up consistently across log configurations.
        print("Forge worker started", flush=True)
        log.info(
            "worker_started",
            worker_name=self._settings.worker_name,
            environment=self._settings.environment,
        )

        loop = asyncio.get_running_loop()
        self._install_signal_handlers(loop)

        if self._settings.sandbox_backend == "docker":
            await _reap_stale_sandbox_containers()

        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            log.info("worker_cancelled")
            self.request_shutdown()
        finally:
            log.info("worker_stopped", worker_name=self._settings.worker_name)

        return 0


def run() -> int:
    """Entry point used by the `forge-worker` console script."""
    try:
        return asyncio.run(Worker().run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(run())
