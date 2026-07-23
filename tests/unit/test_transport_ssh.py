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
