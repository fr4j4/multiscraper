"""Retry utility with exponential backoff and jitter."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 2.0,
    jitter: bool = True,
    no_retry: tuple[type[BaseException], ...] = (),
) -> T:
    """Call func with exponential backoff retry.

    Args:
        func: async callable to call.
        max_attempts: maximum number of attempts.
        base_delay: base delay in seconds; delay = base_delay ** attempt.
        jitter: if True, add random jitter to delay.
        no_retry: exception types that should NOT be retried.

    Returns:
        The result of func on success.

    Raises:
        The last exception raised by func after all attempts are exhausted.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await func()
        except no_retry:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = base_delay**attempt
                if jitter:
                    delay *= random.uniform(0.5, 1.5)
                await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
