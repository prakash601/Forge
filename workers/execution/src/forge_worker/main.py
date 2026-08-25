"""Execution worker process.

Phase 0 responsibilities:

1. Load configuration.
2. Initialize structured logging.
3. Print `Forge worker started`.
4. Wait for `SIGINT` / `SIGTERM`.
5. Shut down gracefully and exit 0.

The worker deliberately does NOT:

- Execute arbitrary shell commands.
- Talk to a database.
- Poll a queue.
- Run agents.

Those capabilities land in Phase 5 (Execution Worker + Docker Sandbox).
"""

from __future__ import annotations

import asyncio
import signal
import sys
from types import FrameType

from forge_worker.config import Settings, get_settings
from forge_worker.logging import configure_logging, get_logger

log = get_logger(__name__)


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
