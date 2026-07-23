"""HTTP session helpers for multiscraper."""

from __future__ import annotations

import aiohttp


def create_http_session(
    *,
    timeout: float = 30.0,
    user_agent: str = "multiscraper/0.1.0",
) -> aiohttp.ClientSession:
    """Create an aiohttp ClientSession with sensible defaults.

    Args:
        timeout: request timeout in seconds.
        user_agent: User-Agent header.

    Returns:
        An aiohttp.ClientSession ready for provider requests.
    """
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    return aiohttp.ClientSession(
        timeout=timeout_cfg,
        headers={"User-Agent": user_agent},
    )
