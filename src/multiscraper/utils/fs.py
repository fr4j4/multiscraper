"""Async filesystem helpers for media downloads.

Downloads are atomic: data is written to a .part file first,
then atomically moved to the final destination. If the download
is interrupted (CancelledError, network error), the .part file
is cleaned up so no partial data remains.
"""

from __future__ import annotations

from pathlib import Path

import aiofiles
import aiofiles.os as aios
from aiohttp import ClientSession


async def safe_download(url: str, dest: Path, session: ClientSession) -> bool:
    """Download a file atomically.

    Writes to <dest>.part first, then moves to <dest> on success.
    Cleans up .part on any error.

    Args:
        url: URL to download.
        dest: Final destination path.
        session: aiohttp ClientSession.

    Returns:
        True if download succeeded, False if the file was not modified.

    Raises:
        Exception on download failure (after cleanup).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        async with session.get(url) as resp:
            resp.raise_for_status()
            async with aiofiles.open(part, "wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    await f.write(chunk)
        await aios.replace(part, dest)
        return True
    except BaseException:
        if part.exists():
            part.unlink(missing_ok=True)
        raise
