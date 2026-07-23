"""Tests for retry with exponential backoff."""

from unittest.mock import AsyncMock

import pytest

from multiscraper.utils.retry import retry_async


@pytest.mark.asyncio
async def test_retry_succeeds_first_attempt():
    func = AsyncMock(return_value="ok")
    result = await retry_async(func, max_attempts=3, base_delay=0.01)
    assert result == "ok"
    assert func.call_count == 1


@pytest.mark.asyncio
async def test_retry_succeeds_after_failure():
    func = AsyncMock(side_effect=[ValueError("fail"), "ok"])
    result = await retry_async(func, max_attempts=3, base_delay=0.01)
    assert result == "ok"
    assert func.call_count == 2


@pytest.mark.asyncio
async def test_retry_exhausts_attempts():
    func = AsyncMock(side_effect=ValueError("always fail"))
    with pytest.raises(ValueError, match="always fail"):
        await retry_async(func, max_attempts=3, base_delay=0.01)
    assert func.call_count == 3


@pytest.mark.asyncio
async def test_retry_does_not_retry_on_specific_exception():
    func = AsyncMock(side_effect=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        await retry_async(func, max_attempts=3, base_delay=0.01, no_retry=(KeyboardInterrupt,))
    assert func.call_count == 1
