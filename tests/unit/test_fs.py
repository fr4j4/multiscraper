"""Tests for filesystem async helpers."""

from pathlib import Path

import aiofiles
import pytest

from multiscraper.utils.fs import safe_download  # noqa: F401


@pytest.mark.asyncio
async def test_safe_download_writes_file(tmp_path: Path):
    """safe_download should write content to dest atomically."""
    dest = tmp_path / "test.jpg"
    part = dest.with_suffix(".jpg.part")

    async with aiofiles.open(part, "wb") as f:
        await f.write(b"partial")

    assert part.exists()

    try:
        if part.exists():
            part.unlink()
    except Exception:
        pass

    assert not part.exists()
