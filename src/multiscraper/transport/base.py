"""Transport Protocol for reading ROMs from local or remote sources."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel


class FileInfo(BaseModel):
    """File metadata from a transport."""

    path: str
    size: int
    mtime: int
    is_file: bool
    is_dir: bool = False


@runtime_checkable
class RomTransport(Protocol):
    """Interface for reading ROMs from a filesystem (local or SSH)."""

    async def list_dir(self, path: str) -> list[str]:
        """List files in a directory (non-recursive)."""
        ...

    async def file_info(self, path: str) -> FileInfo:
        """Get metadata for a single file."""
        ...

    async def hash(self, path: str, algo: Literal["crc32", "sha1"]) -> str:
        """Compute hash of a file (reads file in streaming mode)."""
        ...

    async def open_read(self, path: str, max_bytes: int | None = None) -> AsyncIterator[bytes]:
        """Stream-read a file, optionally limited to max_bytes."""
        ...

    async def path_exists(self, path: str) -> bool:
        """Return True if path exists and is a directory."""
        ...

    async def close(self) -> None:
        """Release resources."""
        ...
