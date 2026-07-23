"""Tests for LocalTransport."""

from pathlib import Path

import pytest

from multiscraper.transport.base import FileInfo
from multiscraper.transport.local import LocalTransport


@pytest.mark.asyncio
async def test_local_list_dir(tmp_path: Path):
    (tmp_path / "game1.smc").write_bytes(b"rom1")
    (tmp_path / "game2.smc").write_bytes(b"rom2")
    (tmp_path / "notarom.txt").write_text("nope")

    transport = LocalTransport()
    files = await transport.list_dir(str(tmp_path))
    assert len(files) == 3
    assert "game1.smc" in files
    assert "game2.smc" in files


@pytest.mark.asyncio
async def test_local_file_info(tmp_path: Path):
    f = tmp_path / "game.smc"
    f.write_bytes(b"hello world")
    transport = LocalTransport()
    info = await transport.file_info(str(f))
    assert isinstance(info, FileInfo)
    assert info.size == 11
    assert info.is_file


@pytest.mark.asyncio
async def test_local_hash_crc32(tmp_path: Path):
    f = tmp_path / "game.smc"
    f.write_bytes(b"hello world")
    transport = LocalTransport()
    crc = await transport.hash(str(f), "crc32")
    assert crc == "0d4a1185"


@pytest.mark.asyncio
async def test_local_hash_sha1(tmp_path: Path):
    f = tmp_path / "game.smc"
    f.write_bytes(b"hello world")
    transport = LocalTransport()
    sha = await transport.hash(str(f), "sha1")
    assert sha == "2aae6c35c94fcfb415dbe95f408b9ce91ee846ed"


@pytest.mark.asyncio
async def test_local_close():
    transport = LocalTransport()
    await transport.close()  # should not raise


@pytest.mark.asyncio
async def test_local_path_exists_ok(tmp_path: Path):
    transport = LocalTransport()
    assert await transport.path_exists(str(tmp_path)) is True


@pytest.mark.asyncio
async def test_local_path_exists_missing(tmp_path: Path):
    transport = LocalTransport()
    missing = tmp_path / "definitely_not_here_xyz123"
    assert await transport.path_exists(str(missing)) is False
