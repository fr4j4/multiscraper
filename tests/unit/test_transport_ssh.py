"""Tests for SshTransport."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_ssh_path_exists_ok():
    from multiscraper.transport.ssh import SshTransport

    transport = SshTransport(host="example", user="test")
    conn = MagicMock()
    conn.is_closed = MagicMock(return_value=False)
    result = MagicMock(exit_status=0)
    conn.run = AsyncMock(return_value=result)
    transport._conn = conn

    assert await transport.path_exists("/some/path") is True
    conn.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_ssh_path_exists_missing():
    from multiscraper.transport.ssh import SshTransport

    transport = SshTransport(host="example", user="test")
    conn = MagicMock()
    conn.is_closed = MagicMock(return_value=False)
    result = MagicMock(exit_status=1)
    conn.run = AsyncMock(return_value=result)
    transport._conn = conn

    assert await transport.path_exists("/missing/path") is False
    conn.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_ssh_list_dir_quotes_path_with_spaces():
    """Regression: path with spaces and parens must be shell-quoted."""
    from multiscraper.transport.ssh import SshTransport

    transport = SshTransport(host="example", user="test")
    conn = MagicMock()
    conn.is_closed = MagicMock(return_value=False)
    result = MagicMock(exit_status=0, stdout="file1.rom\nfile 2.rom\n")
    conn.run = AsyncMock(return_value=result)
    transport._conn = conn

    bad_path = "/roms/My Game (USA).gba"
    files = await transport.list_dir(bad_path)

    assert files == ["file1.rom", "file 2.rom"]
    cmd = conn.run.await_args.args[0]
    assert "'" in cmd or '"' in cmd, f"path not quoted: {cmd!r}"


@pytest.mark.asyncio
async def test_ssh_file_info_quotes_path_with_spaces():
    """Regression: file_info with path containing spaces must work."""
    from multiscraper.transport.ssh import SshTransport

    transport = SshTransport(host="example", user="test")
    conn = MagicMock()
    conn.is_closed = MagicMock(return_value=False)
    result = MagicMock(exit_status=0, stdout="12345 67890\n")
    conn.run = AsyncMock(return_value=result)
    transport._conn = conn

    bad_path = "/roms/Jazz Jackrabbit (USA, Europe).gba"
    info = await transport.file_info(bad_path)

    assert info.size == 12345
    assert info.mtime == 67890
    cmd = conn.run.await_args.args[0]
    assert "'" in cmd or '"' in cmd, f"path not quoted: {cmd!r}"


@pytest.mark.asyncio
async def test_ssh_hash_quotes_path_with_spaces():
    """Regression: hash with path containing spaces must work for sha1."""
    from multiscraper.transport.ssh import SshTransport

    transport = SshTransport(host="example", user="test")
    conn = MagicMock()
    conn.is_closed = MagicMock(return_value=False)
    result = MagicMock(exit_status=0, stdout="abc123\n")
    conn.run = AsyncMock(return_value=result)
    transport._conn = conn

    bad_path = "/roms/My Game (USA).gba"
    h = await transport.hash(bad_path, "sha1")

    assert h == "abc123"
    cmd = conn.run.await_args.args[0]
    assert "'" in cmd or '"' in cmd, f"path not quoted: {cmd!r}"


@pytest.mark.asyncio
async def test_ssh_hash_crc32_streams_locally_when_crc32_command_missing():
    """Regression: `crc32` binary is not always installed on remote hosts.

    The SshTransport should stream the file and compute CRC32 in Python
    via zlib rather than relying on a `crc32` shell command.
    """
    import zlib

    from multiscraper.transport.ssh import SshTransport

    transport = SshTransport(host="example", user="test")

    # Provide fake bytes that hash to a known CRC32
    payload = b"Hello, world! " * 100
    expected_crc = f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}"

    # Build a fake connection that does NOT support `crc32` command.
    # When asked for the file via cat, yield the payload.
    async def fake_stream(path, max_bytes=None):
        yield payload

    transport.open_read = fake_stream  # type: ignore[assignment]

    h = await transport.hash("/anywhere", "crc32")
    assert h == expected_crc
    assert len(h) == 8  # 8 hex chars for CRC32
