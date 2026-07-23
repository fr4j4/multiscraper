"""Async token bucket rate limiter."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token bucket rate limiter for async use."""

    def __init__(self, rate_per_sec: float, burst: int = 1):
        self._rate = rate_per_sec
        self._capacity = max(1, burst)
        self._tokens = float(self._capacity)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire one token, waiting if necessary."""
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self._capacity,
                self._tokens + (now - self._last) * self._rate,
            )
            self._last = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1
