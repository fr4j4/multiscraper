"""Tests for OpenVGDB provider (mocked HTTP, HTML parse)."""

import re
from typing import ClassVar

import pytest
from aioresponses import aioresponses

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.openvgdb import OpenVGDBProvider

_OVG_URL = re.compile(r"https://vgdb\.io/search.*")


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test Game")


def _html_results() -> bytes:
    return (
        b'<html><body>'
        b'<a class="game" href="/game/42">Test Game (1990)</a>'
        b'<a class="game" href="/game/43">Another Game (1991)</a>'
        b'</body></html>'
    )


@pytest.mark.asyncio
async def test_openvgdb_search_returns_candidates():
    provider = OpenVGDBProvider()
    await provider.setup({})

    with aioresponses() as m:
        m.get(_OVG_URL, status=200, body=_html_results())
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates) == 2
    assert candidates[0].source_id == "42"
    assert candidates[0].match_score > 0.5
    assert any(ref.type == MediaType.IMAGE for ref in candidates[0].media)

    await provider.close()


@pytest.mark.asyncio
async def test_openvgdb_fetch_media_from_candidate():
    provider = OpenVGDBProvider()
    await provider.setup({})

    with aioresponses() as m:
        m.get(_OVG_URL, status=200, body=_html_results())
        rom = _make_rom()
        candidates = await provider.search(rom)

    media = await provider.fetch_media(candidates[0], {MediaType.IMAGE})
    assert MediaType.IMAGE in media
    assert "vgdb.io" in str(media[MediaType.IMAGE].url)

    await provider.close()


@pytest.mark.asyncio
async def test_openvgdb_detect_blocked():
    provider = OpenVGDBProvider()
    await provider.setup({})

    class BlockedResp:
        status: ClassVar[int] = 503
        headers: ClassVar[dict[str, str]] = {}

    class OkResp:
        status: ClassVar[int] = 200
        headers: ClassVar[dict[str, str]] = {}

    assert provider.detect_blocked(BlockedResp(), b"<!doctype html>cloudflare</html>") is True
    assert provider.detect_blocked(OkResp(), b"<!doctype html>ok</html>") is False

    await provider.close()
