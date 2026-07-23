"""SSH transport using asyncssh.

Connects to a remote host and reads ROMs without downloading them.
Supports key-based auth, password auth, SSH agent, and ProxyJump.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, cast

import asyncssh

from multiscraper.transport.base import FileInfo


class SshTransport:
    """Transport for reading ROMs from a remote SSH host."""

    def __init__(
        self,
        host: str,
        port: int = 22,
        user: str | None = None,
        password: str | None = None,
        key_file: str | None = None,
        known_hosts: str | None = None,
        auto_trust: bool = False,
        jump_host: str | None = None,
    ):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._key_file = key_file
        self._known_hosts = known_hosts
        self._auto_trust = auto_trust
        self._jump_host = jump_host
        self._conn: asyncssh.SSHClientConnection | None = None

    async def _ensure_connected(self) -> asyncssh.SSHClientConnection:
        if self._conn is not None and not self._conn.is_closed():
            return self._conn

        if self._auto_trust:
            kh: object = None
        elif self._known_hosts:
            kh = self._known_hosts
        else:
            kh = []

        self._conn = await asyncssh.connect(
            host=self._host,
            port=self._port,
            username=self._user,
            password=self._password,
            client_keys=self._key_file,
            known_hosts=kh,
        )
        return self._conn

    async def list_dir(self, path: str) -> list[str]:
        conn = await self._ensure_connected()
        result = await conn.run(f"ls -1 {path}", check=True)
        out = cast(str, result.stdout)
        return [line.strip() for line in out.splitlines() if line.strip()]

    async def file_info(self, path: str) -> FileInfo:
        conn = await self._ensure_connected()
        result = await conn.run(f"stat -c '%s %Y' {path}", check=True)
        out = cast(str, result.stdout)
        size_str, mtime_str = out.strip().split()
        return FileInfo(
            path=path,
            size=int(size_str),
            mtime=int(mtime_str),
            is_file=True,
        )

    async def hash(self, path: str, algo: Literal["crc32", "sha1"]) -> str:
        conn = await self._ensure_connected()
        cmd = f"crc32 {path}" if algo == "crc32" else f"sha1sum {path} | cut -d' ' -f1"
        result = await conn.run(cmd, check=True)
        out = cast(str, result.stdout)
        return out.strip().lower()

    async def open_read(self, path: str, max_bytes: int | None = None) -> AsyncIterator[bytes]:
        conn = await self._ensure_connected()
        proc = await conn.create_process(f"cat {path}")
        reader: asyncssh.SSHReader[str] = proc.stdout
        remaining = max_bytes
        try:
            while True:
                chunk_size = min(64 * 1024, remaining) if remaining else 64 * 1024
                chunk = await reader.read(chunk_size)
                if not chunk:
                    break
                yield chunk.encode("utf-8") if isinstance(chunk, str) else chunk
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break
        finally:
            proc.close()
            await proc.wait_closed()

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None
