"""Graceful shutdown handler for SIGTERM/SIGINT."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

logger = logging.getLogger(__name__)


class ShutdownHandler:
    """Manages graceful shutdown via SIGTERM/SIGINT."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._sigint_count = 0

    def install(self, loop: asyncio.AbstractEventLoop) -> None:
        """Install signal handlers."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handler, sig)

    def _handler(self, sig: signal.Signals) -> None:
        self._sigint_count += 1
        if self._sigint_count >= 2:
            logger.warning("force_shutdown signal=%s (second press)", sig.name)
            self._event.set()
            loop = asyncio.get_event_loop()
            loop.stop()
        else:
            logger.info("shutdown_initiated signal=%s", sig.name)
            self._event.set()

    @property
    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self, timeout: float | None = None) -> None:
        if timeout is None:
            await self._event.wait()
        else:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._event.wait(), timeout=timeout)

    def clear(self) -> None:
        self._event.clear()
        self._sigint_count = 0
