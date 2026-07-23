"""Tests for async rate limiter (token bucket)."""

import time

import pytest

from multiscraper.core.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_allows_burst():
    rl = RateLimiter(rate_per_sec=10.0, burst=3)
    start = time.monotonic()
    for _ in range(3):
        await rl.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_rate_limiter_throttles():
    rl = RateLimiter(rate_per_sec=5.0, burst=1)
    await rl.acquire()
    start = time.monotonic()
    await rl.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.15
