"""Local filesystem transport."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from multiscraper.transport.base import FileInfo
from multiscraper.utils.hash import compute_crc32, compute_sha1


class LocalTransport:
    """Transport for reading ROMs from the local filesystem."""

    async def list_dir(self, path: str) -> list[str]:
        entries = os.listdir(path)
        return [
            e for e in entries
            if os.path.isfile(os.path.join(path, e))
        ]

    async def file_info(self, path: str) -> FileInfo:
        stat = os.stat(path)
        return FileInfo(
            path=path,
            size=stat.st_size,
            mtime=int(stat.st_mtime),
            is_file=os.path.isfile(path),
            is_dir=os.path.isdir(path),
        )

    async def hash(self, path: str, algo: Literal["crc32", "sha1"]) -> str:
        loop = asyncio.get_event_loop()
        if algo == "crc32":
            return await loop.run_in_executor(None, self._hash_sync, path, "crc32")
        elif algo == "sha1":
            return await loop.run_in_executor(None, self._hash_sync, path, "sha1")
        raise ValueError(f"Unknown hash algo: {algo}")

    def _hash_sync(self, path: str, algo: str) -> str:
        with open(path, "rb") as f:
            data = f.read()
        if algo == "crc32":
            return compute_crc32(data)
        return compute_sha1(data)

    async def open_read(self, path: str, max_bytes: int | None = None) -> AsyncIterator[bytes]:
        remaining = max_bytes
        with open(path, "rb") as f:
            while True:
                chunk_size = min(64 * 1024, remaining) if remaining else 64 * 1024
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break

    async def path_exists(self, path: str) -> bool:
        """Return True if path exists and is a directory."""
        return Path(path).expanduser().is_dir()

    async def close(self) -> None:
        pass
